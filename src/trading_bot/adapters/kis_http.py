from __future__ import annotations

import json
from hashlib import sha256
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_bot.config import KisSettings
from trading_bot.retry import NETWORK_RETRY, RetryPolicy, call_with_retry

JsonObject = dict[str, Any]
JsonRequest = Callable[[str, str, Mapping[str, str], JsonObject | None], JsonObject]
DEFAULT_TOKEN_CACHE = Path(".kis-token.json")


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: datetime

    def is_valid(self, now: datetime) -> bool:
        return now < self.expires_at


class KisJsonClient:
    def __init__(
        self,
        settings: KisSettings,
        request_json: JsonRequest | None = None,
        retry_policy: RetryPolicy = NETWORK_RETRY,
        now: Callable[[], datetime] | None = None,
        token_cache: Path | None = DEFAULT_TOKEN_CACHE,
    ) -> None:
        self.settings = settings
        self.request_json = request_json or _urllib_json_request
        self.retry_policy = retry_policy
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.token_cache = (
            None
            if request_json is not None and token_cache == DEFAULT_TOKEN_CACHE
            else _default_token_cache(settings)
            if token_cache == DEFAULT_TOKEN_CACHE
            else token_cache
        )
        self._token: AccessToken | None = None

    def get(self, path: str, tr_id: str, params: Mapping[str, str]) -> JsonObject:
        headers = self._headers(tr_id)
        url = f"{self.settings.base_url}{path}?{urlencode(params)}"
        return call_with_retry(
            lambda: self.request_json("GET", url, headers, None),
            self.retry_policy,
        )

    def post(self, path: str, tr_id: str, body: JsonObject) -> JsonObject:
        return call_with_retry(
            lambda: self.request_json(
                "POST",
                f"{self.settings.base_url}{path}",
                self._headers(tr_id),
                body,
            ),
            self.retry_policy,
        )

    def access_token(self) -> str:
        now = self.now()
        if self._token is None:
            self._token = self._read_cached_token()
        if self._token is not None and self._token.is_valid(now):
            return self._token.value

        body = {
            "grant_type": "client_credentials",
            "appkey": self.settings.app_key,
            "appsecret": self.settings.app_secret,
        }
        response = call_with_retry(
            lambda: self.request_json(
                "POST",
                f"{self.settings.base_url}/oauth2/tokenP",
                {"content-type": "application/json"},
                body,
            ),
            self.retry_policy,
        )
        token = str(response["access_token"])
        expires_in = int(response.get("expires_in", 0))
        refresh_margin = min(300, max(expires_in // 10, 0))
        self._token = AccessToken(
            token,
            now + timedelta(seconds=max(expires_in - refresh_margin, 0)),
        )
        self._write_cached_token(self._token)
        return token

    def _headers(self, tr_id: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.access_token()}",
            "appkey": self.settings.app_key,
            "appsecret": self.settings.app_secret,
            "tr_id": tr_id,
            "content-type": "application/json",
        }

    def _read_cached_token(self) -> AccessToken | None:
        if self.token_cache is None or not self.token_cache.exists():
            return None
        try:
            payload = json.loads(self.token_cache.read_text(encoding="utf-8"))
            if payload.get("client") != self._client_fingerprint():
                return None
            token = AccessToken(
                str(payload["access_token"]),
                datetime.fromisoformat(str(payload["expires_at"])),
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        return token if token.is_valid(self.now()) else None

    def _write_cached_token(self, token: AccessToken) -> None:
        if self.token_cache is None:
            return
        self.token_cache.write_text(
            json.dumps(
                {
                    "client": self._client_fingerprint(),
                    "access_token": token.value,
                    "expires_at": token.expires_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    def _client_fingerprint(self) -> str:
        raw = f"{self.settings.base_url}:{self.settings.app_key}".encode("utf-8")
        return sha256(raw).hexdigest()


def _default_token_cache(settings: KisSettings) -> Path:
    raw = f"{settings.base_url}:{settings.app_key}".encode("utf-8")
    return Path(f".kis-token-{sha256(raw).hexdigest()[:12]}.json")


def _urllib_json_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: JsonObject | None,
) -> JsonObject:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=payload, headers=dict(headers), method=method)
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
