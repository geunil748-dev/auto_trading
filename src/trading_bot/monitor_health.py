from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path

from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.market_calendar import is_current_us_regular_session


STARTUP_TIME = datetime.now(timezone.utc).isoformat()


def _health_state(
    state_path: Path = Path("monitor/state.json"),
    bind_host: str = "127.0.0.1",
) -> dict[str, object]:
    database = _database_health()
    dependency = _dependency_health()
    scheduler = _scheduler_health(state_path)
    monitor_state = _monitor_state_health(state_path)
    security = _monitor_security_state(bind_host)
    degraded = (
        dependency["dependency_status"] != "ok"
        or not bool(database.get("connected")) and bool(database.get("configured"))
        or monitor_state["monitor_state_status"] not in {"fresh", "stale_after_hours"}
        or scheduler.get("heartbeat_status") != "recent"
        or security["status"] != "ok"
    )
    return {
        "ok": not degraded,
        "status": "degraded" if degraded else "ok",
        "security_status": security["status"],
        "security_message": security["message"],
        "dependency_status": dependency["dependency_status"],
        "clr_import": dependency["clr_import"],
        "clr_error": dependency["clr_error"],
        "db_configured": database.get("configured", False),
        "db_connected": database.get("connected", False),
        "db_error": database.get("error"),
        "monitor_state_status": monitor_state["monitor_state_status"],
        "state_last_updated": monitor_state["state_last_updated"],
        "monitor_state_age_seconds": monitor_state["monitor_state_age_seconds"],
        "monitor_state_message": monitor_state["message"],
        "monitor_state_recovery": monitor_state["recovery"],
        "git_head": _git_head(),
        "python_executable": sys.executable,
        "startup_time": STARTUP_TIME,
        "database": database,
        "monitor": {
            "ok": True,
            "pid": os.getpid(),
        },
        "monitor_process": {
            "status": "ok",
            "pid": os.getpid(),
        },
        "security": security,
        "scheduler": scheduler,
        "scheduler_heartbeat": scheduler.get("heartbeat_status", "missing"),
    }


def _database_health() -> dict[str, object]:
    if not mssql_dsn_from_env():
        return {"configured": False, "connected": False}
    try:
        connection = pyodbc_connect_factory()()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        connection.close()
    except Exception as exc:
        return {"configured": True, "connected": False, "error": _safe_error_text(exc)}
    return {"configured": True, "connected": True}


def _dependency_health() -> dict[str, object]:
    try:
        import clr  # noqa: F401
    except Exception as exc:
        return {
            "dependency_status": "fail",
            "clr_import": "fail",
            "clr_error": _safe_error_text(exc),
        }
    return {"dependency_status": "ok", "clr_import": "ok", "clr_error": None}


def _monitor_state_health(state_path: Path) -> dict[str, object]:
    age_seconds = _file_age_seconds(state_path)
    status = _fresh_status(age_seconds, 600)
    regular_session = is_current_us_regular_session()
    if status == "stale" and not regular_session:
        status = "stale_after_hours"
    return {
        "monitor_state_status": status,
        "state_last_updated": _file_updated_iso(state_path),
        "monitor_state_age_seconds": age_seconds,
        "is_regular_session_now": regular_session,
        "message": _monitor_state_message(status),
        "recovery": _monitor_state_recovery(status),
    }


def _monitor_state_message(status: str) -> str:
    if status == "fresh":
        return "monitor state is fresh"
    if status == "stale_after_hours":
        return "monitor state is stale outside the US regular session"
    if status == "missing":
        return "monitor state file is missing"
    return "monitor state is stale during the US regular session"


def _monitor_state_recovery(status: str) -> str | None:
    if status in {"fresh", "stale_after_hours"}:
        return None
    if status == "missing":
        return "Start the scheduler and confirm it can write monitor/state.json."
    return (
        "Confirm the scheduler heartbeat is recent, then inspect scheduler logs for "
        "monitor state write failures."
    )


def _scheduler_health(state_path: Path) -> dict[str, object]:
    heartbeat_path = state_path.parent / "scheduler_heartbeat.json"
    heartbeat_age_seconds = _file_age_seconds(heartbeat_path)
    monitor_state_age_seconds = _file_age_seconds(state_path)
    if heartbeat_age_seconds is not None:
        heartbeat_status = "recent" if heartbeat_age_seconds <= 120 else "stale"
        return {
            "status": "running" if heartbeat_status == "recent" else "stale_heartbeat",
            "heartbeat_exists": True,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat_status": heartbeat_status,
            "monitor_state_exists": state_path.exists(),
            "monitor_state_age_seconds": monitor_state_age_seconds,
            "monitor_state_status": _age_status(monitor_state_age_seconds, 600),
        }
    if not state_path.exists():
        return {
            "status": "missing_state",
            "heartbeat_exists": False,
            "heartbeat_age_seconds": None,
            "heartbeat_status": "missing",
            "monitor_state_exists": False,
            "monitor_state_age_seconds": None,
            "monitor_state_status": "missing",
        }
    status = _age_status(monitor_state_age_seconds, 600)
    return {
        "status": status,
        "heartbeat_exists": False,
        "heartbeat_age_seconds": None,
        "heartbeat_status": "missing",
        "monitor_state_exists": True,
        "monitor_state_age_seconds": monitor_state_age_seconds,
        "monitor_state_status": status,
    }


def _file_age_seconds(path: Path) -> int | None:
    if not path.exists():
        return None
    return max(int(time.time() - path.stat().st_mtime), 0)


def _file_updated_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _age_status(age_seconds: int | None, recent_seconds: int) -> str:
    if age_seconds is None:
        return "missing"
    return "recent" if age_seconds <= recent_seconds else "stale"


def _fresh_status(age_seconds: int | None, recent_seconds: int) -> str:
    if age_seconds is None:
        return "missing"
    return "fresh" if age_seconds <= recent_seconds else "stale"


def _monitor_security_state(bind_host: str) -> dict[str, object]:
    token_configured = bool(os.getenv("MONITOR_BEARER_TOKEN", "").strip())
    token_required = _monitor_bind_requires_token(bind_host)
    status = "ok"
    message = "monitor token policy is satisfied"
    if token_required and not token_configured:
        status = "fail"
        message = "MONITOR_BEARER_TOKEN is required when the monitor binds to LAN"
    return {
        "status": status,
        "bind_host": bind_host,
        "token_configured": token_configured,
        "token_required": token_required,
        "message": message,
    }


def _monitor_bind_requires_token(bind_host: str) -> bool:
    host = str(bind_host or "").strip().lower()
    if host in {"127.0.0.1", "::1", "localhost"}:
        return False
    if host in {"", "0.0.0.0", "::", "[::]", "*"}:
        return True
    try:
        return not ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return True


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path.cwd(),
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        ).strip()
    except Exception:
        return None


def _safe_error_text(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    for key in (
        "MSSQL_DSN",
        "MSSQL_PASSWORD",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_REAL_APP_KEY",
        "KIS_REAL_APP_SECRET",
        "KIS_WS_APP_KEY",
        "KIS_WS_APP_SECRET",
        "KIS_REAL_WS_APP_KEY",
        "KIS_REAL_WS_APP_SECRET",
        "KIS_WS_APPROVAL_KEY",
        "KIS_REAL_WS_APPROVAL_KEY",
        "ALERT_DISCORD_WEBHOOK_URL",
        "ALERT_TELEGRAM_BOT_TOKEN",
        "ALERT_TELEGRAM_CHAT_ID",
        "MONITOR_BEARER_TOKEN",
    ):
        value = os.getenv(key, "")
        if value:
            text = text.replace(value, "***")
    return text
