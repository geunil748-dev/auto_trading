from __future__ import annotations

from trading_bot.database import pyodbc_connect_factory
from trading_bot.models import BotLog
from trading_bot.repositories import SqlServerDailyRepository


def safe_exception_summary(exc: Exception) -> str:
    safe_summary = getattr(exc, "safe_summary", None)
    if callable(safe_summary):
        try:
            return str(safe_summary())
        except Exception:
            return type(exc).__name__
    return type(exc).__name__


def safe_scheduler_log(
    level: str,
    module: str,
    message: str,
    *,
    reject_reason: str = "",
    symbol: str = "",
    actual_value: float | None = None,
    threshold_value: float | None = None,
) -> None:
    try:
        SqlServerDailyRepository(pyodbc_connect_factory()).save_log(
            BotLog(
                level,
                module,
                message,
                symbol=symbol,
                reject_reason=reject_reason,
                actual_value=actual_value,
                threshold_value=threshold_value,
            )
        )
    except Exception:
        return
