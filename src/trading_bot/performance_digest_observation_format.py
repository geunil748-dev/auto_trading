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


def observation_sections(
    stats: dict[str, Any], *, money: Callable[[object], str], pct: Callable[[object], str]
) -> list[str]:
    cumulative = stats["cumulative"]
    audit = cumulative["performance_audit"]
    loss = cumulative["loss_observation"]
    intraday = cumulative["intraday_observation"]
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
        f"- trusted_lineage_error_count: {stats['trusted_lineage_error_count']}",
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
        f"- malformed_json_count: {intraday['malformed_json_count']}",
        f"- false_failure_count: {intraday['false_failure_count']}",
        f"- feature_missing_counts: {_pairs(intraday['feature_missing_counts'])}",
        "",
        "loss_control_observation:",
        f"- basis: {loss['basis']}",
        f"- sell_count: {loss['sell_count']}",
        f"- total_profit_usd: {money(loss['total_profit_usd'])}",
        f"- win_rate: {pct(loss['win_rate'])}",
        f"- avg_win: {money(loss['avg_win'])}",
        f"- avg_loss: {money(loss['avg_loss'])}",
        f"- profit_factor: {_ratio(loss['profit_factor'])}",
        f"- gross_profit: {money(loss['gross_profit'])}",
        f"- gross_loss: {money(loss['gross_loss'])}",
        f"- max_win: {money(loss['max_win'])}",
        f"- max_loss: {money(loss['max_loss'])}",
        f"- stop_loss_count: {loss['stop_loss_count']}",
        f"- stop_loss_total_profit_usd: {money(loss['stop_loss_total_profit_usd'])}",
        f"- stop_loss_average_profit_usd: {money(loss['stop_loss_average_profit_usd'])}",
        f"- stop_loss_share_of_sell_count: {pct(loss['stop_loss_share_of_sell_count'])}",
        f"- stop_loss_share_of_gross_loss: {pct(loss['stop_loss_share_of_gross_loss'])}",
        f"- ambiguous_exit_count: {loss['ambiguous_exit_count']}",
        f"- other_exit_reasons: {', '.join(loss['other_exit_reasons']) or 'none'}",
        "",
        "review_gate:",
        f"- observation_status: {stats['observation_status']}",
        f"- strategy_change_eligibility: {stats['strategy_change_eligibility']}",
        "- automatic_strategy_change_allowed: false",
        "- completed_trade_thresholds: <15 HOLD_INSUFFICIENT_SAMPLE; 15-29 SHADOW_ANALYSIS_ONLY; >=30 REVIEW_ELIGIBLE",
    ]


def _pairs(values: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in values.items()) or "none"


def _ratio(value: object) -> str:
    number = float(value or 0)
    return "inf" if math.isinf(number) else f"{number:.2f}"
