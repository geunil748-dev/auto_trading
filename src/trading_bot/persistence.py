from __future__ import annotations

from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.news_cache import NewsCacheRepository, SqlServerNewsCacheRepository
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.ports import DailyRepository


def build_daily_repository() -> DailyRepository:
    if mssql_dsn_from_env():
        return SqlServerDailyRepository(pyodbc_connect_factory())
    return InMemoryDailyRepository()


def build_news_cache_repository() -> NewsCacheRepository | None:
    if mssql_dsn_from_env():
        return SqlServerNewsCacheRepository(pyodbc_connect_factory())
    return None
