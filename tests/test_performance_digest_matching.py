from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trading_bot.performance_digest import build_strategy_review_digest
from trading_bot.performance_digest_diagnostics import matched_ratio_metrics
from trading_bot.performance_digest_duplicates import build_duplicate_suspects
from trading_bot.performance_digest_matching import (
    build_matching_ledger,
    matching_quality,
    unmatched_breakdown_from_ledger,
)
from trading_bot.performance_digest_reconciliation import build_reconciliation_detail


@dataclass
class Result:
    name: str
    rows: list[dict[str, object]]
    error: str = ""


def test_matching_quality_sell_50_matched_9_is_fail() -> None:
    ledger = [{"matched_status": "MATCHED", "match_confidence": "HIGH"} for _ in range(9)]
    ledger.extend({"matched_status": "UNMATCHED", "unmatched_reason": "NO_CANDIDATE_ROW_FOR_SYMBOL_DATE"} for _ in range(41))

    quality = matching_quality(ledger, 9)
    ratio = matched_ratio_metrics(50, 9)

    assert quality["matched_ratio"] == 0.18
    assert ratio["status"] == "FAIL"


def test_unknown_breakdown_sample_has_required_diagnostic_detail() -> None:
    breakdown = unmatched_breakdown_from_ledger(
        [
            {
                "matched_status": "UNMATCHED",
                "unmatched_reason": "UNKNOWN",
                "unmatched_detail": "",
                "trade_date": "2026-07-02",
                "symbol": "AAA",
            }
        ]
    )

    sample = breakdown["reasons"][0]["samples"][0]
    assert sample["diagnostic_detail"] == "diagnostic_detail_missing_for_unknown_reason"


def test_ledger_decomposes_unknown_to_missing_reason() -> None:
    ledger = build_matching_ledger(
        fill_rows=[
            {
                "trade_date": "2026-07-02",
                "ticker": "AAA",
                "side": "SELL",
                "id": "",
                "order_no": "",
                "fill_time": "10:00:00",
                "fill_price": 10,
                "quantity": 1,
                "profit_usd": -1,
            }
        ],
        candidate_rows=[],
        candidate_evaluation_rows=[],
        duplicate_rows=[],
    )

    assert ledger[0]["unmatched_reason"] == "MISSING_SELL_ORDER_ID"
    assert ledger[0]["unmatched_detail"] == "missing_fields=MISSING_SELL_ORDER_ID,MISSING_SELL_FILL_ID"


def test_same_order_different_fill_ids_is_partial_fill_candidate() -> None:
    suspects = build_duplicate_suspects(
        [
            {
                "trade_date": "2026-07-02",
                "ticker": "AAA",
                "side": "SELL",
                "order_no": "O1",
                "fill_time": "10:00:00",
                "fill_price": 10,
                "row_count": 2,
                "min_quantity": 1,
                "max_quantity": 1,
                "id_list": "F1,F2",
            }
        ]
    )

    sample = suspects["samples"][0]
    assert sample["duplicate_reason"] == "SAME_ORDER_ID_PARTIAL_FILL_LIKELY"
    assert sample["duplicate_confidence"] == "MEDIUM"
    assert suspects["partial_fill_candidate_count"] == 1


def test_same_fill_id_duplicate_is_high_confidence() -> None:
    suspects = build_duplicate_suspects(
        [
            {
                "trade_date": "2026-07-02",
                "ticker": "AAA",
                "side": "SELL",
                "order_no": "O1",
                "fill_time": "10:00:00",
                "fill_price": 10,
                "row_count": 2,
                "min_quantity": 1,
                "max_quantity": 1,
                "id_list": "F1,F1",
            }
        ]
    )

    sample = suspects["samples"][0]
    assert sample["duplicate_reason"] == "SAME_FILL_ID_DUPLICATED"
    assert sample["duplicate_confidence"] == "HIGH"
    assert suspects["true_duplicate_candidate_count"] == 1


def test_multiple_symbol_date_candidates_are_ambiguous_not_high_confidence() -> None:
    ledger = build_matching_ledger(
        fill_rows=[
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "BUY", "id": "B1", "order_no": "BO", "fill_time": "09:30:00"},
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "SELL", "id": "S1", "order_no": "SO", "fill_time": "10:00:00"},
        ],
        candidate_rows=[
            {"trade_date": "2026-07-02", "ticker": "AAA", "sell_count": 1, "final_score": 60, "source": "auto", "id": "C1"},
            {"trade_date": "2026-07-02", "ticker": "AAA", "sell_count": 1, "final_score": 61, "source": "auto", "id": "C2"},
        ],
        candidate_evaluation_rows=[],
        duplicate_rows=[],
    )

    assert ledger[0]["matched_status"] == "UNMATCHED"
    assert ledger[0]["match_confidence"] == "NONE"
    assert ledger[0]["unmatched_reason"] == "MULTIPLE_CANDIDATE_ROWS_AMBIGUOUS"


def test_sell_before_buy_time_is_not_matched() -> None:
    ledger = build_matching_ledger(
        fill_rows=[
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "SELL", "id": "S1", "order_no": "SO", "fill_time": "10:00:00"},
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "BUY", "id": "B1", "order_no": "BO", "fill_time": "11:00:00"},
        ],
        candidate_rows=[],
        candidate_evaluation_rows=[{"trading_date": "2026-07-02", "symbol": "AAA", "buy_allowed": 1, "source": "auto", "final_score": 60}],
        duplicate_rows=[],
    )

    assert ledger[0]["matched_status"] == "UNMATCHED"
    assert ledger[0]["unmatched_reason"] == "SELL_BEFORE_BUY_TIME"


def test_date_boundary_uncertain_when_session_dates_differ() -> None:
    ledger = build_matching_ledger(
        fill_rows=[
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "BUY", "id": "B1", "order_no": "BO", "fill_time": "09:30:00"},
            {"trade_date": "2026-07-02", "ticker": "AAA", "side": "SELL", "id": "S1", "order_no": "SO", "fill_time": "10:00:00"},
        ],
        candidate_rows=[],
        candidate_evaluation_rows=[{"trading_date": "2026-07-01", "symbol": "AAA", "buy_allowed": 1, "source": "auto", "final_score": 60}],
        duplicate_rows=[],
    )

    assert ledger[0]["unmatched_reason"] == "DATE_BOUNDARY_UNCERTAIN"


def test_reconciliation_daily_summary_only_gap_marks_basis_mismatch() -> None:
    detail = build_reconciliation_detail(
        raw_sell_fills=-943.22,
        matched_trades_only=-100,
        daily_summary=-795.04,
        strategy_review_sheet=-943.22,
        exit_reason_sum=-943.22,
        unmatched_count=41,
        duplicate_count=0,
        reconciliation_gap_abs=148.18,
        duplicate_suspects={"samples": []},
    )

    assert detail["raw_sell_fills_vs_exit_reason_sum"] == 0.0
    assert detail["raw_sell_fills_vs_daily_summary"] == -148.18
    assert "daily summary basis mismatch" in detail["suspected_causes"]


def test_slack_preview_disables_score_source_signal_below_50_percent(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result("fill_history", [{"trade_date": "2026-07-02", "side": "SELL", "profit_usd": -100} for _ in range(2)]),
            Result("pnl_by_day", [{"trade_date": "2026-07-02", "sell_count": 2, "total_profit_usd": -100}]),
            Result("pnl_by_exit_reason", [{"trade_date": "2026-07-02", "exit_reason": "STOP_LOSS", "sell_count": 2, "total_profit_usd": -100}]),
            Result("pnl_by_score_bucket", []),
            Result("pnl_by_source", []),
            Result("duplicate_suspects", []),
            Result("summary_reconciliation", [{"trade_date": "2026-07-02", "daily_run_realized_profit_usd": 0, "fill_vs_daily_run_diff": -100}]),
        ],
        report_date=date(2026, 7, 2),
        date_from="2026-07-02",
        date_to="2026-07-02",
        source_xlsx=tmp_path / "strategy_review_20260702.xlsx",
    )

    assert "Status: FAIL" in digest
    assert "- 전략 변경 보류" in digest
    assert "- score/source strategy signal disabled below matched_ratio threshold" in digest
