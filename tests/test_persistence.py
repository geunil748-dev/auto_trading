from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.persistence import build_daily_repository


def test_persistence_falls_back_to_memory_without_mssql_dsn(monkeypatch) -> None:
    monkeypatch.setattr("trading_bot.database.load_dotenv", None)
    monkeypatch.delenv("MSSQL_DSN", raising=False)
    monkeypatch.delenv("MSSQL_HOST", raising=False)
    monkeypatch.delenv("MSSQL_DATABASE", raising=False)
    monkeypatch.delenv("MSSQL_USERNAME", raising=False)
    monkeypatch.delenv("MSSQL_PASSWORD", raising=False)

    assert isinstance(build_daily_repository(), InMemoryDailyRepository)
