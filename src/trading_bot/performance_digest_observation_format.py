from __future__ import annotations

import math
from typing import Any, Callable


def observation_headline_lines(
    stats: dict[str, Any], *, money: Callable[[object], str], pct: Callable[[object], str]
) -> list[str]:
    cumulative = stats["cumulative"]
    audit = cumulative["performance_audit"]
    loss = cumulative["loss_observation"]
    intraday = cumulative["intraday_observation"]
    return [
        f"performance_basis: {stats['performance_basis']}",
        f"observation_status: {stats['observation_status']}",
        f"strategy_change_eligibility: {stats['strategy_change_eligibility']}",
        f"trusted_sell_count: {audit['trusted_sell_order_count']}",
        f"trusted_profit_usd: {money(audit['trusted_profit_usd'])}",
        f"best_effort_profit_usd: {money(audit['best_effort_profit_usd'])}",
        f"raw_profit_usd: {money(audit['raw_profit_usd'])}",
        f"raw_vs_trusted_profit_difference: {money(audit['raw_vs_trusted_profit_difference'])}",
        f"false_failure_count: {intraday['false_failure_count']}",
        f"required_data_incomplete_rate: {pct(intraday['required_data_incomplete_rate'])}",
        f"stop_loss_count: {loss['stop_loss_count']}",
        f"stop_loss_total_profit_usd: {money(loss['stop_loss_total_profit_usd'])}",
        f"stop_loss_share_of_gross_loss: {pct(loss['stop_loss_share_of_gross_loss'])}",
    ]


def overall_section(
    title: str,
    stats: dict[str, Any],
    *,
    money: Callable[[object], str],
    pct: Callable[[object], str],
    ratio: Callable[[object], str],
    join_notes: Callable[[list[str]], str],
    include_note: bool = False,
) -> list[str]:
    performance = stats["performance"]
    overall = performance["overall"]
    reconciliation = performance["reconciliation"]
    lines = [
        f"{title}:",
        f"- buy_count: {overall['buy_count']}",
        f"- sell_count: {overall['sell_count']}",
        f"- fill_history_buy_rows: {overall['fill_history_buy_rows']}",
        f"- fill_history_sell_rows: {overall['fill_history_sell_rows']}",
        f"- realized_pnl: {money(overall['realized_pnl'])}",
        f"- realized_pnl_from_fill_history: {money(overall['realized_pnl_from_fill_history'])}",
        f"- realized_pnl_from_daily_summary: {money(overall['realized_pnl_from_daily_summary'])}",
        f"- realized_pnl_from_raw_sell_fills: {money(overall['realized_pnl_from_raw_sell_fills'])}",
        f"- realized_pnl_from_matched_trades_only: {money(overall['realized_pnl_from_matched_trades_only'])}",
        f"- realized_pnl_from_daily_ops_summary: {money(overall['realized_pnl_from_daily_ops_summary'])}",
        f"- realized_pnl_from_strategy_review_sheet: {money(overall['realized_pnl_from_strategy_review_sheet'])}",
        f"- realized_pnl_from_exit_reason_sum: {money(overall['realized_pnl_from_exit_reason_sum'])}",
        f"- realized_return: {pct(overall['realized_return'])}",
        f"- win_rate: {pct(overall['win_rate'])}",
        f"- avg_win: {money(overall['avg_win'])}",
        f"- avg_loss: {money(overall['avg_loss'])}",
        f"- profit_factor: {ratio(overall['profit_factor'])}",
        f"- realized_exit_count: {overall['realized_exit_count']}",
        f"- matched_trade_count: {overall['matched_trade_count']}",
        f"- unmatched_trade_count: {overall['unmatched_trade_count']}",
        f"- matched_ratio: {pct(overall['matched_ratio'])} {overall['matched_ratio_status']}",
        f"- reconciliation_gap: {money(reconciliation['reconciliation_gap'])}",
        f"- reconciliation_gap_abs: {money(reconciliation['reconciliation_gap_abs'])}",
        f"- reconciliation_gap_pct: {pct(reconciliation['reconciliation_gap_pct'])}",
        f"- reconciliation_status: {reconciliation['status']}",
        f"- {_audit_label(stats, 'count_consistency_status')}: {stats['count_consistency_status']}",
        f"- {_audit_label(stats, 'data_status')}: {stats['data_status']}",
        f"- {_audit_label(stats, 'data_status_reason')}: {join_notes(stats['data_status_reason'])}",
    ]
    if include_note and overall["sell_count"] == 0:
        lines.append("- note: no trades for report_date")
    return lines


def observation_sections(
    stats: dict[str, Any], *, money: Callable[[object], str], pct: Callable[[object], str]
) -> list[str]:
    daily = stats["daily"]
    cumulative = stats["cumulative"]
    audit = cumulative["performance_audit"]
    warnings = ", ".join(stats["observation_warnings"]) or "none"
    missing = ", ".join(stats["normalized_missing_sheets"]) or "none"
    errors = ", ".join(stats["normalized_errors"]) or "none"
    return [
        "normalized_pnl_quality:",
        f"- performance_basis: {stats['performance_basis']}",
        f"- warnings: {warnings}",
        f"- normalized_missing_sheets: {missing}",
        f"- normalized_errors: {errors}",
        f"- mode_contamination_count: {stats['mode_contamination_count']}",
        f"- real_mode_row_count: {stats['real_mode_row_count']}",
        f"- unknown_mode_row_count: {stats['unknown_mode_row_count']}",
        f"- trusted_lineage_error_count: {stats['trusted_lineage_error_count']}",
        f"- trusted_exclusion_reason_counts: {_pairs(stats['trusted_exclusion_reason_counts'])}",
        f"- raw_sell_row_count: {audit['raw_sell_row_count']}",
        f"- raw_profit_usd: {money(audit['raw_profit_usd'])}",
        f"- trusted_sell_order_count: {audit['trusted_sell_order_count']}",
        f"- trusted_profit_usd: {money(audit['trusted_profit_usd'])}",
        f"- best_effort_sell_order_count: {audit['best_effort_sell_order_count']}",
        f"- best_effort_profit_usd: {money(audit['best_effort_profit_usd'])}",
        f"- raw_vs_trusted_count_difference: {audit['raw_vs_trusted_count_difference']}",
        f"- raw_vs_trusted_profit_difference: {money(audit['raw_vs_trusted_profit_difference'])}",
        f"- ambiguous_sell_order_count: {audit['ambiguous_sell_order_count']}",
        f"- ambiguous_profit_usd: {money(audit['ambiguous_profit_usd'])}",
        "",
        "intraday_data_quality_observation:",
        *_intraday_scope_lines("daily", daily["intraday_observation"], pct),
        *_intraday_scope_lines("cumulative", cumulative["intraday_observation"], pct),
        "",
        "loss_control_observation:",
        *_loss_scope_lines("daily", daily["loss_observation"], money, pct),
        *_loss_scope_lines("cumulative", cumulative["loss_observation"], money, pct),
        "",
        "review_gate:",
        f"- observation_status: {stats['observation_status']}",
        f"- strategy_change_eligibility: {stats['strategy_change_eligibility']}",
        "- automatic_strategy_change_allowed: false",
        "- completed_trade_thresholds: <15 HOLD_INSUFFICIENT_SAMPLE; 15-29 SHADOW_ANALYSIS_ONLY; >=30 REVIEW_ELIGIBLE",
    ]


def _pairs(values: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "none"


def _audit_label(stats: dict[str, Any], label: str) -> str:
    return f"raw_audit_{label}" if stats["performance_basis"] == "TRUSTED_NORMALIZED" else label


def _ratio(value: object) -> str:
    number = float(value or 0)
    return "inf" if math.isinf(number) else f"{number:.2f}"


def _intraday_scope_lines(
    scope: str, intraday: dict[str, Any], pct: Callable[[object], str]
) -> list[str]:
    lines = [
        f"{scope}:",
        f"- candidate_evaluation_count: {intraday['candidate_evaluation_count']}",
        f"- buy_allowed_count: {intraday['buy_allowed_count']}",
        f"- order_submitted_count: {intraday['order_submitted_count']}",
        f"- required_data_complete_count: {intraday['required_data_complete_count']}",
        f"- required_data_incomplete_count: {intraday['required_data_incomplete_count']}",
        f"- required_data_incomplete_rate: {pct(intraday['required_data_incomplete_rate'])}",
        f"- raw_data_complete_count: {intraday['raw_data_complete_count']}",
        f"- raw_data_incomplete_count: {intraday['raw_data_incomplete_count']}",
        f"- policy_log_only_count: {intraday['policy_log_only_count']}",
        f"- policy_block_count: {intraday['policy_block_count']}",
        f"- malformed_condition_json_count: {intraday['malformed_condition_json_count']}",
        f"- missing_condition_json_count: {intraday['missing_condition_json_count']}",
        f"- unknown_mode_candidate_count: {intraday['unknown_mode_candidate_count']}",
        f"- false_failure_count: {intraday['false_failure_count']}",
        f"- feature_missing_counts: {_pairs(intraday['feature_missing_counts'])}",
    ]
    for feature, states in intraday["condition_state_counts"].items():
        lines.append(f"- condition_state_{feature}: {_pairs(states)}")
    return lines


def _loss_scope_lines(
    scope: str, loss: dict[str, Any], money: Callable[[object], str],
    pct: Callable[[object], str],
) -> list[str]:
    return [
        f"{scope}:",
        f"- basis: {loss['basis']}",
        f"- trusted_sell_count: {loss['trusted_sell_count']}",
        f"- trusted_total_profit_usd: {money(loss['trusted_total_profit_usd'])}",
        f"- win_rate: {pct(loss['win_rate'])}",
        f"- avg_win: {money(loss['avg_win'])}",
        f"- avg_loss: {money(loss['avg_loss'])}",
        f"- profit_factor: {_ratio(loss['profit_factor'])}",
        f"- gross_profit_usd: {money(loss['gross_profit_usd'])}",
        f"- gross_loss_usd: {money(loss['gross_loss_usd'])}",
        f"- max_win: {money(loss['max_win'])}",
        f"- max_loss: {money(loss['max_loss'])}",
        f"- max_drawdown: {loss['max_drawdown']}",
        f"- stop_loss_count: {loss['stop_loss_count']}",
        f"- stop_loss_total_profit_usd: {money(loss['stop_loss_total_profit_usd'])}",
        f"- stop_loss_average_profit_usd: {money(loss['stop_loss_average_profit_usd'])}",
        f"- stop_loss_share_of_sell_count: {pct(loss['stop_loss_share_of_sell_count'])}",
        f"- stop_loss_share_of_gross_loss: {pct(loss['stop_loss_share_of_gross_loss'])}",
        f"- ambiguous_exit_count: {loss['ambiguous_exit_count']}",
        f"- other_exit_reasons: {', '.join(loss['other_exit_reasons']) or 'none'}",
        *_exit_reason_lines(loss, money),
    ]


def _exit_reason_lines(
    loss: dict[str, Any], money: Callable[[object], str]
) -> list[str]:
    return [
        f"- exit_reason_{reason.lower()}: count={metrics['count']}, pnl={money(metrics['total_profit_usd'])}"
        for reason, metrics in loss["exit_reason_metrics"].items()
    ]
