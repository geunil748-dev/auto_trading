from __future__ import annotations

import os
from datetime import date
from typing import Any

from trading_bot.config import load_settings
from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.monitor_health import _monitor_security_state
from trading_bot.real_trading_control import load_real_trading_control
from trading_bot.trading_date import current_trade_date


def generate_daily_summary_state(body: dict[str, Any]) -> dict[str, object]:
    raw_date = str(body.get("date") or "").strip()
    trade_date = date.fromisoformat(raw_date) if raw_date else current_trade_date()
    mode = str(body.get("mode") or "mock").strip().lower()
    result = generate_daily_trade_summary(trade_date=trade_date, mode=mode)
    return {
        "ok": True,
        "summary": {
            "tradeDate": result.report.trade_date.isoformat(),
            "mode": result.report.mode,
            "strategyVersion": result.report.strategy_version,
            "settingsSnapshotHash": result.report.settings_snapshot_hash,
            "tradeCount": result.report.trade_count,
            "buyCount": result.report.buy_count,
            "sellCount": result.report.sell_count,
            "totalProfitUsd": result.report.total_profit_usd,
            "totalProfitRate": result.report.total_profit_rate,
            "winRate": result.report.win_rate,
            "candidateCount": result.payload.get("candidateCount", 0),
            "selectedCount": result.payload.get("selectedCount", 0),
        },
    }


def runtime_state(
    control: Any | None = None,
    local_bypass: bool = False,
    bind_host: str = "127.0.0.1",
) -> dict[str, object]:
    if control is None:
        control = load_real_trading_control(load_settings())
    security = _monitor_security_state(bind_host)
    return {
        "activeMode": "real" if control.orders_unlocked else "mock",
        "modeLabel": control.mode_label,
        "monitorAuth": {
            "localBypass": local_bypass,
            "tokenConfigured": bool(os.getenv("MONITOR_BEARER_TOKEN", "").strip()),
            "tokenRequired": bool(security["token_required"]),
            "status": security["status"],
            "bindHost": bind_host,
        },
        "realTrading": control.to_dict(),
    }
