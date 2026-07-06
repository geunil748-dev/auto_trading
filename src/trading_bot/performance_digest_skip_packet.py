from __future__ import annotations

from datetime import date, datetime


def format_auto_trading_data_packet_skipped(
    *,
    report_date: date,
    market_status: str,
    skip_reason: str,
    holiday_name: str,
    next_expected_trading_date: date,
    next_expected_market_close: datetime,
    check_slack_after_kst: datetime,
) -> str:
    return "\n".join(
        [
            "[AUTO_TRADING_DATA_PACKET_SKIPPED]",
            f"packet_id: auto_trading_data_packet_skipped_{report_date:%Y-%m-%d}",
            f"report_date: {report_date:%Y-%m-%d}",
            "market: US",
            f"market_status: {market_status}",
            f"skip_reason: {skip_reason}",
            f"holiday_name: {holiday_name or 'local_calendar_reason'}",
            "data_packet_created: false",
            "execution_ledger_included: false",
            "problem_cases_included: false",
            "codex_fix_input_hints_included: false",
            "",
            "decision_for_chatgpt:",
            "- normal_skip: true",
            "- codex_prompt_allowed: false",
            "- strategy_change_allowed: false",
            "- score_source_analysis_allowed: false",
            "- reason: market closed; no trading data packet expected",
            "",
            "next_validation:",
            f"- next_expected_trading_date: {next_expected_trading_date:%Y-%m-%d}",
            f"- next_expected_market_close: {next_expected_market_close.isoformat()}",
            f"- check_slack_after_kst: {check_slack_after_kst.isoformat()}",
            "- search_keywords:",
            "  - AUTO_TRADING_DATA_PACKET",
            "  - AUTO_TRADING_DATA_PACKET_SKIPPED",
            "  - EXECUTION_LEDGER_COMPACT",
            "  - CODEX_FIX_INPUT_HINTS",
        ]
    )
