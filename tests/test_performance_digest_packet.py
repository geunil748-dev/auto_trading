from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trading_bot.performance_digest import build_strategy_review_digest
from trading_bot.performance_digest_packet import format_auto_trading_data_packet
from trading_bot.performance_digest_stats import collect_strategy_review_digest_stats


@dataclass
class Result:
    name: str
    rows: list[dict[str, object]]
    error: str = ""


def test_slack_preview_contains_auto_trading_data_packet_and_execution_ledger(tmp_path) -> None:
    digest = _build_digest(tmp_path)

    assert "[AUTO_TRADING_DATA_PACKET]" in digest
    assert "[EXECUTION_LEDGER_COMPACT]" in digest
    assert "[PROBLEM_CASES_FOR_CODEX]" in digest
    assert "[CODEX_FIX_INPUT_HINTS]" in digest


def test_packet_includes_all_sell_and_buy_rows_or_clear_reason(tmp_path) -> None:
    digest = _build_digest(tmp_path)

    assert _csv_row_count(digest, "sell_exit_ledger_csv:") == 50
    assert _csv_row_count(digest, "buy_fill_ledger_csv:") == 48


def test_problem_cases_have_nonempty_diagnostic_and_missing_buy_reason_is_explicit(tmp_path) -> None:
    digest = _build_digest(tmp_path)

    stop_loss_block = _block_after(digest, "stop_loss_cases:", "trailing_stop_cases:")
    assert "sell_trigger_detail=linked_sell_row=" in stop_loss_block or "diagnostic_detail=" in stop_loss_block
    assert "buy_reason=missing" in digest


def test_unknown_unmatched_reason_has_diagnostic_detail_in_packet(tmp_path) -> None:
    digest = _build_digest(tmp_path)

    assert "unmatched_reason,diagnostic_detail" in digest
    assert "diagnostic_detail=missing" not in _block_after(digest, "unmatched_cases:", "suspicious_or_needs_review:")


def test_packet_omits_db_design_terms(tmp_path) -> None:
    digest = _build_digest(tmp_path)
    forbidden = ["schema_recommendation", "migration", "ALTER TABLE", "minimum_fields"]

    assert not any(term in digest for term in forbidden)


def test_fail_status_disables_strategy_and_score_source_analysis(tmp_path) -> None:
    digest = _build_digest(tmp_path)

    assert "- strategy_change_allowed: false" in digest
    assert "- score_source_analysis_allowed: false" in digest


def test_packet_chunks_include_part_numbers_and_packet_id(tmp_path) -> None:
    stats = collect_strategy_review_digest_stats(_sheet_results(), report_date=date(2026, 7, 2))
    lines = format_auto_trading_data_packet(
        stats,
        report_date=date(2026, 7, 2),
        date_from="2026-07-02",
        date_to="2026-07-02",
        source_xlsx=tmp_path / "strategy_review_20260702.xlsx",
        chunk_size=900,
    )
    text = "\n".join(lines)

    assert "packet_chunk_count:" in text
    assert "packet_id: auto_trading_data_packet_2026-07-02" in text
    assert "report_date: 2026-07-02" in text
    assert "part: 1/" in text
    assert "part: 2/" in text
    assert "packet_complete: true" in text


def test_digest_stats_ignore_legacy_bot_log_sheets() -> None:
    stats = collect_strategy_review_digest_stats(
        _sheet_results()
        + [
            Result(
                "legacy_bot_log",
                [
                    {
                        "trade_date": "2026-07-02",
                        "event_type": "BUY_NOT_SUBMITTED",
                        "sell_count": 999,
                        "total_profit_usd": -999,
                    }
                ],
            ),
            Result(
                "bot_log",
                [
                    {
                        "trade_date": "2026-07-02",
                        "event_type": "ORDER_SUBMIT_FAILED",
                        "sell_count": 999,
                        "total_profit_usd": -999,
                    }
                ],
            ),
        ],
        report_date=date(2026, 7, 2),
    )

    assert stats["daily"]["overall"]["sell_count"] == 50
    assert stats["daily"]["overall"]["realized_pnl"] == 100
    assert not any("bot_log" in item for item in stats["missing_or_limited"])


def test_codex_hints_do_not_direct_strategy_parameter_change(tmp_path) -> None:
    digest = _build_digest(tmp_path)
    hints = _block_after(digest, "[CODEX_FIX_INPUT_HINTS]", "")

    assert "- should_change_strategy_parameter: false" in hints
    assert "- should_fix_data_or_logging_first: true" in hints


def _build_digest(tmp_path) -> str:
    return build_strategy_review_digest(
        _sheet_results(),
        report_date=date(2026, 7, 2),
        date_from="2026-07-02",
        date_to="2026-07-02",
        source_xlsx=tmp_path / "strategy_review_20260702.xlsx",
    )


def _sheet_results() -> list[Result]:
    buys = [
        {
            "trade_date": "2026-07-02",
            "ticker": f"S{i:03d}",
            "side": "BUY",
            "id": f"B{i}",
            "order_no": f"BO{i}",
            "fill_time": "09:30:00",
            "fill_price": 10,
            "quantity": 1,
            "entry_reason": "" if i == 1 else "auto",
        }
        for i in range(1, 49)
    ]
    sells = [
        {
            "trade_date": "2026-07-02",
            "ticker": f"S{i:03d}",
            "side": "SELL",
            "id": f"S{i}",
            "order_no": f"SO{i}",
            "fill_time": "10:30:00",
            "fill_price": 9 if i <= 10 else 11,
            "quantity": 1,
            "profit_usd": -10 if i <= 10 else 5,
            "profit_rate": -0.05 if i <= 10 else 0.02,
        }
        for i in range(1, 51)
    ]
    exit_rows = [
        {
            "trade_date": "2026-07-02",
            "ticker": f"S{i:03d}",
            "exit_reason": "STOP_LOSS" if i <= 10 else ("TRAILING_STOP" if i <= 30 else "EOD"),
            "order_type": "SELL",
        }
        for i in range(1, 51)
    ]
    return [
        Result("fill_history", buys + sells),
        Result("trade_history", exit_rows),
        Result("pnl_by_day", [{"trade_date": "2026-07-02", "sell_count": 50, "total_profit_usd": 100, "win_count": 40, "loss_count": 10}]),
        Result("pnl_by_exit_reason", [{"trade_date": "2026-07-02", "exit_reason": "STOP_LOSS", "sell_count": 10, "total_profit_usd": -100}]),
        Result("pnl_by_score_bucket", [{"trade_date": "2026-07-02", "score_bucket": "50_60", "sell_count": 9, "total_profit_usd": 10}]),
        Result("pnl_by_source", [{"trade_date": "2026-07-02", "source": "auto", "sell_count": 9, "total_profit_usd": 10}]),
        Result("duplicate_suspects", []),
        Result("summary_reconciliation", [{"trade_date": "2026-07-02", "daily_run_realized_profit_usd": 0, "fill_vs_daily_run_diff": 100}]),
        Result("candidate_evaluations", []),
    ]


def _csv_row_count(text: str, marker: str) -> int:
    end = "buy_fill_ledger_csv:" if marker == "sell_exit_ledger_csv:" else "[PROBLEM_CASES_FOR_CODEX]"
    block = _block_after(text, marker, end)
    lines = [line for line in block.splitlines()[1:] if line and not line.startswith("[") and not line.endswith(":")]
    return sum(1 for line in lines if line[:1].isdigit())


def _block_after(text: str, start: str, end: str) -> str:
    tail = text.split(start, 1)[1]
    if end and end in tail:
        return tail.split(end, 1)[0]
    return tail
