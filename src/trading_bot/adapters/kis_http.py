from __future__ import annotations

import json
import os
import re
import time
from hashlib import sha256
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from trading_bot.config import KisSettings
from trading_bot.retry import NETWORK_RETRY, RetryPolicy, call_with_retry

JsonObject = dict[str, Any]
JsonRequest = Callable[[str, str, Mapping[str, str], JsonObject | None], JsonObject]
DEFAULT_TOKEN_CACHE = Path(".kis-token.json")
HTTP_ERROR_BODY_PREVIEW_LIMIT = 800
KIS_API_ENABLED_ENV = "KIS_API_ENABLED"
SENSITIVE_BODY_KEY_PATTERN = re.compile(
    r'(?i)("?(?:authorization|appkey|appsecret|access_token|token|secret|'
    r'cano|acnt_prdt_cd|account_no|account|password)"?\s*[:=]\s*)("[^"]*"|[^,\s}]+)'
)


class KisHttpResponseError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        reason: str,
        method: str,
        path: str,
        tr_id: str,
        body_preview: str,
    ) -> None:
        self.status_code = status_code
        self.reason = reason
        self.method = method
        self.path = path
        self.tr_id = tr_id
        self.body_preview = body_preview
        super().__init__(self.safe_summary())

    def safe_summary(self) -> str:
        parts = [
            f"KisHttpResponseError {self.status_code}",
            self.reason,
            self.method,
            self.path,
        ]
        if self.tr_id:
            parts.append(f"tr_id={self.tr_id}")
        if self.body_preview:
            parts.append(f"body={_redact_sensitive_text(self.body_preview)}")
        return " ".join(parts)


class KisApiDisabledError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: datetime
    token_type: str = "Bearer"

    def is_valid(self, now: datetime, refresh_margin_seconds: int = 0) -> bool:
        return now + timedelta(seconds=refresh_margin_seconds) < self.expires_at


class TokenStore(Protocol):
    def read_valid(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
    ) -> AccessToken | None: ...

    def refresh_with_lock(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
        refresh: Callable[[], AccessToken],
    ) -> AccessToken: ...


class KisJsonClient:
    def __init__(
        self,
        settings: KisSettings,
        request_json: JsonRequest | None = None,
        retry_policy: RetryPolicy = NETWORK_RETRY,
        now: Callable[[], datetime] | None = None,
        token_cache: Path | None = DEFAULT_TOKEN_CACHE,
        token_store: TokenStore | None = None,
        token_environment: str | None = None,
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
        self.token_store = token_store or _db_token_store_from_env()
        self.token_environment = token_environment or _token_environment(settings)
        self._token: AccessToken | None = None

    def get(self, path: str, tr_id: str, params: Mapping[str, str]) -> JsonObject:
        _ensure_kis_api_enabled()
        headers = self._headers(tr_id)
        url = f"{self.settings.base_url}{path}?{urlencode(params)}"
        return call_with_retry(
            lambda: self.request_json("GET", url, headers, None),
            self.retry_policy,
        )

    def post(self, path: str, tr_id: str, body: JsonObject) -> JsonObject:
        _ensure_kis_api_enabled()
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
        _ensure_kis_api_enabled()
        now = self.now()
        refresh_margin_seconds = _token_refresh_margin_seconds()
        if self._token is not None and self._token.is_valid(now, refresh_margin_seconds):
            return self._token.value
        if self.token_store is not None:
            try:
                store_token = self.token_store.read_valid(
                    self.token_environment,
                    self._client_fingerprint(),
                    now,
                    refresh_margin_seconds,
                )
            except Exception as exc:
                fallback_token = self._read_cached_token()
                if fallback_token is not None and fallback_token.is_valid(now, refresh_margin_seconds):
                    self._token = fallback_token
                    return fallback_token.value
                raise RuntimeError(f"KIS DB 토큰 캐시 조회 실패: {exc}") from exc
            if store_token is not None:
                self._token = store_token
                return store_token.value
            if not _allow_token_refresh():
                raise RuntimeError(
                    "KIS 토큰 갱신이 비활성화되어 있습니다. "
                    "유효한 DB 토큰이 없으면 KIS_ALLOW_TOKEN_REFRESH=true인 서버에서 먼저 발급하세요."
                )
            try:
                self._token = self.token_store.refresh_with_lock(
                    self.token_environment,
                    self._client_fingerprint(),
                    now,
                    refresh_margin_seconds,
                    self._issue_access_token,
                )
            except Exception as exc:
                fallback_token = self._read_cached_token()
                if fallback_token is not None and fallback_token.is_valid(now, refresh_margin_seconds):
                    self._token = fallback_token
                    return fallback_token.value
                raise RuntimeError(f"KIS DB 토큰 캐시 갱신 실패: {exc}") from exc
            return self._token.value
        if self._token is None:
            self._token = self._read_cached_token()
        if self._token is not None and self._token.is_valid(now, refresh_margin_seconds):
            return self._token.value
        if not _allow_token_refresh():
            raise RuntimeError("KIS 토큰 갱신이 비활성화되어 있습니다.")

        self._token = self._issue_access_token()
        self._write_cached_token(self._token)
        return self._token.value

    def _issue_access_token(self) -> AccessToken:
        now = self.now()

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
        return AccessToken(
            token,
            now + timedelta(seconds=max(expires_in, 0)),
            str(response.get("token_type") or "Bearer"),
        )

    def _headers(self, tr_id: str) -> dict[str, str]:
        token = self.access_token()
        return {
            "authorization": f"{self._token_type()} {token}",
            "appkey": self.settings.app_key,
            "appsecret": self.settings.app_secret,
            "tr_id": tr_id,
            "content-type": "application/json",
        }

    def _token_type(self) -> str:
        if self._token is not None and self._token.token_type:
            return self._token.token_type
        return "Bearer"

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
                str(payload.get("token_type") or "Bearer"),
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
                    "token_type": token.token_type,
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


def _token_environment(settings: KisSettings) -> str:
    return "test" if "openapivts" in settings.base_url.lower() else "real"


def _token_refresh_margin_seconds() -> int:
    try:
        return max(int(os.getenv("KIS_TOKEN_REFRESH_MARGIN_SECONDS", "300")), 0)
    except ValueError:
        return 300


def _allow_token_refresh() -> bool:
    return os.getenv("KIS_ALLOW_TOKEN_REFRESH", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }


def _ensure_kis_api_enabled() -> None:
    enabled = os.getenv(KIS_API_ENABLED_ENV, "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
    }
    if not enabled:
        raise KisApiDisabledError(
            "KIS_API_DISABLED: KIS API 호출이 임시 비활성화되어 있습니다. "
            f"{KIS_API_ENABLED_ENV}=true로 설정하면 다시 활성화됩니다."
        )


def _db_token_store_from_env() -> TokenStore | None:
    if os.getenv("KIS_TOKEN_STORE", "file").strip().lower() != "db":
        return None
    from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
    from trading_bot.kis_token_store import SqlServerKisTokenStore

    if not mssql_dsn_from_env():
        raise RuntimeError("KIS_TOKEN_STORE=db requires MSSQL connection settings.")
    return SqlServerKisTokenStore(pyodbc_connect_factory(), sleep=time.sleep)


def _urllib_json_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: JsonObject | None,
) -> JsonObject:
    _ensure_kis_api_enabled()
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=payload, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise KisHttpResponseError(
            status_code=int(exc.code),
            reason=str(exc.reason),
            method=method,
            path=urlparse(url).path,
            tr_id=_header_value(headers, "tr_id"),
            body_preview=_http_error_body_preview(exc),
        ) from exc


def _header_value(headers: Mapping[str, str], name: str) -> str:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return ""


def _http_error_body_preview(exc: HTTPError) -> str:
    try:
        body = exc.read()
    except Exception:
        return ""
    if not body:
        return ""
    text = body.decode("utf-8", errors="replace")
    text = _redact_sensitive_text(text)
    if len(text) > HTTP_ERROR_BODY_PREVIEW_LIMIT:
        return text[:HTTP_ERROR_BODY_PREVIEW_LIMIT] + "..."
    return text


def _redact_sensitive_text(text: str) -> str:
    return SENSITIVE_BODY_KEY_PATTERN.sub("<redacted>", text)
