from __future__ import annotations

import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS,
    SCORE_BUCKETS,
    SOURCE_BUCKETS,
    UNKNOWN,
    BucketStats,
)
from trading_bot.performance_digest_format_sections import (
    candidate_ambiguity_breakdown_section,
    candidate_matching_quality_section,
    decision_lines,
    duplicate_suspects_section,
    linkage_limitations_section,
    matching_quality_section,
    quality_overview_lines,
    reconciliation_detail_section,
    score_source_guardrail_lines,
    unmatched_breakdown_section,
)
from trading_bot.performance_digest_packet import format_auto_trading_data_packet


def format_strategy_review_digest(
    stats: dict[str, Any],
    *,
    marker: str,
    report_date: date | str,
    date_from: date | str,
    date_to: date | str,
    source_xlsx: Path | str,
    max_chars: int,
    default_max_chars: int,
) -> str:
    daily = stats["daily"]
    cumulative = stats["cumulative"]
    status = _worst_status(daily["data_status"], cumulative["data_status"])
    lines = [
        marker,
        "[Daily Strategy Review]",
        f"Status: {status}",
        f"Report date: {_date_text(report_date)}",
        "Data quality:",
        *quality_overview_lines(cumulative, money=_money, pct=_pct),
        "",
        "Decision:",
        *decision_lines(status, cumulative),
        "",
        f"report_date: {_date_text(report_date)}",
        "date_range_basis: cumulative",
        f"daily_range: {_date_text(date_to)}..{_date_text(date_to)}",
        f"cumulative_range: {_date_text(date_from)}..{_date_text(date_to)}",
        f"source_xlsx: {Path(source_xlsx)}",
        f"daily_data_status: {daily['data_status']}",
        f"cumulative_data_status: {cumulative['data_status']}",
        "",
        *_overall_section("daily_overall", daily, include_note=True),
        "",
        *_overall_section("cumulative_overall", cumulative),
        "",
        *matching_quality_section("daily_matching_quality", daily, pct=_pct),
        "",
        *matching_quality_section("cumulative_matching_quality", cumulative, pct=_pct),
        "",
        *candidate_matching_quality_section("daily_candidate_matching_quality", daily),
        "",
        *candidate_matching_quality_section("cumulative_candidate_matching_quality", cumulative),
        "",
        *candidate_ambiguity_breakdown_section("daily_candidate_ambiguity_breakdown", daily),
        "",
        *candidate_ambiguity_breakdown_section("cumulative_candidate_ambiguity_breakdown", cumulative),
        "",
        *linkage_limitations_section("linkage_limitations", cumulative),
        "",
        *reconciliation_detail_section("daily_reconciliation_detail", daily, money=_money),
        "",
        *reconciliation_detail_section("cumulative_reconciliation_detail", cumulative, money=_money),
        "",
        *unmatched_breakdown_section("daily_unmatched_breakdown", daily),
        "",
        *unmatched_breakdown_section("cumulative_unmatched_breakdown", cumulative),
        "",
        *duplicate_suspects_section("duplicate_suspects", cumulative),
        "",
        "daily_pnl_by_exit_reason:",
        f"- basis: {stats['exit_reason_basis']}",
        *_bucket_lines(daily["exit_stats"], EXIT_REASON_BUCKETS),
        "",
        "cumulative_pnl_by_exit_reason:",
        f"- basis: {stats['exit_reason_basis']}",
        *_bucket_lines(cumulative["exit_stats"], EXIT_REASON_BUCKETS),
        "",
        "daily_pnl_by_score_bucket:",
        f"- basis: {stats['score_source_basis']}",
        f"- matched_sell_count: {daily['overall']['matched_trade_count']}",
        f"- confidence: {daily['interpretation']['score_source_confidence']}",
        *score_source_guardrail_lines(daily),
        *_bucket_lines(daily["score_stats"], SCORE_BUCKETS, include_zero=False),
        "",
        "cumulative_pnl_by_score_bucket:",
        f"- basis: {stats['score_source_basis']}",
        f"- matched_sell_count: {cumulative['overall']['matched_trade_count']}",
        f"- confidence: {cumulative['interpretation']['score_source_confidence']}",
        *score_source_guardrail_lines(cumulative),
        *_bucket_lines(cumulative["score_stats"], SCORE_BUCKETS, include_zero=False),
        "",
        "daily_pnl_by_source:",
        f"- basis: {stats['score_source_basis']}",
        f"- matched_sell_count: {daily['overall']['matched_trade_count']}",
        f"- confidence: {daily['interpretation']['score_source_confidence']}",
        *score_source_guardrail_lines(daily),
        *_bucket_lines(daily["source_stats"], SOURCE_BUCKETS, include_zero=False),
        "",
        "cumulative_pnl_by_source:",
        f"- basis: {stats['score_source_basis']}",
        f"- matched_sell_count: {cumulative['overall']['matched_trade_count']}",
        f"- confidence: {cumulative['interpretation']['score_source_confidence']}",
        *score_source_guardrail_lines(cumulative),
        *_bucket_lines(cumulative["source_stats"], SOURCE_BUCKETS, include_zero=False),
        "",
        "data_quality:",
        f"- daily_data_status: {daily['data_status']}",
        f"- cumulative_data_status: {cumulative['data_status']}",
        "- count_basis: daily_and_cumulative_separated",
        f"- daily_duplicate_suspects_count: {daily['duplicate_count']}",
        f"- cumulative_duplicate_suspects_count: {cumulative['duplicate_count']}",
        f"- daily_matched_ratio: {_pct(daily['overall']['matched_ratio'])} {daily['overall']['matched_ratio_status']}",
        f"- cumulative_matched_ratio: {_pct(cumulative['overall']['matched_ratio'])} {cumulative['overall']['matched_ratio_status']}",
        f"- daily_fill_history_buy_rows: {daily['fill_history_buy_rows']}",
        f"- cumulative_fill_history_buy_rows: {cumulative['fill_history_buy_rows']}",
        f"- daily_fill_history_sell_rows: {daily['fill_history_sell_rows']}",
        f"- cumulative_fill_history_sell_rows: {cumulative['fill_history_sell_rows']}",
        f"- daily_count_consistency_status: {daily['count_consistency_status']}",
        f"- cumulative_count_consistency_status: {cumulative['count_consistency_status']}",
        f"- daily_reconciliation_status: {daily['reconciliation']['status']}",
        f"- cumulative_reconciliation_status: {cumulative['reconciliation']['status']}",
        f"- daily_reconciliation_gap: {_money(daily['reconciliation']['reconciliation_gap'])}",
        f"- cumulative_reconciliation_gap: {_money(cumulative['reconciliation']['reconciliation_gap'])}",
        f"- daily_reconciliation_gap_abs: {_money(daily['reconciliation']['reconciliation_gap_abs'])}",
        f"- cumulative_reconciliation_gap_abs: {_money(cumulative['reconciliation']['reconciliation_gap_abs'])}",
        f"- daily_reconciliation_gap_pct: {_pct(daily['reconciliation']['reconciliation_gap_pct'])}",
        f"- cumulative_reconciliation_gap_pct: {_pct(cumulative['reconciliation']['reconciliation_gap_pct'])}",
        f"- reconciliation_gap_basis: {cumulative['reconciliation']['reconciliation_gap_basis']}",
        f"- daily_data_status_reason: {_join_notes(daily['data_status_reason'])}",
        f"- cumulative_data_status_reason: {_join_notes(cumulative['data_status_reason'])}",
        f"- missing_or_limited_fields: {_join_notes(stats['missing_or_limited'])}",
        "",
        "interpretation:",
        f"- daily_main_loss_driver: {daily['interpretation']['main_loss_driver']}",
        f"- cumulative_main_loss_driver: {cumulative['interpretation']['main_loss_driver']}",
        f"- daily_strategy_change_signal: {daily['interpretation']['strategy_change_signal']}",
        f"- cumulative_strategy_change_signal: {cumulative['interpretation']['strategy_change_signal']}",
        f"- daily_confidence: {daily['interpretation']['confidence']}",
        f"- cumulative_confidence: {cumulative['interpretation']['confidence']}",
        f"- reason: {_join_notes(cumulative['interpretation']['reason'])}",
        f"- provisional_observation: {_join_notes(cumulative['interpretation']['provisional_observation'])}",
        f"- recommended_review_focus: {_review_focus(daily, cumulative)}",
        "",
        *format_auto_trading_data_packet(
            stats,
            report_date=report_date,
            date_from=date_from,
            date_to=date_to,
            source_xlsx=source_xlsx,
        ),
    ]
    return _truncate_digest("\n".join(lines), max_chars, default_max_chars)


def save_strategy_review_digest(text: str, strategy_review_path: Path | str) -> Path:
    xlsx_path = Path(strategy_review_path)
    digest_path = xlsx_path.with_name(
        xlsx_path.name.replace("strategy_review_", "strategy_digest_").removesuffix(".xlsx")
        + ".txt"
    )
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    digest_path.write_text(text, encoding="utf-8", newline="\n")
    return digest_path


def _bucket_lines(
    stats: dict[str, BucketStats],
    buckets: tuple[str, ...],
    *,
    include_zero: bool = True,
) -> list[str]:
    lines = [
        (
            f"- {bucket}: sell_count={stats.get(bucket, BucketStats()).sell_count}, "
            f"pnl={_money(stats.get(bucket, BucketStats()).total_profit_usd)}, "
            f"win_rate={_pct(stats.get(bucket, BucketStats()).win_rate)}"
        )
        for bucket in buckets
        if include_zero
        or stats.get(bucket, BucketStats()).sell_count
        or stats.get(bucket, BucketStats()).total_profit_usd
    ]
    return lines or ["- no_matched_rows: sell_count=0, pnl=0.00, win_rate=0.00%"]


def _overall_section(
    title: str,
    stats: dict[str, Any],
    *,
    include_note: bool = False,
) -> list[str]:
    overall = stats["overall"]
    lines = [
        f"{title}:",
        f"- buy_count: {overall['buy_count']}",
        f"- sell_count: {overall['sell_count']}",
        f"- fill_history_buy_rows: {overall['fill_history_buy_rows']}",
        f"- fill_history_sell_rows: {overall['fill_history_sell_rows']}",
        f"- realized_pnl: {_money(overall['realized_pnl'])}",
        f"- realized_pnl_from_fill_history: {_money(overall['realized_pnl_from_fill_history'])}",
        f"- realized_pnl_from_daily_summary: {_money(overall['realized_pnl_from_daily_summary'])}",
        f"- realized_pnl_from_raw_sell_fills: {_money(overall['realized_pnl_from_raw_sell_fills'])}",
        f"- realized_pnl_from_matched_trades_only: {_money(overall['realized_pnl_from_matched_trades_only'])}",
        f"- realized_pnl_from_daily_ops_summary: {_money(overall['realized_pnl_from_daily_ops_summary'])}",
        f"- realized_pnl_from_strategy_review_sheet: {_money(overall['realized_pnl_from_strategy_review_sheet'])}",
        f"- realized_pnl_from_exit_reason_sum: {_money(overall['realized_pnl_from_exit_reason_sum'])}",
        f"- realized_return: {_pct(overall['realized_return'])}",
        f"- win_rate: {_pct(overall['win_rate'])}",
        f"- avg_win: {_money(overall['avg_win'])}",
        f"- avg_loss: {_money(overall['avg_loss'])}",
        f"- profit_factor: {_ratio(overall['profit_factor'])}",
        f"- realized_exit_count: {overall['realized_exit_count']}",
        f"- matched_trade_count: {overall['matched_trade_count']}",
        f"- unmatched_trade_count: {overall['unmatched_trade_count']}",
        f"- matched_ratio: {_pct(overall['matched_ratio'])} {overall['matched_ratio_status']}",
        f"- reconciliation_gap: {_money(stats['reconciliation']['reconciliation_gap'])}",
        f"- reconciliation_gap_abs: {_money(stats['reconciliation']['reconciliation_gap_abs'])}",
        f"- reconciliation_gap_pct: {_pct(stats['reconciliation']['reconciliation_gap_pct'])}",
        f"- reconciliation_status: {stats['reconciliation']['status']}",
        f"- count_consistency_status: {stats['count_consistency_status']}",
        f"- data_status: {stats['data_status']}",
        f"- data_status_reason: {_join_notes(stats['data_status_reason'])}",
    ]
    if include_note and overall["sell_count"] == 0:
        lines.append("- note: no trades for report_date")
    return lines


def _review_focus(daily: dict[str, Any], cumulative: dict[str, Any]) -> str:
    daily_focus = daily["interpretation"]["recommended_review_focus"]
    cumulative_focus = cumulative["interpretation"]["recommended_review_focus"]
    if daily_focus == cumulative_focus:
        return daily_focus
    return f"daily={daily_focus}; cumulative={cumulative_focus}"


def _date_text(value: date | str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _money(value: object) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return f"{float(value or 0):.2f}"


def _pct(value: object) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return f"{float(value or 0) * 100:.2f}%"


def _ratio(value: object) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    if isinstance(value, (int, float)) and math.isinf(float(value)):
        return "inf"
    return f"{float(value or 0):.2f}"


def _join_notes(notes: list[str]) -> str:
    return ", ".join(notes) if notes else "none"


def _worst_status(*statuses: str) -> str:
    rank = {"OK": 0, "WARN": 1, "FAIL": 2}
    return max(statuses, key=lambda status: rank.get(status, 1))


def _truncate_digest(text: str, max_chars: int, default_max_chars: int) -> str:
    if max_chars <= 0:
        max_chars = default_max_chars
    if len(text) <= max_chars:
        return text
    suffix = "\n[truncated: max_chars]"
    return text[: max_chars - len(suffix)].rstrip() + suffix
