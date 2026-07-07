from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from trading_bot.adapters.kis_http import _default_token_cache, _token_environment
from trading_bot.composition_real import build_real_readonly_account
from trading_bot.config import (
    APP_MODE_REAL,
    KIS_REAL_BASE_URL,
    KisSettings,
    TradingSettings,
    load_settings,
)
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.real_trading_control import load_real_trading_control

MOCK_MONITOR_STATE_PATH = Path("monitor/state.json")
REAL_MONITOR_STATE_PATH = Path("monitor/real_state.json")
MOCK_SCHEDULER_HEARTBEAT_PATH = Path("monitor/scheduler_heartbeat.json")
REAL_SCHEDULER_HEARTBEAT_PATH = Path("monitor/real_scheduler_heartbeat.json")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(appkey|appsecret|access_token|token|secret|account|account_no|"
    r"cano|acnt_prdt_cd|password)\s*[:=]\s*[^,\s}]+"
)


AccountReaderFactory = Callable[[KisSettings], Any]


def real_preflight(
    *,
    check_account: bool = False,
    real_state_path: Path = REAL_MONITOR_STATE_PATH,
    mock_state_path: Path = MOCK_MONITOR_STATE_PATH,
    real_heartbeat_path: Path = REAL_SCHEDULER_HEARTBEAT_PATH,
    mock_heartbeat_path: Path = MOCK_SCHEDULER_HEARTBEAT_PATH,
    settings: TradingSettings | None = None,
    account_reader_factory: AccountReaderFactory | None = None,
    db_health_func: Callable[[], dict[str, object]] | None = None,
) -> dict[str, object]:
    current = settings or load_settings()
    control = load_real_trading_control(current)
    kis_config = _kis_real_config_status()
    kis_settings = _kis_settings_from_config(kis_config)
    db = db_health_func() if db_health_func is not None else _database_health()
    state_isolation = _state_isolation(
        real_state_path,
        mock_state_path,
        real_heartbeat_path,
        mock_heartbeat_path,
    )
    blocking_reasons = _blocking_reasons(current, control.manual_enabled, kis_config, state_isolation)
    warnings = _warnings(current, db, state_isolation, check_account)
    real_account = _real_account_status(
        check_account,
        current,
        kis_config,
        kis_settings,
        account_reader_factory,
    )
    if real_account["error"]:
        warnings.append("REAL_ACCOUNT_READ_ONLY_UNAVAILABLE")

    return {
        "ok": not blocking_reasons,
        "appMode": current.app_mode,
        "mockTrading": current.mock_trading,
        "realTradingEnabled": current.real_trading_enabled,
        "realEmergencyStop": current.real_emergency_stop,
        "manualEnabled": control.manual_enabled,
        "ordersUnlocked": control.orders_unlocked,
        "realAutoTradingEnabled": current.real_auto_trading_enabled,
        "realOrderExecutionEnabled": current.real_order_execution_enabled,
        "realOrderProtectionFailClosed": current.real_order_protection_fail_closed,
        "kisRealConfig": {
            "configured": kis_config["configured"],
            "appKey": kis_config["appKey"],
            "appSecret": kis_config["appSecret"],
            "accountNo": kis_config["accountNo"],
            "accountProduct": kis_config["accountProduct"],
            "baseUrl": kis_config["baseUrl"],
        },
        "kisTokenEnvironment": _token_environment(kis_settings),
        "kisTokenCache": {
            "environment": _token_environment(kis_settings),
            "fileName": _default_token_cache(kis_settings).name,
        },
        "realAccountReadOnly": real_account,
        "realStatePath": str(real_state_path),
        "mockStatePath": str(mock_state_path),
        "realSchedulerHeartbeatPath": str(real_heartbeat_path),
        "mockSchedulerHeartbeatPath": str(mock_heartbeat_path),
        "stateIsolation": state_isolation,
        "dbConfigured": bool(db.get("configured")),
        "dbConnected": bool(db.get("connected")),
        "warnings": warnings,
        "blockingReasons": blocking_reasons,
    }


def _kis_real_config_status() -> dict[str, object]:
    base_url = os.getenv("KIS_REAL_BASE_URL", KIS_REAL_BASE_URL).rstrip("/")
    app_key = os.getenv("KIS_REAL_APP_KEY", "").strip()
    app_secret = os.getenv("KIS_REAL_APP_SECRET", "").strip()
    account_no = os.getenv("KIS_REAL_ACCOUNT_NO", "").strip()
    account_product = os.getenv("KIS_REAL_ACCOUNT_PRODUCT", "01").strip()
    return {
        "configured": bool(app_key and app_secret and account_no and account_product and base_url),
        "appKey": bool(app_key),
        "appSecret": bool(app_secret),
        "accountNo": bool(account_no),
        "accountProduct": bool(account_product),
        "baseUrl": base_url,
        "_settings": KisSettings(
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            account_product=account_product or "01",
            base_url=base_url,
        ),
    }


def _kis_settings_from_config(config: dict[str, object]) -> KisSettings:
    settings = config.get("_settings")
    if isinstance(settings, KisSettings):
        return settings
    return KisSettings("", "", "", "01", KIS_REAL_BASE_URL)


def _real_account_status(
    check_account: bool,
    settings: TradingSettings,
    config: dict[str, object],
    kis_settings: KisSettings,
    account_reader_factory: AccountReaderFactory | None,
) -> dict[str, object]:
    if not check_account:
        return {"checked": False, "available": False, "error": "not checked"}
    if settings.app_mode != APP_MODE_REAL:
        return {"checked": True, "available": False, "error": "APP_MODE_NOT_REAL"}
    if not config["configured"]:
        return {"checked": True, "available": False, "error": "KIS_REAL_CONFIG_MISSING"}
    try:
        factory = account_reader_factory or build_real_readonly_account
        reader = factory(kis_settings)
        reader.current_account()
    except Exception as exc:
        return {"checked": True, "available": False, "error": safe_error_text(exc)}
    return {"checked": True, "available": True, "error": ""}


def _database_health() -> dict[str, object]:
    if not mssql_dsn_from_env():
        return {"configured": False, "connected": False, "error": ""}
    connection = None
    try:
        connection = pyodbc_connect_factory()()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
    except Exception as exc:
        return {"configured": True, "connected": False, "error": safe_error_text(exc)}
    finally:
        if connection is not None:
            connection.close()
    return {"configured": True, "connected": True, "error": ""}


def _state_isolation(
    real_state_path: Path,
    mock_state_path: Path,
    real_heartbeat_path: Path,
    mock_heartbeat_path: Path,
) -> dict[str, object]:
    real_state = _normalized_path(real_state_path)
    mock_state = _normalized_path(mock_state_path)
    real_heartbeat = _normalized_path(real_heartbeat_path)
    mock_heartbeat = _normalized_path(mock_heartbeat_path)
    return {
        "ok": real_state != mock_state and real_heartbeat != mock_heartbeat,
        "statePathSeparated": real_state != mock_state,
        "heartbeatPathSeparated": real_heartbeat != mock_heartbeat,
    }


def _blocking_reasons(
    settings: TradingSettings,
    manual_enabled: bool,
    config: dict[str, object],
    state_isolation: dict[str, object],
) -> list[str]:
    reasons: list[str] = []
    if settings.app_mode != APP_MODE_REAL:
        reasons.append("APP_MODE_NOT_REAL")
    if not settings.real_trading_enabled:
        reasons.append("REAL_TRADING_DISABLED")
    if settings.real_emergency_stop:
        reasons.append("REAL_EMERGENCY_STOP")
    if not manual_enabled:
        reasons.append("MANUAL_UNLOCK_DISABLED")
    if not settings.real_order_execution_enabled:
        reasons.append("REAL_ORDER_EXECUTION_DISABLED")
    if not config["configured"]:
        reasons.append("KIS_REAL_CONFIG_MISSING")
    if not state_isolation["ok"]:
        reasons.append("STATE_ISOLATION_FAILED")
    return reasons


def _warnings(
    settings: TradingSettings,
    db: dict[str, object],
    state_isolation: dict[str, object],
    check_account: bool,
) -> list[str]:
    warnings: list[str] = []
    if not settings.real_auto_trading_enabled:
        warnings.append("REAL_AUTO_TRADING_DISABLED")
    if bool(db.get("configured")) and not bool(db.get("connected")):
        warnings.append("DB_NOT_CONNECTED")
    if not bool(db.get("configured")):
        warnings.append("DB_NOT_CONFIGURED")
    if not state_isolation["ok"]:
        warnings.append("STATE_PATHS_NOT_ISOLATED")
    if not check_account:
        warnings.append("REAL_ACCOUNT_NOT_CHECKED")
    warnings.append("REAL_DRY_RUN_DB_WRITE_DISABLED")
    return warnings


def safe_error_text(error: Exception) -> str:
    text = str(error).splitlines()[0] if str(error) else error.__class__.__name__
    for key in (
        "MSSQL_DSN",
        "MSSQL_PASSWORD",
        "KIS_APP_KEY",
        "KIS_APP_SECRET",
        "KIS_ACCOUNT_NO",
        "KIS_REAL_APP_KEY",
        "KIS_REAL_APP_SECRET",
        "KIS_REAL_ACCOUNT_NO",
        "KIS_WS_APP_KEY",
        "KIS_WS_APP_SECRET",
        "KIS_WS_ACCOUNT_NO",
        "KIS_REAL_WS_APP_KEY",
        "KIS_REAL_WS_APP_SECRET",
        "KIS_REAL_WS_ACCOUNT_NO",
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
    return SENSITIVE_KEY_PATTERN.sub("<redacted>", text)[:300]


def _normalized_path(path: Path) -> str:
    return str(path).replace("\\", "/").lower()
