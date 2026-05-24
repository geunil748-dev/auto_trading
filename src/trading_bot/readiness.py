from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.config import load_kis_settings
from trading_bot.database import pyodbc_connect_factory
from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_us_trading_day,
)


REQUIRED_TABLES = {
    "bot_log",
    "daily_target",
    "scoring",
    "trade_history",
}


def mock_trading_readiness(
    monitor_state: Path = Path("monitor/state.json"),
    now: datetime | None = None,
    market_date: date | None = None,
) -> dict[str, Any]:
    target_date = market_date or current_us_market_date(now)
    # 실투자 전환 전에는 이 결과를 먼저 보고 휴장/DB/API 준비 상태를 분리해서 판단한다.
    return {
        "us_market_date": target_date.isoformat(),
        "is_us_trading_day": is_us_trading_day(target_date),
        "is_regular_session_now": is_current_us_regular_session(now),
        "next_us_trading_day": next_us_trading_day(target_date).isoformat(),
        "kis_config": _kis_config_status(),
        "mssql": _mssql_status(),
        "monitor_state_exists": monitor_state.exists(),
        "ready_for_live_mock_session": is_us_trading_day(target_date),
    }


def next_us_trading_day(start: date) -> date:
    candidate = start
    for _ in range(14):
        if is_us_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError("No US trading day found in the next 14 days")


def _kis_config_status() -> dict[str, bool]:
    try:
        settings = load_kis_settings()
    except Exception:
        return {
            "configured": False,
            "app_key": False,
            "app_secret": False,
            "account_no": False,
            "account_product": False,
        }
    return {
        "configured": True,
        "app_key": bool(settings.app_key),
        "app_secret": bool(settings.app_secret),
        "account_no": bool(settings.account_no),
        "account_product": bool(settings.account_product),
    }


def _mssql_status() -> dict[str, Any]:
    try:
        connection = pyodbc_connect_factory()()
        cursor = connection.cursor()
        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = ?", ("BASE TABLE",))
        tables = {str(row[0]) for row in cursor.fetchall()}
        connection.close()
    except Exception as error:
        return {"connected": False, "error": str(error)}

    missing = sorted(REQUIRED_TABLES - tables)
    return {
        "connected": True,
        "required_tables_ready": not missing,
        "missing_tables": missing,
    }
