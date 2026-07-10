from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Any, Iterable, Mapping


def normalize_trading_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


def rows_for_date(rows: Iterable[Mapping[str, Any]], field: str, trading_date: object) -> list[Mapping[str, Any]]:
    target = normalize_trading_date(trading_date)
    return [row for row in rows if normalize_trading_date(row.get(field)) == target]


def representative_block_reasons(rows: Iterable[Mapping[str, Any]]) -> Counter[str]:
    return Counter(
        str(row.get("representative_reason") or row.get("buy_block_reason") or "UNKNOWN")
        for row in rows
        if str(row.get("decision") or "").upper() == "BUY_BLOCKED"
    )


def order_fill_metrics(
    events: Iterable[Mapping[str, Any]],
    orders: Iterable[Mapping[str, Any]],
    fills: Iterable[Mapping[str, Any]],
    trades: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    event_rows = list(events)
    fill_rows = list(fills)
    return {
        "candidate_buy_allowed_count": sum(_event(row, "BUY_ALLOWED") for row in event_rows),
        "buy_not_submitted_count": sum(_event(row, "BUY_NOT_SUBMITTED") for row in event_rows),
        "buy_order_submit_success_count": sum(_submitted(row, "BUY") for row in event_rows),
        "sell_order_submit_success_count": sum(_submitted(row, "SELL") for row in event_rows),
        "order_reconciliation_count": sum(_event(row, "ORDER_RECONCILIATION") for row in event_rows),
        "order_snapshot_row_count": len(list(orders)),
        "actual_buy_fill_count": sum(_side(row, "BUY") for row in fill_rows),
        "actual_sell_fill_count": sum(_side(row, "SELL") for row in fill_rows),
        "completed_round_trip_count": _completed_round_trips(fill_rows),
        "trade_submission_record_count": len(list(trades)),
    }


def shadow_pass_counts(
    rows: Iterable[Mapping[str, Any]], threshold: float, soft_penalty: float = -5.0
) -> dict[str, int]:
    material = list(rows)
    soft = [row for row in material if _score(row) + soft_penalty >= threshold]
    log_only = [row for row in material if _score(row) >= threshold]
    return {
        "soft_score_pass_rows": len(soft),
        "soft_score_unique_candidates": len(_unique_candidates(soft)),
        "log_only_pass_rows": len(log_only),
        "log_only_unique_candidates": len(_unique_candidates(log_only)),
    }


def data_quality_status(checks: Mapping[str, bool], warnings: Iterable[str] = ()) -> str:
    if not all(checks.values()):
        return "FAIL"
    return "PASS_WITH_WARNINGS" if any(warnings) else "PASS"


def _event(row: Mapping[str, Any], name: str) -> bool:
    return str(row.get("event_type") or row.get("decision") or "").upper() == name


def _submitted(row: Mapping[str, Any], side: str) -> bool:
    return bool(row.get("order_submitted")) and str(row.get("side") or "").upper() == side


def _side(row: Mapping[str, Any], side: str) -> bool:
    return str(row.get("side") or "").upper() == side


def _completed_round_trips(rows: Iterable[Mapping[str, Any]]) -> int:
    sides: dict[str, set[str]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper()
        if ticker:
            sides.setdefault(ticker, set()).add(str(row.get("side") or "").upper())
    return sum({"BUY", "SELL"}.issubset(value) for value in sides.values())


def _score(row: Mapping[str, Any]) -> float:
    return float(row.get("selection_score") or row.get("score") or 0)


def _unique_candidates(rows: Iterable[Mapping[str, Any]]) -> set[tuple[str | None, str]]:
    return {
        (normalize_trading_date(row.get("trading_date")), str(row.get("ticker") or row.get("symbol") or "").upper())
        for row in rows
    }
