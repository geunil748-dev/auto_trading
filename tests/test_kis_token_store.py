from trading_bot.kis_token_store import KIS_TOKEN_CACHE_SCHEMA, _fetchone


def test_kis_token_cache_schema_keeps_token_unique_per_environment_and_app_key() -> None:
    assert "CREATE TABLE dbo.KisTokenCache" in KIS_TOKEN_CACHE_SCHEMA
    assert "access_token NVARCHAR(2048)" in KIS_TOKEN_CACHE_SCHEMA
    assert "app_key_hash VARCHAR(64)" in KIS_TOKEN_CACHE_SCHEMA
    assert "UNIQUE (environment, app_key_hash)" in KIS_TOKEN_CACHE_SCHEMA


def test_fetchone_supports_fetchall_only_cursor() -> None:
    class Cursor:
        def fetchall(self) -> list[tuple[int]]:
            return [(1,)]

    assert _fetchone(Cursor()) == (1,)
