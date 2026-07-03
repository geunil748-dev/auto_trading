from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PACKET_MARKER = "[AUTO_TRADING_DATA_PACKET]"
REQUIRED_SECTIONS = (
    "[AUTO_TRADING_DATA_DIGEST]", "[Daily Strategy Review]", "[AUTO_TRADING_DATA_PACKET]",
    "[EXECUTION_LEDGER_COMPACT]", "[PROBLEM_CASES_FOR_CODEX]", "[CODEX_FIX_INPUT_HINTS]",
)


@dataclass(frozen=True)
class PacketPart:
    part_no: int; total_parts: int; packet_complete: bool
    report_date: str; text: str


@dataclass(frozen=True)
class ReassemblyResult:
    status: str; packet_id: str; report_date: str; expected_parts: int
    found_parts: list[int]; missing_parts: list[int]; duplicate_parts: list[int]
    packet_complete: bool; required_sections_present: dict[str, bool]
    sell_ledger_rows: int; buy_ledger_rows: int; values: dict[str, str]
    codex_fix_input_hints_present: bool; required_source_files_to_inspect_present: bool
    can_generate_codex_prompt: bool; reason_if_not: str; assembled_text: str


def reassemble_slack_packet(
    text: str,
    *,
    packet_id: str,
    report_date: str,
    expected_sell_rows: int | None = None,
    expected_buy_rows: int | None = None,
) -> ReassemblyResult:
    parts, duplicate_parts = _collect_parts(text, packet_id=packet_id)
    expected_parts = max((part.total_parts for part in parts), default=0)
    unique_parts = _unique_parts(parts)
    found_parts = sorted(part.part_no for part in unique_parts)
    missing_parts = [num for num in range(1, expected_parts + 1) if num not in found_parts]
    assembled = "\n".join(part.text.strip("\n") for part in sorted(unique_parts, key=lambda item: item.part_no))
    required_sections = {section: section in assembled for section in REQUIRED_SECTIONS}
    values = _packet_values(assembled)
    packet_complete = _packet_complete_ok(unique_parts, expected_parts)
    sell_rows = _ledger_row_count(assembled, "sell_exit_ledger_csv:", ("buy_fill_ledger_csv:", "[PROBLEM_CASES_FOR_CODEX]"))
    buy_rows = _ledger_row_count(assembled, "buy_fill_ledger_csv:", ("[PROBLEM_CASES_FOR_CODEX]",))

    failures: list[str] = []
    warnings: list[str] = []
    if not unique_parts:
        failures.append("no parts found for packet_id")
    if missing_parts:
        failures.append("missing packet parts")
    if not packet_complete:
        failures.append("packet_complete true missing or not on final part")
    if any(part.report_date and part.report_date != report_date for part in unique_parts):
        failures.append("report_date mismatch")
    if not all(required_sections.values()):
        failures.append("required sections missing")
    if duplicate_parts:
        warnings.append("duplicate packet parts")
    if expected_sell_rows is not None and sell_rows != expected_sell_rows:
        warnings.append("sell ledger row count mismatch")
    if expected_buy_rows is not None and buy_rows != expected_buy_rows:
        warnings.append("buy ledger row count mismatch")

    required_source_files = "required_source_files_to_inspect" in assembled
    hints_present = "[CODEX_FIX_INPUT_HINTS]" in assembled
    if hints_present and not required_source_files:
        warnings.append("required_source_files_to_inspect missing")

    if failures:
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"
    can_generate = status != "FAIL" and hints_present and required_source_files
    reason = "; ".join(failures or warnings) if not can_generate else "ready"

    return ReassemblyResult(
        status=status,
        packet_id=packet_id,
        report_date=report_date,
        expected_parts=expected_parts,
        found_parts=found_parts,
        missing_parts=missing_parts,
        duplicate_parts=duplicate_parts,
        packet_complete=packet_complete,
        required_sections_present=required_sections,
        sell_ledger_rows=sell_rows,
        buy_ledger_rows=buy_rows,
        values=values,
        codex_fix_input_hints_present=hints_present,
        required_source_files_to_inspect_present=required_source_files,
        can_generate_codex_prompt=can_generate,
        reason_if_not=reason,
        assembled_text=assembled,
    )


def format_reassembly_summary(result: ReassemblyResult) -> str:
    sections = ", ".join(
        f"{name}={str(present).lower()}" for name, present in result.required_sections_present.items()
    )
    lines = [
        "slack_packet_reassembly:",
        f"- status: {result.status}",
        f"- packet_id: {result.packet_id}",
        f"- report_date: {result.report_date}",
        f"- expected_parts: {result.expected_parts}",
        f"- found_parts: {_fmt_list(result.found_parts)}",
        f"- missing_parts: {_fmt_list(result.missing_parts)}",
        f"- duplicate_parts: {_fmt_list(result.duplicate_parts)}",
        f"- packet_complete: {str(result.packet_complete).lower()}",
        f"- required_sections_present: {sections}",
        f"- sell_ledger_rows: {result.sell_ledger_rows}",
        f"- buy_ledger_rows: {result.buy_ledger_rows}",
        *[
            f"- {key}: {result.values.get(key, 'missing')}"
            for key in (
                "data_status", "strategy_change_allowed", "score_source_analysis_allowed",
                "matched_ratio", "reconciliation_gap_abs", "buy_count", "sell_count",
            )
        ],
        f"- codex_fix_input_hints_present: {_bool(result.codex_fix_input_hints_present)}",
        f"- required_source_files_to_inspect_present: {_bool(result.required_source_files_to_inspect_present)}",
        f"- can_generate_codex_prompt: {_bool(result.can_generate_codex_prompt)}",
        f"- strategy_parameter_prompt_allowed: false",
        f"- score_source_bucket_tuning_allowed: false",
        f"- reason_if_not: {result.reason_if_not}",
    ]
    return "\n".join(lines) + "\n"


def format_codex_prompt_dry_run(result: ReassemblyResult) -> str:
    values = result.values
    title = "Strengthen digest evidence logging before strategy changes"
    return f"""[CODEX_PROMPT_FROM_SLACK_PACKET_DRY_RUN]
This is a preview only. Do not execute Codex automatically.
packet_id: {result.packet_id}
report_date: {result.report_date}
data_status: {values.get('data_status', 'missing')}
strategy_change_allowed: {values.get('strategy_change_allowed', 'missing')}
score_source_analysis_allowed: {values.get('score_source_analysis_allowed', 'missing')}
next_analysis_focus: {values.get('next_analysis_focus', 'missing')}
observed_issue: {values.get('observed_issue', 'missing')}
affected_rows: {values.get('affected_rows', 'missing')}
evidence: {values.get('evidence', 'missing')}
likely_code_area: {values.get('likely_code_area', 'missing')}
required_source_files_to_inspect: {values.get('required_source_files_to_inspect', 'missing')}
proposed_codex_task_title: {title}

proposed_codex_prompt_body:
Use the Codex cloud environment named auto_trading.
Base branch: main

Task:
{title}

Scope:
- Inspect GitHub main source before making changes.
- Focus only on data, logging, report, matching, reconciliation, or exit trigger detail evidence.
- Use Slack packet row evidence from EXECUTION_LEDGER_COMPACT and PROBLEM_CASES_FOR_CODEX.

Non-goals:
- Do not change strategy parameters.
- Do not tune score/source buckets.
- Do not change buy/sell strategy logic, order logic, KIS API code, DB schema, scheduler, or settings.
- Do not call Slack, broker, KIS, order, or database write APIs.

Validation:
- Run the relevant tests for reporting/digest changes.
- Run compileall and git diff --check.
"""


def _collect_parts(text: str, *, packet_id: str) -> tuple[list[PacketPart], list[int]]:
    starts = [match.start() for match in re.finditer(re.escape(PACKET_MARKER), text)]
    if not starts:
        return [], []

    raw_parts: list[PacketPart] = []
    preamble = text[: starts[0]]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        block = text[start:end]
        if f"packet_id: {packet_id}" not in block:
            continue
        if index == 0 and ("[AUTO_TRADING_DATA_DIGEST]" in preamble or "[Daily Strategy Review]" in preamble):
            block = preamble + block
        part = _parse_part(block)
        if part:
            raw_parts.append(part)

    seen: set[int] = set()
    duplicates: list[int] = []
    for part in raw_parts:
        if part.part_no in seen and part.part_no not in duplicates:
            duplicates.append(part.part_no)
        seen.add(part.part_no)
    return raw_parts, sorted(duplicates)


def _parse_part(text: str) -> PacketPart | None:
    part_match = re.search(r"^part:\s*(\d+)\s*/\s*(\d+)\s*$", text, re.MULTILINE)
    if not part_match:
        return None
    date_match = re.search(r"^report_date:\s*(.+?)\s*$", text, re.MULTILINE)
    return PacketPart(
        part_no=int(part_match.group(1)),
        total_parts=int(part_match.group(2)),
        packet_complete=bool(re.search(r"^packet_complete:\s*true\s*$", text, re.MULTILINE | re.IGNORECASE)),
        report_date=(date_match.group(1).strip() if date_match else ""),
        text=text,
    )


def _unique_parts(parts: Sequence[PacketPart]) -> list[PacketPart]:
    selected: dict[int, PacketPart] = {}
    for part in parts:
        selected.setdefault(part.part_no, part)
    return list(selected.values())


def _packet_complete_ok(parts: Sequence[PacketPart], expected_parts: int) -> bool:
    complete_parts = [part.part_no for part in parts if part.packet_complete]
    return complete_parts == [expected_parts] if expected_parts else False


def _ledger_row_count(text: str, start_marker: str, end_markers: Sequence[str]) -> int:
    lines = text.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == start_marker)
    except StopIteration:
        return 0
    end = len(lines)
    for marker in end_markers:
        for index in range(start + 1, len(lines)):
            if lines[index].strip() == marker or lines[index].startswith(marker):
                end = min(end, index)
                break
    return sum(1 for line in lines[start + 2 : end] if re.match(r"^\d+,", line))


def _packet_values(text: str) -> dict[str, str]:
    keys = (
        "data_status", "strategy_change_allowed", "score_source_analysis_allowed", "matched_ratio",
        "reconciliation_gap_abs", "buy_count", "sell_count", "next_analysis_focus", "observed_issue",
        "affected_rows", "evidence", "likely_code_area", "required_source_files_to_inspect",
    )
    return {key: _last_field_value(text, key) for key in keys}


def _last_field_value(text: str, key: str) -> str:
    pattern = re.compile(rf"^\s*-?\s*{re.escape(key)}:\s*(.+?)\s*$", re.MULTILINE)
    values = [match.group(1).strip() for match in pattern.finditer(text)]
    return values[-1] if values else "missing"


def _fmt_list(values: Sequence[int]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Slack AUTO_TRADING_DATA_PACKET reassembly.")
    parser.add_argument("input_file", type=Path)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--expected-sell-rows", type=int); parser.add_argument("--expected-buy-rows", type=int)
    parser.add_argument("--report-output", type=Path); parser.add_argument("--codex-prompt-output", type=Path)
    args = parser.parse_args(argv)

    text = args.input_file.read_text(encoding="utf-8")
    result = reassemble_slack_packet(
        text,
        packet_id=args.packet_id,
        report_date=args.report_date,
        expected_sell_rows=args.expected_sell_rows,
        expected_buy_rows=args.expected_buy_rows,
    )
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(format_reassembly_summary(result), encoding="utf-8")
    if args.codex_prompt_output:
        args.codex_prompt_output.parent.mkdir(parents=True, exist_ok=True)
        args.codex_prompt_output.write_text(format_codex_prompt_dry_run(result), encoding="utf-8")
    print(format_reassembly_summary(result), end="")
    return 1 if result.status == "FAIL" else 0


def _bool(value: bool) -> str:
    return str(value).lower()


if __name__ == "__main__": raise SystemExit(main())
