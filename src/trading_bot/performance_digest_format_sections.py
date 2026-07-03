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
        f"- buy_count: {buy_count}",
        f"- fill_history_sell_rows: {fill_sells}",
        f"- duplicate_suspects: {stats['duplicate_count']} {duplicate_status}",
    ]


def decision_lines(status: str) -> list[str]:
    if status == "OK":
        return ["- 데이터 품질 OK", "- 전략 변경 판단 가능"]
    return ["- 전략 변경 보류", "- 먼저 매칭/중복/PnL 대조 문제 수정 필요"]


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
                f"candidate_id={sample.get('candidate_id')}, evaluation_id={sample.get('evaluation_id')}"
            )
    return lines


def duplicate_suspects_section(title: str, stats: dict[str, Any]) -> list[str]:
    suspects = stats["duplicate_suspects"]
    lines = [
        f"{title}:",
        f"- count: {suspects['count']}",
        f"- grouping_key: {suspects['grouping_key']}",
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
