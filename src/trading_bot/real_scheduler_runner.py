from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_bot.config import APP_MODE_REAL, TradingSettings, load_settings
from trading_bot.real_preflight import REAL_SCHEDULER_HEARTBEAT_PATH


def real_scheduler_status(settings: TradingSettings | None = None) -> dict[str, object]:
    current = settings or load_settings()
    return {
        "ok": current.app_mode == APP_MODE_REAL,
        "mode": "real",
        "readOnly": True,
        "appMode": current.app_mode,
        "realTradingEnabled": current.real_trading_enabled,
        "realEmergencyStop": current.real_emergency_stop,
        "realAutoTradingEnabled": current.real_auto_trading_enabled,
        "realOrderExecutionEnabled": current.real_order_execution_enabled,
        "orderStage": "skipped",
        "reason": _skip_reason(current),
    }


def run_real_scheduler(monitor_state: Path) -> dict[str, object]:
    status = real_scheduler_status()
    status["monitorState"] = str(monitor_state)
    status["heartbeatPath"] = str(REAL_SCHEDULER_HEARTBEAT_PATH)
    _write_real_scheduler_heartbeat(REAL_SCHEDULER_HEARTBEAT_PATH)
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return status


def _skip_reason(settings: TradingSettings) -> str:
    if settings.app_mode != APP_MODE_REAL:
        return "APP_MODE_REAL_REQUIRED"
    if not settings.real_auto_trading_enabled:
        return "REAL_AUTO_TRADING_DISABLED"
    if not settings.real_order_execution_enabled:
        return "REAL_ORDER_EXECUTION_DISABLED"
    return "REAL_SCHEDULER_SKELETON_READ_ONLY"


def _write_real_scheduler_heartbeat(heartbeat_path: Path) -> str:
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(
        json.dumps(
            {
                "status": "read_only_skeleton",
                "pid": os.getpid(),
                "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return "Real scheduler heartbeat updated."
