from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trading_bot.performance_digest import (
    AUTO_TRADING_DATA_DIGEST_MARKER,
    build_strategy_review_digest,
    save_strategy_review_digest,
)


@dataclass
class Result:
    name: str
    rows: list[dict[str, object]]
    error: str = ""


def test_build_strategy_review_digest_contains_required_sections(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result(
                "fill_history",
                [
                    {"trade_date": "2026-06-29", "side": "BUY", "quantity": 1, "fill_amount": 100},
                    {"trade_date": "2026-06-29", "side": "SELL", "quantity": 1, "fill_amount": 110, "profit_usd": 10},
                    {"trade_date": "2026-06-29", "side": "SELL", "quantity": 1, "fill_amount": 90, "profit_usd": -5},
                ],
            ),
            Result(
                "pnl_by_day",
                [
                    {
                        "trade_date": "2026-06-29",
                        "sell_count": 2,
                        "total_profit_usd": 5,
                        "win_count": 1,
                        "loss_count": 1,
                        "avg_win": 10,
                        "avg_loss": -5,
                        "max_win": 10,
                        "max_loss": -5,
                    }
                ],
            ),
            Result("pnl_by_exit_reason", [{"trade_date": "2026-06-29", "exit_reason": "STOP_LOSS", "sell_count": 1, "total_profit_usd": -5, "win_rate": 0}]),
            Result("pnl_by_score_bucket", [{"trade_date": "2026-06-29", "score_bucket": "60_70", "sell_count": 2, "total_profit_usd": 5, "win_rate": 0.5}]),
            Result("pnl_by_source", [{"trade_date": "2026-06-29", "source": "fixed_recheck", "sell_count": 1, "total_profit_usd": -5, "win_rate": 0}]),
            Result("duplicate_suspects", [{"trade_date": "2026-06-29", "ticker": "AAA"}]),
            Result(
                "summary_reconciliation",
                [
                    {
                        "trade_date": "2026-06-29",
                        "daily_run_realized_profit_usd": 5,
                        "fill_vs_daily_run_diff": 0,
                        "fill_vs_trade_summary_diff": 0,
                    }
                ],
            ),
        ],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
        source_xlsx=tmp_path / "strategy_review_20260629.xlsx",
    )

    assert digest.startswith(AUTO_TRADING_DATA_DIGEST_MARKER)
    assert "report_date: 2026-06-29" in digest
    assert "date_range_basis: cumulative" in digest
    assert "daily_range: 2026-06-29..2026-06-29" in digest
    assert "cumulative_range: 2026-05-20..2026-06-29" in digest
    assert "daily_overall:" in digest
    assert "cumulative_overall:" in digest
    assert "- buy_count: 1" in digest
    assert "- sell_count: 2" in digest
    assert "- realized_exit_count: 2" in digest
    assert "- matched_trade_count: 2" in digest
    assert "- unmatched_trade_count: 0" in digest
    assert "daily_pnl_by_exit_reason:\n- basis: all_realized_sell_exits" in digest
    assert "cumulative_pnl_by_exit_reason:\n- basis: all_realized_sell_exits" in digest
    assert "- basis: all_realized_sell_exits" in digest
    assert "- basis: matched_candidate_rows_only" in digest
    assert "- STOP_LOSS: sell_count=1, pnl=-5.00" in digest
    assert "- 60_70: sell_count=2, pnl=5.00" in digest
    assert "- fixed_recheck: sell_count=1, pnl=-5.00" in digest
    assert "- daily_duplicate_suspects_count: 1" in digest
    assert "- cumulative_duplicate_suspects_count: 1" in digest
    assert "- daily_main_loss_driver: STOP_LOSS" in digest
    assert "- cumulative_main_loss_driver: STOP_LOSS" in digest


def test_build_strategy_review_digest_handles_zero_trades(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result("fill_history", []),
            Result("pnl_by_day", []),
            Result("pnl_by_exit_reason", []),
            Result("pnl_by_score_bucket", []),
            Result("pnl_by_source", []),
            Result("duplicate_suspects", []),
            Result("summary_reconciliation", []),
        ],
        report_date="2026-06-29",
        date_from="2026-05-20",
        date_to="2026-06-29",
        source_xlsx=tmp_path / "strategy_review_20260629.xlsx",
    )

    assert "daily_data_status: WARN" in digest
    assert "cumulative_data_status: WARN" in digest
    assert "daily_overall:\n- buy_count: 0\n- sell_count: 0" in digest
    assert "- sell_count: 0" in digest
    assert "- note: no trades for report_date" in digest
    assert "- missing_or_limited_fields: no_sell_rows, sell_sample_below_30" in digest


def test_build_strategy_review_digest_marks_missing_sheets_limited(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [Result("fill_history", [])],
        report_date="2026-06-29",
        date_from="2026-05-20",
        date_to="2026-06-29",
        source_xlsx=tmp_path / "strategy_review_20260629.xlsx",
    )

    assert "daily_data_status: WARN" in digest
    assert "cumulative_data_status: WARN" in digest
    assert "missing_sheet:pnl_by_exit_reason" in digest
    assert "missing_sheet:summary_reconciliation" in digest


def test_digest_separates_realized_exits_from_matched_candidate_counts(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result("fill_history", []),
            Result(
                "pnl_by_day",
                [
                    {
                        "trade_date": "2026-06-29",
                        "sell_count": 49,
                        "total_profit_usd": -895.66,
                        "win_count": 20,
                        "loss_count": 29,
                        "avg_win": 164.00,
                        "avg_loss": -143.99,
                        "max_win": 500,
                        "max_loss": -300,
                    }
                ],
            ),
            Result(
                "pnl_by_exit_reason",
                [
                    {"trade_date": "2026-06-29", "exit_reason": "STOP_LOSS", "sell_count": 13, "total_profit_usd": -2537.78, "win_rate": 0.0769},
                    {"trade_date": "2026-06-29", "exit_reason": "TRAILING_STOP", "sell_count": 26, "total_profit_usd": 1362.75, "win_rate": 0.7},
                    {"trade_date": "2026-06-29", "exit_reason": "EOD", "sell_count": 10, "total_profit_usd": 279.37, "win_rate": 0.4},
                ],
            ),
            Result("pnl_by_score_bucket", [{"trade_date": "2026-06-29", "score_bucket": "50_60", "sell_count": 8, "total_profit_usd": -632.23, "win_rate": 0.25}]),
            Result("pnl_by_source", [{"trade_date": "2026-06-29", "source": "fixed_recheck", "sell_count": 8, "total_profit_usd": -632.23, "win_rate": 0.25}]),
            Result("duplicate_suspects", []),
            Result(
                "summary_reconciliation",
                [
                    {
                        "trade_date": "2026-06-29",
                        "daily_run_realized_profit_usd": -747.48,
                        "fill_history_sell_profit_usd": -895.66,
                        "fill_vs_daily_run_diff": -148.18,
                    }
                ],
            ),
        ],
        report_date="2026-06-30",
        date_from="2026-05-20",
        date_to="2026-06-30",
        source_xlsx=tmp_path / "strategy_review_20260630.xlsx",
    )

    assert "date_range_basis: cumulative" in digest
    assert "daily_range: 2026-06-30..2026-06-30" in digest
    assert "cumulative_range: 2026-05-20..2026-06-30" in digest
    assert "daily_data_status: WARN" in digest
    assert "cumulative_data_status: FAIL" in digest
    assert "daily_overall:\n- buy_count: 0\n- sell_count: 0" in digest
    assert "- note: no trades for report_date" in digest
    assert "cumulative_overall:\n- buy_count: unknown\n- sell_count: 49" in digest
    assert "- buy_count: unknown" in digest
    assert "- sell_count: 49" in digest
    assert "- realized_exit_count: 49" in digest
    assert "- matched_trade_count: 8" in digest
    assert "- unmatched_trade_count: 41" in digest
    assert "daily_pnl_by_exit_reason:\n- basis: all_realized_sell_exits" in digest
    assert "cumulative_pnl_by_exit_reason:\n- basis: all_realized_sell_exits" in digest
    assert "daily_pnl_by_score_bucket:\n- basis: matched_candidate_rows_only\n- matched_sell_count: 0" in digest
    assert "cumulative_pnl_by_score_bucket:\n- basis: matched_candidate_rows_only\n- matched_sell_count: 8" in digest
    assert "daily_pnl_by_source:\n- basis: matched_candidate_rows_only\n- matched_sell_count: 0" in digest
    assert "cumulative_pnl_by_source:\n- basis: matched_candidate_rows_only\n- matched_sell_count: 8" in digest
    assert "- cumulative_fill_history_sell_rows: unknown" in digest
    assert "- cumulative_count_consistency_status: FAIL" in digest
    assert "- cumulative_matched_ratio: 16.33% FAIL" in digest
    assert "- signal_usage: disabled_below_50_percent_matched_ratio" in digest
    assert "- cumulative_reconciliation_gap: 148.18" in digest
    assert "- reconciliation_gap_basis: abs(realized_pnl - daily_summary_realized_pnl)" in digest
    assert "buy_count" in digest
    assert "fill_history_sell_rows" in digest
    assert "unmatched_score_source_rows" in digest
    assert "- daily_strategy_change_signal: HOLD_STRATEGY_CHANGE_UNTIL_DATA_QUALITY_FIXED" in digest
    assert "- cumulative_strategy_change_signal: HOLD_STRATEGY_CHANGE_UNTIL_DATA_QUALITY_FIXED" in digest
    assert "- recommended_review_focus: fix matching/reconciliation/count consistency before changing entry/exit rules" in digest


def test_digest_flags_low_match_ratio_reconciliation_missing_counts_and_duplicates(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result("fill_history", []),
            Result(
                "pnl_by_day",
                [
                    {
                        "trade_date": "2026-07-02",
                        "sell_count": 50,
                        "total_profit_usd": -943.22,
                        "win_count": 20,
                        "loss_count": 30,
                        "avg_win": 30,
                        "avg_loss": -51.44,
                        "max_win": 120,
                        "max_loss": -200,
                    }
                ],
            ),
            Result(
                "pnl_by_exit_reason",
                [
                    {"trade_date": "2026-07-02", "exit_reason": "STOP_LOSS", "sell_count": 25, "total_profit_usd": -1200, "win_rate": 0.0},
                    {"trade_date": "2026-07-02", "exit_reason": "TRAILING_STOP", "sell_count": 25, "total_profit_usd": 300, "win_rate": 0.8},
                ],
            ),
            Result("pnl_by_score_bucket", [{"trade_date": "2026-07-02", "score_bucket": "50_60", "sell_count": 9, "total_profit_usd": -100, "win_rate": 0.2}]),
            Result("pnl_by_source", [{"trade_date": "2026-07-02", "source": "fixed_recheck", "sell_count": 9, "total_profit_usd": -100, "win_rate": 0.2}]),
            Result(
                "duplicate_suspects",
                [
                    {
                        "trade_date": "2026-07-02",
                        "ticker": f"AAA{i}",
                        "side": "SELL",
                        "order_no": f"O{i}",
                        "fill_time": "15:00:00",
                        "fill_price": 10,
                        "row_count": 2,
                        "sum_quantity": 2,
                        "min_quantity": 1,
                        "max_quantity": 1,
                        "sum_profit_usd": -1,
                        "id_list": f"{i},{i + 100}",
                    }
                    for i in range(6)
                ],
            ),
            Result(
                "summary_reconciliation",
                [
                    {
                        "trade_date": "2026-07-02",
                        "daily_run_realized_profit_usd": -795.04,
                        "fill_history_sell_profit_usd": -943.22,
                        "fill_vs_daily_run_diff": -148.18,
                    }
                ],
            ),
        ],
        report_date="2026-07-02",
        date_from="2026-05-20",
        date_to="2026-07-02",
        source_xlsx=tmp_path / "strategy_review_20260702.xlsx",
    )

    assert "Status: FAIL" in digest
    assert "- matched_ratio: 18.00% FAIL" in digest
    assert "- cumulative_data_status: FAIL" in digest
    assert "- cumulative_reconciliation_status: FAIL" in digest
    assert "- cumulative_reconciliation_gap_abs: 148.18" in digest
    assert "buy_count missing" in digest
    assert "fill_history_sell_rows missing" in digest
    assert "- duplicate_suspects: 6 WARN" in digest
    assert "- count: 6" in digest
    assert "DUPLICATE_CONFIDENCE=HIGH" in digest
    assert "- cumulative_strategy_change_signal: HOLD_STRATEGY_CHANGE_UNTIL_DATA_QUALITY_FIXED" in digest
    assert "- confidence: LOW" in digest
    assert "- signal_usage: disabled_below_50_percent_matched_ratio" in digest
    assert "- strategy_review_vs_exit_reason_sum: -43.22" in digest


def test_build_strategy_review_digest_truncates_to_max_chars(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [Result("fill_history", [])],
        report_date="2026-06-29",
        date_from="2026-05-20",
        date_to="2026-06-29",
        source_xlsx=tmp_path / "strategy_review_20260629.xlsx",
        max_chars=300,
    )

    assert len(digest) <= 300
    assert digest.startswith(AUTO_TRADING_DATA_DIGEST_MARKER)
    assert digest.endswith("[truncated: max_chars]")


def test_save_strategy_review_digest_writes_utf8_without_bom(tmp_path) -> None:
    xlsx_path = tmp_path / "strategy_review_20260629.xlsx"
    digest_path = save_strategy_review_digest(
        AUTO_TRADING_DATA_DIGEST_MARKER + "\nhello",
        xlsx_path,
    )

    assert digest_path == tmp_path / "strategy_digest_20260629.txt"
    raw = digest_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8") == AUTO_TRADING_DATA_DIGEST_MARKER + "\nhello"
