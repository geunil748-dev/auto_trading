from __future__ import annotations

from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN


def quality_overview_lines(stats: dict[str, Any], *, money, pct) -> list[str]:
    overall = stats["overall"]
    buy_count = "missing" if overall["buy_count"] == UNKNOWN else overall["buy_count"]
    fill_sells = "missing" if stats["fill_history_sell_rows"] == UNKNOWN else stats["fill_history_sell_rows"]
    duplicate_status = "WARN" if stats["duplicate_count"] else "OK"
    return [
        f"- matched_ratio: {pct(overall['matched_ratio'])} {overall['matched_ratio_status']}",
        f"- reconciliation_gap: {money(stats['reconciliation']['reconciliation_gap_abs'])} {stats['reconciliation']['status']}",
        f"- reconciliation_status: {stats['reconciliation']['status']}",
        f"- buy_count: {buy_count}",
        f"- fill_history_sell_rows: {fill_sells}",
        f"- duplicate_suspects: {stats['duplicate_count']} {duplicate_status}",
        f"- unknown_reason_count: {stats['matching_quality']['unknown_reason_count']}",
        f"- multiple_candidate_ambiguous_count: {stats['candidate_matching_quality']['multiple_candidate_ambiguous_count']}",
        f"- still_ambiguous_count: {stats['candidate_matching_quality']['still_ambiguous_count']}",
        f"- score_source_analysis_eligible_count: {stats['candidate_matching_quality']['score_source_analysis_eligible_count']}",
        f"- next_data_quality_fix: {stats['matching_recommendation']['next_data_quality_fix']}",
    ]


def decision_lines(status: str, stats: dict[str, Any] | None = None) -> list[str]:
    if status == "OK":
        return ["- 데이터 품질 OK", "- 전략 변경 판단 가능"]
    lines = ["- 전략 변경 보류", "- 먼저 매칭/중복/PnL 대조 문제 수정 필요"]
    if stats and stats["overall"]["matched_ratio_status"] == "FAIL":
        lines.append("- score/source strategy signal disabled below matched_ratio threshold")
    if stats and stats["matching_quality"]["unknown_reason_count"] > 0:
        lines.append("- 매칭 진단 추가 필요")
    if stats and stats["candidate_matching_quality"]["still_ambiguous_count"] > 0:
        lines.append("- candidate/order linkage is incomplete in current report data")
    return lines


def reconciliation_detail_section(title: str, stats: dict[str, Any], *, money) -> list[str]:
    detail = stats["reconciliation_detail"]
    return [
        f"{title}:",
        f"- raw_sell_fills_vs_daily_summary: {money(detail['raw_sell_fills_vs_daily_summary'])}",
        f"- raw_sell_fills_vs_exit_reason_sum: {money(detail['raw_sell_fills_vs_exit_reason_sum'])}",
        f"- strategy_review_vs_daily_summary: {money(detail['strategy_review_vs_daily_summary'])}",
        f"- strategy_review_vs_exit_reason_sum: {money(detail['strategy_review_vs_exit_reason_sum'])}",
        f"- matched_only_vs_all_sells: {money(detail['matched_only_vs_all_sells'])}",
        f"- suspected_causes: {_join_notes(detail['suspected_causes'])}",
    ]


def matching_quality_section(title: str, stats: dict[str, Any], *, pct) -> list[str]:
    quality = stats["matching_quality"]
    return [
        f"{title}:",
        f"- sell_count: {quality['sell_count']}",
        f"- matched_trade_count: {quality['matched_trade_count']}",
        f"- matched_ratio: {pct(quality['matched_ratio'])}",
        f"- high_confidence_match_count: {quality['high_confidence_match_count']}",
        f"- medium_confidence_match_count: {quality['medium_confidence_match_count']}",
        f"- low_confidence_match_count: {quality['low_confidence_match_count']}",
        f"- unmatched_trade_count: {quality['unmatched_trade_count']}",
        f"- unknown_reason_count: {quality['unknown_reason_count']}",
        f"- ambiguous_match_count: {quality['ambiguous_match_count']}",
        f"- next_data_quality_fix: {stats['matching_recommendation']['next_data_quality_fix']}",
        f"- recommendation_category: {stats['matching_recommendation']['category']}",
    ]


def candidate_matching_quality_section(title: str, stats: dict[str, Any]) -> list[str]:
    quality = stats["candidate_matching_quality"]
    return [
        f"{title}:",
        f"- multiple_candidate_ambiguous_count: {quality['multiple_candidate_ambiguous_count']}",
        f"- resolved_by_explicit_link_count: {quality['resolved_by_explicit_link_count']}",
        f"- resolved_by_unique_submitted_candidate_count: {quality['resolved_by_unique_submitted_candidate_count']}",
        f"- resolved_by_time_lifecycle_count: {quality['resolved_by_time_lifecycle_count']}",
        f"- still_ambiguous_count: {quality['still_ambiguous_count']}",
        f"- candidate_after_buy_excluded_count: {quality['candidate_after_buy_excluded_count']}",
        f"- candidate_blocked_excluded_count: {quality['candidate_blocked_excluded_count']}",
        f"- candidate_missing_link_count: {quality['candidate_missing_link_count']}",
        f"- score_source_analysis_eligible_count: {quality['score_source_analysis_eligible_count']}",
        f"- score_source_analysis_excluded_count: {quality['score_source_analysis_excluded_count']}",
        f"- ambiguous_rows_realized_pnl_sum: {quality['ambiguous_rows_realized_pnl_sum']:.2f}",
        f"- score_source_excluded_pnl_sum: {quality['score_source_excluded_pnl_sum']:.2f}",
        f"- next_required_link_field: {quality['next_required_link_field']}",
    ]


def candidate_ambiguity_breakdown_section(title: str, stats: dict[str, Any]) -> list[str]:
    breakdown = stats["candidate_ambiguity_breakdown"]
    lines = [
        f"{title}:",
        f"- next_required_link_field: {breakdown['next_required_link_field']}",
    ]
    for item in breakdown["reasons"]:
        lines.append(f"- {item['reason']}: count={item['count']}")
        for sample in item.get("samples", [])[:5]:
            lines.append(
                "- sample: "
                f"row_no={sample.get('row_no')}, trade_date={sample.get('trade_date')}, "
                f"symbol={sample.get('symbol')}, buy_time={sample.get('buy_time')}, "
                f"sell_time={sample.get('sell_time')}, active_candidate={sample.get('active_candidate_candidate_id')}, "
                f"diagnostic_detail={sample.get('diagnostic_detail')}"
            )
    return lines


def linkage_limitations_section(title: str, stats: dict[str, Any]) -> list[str]:
    limitation = stats["linkage_limitations"]
    return [
        f"{title}:",
        f"- explicit_candidate_order_link_available: {str(limitation['explicit_candidate_order_link_available']).lower()}",
        f"- effect: {limitation['effect']}",
        f"- action_for_chatgpt: {limitation['action_for_chatgpt']}",
        f"- still_ambiguous_count: {limitation['still_ambiguous_count']}",
    ]


def unmatched_breakdown_section(title: str, stats: dict[str, Any]) -> list[str]:
    breakdown = stats["unmatched_breakdown"]
    lines = [
        f"{title}:",
        f"- count: {breakdown['count']}",
        f"- count_basis: {breakdown['count_basis']}",
    ]
    for item in breakdown["reasons"]:
        lines.append(f"- {item['reason']}: count={item['count']}")
        for sample in item.get("samples", [])[:5]:
            lines.append(
                "- sample: "
                f"trade_date={sample.get('trade_date')}, symbol={sample.get('symbol')}, "
                f"sell_time={sample.get('sell_time')}, sell_price={sample.get('sell_price')}, "
                f"pnl={sample.get('pnl')}, order_id={sample.get('order_id')}, "
                f"candidate_id={sample.get('candidate_id')}, evaluation_id={sample.get('evaluation_id')}, "
                f"missing_fields={sample.get('missing_fields')}, diagnostic_detail={sample.get('diagnostic_detail')}"
            )
    return lines


def duplicate_suspects_section(title: str, stats: dict[str, Any]) -> list[str]:
    suspects = stats["duplicate_suspects"]
    lines = [
        f"{title}:",
        f"- count: {suspects['count']}",
        f"- grouping_key: {suspects['grouping_key']}",
        f"- confidence_counts: {_format_counts(suspects.get('confidence_counts', {}))}",
        f"- duplicate_reason_counts: {_format_counts(suspects.get('duplicate_reason_counts', {}))}",
        f"- partial_fill_candidate_count: {suspects.get('partial_fill_candidate_count', 0)}",
        f"- true_duplicate_candidate_count: {suspects.get('true_duplicate_candidate_count', 0)}",
    ]
    for sample in suspects["samples"]:
        lines.append(
            "- sample: "
            f"trade_date={sample.get('trade_date')}, symbol={sample.get('symbol')}, "
            f"side={sample.get('side')}, order_id={sample.get('order_id')}, "
            f"fill_id={sample.get('fill_id')}, fill_time={sample.get('fill_time')}, "
            f"qty={sample.get('qty')}, price={sample.get('price')}, "
            f"realized_pnl={sample.get('realized_pnl')}, duplicate_reason={sample.get('duplicate_reason')}, "
            f"DUPLICATE_CONFIDENCE={sample.get('duplicate_confidence')}"
        )
    return lines


def score_source_guardrail_lines(stats: dict[str, Any]) -> list[str]:
    if stats["overall"]["matched_ratio_status"] == "FAIL":
        return ["- signal_usage: disabled_below_50_percent_matched_ratio"]
    if stats["overall"]["matched_ratio_status"] == "WARN":
        return ["- signal_usage: provisional_matched_ratio_below_ok_threshold"]
    return ["- signal_usage: allowed"]


def _join_notes(notes: list[str]) -> str:
    return ", ".join(notes) if notes else "none"


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) if counts else "none"
