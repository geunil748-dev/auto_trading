from __future__ import annotations

import json
from pathlib import Path


def write_daily_report(
    report_dir: Path,
    trade_day: str,
    state: dict[str, object],
    cancelled_orders: list[dict[str, object]],
    eod_sell_count: int,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{trade_day}.json"
    payload = {
        "tradeDate": trade_day,
        "cancelledOrders": cancelled_orders,
        "eodSellCount": eod_sell_count,
        "orders": state.get("orders", []),
        "fills": state.get("fills", []),
        "holdings": state.get("holdings", []),
        "gates": state.get("gates", []),
        "logs": state.get("logs", []),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
