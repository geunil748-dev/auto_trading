from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _doc(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_scheduled_task_prompt_documents_slack_packet_reassembly() -> None:
    text = _doc("docs/chatgpt_scheduled_task_prompt.md")

    required = [
        "packet_id",
        "part: N/M",
        "sort parts by `N`",
        "packet_complete: true",
        "If any `part: N/M` is missing",
        "do not create a Codex-ready prompt",
        "[EXECUTION_LEDGER_COMPACT]",
        "[PROBLEM_CASES_FOR_CODEX]",
        "[CODEX_FIX_INPUT_HINTS]",
        "required_source_files_to_inspect",
        "Do not read only the latest Slack message",
    ]
    for phrase in required:
        assert phrase in text


def test_scheduled_task_prompt_documents_strategy_packet_guardrails() -> None:
    text = _doc("docs/chatgpt_scheduled_task_prompt.md")

    assert "`strategy_change_allowed: false` means strategy parameter changes are prohibited" in text
    assert (
        "`score_source_analysis_allowed: false` means score/source bucket based strategy changes are prohibited"
        in text
    )
    assert "`data_status: FAIL` means data, logging, report, matching, or reconciliation fixes take priority" in text
    assert "GitHub `main`" in text


def test_scheduled_task_prompt_documents_skipped_packet_handling() -> None:
    text = _doc("docs/chatgpt_scheduled_task_prompt.md")

    required = [
        "[AUTO_TRADING_DATA_PACKET_SKIPPED]",
        "normal market-closed skip notice",
        "not as a failed data packet",
        "normal_skip: true",
        "not a Codex modification prompt source",
        "calendar/session-date check",
        "MARKET_CLOSE_TASK_NOT_TRIGGERED",
        "PACKET_BUILT_BUT_NOT_SENT",
    ]
    for phrase in required:
        assert phrase in text


def test_slack_loop_documents_packet_chunk_review() -> None:
    text = _doc("docs/chatgpt_codex_slack_loop.md")

    required = [
        "AUTO_TRADING_DATA_PACKET Chunk Review",
        "Group candidate messages by `packet_id`",
        "Confirm all parts `1..M` are present",
        "Confirm the final part contains `packet_complete: true`",
        "If any part is missing",
        "[EXECUTION_LEDGER_COMPACT]",
        "[PROBLEM_CASES_FOR_CODEX]",
        "[CODEX_FIX_INPUT_HINTS]",
        "required_source_files_to_inspect",
        "do not use score/source bucket analysis as a strategy-change basis",
    ]
    for phrase in required:
        assert phrase in text


def test_slack_loop_documents_skipped_packet_review() -> None:
    text = _doc("docs/chatgpt_codex_slack_loop.md")

    required = [
        "[AUTO_TRADING_DATA_PACKET_SKIPPED]",
        "normal market-closed skip notice",
        "Do not reassemble it as a regular packet",
        "do not create a Codex-ready prompt from it",
        "normal_skip: true",
        "calendar/session-date investigation",
    ]
    for phrase in required:
        assert phrase in text
