from datetime import datetime, timezone

import pytest

from trading_bot.adapters.kis_http import (
    AccessToken,
    KisJsonClient,
    _default_token_cache,
    _token_environment,
)
from trading_bot.config import KisSettings
from trading_bot.retry import RetryPolicy


class MemoryTokenStore:
    def __init__(self, token: AccessToken | None = None, fail_read: bool = False) -> None:
        self.token = token
        self.fail_read = fail_read
        self.refresh_count = 0
        self.lock_count = 0
        self.read_count = 0

    def read_valid(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
    ) -> AccessToken | None:
        self.read_count += 1
        if self.fail_read:
            raise RuntimeError("db unavailable")
        if self.token is not None and self.token.is_valid(now, refresh_margin_seconds):
            return self.token
        return None

    def refresh_with_lock(
        self,
        environment: str,
        app_key_hash: str,
        now: datetime,
        refresh_margin_seconds: int,
        refresh,
    ) -> AccessToken:
        self.lock_count += 1
        if self.token is not None and self.token.is_valid(now, refresh_margin_seconds):
            return self.token
        self.refresh_count += 1
        self.token = refresh()
        return self.token


@pytest.fixture(autouse=True)
def default_file_token_store(monkeypatch) -> None:
    monkeypatch.setenv("KIS_TOKEN_STORE", "file")
    monkeypatch.delenv("KIS_ALLOW_TOKEN_REFRESH", raising=False)


def test_kis_json_client_reuses_access_token_and_builds_query_headers() -> None:
    requests: list[tuple[str, str, dict[str, str], dict[str, object] | None]] = []
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)

    def request(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, object] | None,
    ) -> dict[str, object]:
        requests.append((method, url, headers, body))
        if method == "POST":
            return {"access_token": "token", "expires_in": 3600}
        return {"output": {"last": "12.30"}}

    client = KisJsonClient(
        KisSettings("app", "secret", "account", "01", "https://kis.test"),
        request_json=request,
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
    )
    client.get("/quote", "TR1", {"SYMB": "AAA"})
    client.get("/quote", "TR1", {"SYMB": "BBB"})

    get_requests = [item for item in requests if item[0] == "GET"]
    assert len([item for item in requests if item[0] == "POST"]) == 1
    assert get_requests[0][1] == "https://kis.test/quote?SYMB=AAA"
    assert get_requests[0][2]["authorization"] == "Bearer token"
    assert get_requests[0][2]["tr_id"] == "TR1"


def test_kis_json_client_reads_matching_cached_access_token(tmp_path) -> None:
    requests: list[tuple[str, str]] = []
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    settings = KisSettings("app", "secret", "account", "01", "https://kis.test")
    cache = tmp_path / "token.json"

    seed = KisJsonClient(
        settings,
        request_json=lambda *args: {"access_token": "cached", "expires_in": 3600},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
    )
    assert seed.access_token() == "cached"

    def request(method: str, url: str, headers: dict[str, str], body: object) -> dict[str, object]:
        requests.append((method, headers["authorization"]))
        return {"output": {}}

    client = KisJsonClient(
        settings,
        request_json=request,
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
    )
    client.get("/quote", "TR1", {"SYMB": "AAA"})

    assert requests == [("GET", "Bearer cached")]


def test_kis_json_client_reuses_db_token_without_refresh(monkeypatch) -> None:
    monkeypatch.setenv("KIS_TOKEN_REFRESH_MARGIN_SECONDS", "300")
    requests: list[tuple[str, str]] = []
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    store = MemoryTokenStore(AccessToken("db-token", now.replace(hour=2)))

    def request(method: str, url: str, headers: dict[str, str], body: object) -> dict[str, object]:
        requests.append((method, headers["authorization"]))
        return {"output": {}}

    client = KisJsonClient(
        KisSettings("app", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443"),
        request_json=request,
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_store=store,
    )
    client.get("/quote", "TR1", {"SYMB": "AAA"})

    assert requests == [("GET", "Bearer db-token")]
    assert store.refresh_count == 0


def test_kis_json_client_prefers_db_token_over_file_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KIS_TOKEN_REFRESH_MARGIN_SECONDS", "300")
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    settings = KisSettings("app", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443")
    cache = tmp_path / "token.json"
    seed = KisJsonClient(
        settings,
        request_json=lambda *args: {"access_token": "file-token", "expires_in": 3600},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
    )
    assert seed.access_token() == "file-token"
    store = MemoryTokenStore(AccessToken("db-token", now.replace(hour=2)))

    client = KisJsonClient(
        settings,
        request_json=lambda *args: {"output": {}},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
        token_store=store,
    )

    assert client.access_token() == "db-token"
    assert store.read_count == 1


def test_kis_json_client_uses_file_cache_only_when_db_store_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("KIS_TOKEN_REFRESH_MARGIN_SECONDS", "300")
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    settings = KisSettings("app", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443")
    cache = tmp_path / "token.json"
    seed = KisJsonClient(
        settings,
        request_json=lambda *args: {"access_token": "file-token", "expires_in": 3600},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
    )
    assert seed.access_token() == "file-token"
    monkeypatch.setenv("KIS_ALLOW_TOKEN_REFRESH", "false")

    client = KisJsonClient(
        settings,
        request_json=lambda *args: {"access_token": "new", "expires_in": 3600},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_cache=cache,
        token_store=MemoryTokenStore(fail_read=True),
    )

    assert client.access_token() == "file-token"


def test_kis_json_client_refreshes_expired_db_token_once(monkeypatch) -> None:
    monkeypatch.setenv("KIS_TOKEN_REFRESH_MARGIN_SECONDS", "300")
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)
    store = MemoryTokenStore(AccessToken("expired", now))
    posts = 0

    def request(
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, object] | None,
    ) -> dict[str, object]:
        nonlocal posts
        if method == "POST":
            posts += 1
            return {"access_token": "fresh", "expires_in": 3600}
        return {"output": {}}

    settings = KisSettings("app", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443")
    first = KisJsonClient(
        settings,
        request_json=request,
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_store=store,
    )
    second = KisJsonClient(
        settings,
        request_json=request,
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_store=store,
    )

    assert first.access_token() == "fresh"
    assert second.access_token() == "fresh"
    assert posts == 1
    assert store.refresh_count == 1
    assert store.lock_count == 1


def test_kis_json_client_blocks_refresh_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("KIS_ALLOW_TOKEN_REFRESH", "false")
    store = MemoryTokenStore()
    now = datetime(2026, 5, 22, tzinfo=timezone.utc)

    client = KisJsonClient(
        KisSettings("app", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443"),
        request_json=lambda *args: {"access_token": "new", "expires_in": 3600},
        retry_policy=RetryPolicy(attempts=1, retry_delay_seconds=0),
        now=lambda: now,
        token_store=store,
    )

    with pytest.raises(RuntimeError, match="KIS 토큰 갱신이 비활성화"):
        client.access_token()

    assert store.refresh_count == 0


def test_default_token_cache_is_split_by_kis_client() -> None:
    mock = KisSettings("mock-key", "secret", "account", "01", "https://mock.kis.test")
    real = KisSettings("real-key", "secret", "account", "01", "https://real.kis.test")

    assert _default_token_cache(mock) != _default_token_cache(real)
    assert _default_token_cache(mock).name.startswith(".kis-token-")


def test_token_environment_names_mock_as_test() -> None:
    mock = KisSettings("mock-key", "secret", "account", "01", "https://openapivts.koreainvestment.com:29443")
    real = KisSettings("real-key", "secret", "account", "01", "https://openapi.koreainvestment.com:9443")

    assert _token_environment(mock) == "test"
    assert _token_environment(real) == "real"
