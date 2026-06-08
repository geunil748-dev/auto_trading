from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path

from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory


def trading_cycle_skip_reason(monitor_state: Path) -> str | None:
    reasons: list[str] = []
    try:
        import clr  # noqa: F401
    except Exception:
        reasons.append("clr_import=fail")
    if not mssql_dsn_from_env():
        reasons.append("db_configured=false")
    else:
        try:
            with closing(pyodbc_connect_factory()()) as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchall()
        except Exception:
            reasons.append("db_connected=false")
    age_seconds = state_age_seconds(monitor_state)
    if age_seconds is None:
        reasons.append("state=missing")
    elif age_seconds > 600:
        reasons.append(
            f"state=stale age_seconds={age_seconds} "
            "recovery=inspect_scheduler_state_write"
        )
    if not reasons:
        return None
    return "SKIP trading cycle: monitor degraded reason=" + ",".join(reasons)


def guarded_trading_skip(
    trading_guard: Callable[[], str | None] | None,
) -> str | None:
    if trading_guard is None:
        return None
    return trading_guard()


def state_age_seconds(path: Path) -> int | None:
    if not path.exists():
        return None
    return max(int(datetime.now().timestamp() - path.stat().st_mtime), 0)
