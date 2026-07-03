from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN, BucketStats, num


def realized_pnl_sources(
    *,
    sell_rows: Sequence[Mapping[str, Any]],
    fill_history_sell_rows: object,
    score_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    exit_stats: Mapping[str, BucketStats],
    overall: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> dict[str, Any]:
    raw_sell_fills = (
        sum(num(row.get("profit_usd")) for row in sell_rows)
        if fill_history_sell_rows != UNKNOWN
        else UNKNOWN
    )
    matched_rows = score_rows if score_rows else source_rows
    return {
        "raw_sell_fills": raw_sell_fills,
        "matched_trades_only": sum(num(row.get("total_profit_usd")) for row in matched_rows)
        if matched_rows
        else UNKNOWN,
        "daily_summary": reconciliation.get("daily_summary_realized_pnl", UNKNOWN),
        "strategy_review_sheet": overall.get("realized_pnl", UNKNOWN),
        "exit_reason_sum": sum(item.total_profit_usd for item in exit_stats.values()),
    }


def build_reconciliation_detail(
    *,
    raw_sell_fills: object,
    matched_trades_only: object,
    daily_summary: object,
    strategy_review_sheet: object,
    exit_reason_sum: object,
    unmatched_count: object,
    duplicate_count: int,
    reconciliation_gap_abs: object,
    duplicate_suspects: Mapping[str, Any],
) -> dict[str, Any]:
    causes = []
    if _count_or_none(unmatched_count):
        causes.append("unmatched rows excluded from one side")
    if duplicate_count:
        causes.append("duplicate rows included")
    if any(sample.get("duplicate_confidence") in {"LOW", "MEDIUM"} for sample in duplicate_suspects.get("samples", [])):
        causes.append("partial fill aggregation mismatch")
    gap = float(reconciliation_gap_abs) if isinstance(reconciliation_gap_abs, (int, float)) else 0.0
    raw_vs_exit = _gap(raw_sell_fills, exit_reason_sum)
    raw_vs_daily = _gap(raw_sell_fills, daily_summary)
    if raw_vs_exit == 0.0 and raw_vs_daily not in {0.0, UNKNOWN}:
        causes.append("daily summary basis mismatch")
    if 0.0 < gap <= 50.0:
        causes.append("fees/taxes/slippage/fx/rounding included on one side only")
    if gap > 50.0:
        causes.append("date boundary/timezone mismatch")
    return {
        "raw_sell_fills_vs_daily_summary": raw_vs_daily,
        "raw_sell_fills_vs_exit_reason_sum": raw_vs_exit,
        "strategy_review_vs_daily_summary": _gap(strategy_review_sheet, daily_summary),
        "strategy_review_vs_exit_reason_sum": _gap(strategy_review_sheet, exit_reason_sum),
        "matched_only_vs_all_sells": _gap(matched_trades_only, strategy_review_sheet),
        "suspected_causes": causes or ["none"],
    }


def _gap(left: object, right: object) -> float | str:
    if left == UNKNOWN or right == UNKNOWN:
        return UNKNOWN
    return round(float(num(left) - num(right)), 2)


def _count_or_none(value: object) -> int | None:
    if value == UNKNOWN:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None
