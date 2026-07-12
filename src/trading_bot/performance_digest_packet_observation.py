from __future__ import annotations

from typing import Any, Callable


def packet_observation_lines(
    cumulative: dict[str, Any], *, money: Callable[[Any], str],
    pct: Callable[[Any], str], clean: Callable[[Any], str],
) -> list[str]:
    audit = cumulative["performance_audit"]
    loss = cumulative["loss_observation"]
    intraday = cumulative["intraday_observation"]
    return [
        f"- performance_basis: {cumulative['performance_basis']}",
        f"- observation_status: {cumulative['observation_status']}",
        f"- strategy_change_eligibility: {cumulative['strategy_change_eligibility']}",
        f"- trusted_sell_count: {audit['trusted_sell_order_count']}",
        f"- trusted_profit_usd: {money(audit['trusted_profit_usd'])}",
        f"- best_effort_profit_usd: {money(audit['best_effort_profit_usd'])}",
        f"- raw_profit_usd: {money(audit['raw_profit_usd'])}",
        f"- raw_vs_trusted_profit_difference: {money(audit['raw_vs_trusted_profit_difference'])}",
        f"- false_failure_count: {intraday['false_failure_count']}",
        f"- required_data_incomplete_rate: {pct(intraday['required_data_incomplete_rate'])}",
        f"- malformed_condition_json_count: {intraday['malformed_condition_json_count']}",
        f"- missing_condition_json_count: {intraday['missing_condition_json_count']}",
        f"- real_mode_row_count: {cumulative['real_mode_row_count']}",
        f"- unknown_mode_row_count: {cumulative['unknown_mode_row_count']}",
        f"- gross_profit_usd: {money(loss['gross_profit_usd'])}",
        f"- gross_loss_usd: {money(loss['gross_loss_usd'])}",
        f"- avg_win: {money(loss['avg_win'])}",
        f"- avg_loss: {money(loss['avg_loss'])}",
        f"- max_win: {money(loss['max_win'])}",
        f"- max_loss: {money(loss['max_loss'])}",
        f"- max_drawdown: {clean(loss['max_drawdown'])}",
        f"- stop_loss_count: {loss['stop_loss_count']}",
        f"- stop_loss_total_profit_usd: {money(loss['stop_loss_total_profit_usd'])}",
        f"- stop_loss_average_profit_usd: {money(loss['stop_loss_average_profit_usd'])}",
        f"- stop_loss_share_of_sell_count: {pct(loss['stop_loss_share_of_sell_count'])}",
        f"- stop_loss_share_of_gross_loss: {pct(loss['stop_loss_share_of_gross_loss'])}",
    ]


def codex_hint_lines(
    cumulative: dict[str, Any], *, money: Callable[[Any], str],
    pct: Callable[[Any], str],
) -> list[str]:
    quality = cumulative["candidate_matching_quality"]
    reconciliation = cumulative["reconciliation_detail"]
    return [
        "[CODEX_FIX_INPUT_HINTS]",
        "- observed_issue: score/source analysis remains low confidence while execution ledger has enough trade rows for exit-reason review",
        f"- affected_rows: unmatched={cumulative['overall']['unmatched_trade_count']}; still_ambiguous={quality['still_ambiguous_count']}; duplicate_suspects={cumulative['duplicate_count']}",
        f"- evidence: matched_ratio={pct(cumulative['overall']['matched_ratio'])}; raw_vs_daily_summary={money(reconciliation['raw_sell_fills_vs_daily_summary'])}",
        "- likely_code_area: exit reason logging, fill aggregation, daily summary reconciliation, report packet generation",
        "- should_change_strategy_parameter: false",
        "- should_fix_data_or_logging_first: true",
        "- required_source_files_to_inspect: src/trading_bot/performance_digest*.py, tools/export_strategy_review.py, exit/summary logging modules",
        "- notes_for_chatgpt: use row-level execution ledger evidence before asking Codex for code changes; do not use score/source buckets as strategy signal while data_status is not OK",
    ]
