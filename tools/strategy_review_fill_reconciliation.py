from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

try:
    from tools.strategy_review_fill_normalization_utils import (
        AMBIGUOUS_EXCLUDED,
        AMBIGUOUS_WARNING,
        MONEY_TOLERANCE,
        NO_ORDER_NO_FALLBACK,
        date_text,
        decimal_value,
        float_value,
        is_best_effort_normalized_row,
        is_trusted_normalized_row,
        mode_text,
        normalize_side,
        prepare_fill,
        source_sort_key,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from strategy_review_fill_normalization_utils import (  # type: ignore[no-redef]
        AMBIGUOUS_EXCLUDED, AMBIGUOUS_WARNING, MONEY_TOLERANCE,
        NO_ORDER_NO_FALLBACK, date_text, decimal_value, float_value,
        is_best_effort_normalized_row, is_trusted_normalized_row, mode_text,
        normalize_side, prepare_fill, source_sort_key,
    )


def reconciliation_rows(
    fill_rows: Sequence[Mapping[str, Any]],
    normalized_rows: Sequence[Mapping[str, Any]],
    daily_summary_rows: Sequence[Mapping[str, Any]],
    trade_summary_rows: Sequence[Mapping[str, Any]],
    warnings: set[str],
) -> list[dict[str, Any]]:
    raw_by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in fill_rows:
        row = prepare_fill(source)
        if row["side"] == "SELL":
            raw_by_group[(row["trade_date"], mode_text(row))].append(row)
    normalized_by_group: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in normalized_rows:
        if _is_sell(row):
            normalized_by_group[(date_text(row.get("trade_date")), mode_text(row))].append(row)
    daily = _latest_summary(daily_summary_rows, "realized_profit_usd")
    trade = _latest_summary(trade_summary_rows, "total_profit_usd")
    groups = sorted(set(raw_by_group) | set(normalized_by_group) | set(daily) | set(trade))
    result: list[dict[str, Any]] = []
    for trade_date_value, mode in groups:
        key = (trade_date_value, mode)
        raw_rows = raw_by_group.get(key, [])
        normalized = normalized_by_group.get(key, [])
        trusted = [row for row in normalized if is_trusted_normalized_row(row)]
        best = [row for row in normalized if is_best_effort_normalized_row(row)]
        ambiguous = [row for row in normalized if row.get("normalization_method") == AMBIGUOUS_EXCLUDED]
        raw_profit = sum((row["profit_usd"] or Decimal("0") for row in raw_rows), Decimal("0"))
        trusted_profit = _normalized_profit(trusted)
        best_profit = _normalized_profit(best)
        ambiguous_profit = sum(
            (decimal_value(row.get("raw_profit_usd_sum")) or Decimal("0") for row in ambiguous),
            Decimal("0"),
        )
        daily_profit, trade_profit = daily.get(key), trade.get(key)
        daily_diff = trusted_profit - daily_profit if daily_profit is not None else None
        trade_diff = trusted_profit - trade_profit if trade_profit is not None else None
        row_warnings: list[str] = []
        if ambiguous:
            row_warnings.append(AMBIGUOUS_WARNING)
        no_order_no_sells = [
            row
            for row in normalized
            if _is_sell(row) and row.get("normalization_method") == NO_ORDER_NO_FALLBACK
        ]
        if no_order_no_sells:
            row_warnings.append("SELL_WITHOUT_ORDER_NO")
        if daily_diff is not None and abs(daily_diff) > MONEY_TOLERANCE:
            warnings.add("NORMALIZED_DAILY_SUMMARY_MISMATCH")
            row_warnings.append("NORMALIZED_DAILY_SUMMARY_MISMATCH")
        if trade_diff is not None and abs(trade_diff) > MONEY_TOLERANCE:
            warnings.add("NORMALIZED_TRADE_SUMMARY_MISMATCH")
            row_warnings.append("NORMALIZED_TRADE_SUMMARY_MISMATCH")
        result.append(
            {
                "trade_date": trade_date_value,
                "mode": mode,
                "raw_sell_row_count": len(raw_rows),
                "normalized_sell_order_count": len(trusted),
                "best_effort_sell_order_count": len(best),
                "raw_profit_usd": float_value(raw_profit),
                "normalized_profit_usd": float_value(trusted_profit),
                "best_effort_profit_usd": float_value(best_profit),
                "count_difference": len(raw_rows) - len(trusted),
                "profit_difference": float_value(raw_profit - trusted_profit),
                "ambiguous_order_count": len(ambiguous),
                "ambiguous_profit_usd": float_value(ambiguous_profit),
                "no_order_no_sell_count": len(no_order_no_sells),
                "daily_run_realized_profit_usd": float_value(daily_profit),
                "trade_summary_profit_usd": float_value(trade_profit),
                "normalized_vs_daily_run_diff": float_value(daily_diff),
                "normalized_vs_trade_summary_diff": float_value(trade_diff),
                "data_quality_warning": ",".join(sorted(set(row_warnings))),
            }
        )
    return result


def audit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "normalization_group_key", "trade_date", "is_mock", "mode", "ticker", "side", "order_no",
        "source_row_count", "source_id_list", "quantity_list", "fill_price_list",
        "fill_time_list", "created_at_list", "normalization_method",
        "normalization_confidence", "normalization_reason", "exact_duplicate_count",
        "order_quantity_evidence_list", "raw_quantity_sum", "normalized_quantity",
        "raw_profit_usd_sum", "normalized_profit_usd", "excluded_from_trusted_pnl",
        "trusted_exclusion_reason",
        "excluded_from_best_effort_pnl", "match_method", "match_distance_seconds",
        "match_ambiguous",
    )
    return {field: row.get(field) for field in fields}


def _normalized_profit(rows: Sequence[Mapping[str, Any]]) -> Decimal:
    return sum(
        (decimal_value(row.get("normalized_profit_usd")) or Decimal("0") for row in rows),
        Decimal("0"),
    )


def _latest_summary(
    rows: Sequence[Mapping[str, Any]],
    value_field: str,
) -> dict[tuple[str, str], Decimal | None]:
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = (date_text(row.get("trade_date")), mode_text(row))
        if key[0] and (key not in latest or source_sort_key(row) > source_sort_key(latest[key])):
            latest[key] = row
    return {key: decimal_value(row.get(value_field)) for key, row in latest.items()}


def _is_sell(row: Mapping[str, Any]) -> bool:
    return normalize_side(row.get("normalized_side") or row.get("side")) == "SELL"
