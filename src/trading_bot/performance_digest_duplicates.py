from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import num

DUPLICATE_SAMPLE_LIMIT = 10


def build_duplicate_suspects(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    samples = [_duplicate_sample(row) for row in rows[:DUPLICATE_SAMPLE_LIMIT]]
    all_samples = [_duplicate_sample(row) for row in rows]
    return {
        "count": len(rows),
        "grouping_key": "trade_date,ticker,side,order_no,fill_time,fill_price",
        "confidence_counts": _counts(all_samples, "duplicate_confidence"),
        "duplicate_reason_counts": _counts(all_samples, "duplicate_reason"),
        "partial_fill_candidate_count": sum(
            1 for sample in all_samples if "PARTIAL_FILL" in str(sample.get("duplicate_reason"))
        ),
        "true_duplicate_candidate_count": sum(
            1 for sample in all_samples if sample.get("duplicate_confidence") == "HIGH"
        ),
        "samples": samples,
    }


def duplicate_reason_and_confidence(row: Mapping[str, Any]) -> tuple[str, str]:
    return _duplicate_reason_and_confidence(row)


def _duplicate_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    reason, confidence = duplicate_reason_and_confidence(row)
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
    fill_ids = _split(row.get("id_list"))
    if not fill_ids:
        return "MISSING_FILL_ID_CANNOT_CONFIRM", "LOW"
    if len(fill_ids) != len(set(fill_ids)):
        return "SAME_FILL_ID_DUPLICATED", "HIGH"
    if not order_no:
        return "MISSING_ORDER_ID_CANNOT_CONFIRM", "LOW"
    if row_count > 1 and len(fill_ids) > 1:
        return "SAME_ORDER_ID_PARTIAL_FILL_LIKELY", "MEDIUM"
    if row_count > 1 and min_quantity == max_quantity:
        return "SAME_SYMBOL_SIDE_TIME_PRICE_AMBIGUOUS", "MEDIUM"
    return "SAME_ORDER_ID_PARTIAL_FILL_LIKELY", "LOW"


def _counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN")
        result[value] = result.get(value, 0) + 1
    return result


def _split(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _date_text(value: object) -> str:
    return str(value or "")[:10]


def _symbol_text(value: object) -> str:
    return str(value or "").strip().upper()
