from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN, BucketStats, num
from trading_bot.performance_digest_diagnostics import matched_ratio_metrics


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


def safe_fill_history_buy_rows(
    buy_rows: Sequence[Mapping[str, Any]],
    fill_sheet_available: bool,
    parseable_fill_rows: int,
    realized_exit_count_value: object,
) -> int | str:
    return safe_buy_count(
        buy_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )


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
    ratio_status = matched_ratio_metrics(realized_exit_count_value, matched_trade_count_value)["status"]
    if ratio_status == "FAIL":
        return "FAIL"
    if UNKNOWN in {realized_exit_count_value, matched_trade_count_value, fill_history_sell_rows, buy_count}:
        return "WARN"
    if ratio_status == "WARN":
        return "WARN"
    realized = count_or_none(realized_exit_count_value)
    fill_sells = count_or_none(fill_history_sell_rows)
    if realized is not None and fill_sells is not None and realized != fill_sells:
        return "WARN"
    return "OK"


def reconciliation_metrics(
    rows: Sequence[Mapping[str, Any]],
    realized_pnl: object,
) -> dict[str, float | str]:
    if not rows:
        realized_value = num(realized_pnl)
        status = "OK" if abs(realized_value) <= 1.0 else "WARN"
        return {
            "status": status,
            "daily_summary_realized_pnl": UNKNOWN,
            "reconciliation_gap": UNKNOWN,
            "reconciliation_gap_abs": UNKNOWN,
            "reconciliation_gap_pct": UNKNOWN,
            "reconciliation_gap_signed": UNKNOWN,
            "reconciliation_gap_basis": "missing_summary_reconciliation",
        }
    daily_pnl = sum(num(row.get("daily_run_realized_profit_usd")) for row in rows)
    realized_value = num(realized_pnl)
    signed_gap = realized_value - daily_pnl
    gap = abs(signed_gap)
    gap_pct = gap / abs(realized_value) if realized_value else (0.0 if gap == 0 else UNKNOWN)
    return {
        "status": reconciliation_status(gap),
        "daily_summary_realized_pnl": daily_pnl,
        "reconciliation_gap": gap,
        "reconciliation_gap_abs": gap,
        "reconciliation_gap_pct": gap_pct,
        "reconciliation_gap_signed": signed_gap,
        "reconciliation_gap_basis": "abs(realized_pnl - daily_summary_realized_pnl)",
    }


def reconciliation_status(gap_abs: object) -> str:
    if gap_abs == UNKNOWN:
        return "WARN"
    gap = float(gap_abs or 0.0)
    if gap <= 1.0:
        return "OK"
    if gap <= 50.0:
        return "WARN"
    return "FAIL"


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
    if reconciliation_status == "FAIL" or count_consistency_status_value == "FAIL":
        return "FAIL"
    if any(note.startswith("sheet_error:") or note.startswith("export_failure:") for note in notes):
        return "WARN"
    if reconciliation_status == "WARN" or count_consistency_status_value == "WARN":
        return "WARN"
    return "WARN" if notes else "OK"


def data_status_reasons(
    *,
    notes: Sequence[str],
    reconciliation: Mapping[str, Any],
    matched_ratio_status: str,
    duplicate_count: int,
) -> list[str]:
    reasons: list[str] = []
    if matched_ratio_status == "FAIL":
        reasons.append("matched_ratio below threshold")
    elif matched_ratio_status == "WARN":
        reasons.append("matched_ratio below OK threshold")
    if reconciliation.get("status") == "FAIL":
        reasons.append("reconciliation gap too large")
    elif reconciliation.get("status") == "WARN":
        reasons.append("reconciliation gap requires review")
    if (
        reconciliation.get("status") == "WARN"
        and reconciliation.get("reconciliation_gap_abs") != UNKNOWN
    ):
        reasons.append("possible fees/taxes/slippage/fx/rounding difference")
    if "buy_count" in notes:
        reasons.append("buy_count missing")
    if "fill_history_sell_rows" in notes:
        reasons.append("fill_history_sell_rows missing")
    if duplicate_count:
        reasons.append("duplicate_suspects_count > 0")
    for note in notes:
        if note not in {"buy_count", "fill_history_sell_rows"} and note not in reasons:
            reasons.append(note)
    return reasons


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
