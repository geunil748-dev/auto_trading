from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.verify_slack_packet_reassembly import (  # noqa: E402
    format_codex_prompt_dry_run,
    reassemble_slack_packet,
)


PACKET_ID = "auto_trading_data_packet_2026-07-02"
REPORT_DATE = "2026-07-02"


def test_reassembles_nine_ordered_chunks() -> None:
    result = _verify(_packet_text())

    assert result.status == "PASS"
    assert result.expected_parts == 9
    assert result.found_parts == list(range(1, 10))
    assert result.sell_ledger_rows == 50
    assert result.buy_ledger_rows == 48


def test_reassembles_nine_shuffled_chunks_by_part_number() -> None:
    result = _verify(_packet_text(shuffled=True))

    assert result.status == "PASS"
    assert result.found_parts == list(range(1, 10))
    assert "[EXECUTION_LEDGER_COMPACT]" in result.assembled_text


def test_missing_part_fails() -> None:
    result = _verify(_packet_text(omit_part=5))

    assert result.status == "FAIL"
    assert result.missing_parts == [5]


def test_missing_packet_complete_fails() -> None:
    result = _verify(_packet_text(omit_complete=True))

    assert result.status == "FAIL"
    assert result.packet_complete is False


def test_different_packet_id_chunk_is_excluded() -> None:
    text = _packet_text(extra_other_packet=True)
    result = _verify(text)

    assert result.status == "PASS"
    assert result.found_parts == list(range(1, 10))


def test_duplicate_part_warns() -> None:
    result = _verify(_packet_text(duplicate_part=4))

    assert result.status == "WARN"
    assert result.duplicate_parts == [4]


def test_missing_execution_ledger_fails() -> None:
    result = _verify(_packet_text(missing_section="[EXECUTION_LEDGER_COMPACT]"))

    assert result.status == "FAIL"
    assert result.required_sections_present["[EXECUTION_LEDGER_COMPACT]"] is False


def test_missing_problem_cases_fails() -> None:
    result = _verify(_packet_text(missing_section="[PROBLEM_CASES_FOR_CODEX]"))

    assert result.status == "FAIL"
    assert result.required_sections_present["[PROBLEM_CASES_FOR_CODEX]"] is False


def test_missing_codex_fix_hints_fails() -> None:
    result = _verify(_packet_text(missing_section="[CODEX_FIX_INPUT_HINTS]"))

    assert result.status == "FAIL"
    assert result.required_sections_present["[CODEX_FIX_INPUT_HINTS]"] is False


def test_expected_sell_and_buy_row_counts_pass() -> None:
    result = _verify(_packet_text())

    assert result.sell_ledger_rows == 50
    assert result.buy_ledger_rows == 48


def test_strategy_guardrails_are_kept_in_generated_prompt() -> None:
    result = _verify(_packet_text())
    prompt = format_codex_prompt_dry_run(result)

    assert "Do not change strategy parameters." in prompt
    assert "Do not tune score/source buckets." in prompt
    assert "data, logging, report, matching, reconciliation" in prompt
    assert "Change strategy parameters." not in prompt
    assert "Tune score/source buckets." not in prompt


def test_missing_required_source_files_blocks_prompt_generation() -> None:
    result = _verify(_packet_text(omit_required_sources=True))

    assert result.status == "WARN"
    assert result.can_generate_codex_prompt is False
    assert result.required_source_files_to_inspect_present is False


def _verify(text: str):
    return reassemble_slack_packet(
        text,
        packet_id=PACKET_ID,
        report_date=REPORT_DATE,
        expected_sell_rows=50,
        expected_buy_rows=48,
    )


def _packet_text(
    *,
    shuffled: bool = False,
    omit_part: int | None = None,
    omit_complete: bool = False,
    duplicate_part: int | None = None,
    extra_other_packet: bool = False,
    missing_section: str | None = None,
    omit_required_sources: bool = False,
) -> str:
    chunks = [
        _chunk(part, missing_section=missing_section, omit_complete=omit_complete, omit_required_sources=omit_required_sources)
        for part in range(1, 10)
        if part != omit_part
    ]
    if duplicate_part is not None:
        chunks.append(_chunk(duplicate_part, missing_section=missing_section, omit_complete=omit_complete))
    if extra_other_packet:
        chunks.append(_chunk(1, packet_id="other_packet", total=1))
    if shuffled:
        chunks = list(reversed(chunks))
    return "\n".join(chunks)


def _chunk(
    part: int,
    *,
    packet_id: str = PACKET_ID,
    total: int = 9,
    missing_section: str | None = None,
    omit_complete: bool = False,
    omit_required_sources: bool = False,
) -> str:
    complete = part == total and not omit_complete
    lines = [
        "[AUTO_TRADING_DATA_PACKET]",
        f"packet_id: {packet_id}",
        f"report_date: {REPORT_DATE}",
        f"part: {part}/{total}",
        f"packet_complete: {str(complete).lower()}",
    ]
    if part == 1:
        lines.extend(_packet_body(missing_section=missing_section, omit_required_sources=omit_required_sources))
    else:
        lines.append(f"part_{part}_payload: ok")
    return "\n".join(lines)


def _packet_body(*, missing_section: str | None = None, omit_required_sources: bool = False) -> list[str]:
    body = [
        "[AUTO_TRADING_DATA_DIGEST]",
        "[Daily Strategy Review]",
        "data_status: FAIL",
        "- buy_count: 48",
        "- sell_count: 50",
        "- matched_ratio: 18.00%",
        "- reconciliation_gap_abs: 148.18",
        "- strategy_change_allowed: false",
        "- score_source_analysis_allowed: false",
        "- next_analysis_focus: review execution ledger rows",
        "[EXECUTION_LEDGER_COMPACT]",
        "sell_exit_ledger_csv:",
        "row_no,symbol",
        *[f"{num},SELL{num}" for num in range(1, 51)],
        "buy_fill_ledger_csv:",
        "row_no,symbol",
        *[f"{num},BUY{num}" for num in range(1, 49)],
        "[PROBLEM_CASES_FOR_CODEX]",
        "top_loss_trades:",
        "- symbol=ABC; realized_pnl=-1.00",
        "[CODEX_FIX_INPUT_HINTS]",
        "- observed_issue: score/source analysis remains low confidence",
        "- affected_rows: unmatched=41; still_ambiguous=12",
        "- evidence: matched_ratio=18.00%; raw_vs_daily_summary=-148.18",
        "- likely_code_area: exit reason logging, fill aggregation",
    ]
    if not omit_required_sources:
        body.append("- required_source_files_to_inspect: src/trading_bot/performance_digest*.py")
    return [line for line in body if line != missing_section]
