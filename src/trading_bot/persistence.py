from __future__ import annotations

import os

from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.ports import DailyRepository


def build_daily_repository() -> DailyRepository:
    if mssql_dsn_from_env():
        return SqlServerDailyRepository(pyodbc_connect_factory())
    return InMemoryDailyRepository()
