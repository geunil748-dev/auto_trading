from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN, BucketStats, num


def realized_exit_count(
    overall: Mapping[str, Any],
    exit_stats: Mapping[str, BucketStats],
    pnl_by_day_rows: Sequence[Mapping[str, Any]],
    fill_sheet_available: bool,
) -> int | str:
    overall_sell_count = count_or_none(overall.get("sell_count"))
    if overall_sell_count is not None:
        return overall_sell_count
    exit_reason_count = stats_sell_count(exit_stats)
    if exit_reason_count:
        return exit_reason_count
    if pnl_by_day_rows or fill_sheet_available:
        return 0
    return UNKNOWN


def matched_trade_count(
    score_stats: Mapping[str, BucketStats],
    source_stats: Mapping[str, BucketStats],
    score_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]],
    score_sheet_available: bool,
    source_sheet_available: bool,
) -> int | str:
    score_count = stats_sell_count(score_stats)
    source_count = stats_sell_count(source_stats)
    if score_rows or source_rows or score_count or source_count:
        return max(score_count, source_count)
    if score_sheet_available or source_sheet_available:
        return 0
    return UNKNOWN


def unmatched_count(realized_exit_count_value: object, matched_trade_count_value: object) -> int | str:
    realized = count_or_none(realized_exit_count_value)
    matched = count_or_none(matched_trade_count_value)
    if realized is None or matched is None:
        return UNKNOWN
    return max(realized - matched, 0)


def safe_buy_count(
    buy_rows: Sequence[Mapping[str, Any]],
    fill_sheet_available: bool,
    parseable_fill_rows: int,
    realized_exit_count_value: object,
) -> int | str:
    if not fill_sheet_available:
        return UNKNOWN
    if parseable_fill_rows:
        return len(buy_rows)
    if count_or_none(realized_exit_count_value) == 0:
        return 0
    return UNKNOWN


def safe_fill_history_sell_rows(
    sell_rows: Sequence[Mapping[str, Any]],
    fill_sheet_available: bool,
    parseable_fill_rows: int,
    realized_exit_count_value: object,
) -> int | str:
    if not fill_sheet_available:
        return UNKNOWN
    if parseable_fill_rows:
        return len(sell_rows)
    if count_or_none(realized_exit_count_value) == 0:
        return 0
    return UNKNOWN


def count_consistency_status(
    realized_exit_count_value: object,
    matched_trade_count_value: object,
    fill_history_sell_rows: object,
    buy_count: object,
) -> str:
    if UNKNOWN in {realized_exit_count_value, matched_trade_count_value, fill_history_sell_rows, buy_count}:
        return "WARN"
    realized = count_or_none(realized_exit_count_value)
    matched = count_or_none(matched_trade_count_value)
    if realized is not None and matched is not None and matched < realized:
        return "WARN"
    return "OK"


def reconciliation_metrics(
    rows: Sequence[Mapping[str, Any]],
    realized_pnl: object,
) -> dict[str, float | str]:
    if not rows:
        return {
            "status": "LIMITED",
            "daily_summary_realized_pnl": UNKNOWN,
            "reconciliation_gap": UNKNOWN,
            "reconciliation_gap_basis": "missing_summary_reconciliation",
        }
    daily_pnl = sum(num(row.get("daily_run_realized_profit_usd")) for row in rows)
    realized_value = num(realized_pnl)
    gap = abs(realized_value - daily_pnl)
    return {
        "status": "OK" if gap <= 0.01 else "WARN",
        "daily_summary_realized_pnl": daily_pnl,
        "reconciliation_gap": gap,
        "reconciliation_gap_basis": "abs(realized_pnl - daily_summary_realized_pnl)",
    }


def interpretation(
    exit_stats: Mapping[str, BucketStats],
    source_stats: Mapping[str, BucketStats],
    overall: Mapping[str, float | int],
    duplicate_count: int,
    data_status_value: str,
) -> dict[str, str]:
    loss_bucket = largest_negative(exit_stats)
    loss_source = largest_negative(source_stats)
    sell_count = count_or_none(overall.get("sell_count")) or 0
    realized_pnl = float(overall.get("realized_pnl", 0.0))
    if data_status_value in {"WARN", "LIMITED"}:
        signal = "insufficient_data_or_data_quality_review_needed"
    elif sell_count == 0:
        signal = "no_sell_data"
    elif sell_count < 30:
        signal = "sample_below_30"
    elif realized_pnl < 0:
        signal = "negative_expectancy_review_needed"
    else:
        signal = "monitor_without_rule_change"
    focus = _review_focus(loss_bucket, loss_source, duplicate_count)
    return {
        "main_loss_driver": loss_bucket,
        "main_profit_driver": largest_positive(exit_stats),
        "strategy_change_signal": signal,
        "recommended_review_focus": (
            "fix digest/reconciliation/count consistency before strategy changes"
            if data_status_value in {"WARN", "LIMITED"}
            else focus
        ),
    }


def limited_notes(
    missing: Sequence[str],
    errors: Sequence[str],
    failures: Sequence[str],
    realized_exit_count_value: object,
    matched_trade_count_value: object,
    fill_history_sell_rows: object,
    buy_count: object,
    count_consistency_status_value: str,
) -> list[str]:
    notes = [f"missing_sheet:{name}" for name in missing]
    notes.extend(f"sheet_error:{item}" for item in errors)
    notes.extend(f"export_failure:{item}" for item in failures)
    sell_count = count_or_none(realized_exit_count_value)
    matched_count = count_or_none(matched_trade_count_value)
    if buy_count == UNKNOWN:
        notes.append("buy_count")
    if fill_history_sell_rows == UNKNOWN:
        notes.append("fill_history_sell_rows")
    if sell_count is not None and matched_count is not None and matched_count < sell_count:
        notes.append("unmatched_score_source_rows")
    if count_consistency_status_value != "OK":
        notes.append("count_consistency")
    if sell_count == 0:
        notes.append("no_sell_rows")
    if sell_count is None or sell_count < 30:
        notes.append("sell_sample_below_30")
    return notes


def data_status(
    notes: Sequence[str],
    reconciliation_status: object,
    count_consistency_status_value: str,
) -> str:
    if any(note.startswith("sheet_error:") or note.startswith("export_failure:") for note in notes):
        return "WARN"
    if reconciliation_status == "WARN" or count_consistency_status_value == "WARN":
        return "WARN"
    return "LIMITED" if notes else "OK"


def stats_sell_count(stats: Mapping[str, BucketStats]) -> int:
    return sum(item.sell_count for item in stats.values())


def count_or_none(value: object) -> int | None:
    if value == UNKNOWN:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def largest_negative(stats: Mapping[str, BucketStats]) -> str:
    negatives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd < 0]
    return min(negatives, key=lambda item: item[1])[0] if negatives else "none"


def largest_positive(stats: Mapping[str, BucketStats]) -> str:
    positives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd > 0]
    return max(positives, key=lambda item: item[1])[0] if positives else "none"


def _review_focus(loss_bucket: str, loss_source: str, duplicate_count: int) -> str:
    focus = []
    if loss_bucket != "none":
        focus.append(f"exit_reason={loss_bucket}")
    if loss_source != "none":
        focus.append(f"source={loss_source}")
    if duplicate_count:
        focus.append("duplicate_suspects")
    return ", ".join(focus) if focus else "collect_more_data"
