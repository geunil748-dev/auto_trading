from trading_bot.kis_token_store import KIS_TOKEN_CACHE_SCHEMA, _as_utc, _fetchone


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


def test_as_utc_supports_dotnet_datetime_shape() -> None:
    class DotNetDateTime:
        Year = 2026
        Month = 5
        Day = 22
        Hour = 1
        Minute = 2
        Second = 3

    assert _as_utc(DotNetDateTime()).isoformat() == "2026-05-22T01:02:03+00:00"
