from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.performance_digest_buckets import is_buy, num
from trading_bot.performance_digest_packet_observation import (
    codex_hint_lines,
    packet_observation_lines,
)

PACKET_CHUNK_SIZE = 8000
SELL_COLUMNS = (
    "row_no", "symbol", "trade_date", "buy_time", "buy_price", "buy_qty",
    "buy_reason", "buy_source", "buy_score", "sell_time", "sell_price",
    "sell_qty", "realized_pnl", "realized_return_pct", "exit_reason",
    "sell_reason", "sell_trigger_detail", "hold_minutes", "matched_status",
    "match_confidence", "unmatched_reason", "diagnostic_detail",
)
BUY_COLUMNS = (
    "row_no", "symbol", "trade_date", "buy_time", "buy_price", "buy_qty",
    "buy_reason", "buy_source", "buy_score", "candidate_final_decision",
    "candidate_block_reason", "order_status", "diagnostic_detail",
)


def build_execution_ledgers(
    fill_rows: Sequence[Mapping[str, Any]],
    ledger_v2: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    sell_rows = [_sell_packet_row(row) for row in ledger_v2]
    buy_context = _buy_context_by_fill(ledger_v2)
    buy_rows = []
    for row_no, row in enumerate([item for item in fill_rows if is_buy(item.get("side"))], start=1):
        key = str(row.get("id") or "")
        context = buy_context.get(key) or {}
        buy_rows.append(_buy_packet_row(row_no, row, context))
    return {"sell_rows": sell_rows, "buy_rows": buy_rows}


def format_auto_trading_data_packet(
    stats: dict[str, Any],
    *,
    report_date: Any,
    date_from: Any,
    date_to: Any,
    source_xlsx: Path | str,
    chunk_size: int = PACKET_CHUNK_SIZE,
) -> list[str]:
    cumulative = stats["cumulative"]
    packet_id = f"auto_trading_data_packet_{_clean(report_date)}"
    body = _packet_body(cumulative, report_date, date_from, date_to, source_xlsx)
    chunks = _chunk_lines(body, chunk_size)
    lines = [f"packet_chunk_count: {len(chunks)}"]
    for index, chunk in enumerate(chunks, start=1):
        lines.extend(
            [
                "",
                "[AUTO_TRADING_DATA_PACKET]",
                f"packet_id: {packet_id}",
                f"report_date: {_clean(report_date)}",
                f"part: {index}/{len(chunks)}",
                f"packet_complete: {str(index == len(chunks)).lower()}",
                *chunk,
            ]
        )
    return lines


def write_execution_ledger_compact_csv(path: Path | str, stats: dict[str, Any]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ledgers = stats["cumulative"]["execution_ledger_compact"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", *SELL_COLUMNS])
        for row in ledgers["sell_rows"]:
            writer.writerow(["SELL", *[_clean(row.get(col)) for col in SELL_COLUMNS]])
        writer.writerow([])
        writer.writerow(["section", *BUY_COLUMNS])
        for row in ledgers["buy_rows"]:
            writer.writerow(["BUY", *[_clean(row.get(col)) for col in BUY_COLUMNS]])
    return output


def _packet_body(cumulative: dict[str, Any], report_date: Any, date_from: Any, date_to: Any, source_xlsx: Path | str) -> list[str]:
    overall = cumulative["performance"]["overall"]
    quality = cumulative["candidate_matching_quality"]
    ledgers = cumulative["execution_ledger_compact"]
    return [
        "version: 1",
        f"report_date: {_clean(report_date)}",
        f"date_range: {_clean(date_from)}..{_clean(date_to)}",
        f"source_xlsx: {_clean(source_xlsx)}",
        f"data_status: {cumulative['data_status']}",
        "",
        "summary:",
        *packet_observation_lines(cumulative, money=_money, pct=_pct, clean=_clean),
        f"- buy_count: {_clean(overall['buy_count'])}",
        f"- sell_count: {_clean(overall['sell_count'])}",
        f"- realized_pnl: {_money(overall['realized_pnl'])}",
        f"- win_rate: {_pct(overall['win_rate'])}",
        f"- profit_factor: {_clean(round(num(overall['profit_factor']), 4))}",
        f"- matched_trade_count: {_clean(overall['matched_trade_count'])}",
        f"- unmatched_trade_count: {_clean(overall['unmatched_trade_count'])}",
        f"- matched_ratio: {_pct(overall['matched_ratio'])}",
        f"- reconciliation_gap_abs: {_money(cumulative['reconciliation']['reconciliation_gap_abs'])}",
        f"- duplicate_suspects_count: {cumulative['duplicate_count']}",
        f"- partial_fill_candidate_count: {cumulative['duplicate_suspects'].get('partial_fill_candidate_count', 0)}",
        f"- still_ambiguous_count: {quality['still_ambiguous_count']}",
        "",
        "data_quality_reasons:",
        *[f"- {reason}" for reason in cumulative["data_status_reason"]],
        "",
        "decision_for_chatgpt:",
        "- strategy_change_allowed: false",
        f"- reason: observation_status={cumulative['observation_status']}; eligibility={cumulative['strategy_change_eligibility']}; automatic changes are disabled",
        f"- score_source_analysis_allowed: {str(num(overall['matched_ratio']) >= 0.5 and quality['still_ambiguous_count'] == 0).lower()}",
        "- reason: score/source buckets are disabled when matched_ratio is below 50% or candidate ambiguity remains",
        f"- next_analysis_focus: {cumulative['matching_recommendation']['next_data_quality_fix']}",
        "",
        *(_execution_ledger_lines(ledgers)),
        "",
        *(_problem_case_lines(cumulative, ledgers["sell_rows"])),
        "",
        *(codex_hint_lines(cumulative, money=_money, pct=_pct)),
    ]


def _execution_ledger_lines(ledgers: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[str]:
    return [
        "[EXECUTION_LEDGER_COMPACT]",
        "basis: RAW_AUDIT",
        "sell_exit_ledger_csv:",
        _csv_line(SELL_COLUMNS),
        *[_csv_line([row.get(col) for col in SELL_COLUMNS]) for row in ledgers["sell_rows"]],
        "",
        "buy_fill_ledger_csv:",
        _csv_line(BUY_COLUMNS),
        *[_csv_line([row.get(col) for col in BUY_COLUMNS]) for row in ledgers["buy_rows"]],
    ]


def _problem_case_lines(cumulative: dict[str, Any], sell_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    losses = sorted(sell_rows, key=lambda row: num(row.get("realized_pnl")))[:10]
    profits = sorted(sell_rows, key=lambda row: num(row.get("realized_pnl")), reverse=True)[:10]
    by_exit = defaultdict(list)
    for row in sell_rows:
        by_exit[str(row.get("exit_reason") or "unknown").upper()].append(row)
    suspicious = [
        row for row in sell_rows
        if (str(row.get("exit_reason")).upper() == "STOP_LOSS" and num(row.get("realized_return_pct")) > 0)
        or (str(row.get("exit_reason")).upper() == "TRAILING_STOP" and num(row.get("realized_pnl")) < 0)
        or row.get("unmatched_reason") in {"PARTIAL_FILL_NEEDS_AGGREGATION", "DATE_BOUNDARY_UNCERTAIN"}
    ][:20]
    return [
        "[PROBLEM_CASES_FOR_CODEX]",
        "basis: RAW_AUDIT",
        "top_loss_trades:",
        *_case_lines(losses),
        "top_profit_trades:",
        *_case_lines(profits),
        "stop_loss_cases:",
        *_case_lines(by_exit.get("STOP_LOSS", [])[:20]),
        "trailing_stop_cases:",
        *_case_lines(by_exit.get("TRAILING_STOP", [])[:20]),
        "eod_cases:",
        *_case_lines(by_exit.get("EOD", [])[:20]),
        "unmatched_cases:",
        *_unmatched_case_lines(cumulative),
        "suspicious_or_needs_review:",
        *_case_lines(suspicious),
    ]


def _sell_packet_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row_no": row.get("row_no"),
        "symbol": row.get("symbol"),
        "trade_date": row.get("trade_date"),
        "buy_time": row.get("buy_time"),
        "buy_price": row.get("buy_price"),
        "buy_qty": row.get("buy_qty"),
        "buy_reason": row.get("buy_entry_reason") or row.get("buy_entry_reason_detail"),
        "buy_source": row.get("active_candidate_source") or row.get("candidate_source"),
        "buy_score": row.get("active_candidate_score") or row.get("candidate_score"),
        "sell_time": row.get("sell_time"),
        "sell_price": row.get("sell_price"),
        "sell_qty": row.get("sell_qty"),
        "realized_pnl": row.get("realized_pnl"),
        "realized_return_pct": row.get("profit_rate"),
        "exit_reason": row.get("exit_reason"),
        "sell_reason": row.get("exit_reason"),
        "sell_trigger_detail": row.get("sell_trigger_detail") or row.get("diagnostic_detail"),
        "hold_minutes": _hold_minutes(row.get("buy_time"), row.get("sell_time")),
        "matched_status": row.get("matched_status"),
        "match_confidence": row.get("match_confidence"),
        "unmatched_reason": row.get("new_unmatched_reason") or row.get("previous_unmatched_reason") or row.get("unmatched_reason"),
        "diagnostic_detail": row.get("diagnostic_detail"),
    }


def _buy_packet_row(row_no: int, row: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row_no": row_no,
        "symbol": row.get("ticker"),
        "trade_date": row.get("trade_date"),
        "buy_time": row.get("fill_time"),
        "buy_price": row.get("fill_price"),
        "buy_qty": row.get("quantity"),
        "buy_reason": row.get("entry_reason") or row.get("entry_reason_detail"),
        "buy_source": context.get("buy_source"),
        "buy_score": context.get("buy_score"),
        "candidate_final_decision": context.get("candidate_final_decision"),
        "candidate_block_reason": context.get("candidate_block_reason"),
        "order_status": context.get("order_status"),
        "diagnostic_detail": context.get("diagnostic_detail") or "not_available",
    }


def _buy_context_by_fill(ledger_v2: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in ledger_v2:
        key = str(row.get("buy_fill_id") or "")
        if not key or key in result:
            continue
        result[key] = {
            "buy_source": row.get("active_candidate_source") or row.get("candidate_source"),
            "buy_score": row.get("active_candidate_score") or row.get("candidate_score"),
            "candidate_final_decision": row.get("active_candidate_final_decision"),
            "candidate_block_reason": row.get("candidate_block_reason"),
            "order_status": row.get("order_status"),
            "diagnostic_detail": f"linked_sell_row={row.get('row_no')}; {row.get('diagnostic_detail')}",
        }
    return result


def _case_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return ["- none"]
    keys = ("symbol", "buy_time", "buy_price", "sell_time", "sell_price", "realized_pnl", "realized_return_pct", "exit_reason", "sell_trigger_detail", "buy_reason", "diagnostic_detail")
    return ["- " + "; ".join(f"{key}={_clean(row.get(key))}" for key in keys) for row in rows]


def _unmatched_case_lines(cumulative: dict[str, Any]) -> list[str]:
    lines = []
    for item in cumulative["unmatched_breakdown"]["reasons"]:
        lines.append(f"- reason={item['reason']}; count={item['count']}")
        for sample in item.get("samples", [])[:3]:
            lines.append(f"  sample: symbol={_clean(sample.get('symbol'))}; sell_time={_clean(sample.get('sell_time'))}; diagnostic_detail={_clean(sample.get('diagnostic_detail'))}")
    return lines or ["- none"]


def _chunk_lines(lines: Sequence[str], max_chars: int) -> list[list[str]]:
    chunks: list[list[str]] = [[]]
    current = 0
    for line in lines:
        line_len = len(line) + 1
        if chunks[-1] and current + line_len > max_chars:
            chunks.append([])
            current = 0
        chunks[-1].append(line)
        current += line_len
    return chunks


def _csv_line(values: Sequence[Any]) -> str:
    handle = io.StringIO()
    writer = csv.writer(handle, lineterminator="")
    writer.writerow([_clean(value) for value in values])
    return handle.getvalue()


def _hold_minutes(buy_time: Any, sell_time: Any) -> str:
    if buy_time in {None, "", "missing"} or sell_time in {None, "", "missing"}:
        return "not_available"
    try:
        from trading_bot.performance_digest_matching_utils import seconds
        diff = seconds(sell_time) - seconds(buy_time)
        return str(round(diff / 60, 2)) if diff >= 0 else "not_available"
    except Exception:
        return "not_available"


def _clean(value: Any) -> str:
    text = str(value if value not in {None, ""} else "missing").replace("\n", " ").strip()
    return text if text else "missing"
def _money(value: Any) -> str:
    return "unknown" if value == "unknown" else f"{num(value):.2f}"
def _pct(value: Any) -> str:
    return "unknown" if value == "unknown" else f"{num(value) * 100:.2f}%"
