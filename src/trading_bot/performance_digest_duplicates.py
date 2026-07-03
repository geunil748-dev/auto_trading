from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import num

DUPLICATE_SAMPLE_LIMIT = 10


def build_duplicate_suspects(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "grouping_key": "trade_date,ticker,side,order_no,fill_time,fill_price",
        "samples": [_duplicate_sample(row) for row in rows[:DUPLICATE_SAMPLE_LIMIT]],
    }


def _duplicate_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    reason, confidence = _duplicate_reason_and_confidence(row)
    return {
        "trade_date": _date_text(row.get("trade_date")),
        "symbol": _symbol_text(row.get("ticker")),
        "side": row.get("side"),
        "order_id": row.get("order_no"),
        "fill_id": row.get("id_list"),
        "fill_time": row.get("fill_time"),
        "qty": row.get("sum_quantity") or row.get("quantity_list"),
        "price": row.get("fill_price"),
        "realized_pnl": row.get("sum_profit_usd"),
        "duplicate_reason": reason,
        "duplicate_confidence": confidence,
    }


def _duplicate_reason_and_confidence(row: Mapping[str, Any]) -> tuple[str, str]:
    row_count = int(num(row.get("row_count")))
    min_quantity = num(row.get("min_quantity"))
    max_quantity = num(row.get("max_quantity"))
    order_no = str(row.get("order_no") or "").strip()
    if row_count > 1 and min_quantity == max_quantity and order_no:
        return "EXACT_DUPLICATE_FILL_KEY", "HIGH"
    if row_count > 1 and order_no:
        return "DUPLICATE_FILL_KEY_WITH_QUANTITY_VARIATION", "MEDIUM"
    return "PARTIAL_FILL_OR_SPLIT_ORDER", "LOW"


def _date_text(value: object) -> str:
    return str(value or "")[:10]


def _symbol_text(value: object) -> str:
    return str(value or "").strip().upper()
