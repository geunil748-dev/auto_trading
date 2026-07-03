from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from trading_bot.performance_digest_aggregates import bucket_stats, overall_metrics
from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS,
    SCORE_BUCKETS,
    SOURCE_BUCKETS,
    UNKNOWN,
    exit_reason_bucket,
    is_buy,
    is_sell,
    score_bucket,
    source_bucket,
)
from trading_bot.performance_digest_duplicates import build_duplicate_suspects
from trading_bot.performance_digest_diagnostics import (
    build_unmatched_breakdown,
    matched_ratio_metrics,
)
from trading_bot.performance_digest_interpretation import interpretation
from trading_bot.performance_digest_reconciliation import (
    build_reconciliation_detail,
    realized_pnl_sources,
)
from trading_bot.performance_digest_quality import (
    count_consistency_status,
    data_status,
    data_status_reasons,
    limited_notes,
    matched_trade_count,
    realized_exit_count,
    reconciliation_metrics,
    safe_buy_count,
    safe_fill_history_buy_rows,
    safe_fill_history_sell_rows,
    unmatched_count,
)


def collect_scope_stats(
    rows_by_name: Mapping[str, list[dict[str, Any]]],
    *,
    missing: Sequence[str],
    errors: Sequence[str],
    failure_notes: Sequence[str],
    fill_sheet_available: bool,
    score_sheet_available: bool,
    source_sheet_available: bool,
) -> dict[str, Any]:
    pnl_by_day_rows = rows_by_name["pnl_by_day"]
    exit_reason_rows = rows_by_name["pnl_by_exit_reason"]
    score_rows = rows_by_name["pnl_by_score_bucket"]
    source_rows = rows_by_name["pnl_by_source"]
    fill_rows = rows_by_name["fill_history"]
    candidate_rows = rows_by_name.get("candidate_orders_matched", [])
    candidate_evaluation_rows = rows_by_name.get("candidate_evaluations", [])
    duplicate_rows = rows_by_name["duplicate_suspects"]
    sell_rows = [row for row in fill_rows if is_sell(row.get("side"))]
    buy_rows = [row for row in fill_rows if is_buy(row.get("side"))]
    parseable_fill_rows = len(sell_rows) + len(buy_rows)
    overall = overall_metrics(pnl_by_day_rows, sell_rows, buy_rows)
    exit_stats = bucket_stats(
        exit_reason_rows,
        key_name="exit_reason",
        buckets=EXIT_REASON_BUCKETS,
        normalizer=exit_reason_bucket,
    )
    score_stats = bucket_stats(
        score_rows,
        key_name="score_bucket",
        buckets=SCORE_BUCKETS,
        normalizer=score_bucket,
    )
    source_stats = bucket_stats(
        source_rows,
        key_name="source",
        buckets=SOURCE_BUCKETS,
        normalizer=source_bucket,
    )
    realized_exit_count_value = realized_exit_count(overall, exit_stats, pnl_by_day_rows, fill_sheet_available)
    matched_trade_count_value = matched_trade_count(
        score_stats,
        source_stats,
        score_rows,
        source_rows,
        score_sheet_available,
        source_sheet_available,
    )
    overall["sell_count"] = realized_exit_count_value
    overall["realized_exit_count"] = realized_exit_count_value
    overall["matched_trade_count"] = matched_trade_count_value
    overall["unmatched_trade_count"] = unmatched_count(realized_exit_count_value, matched_trade_count_value)
    matched_ratio = matched_ratio_metrics(realized_exit_count_value, matched_trade_count_value)
    overall["matched_ratio"] = matched_ratio["ratio"]
    overall["matched_ratio_status"] = matched_ratio["status"]
    overall["buy_count"] = safe_buy_count(
        buy_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )
    fill_history_buy_rows = safe_fill_history_buy_rows(
        buy_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )
    duplicate_suspects = build_duplicate_suspects(duplicate_rows)
    duplicate_count = int(duplicate_suspects["count"])
    reconciliation = reconciliation_metrics(
        rows_by_name["summary_reconciliation"],
        overall.get("realized_pnl"),
    )
    fill_history_sell_rows = safe_fill_history_sell_rows(
        sell_rows,
        fill_sheet_available,
        parseable_fill_rows,
        realized_exit_count_value,
    )
    buy_count_status = (
        "missing_or_unparsed" if overall["buy_count"] == UNKNOWN else "computed_from_fill_history"
    )
    count_consistency_status_value = count_consistency_status(
        realized_exit_count_value,
        matched_trade_count_value,
        fill_history_sell_rows,
        overall["buy_count"],
    )
    limited = limited_notes(
        missing,
        errors,
        failure_notes,
        realized_exit_count_value,
        matched_trade_count_value,
        fill_history_sell_rows,
        overall["buy_count"],
        count_consistency_status_value,
    )
    realized_pnl_sources_value = realized_pnl_sources(
        sell_rows=sell_rows,
        fill_history_sell_rows=fill_history_sell_rows,
        score_rows=score_rows,
        source_rows=source_rows,
        exit_stats=exit_stats,
        overall=overall,
        reconciliation=reconciliation,
    )
    overall.update(
        {
            "fill_history_buy_rows": fill_history_buy_rows,
            "fill_history_sell_rows": fill_history_sell_rows,
            "realized_pnl_from_fill_history": realized_pnl_sources_value["raw_sell_fills"],
            "realized_pnl_from_daily_summary": realized_pnl_sources_value["daily_summary"],
            "realized_pnl_from_raw_sell_fills": realized_pnl_sources_value["raw_sell_fills"],
            "realized_pnl_from_matched_trades_only": realized_pnl_sources_value["matched_trades_only"],
            "realized_pnl_from_daily_ops_summary": realized_pnl_sources_value["daily_summary"],
            "realized_pnl_from_strategy_review_sheet": realized_pnl_sources_value["strategy_review_sheet"],
            "realized_pnl_from_exit_reason_sum": realized_pnl_sources_value["exit_reason_sum"],
        }
    )
    unmatched_breakdown = build_unmatched_breakdown(
        sell_rows=sell_rows,
        buy_rows=buy_rows,
        candidate_rows=candidate_rows,
        candidate_evaluation_rows=candidate_evaluation_rows,
        duplicate_rows=duplicate_rows,
        realized_exit_count=realized_exit_count_value,
        matched_trade_count=matched_trade_count_value,
    )
    reconciliation_detail = build_reconciliation_detail(
        raw_sell_fills=realized_pnl_sources_value["raw_sell_fills"],
        matched_trades_only=realized_pnl_sources_value["matched_trades_only"],
        daily_summary=realized_pnl_sources_value["daily_summary"],
        strategy_review_sheet=realized_pnl_sources_value["strategy_review_sheet"],
        exit_reason_sum=realized_pnl_sources_value["exit_reason_sum"],
        unmatched_count=overall["unmatched_trade_count"],
        duplicate_count=duplicate_count,
        reconciliation_gap_abs=reconciliation["reconciliation_gap_abs"],
        duplicate_suspects=duplicate_suspects,
    )
    data_status_value = data_status(limited, reconciliation["status"], count_consistency_status_value)
    status_reasons = data_status_reasons(
        notes=limited,
        reconciliation=reconciliation,
        matched_ratio_status=str(matched_ratio["status"]),
        duplicate_count=duplicate_count,
    )
    return {
        "overall": overall,
        "exit_stats": exit_stats,
        "score_stats": score_stats,
        "source_stats": source_stats,
        "duplicate_count": duplicate_count,
        "duplicate_suspects": duplicate_suspects,
        "unmatched_breakdown": unmatched_breakdown,
        "reconciliation": reconciliation,
        "reconciliation_detail": reconciliation_detail,
        "missing_or_limited": limited,
        "data_status_reason": status_reasons,
        "data_status": data_status_value,
        "interpretation": interpretation(
            exit_stats,
            source_stats,
            overall,
            duplicate_count,
            data_status_value,
            status_reasons,
        ),
        "fill_history_sell_rows": fill_history_sell_rows,
        "fill_history_buy_rows": fill_history_buy_rows,
        "buy_count_status": buy_count_status,
        "count_consistency_status": count_consistency_status_value,
    }


def filter_rows_by_date(
    rows: Sequence[Mapping[str, Any]],
    target_date: date | str | None,
) -> list[dict[str, Any]]:
    if target_date is None:
        return []
    expected = _date_key(target_date)
    return [
        dict(row)
        for row in rows
        if _date_key(row.get("trade_date") or row.get("trading_date")) == expected
    ]


def _date_key(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return text[:10]
