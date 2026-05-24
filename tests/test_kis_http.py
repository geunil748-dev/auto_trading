from datetime import datetime, timezone

from trading_bot.adapters.kis_http import KisJsonClient, _default_token_cache
from trading_bot.config import KisSettings
from trading_bot.retry import RetryPolicy


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


def test_default_token_cache_is_split_by_kis_client() -> None:
    mock = KisSettings("mock-key", "secret", "account", "01", "https://mock.kis.test")
    real = KisSettings("real-key", "secret", "account", "01", "https://real.kis.test")

    assert _default_token_cache(mock) != _default_token_cache(real)
    assert _default_token_cache(mock).name.startswith(".kis-token-")
