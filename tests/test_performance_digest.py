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
                    {"side": "BUY", "quantity": 1, "fill_amount": 100},
                    {"side": "SELL", "quantity": 1, "fill_amount": 110, "profit_usd": 10},
                    {"side": "SELL", "quantity": 1, "fill_amount": 90, "profit_usd": -5},
                ],
            ),
            Result(
                "pnl_by_day",
                [
                    {
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
            Result("pnl_by_exit_reason", [{"exit_reason": "STOP_LOSS", "sell_count": 1, "total_profit_usd": -5, "win_rate": 0}]),
            Result("pnl_by_score_bucket", [{"score_bucket": "60_70", "sell_count": 2, "total_profit_usd": 5, "win_rate": 0.5}]),
            Result("pnl_by_source", [{"source": "fixed_recheck", "sell_count": 1, "total_profit_usd": -5, "win_rate": 0}]),
            Result("duplicate_suspects", [{"ticker": "AAA"}]),
            Result(
                "summary_reconciliation",
                [
                    {
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
    assert "overall:" in digest
    assert "- buy_count: 1" in digest
    assert "- sell_count: 2" in digest
    assert "- STOP_LOSS: sell_count=1, pnl=-5.00" in digest
    assert "- 60_70: sell_count=2, pnl=5.00" in digest
    assert "- fixed_recheck: sell_count=1, pnl=-5.00" in digest
    assert "- duplicate_suspects_count: 1" in digest
    assert "- main_loss_driver: STOP_LOSS" in digest


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

    assert "data_status: LIMITED" in digest
    assert "- sell_count: 0" in digest
    assert "- missing_or_limited_fields: no_sell_rows, sell_sample_below_30" in digest


def test_build_strategy_review_digest_marks_missing_sheets_limited(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [Result("fill_history", [])],
        report_date="2026-06-29",
        date_from="2026-05-20",
        date_to="2026-06-29",
        source_xlsx=tmp_path / "strategy_review_20260629.xlsx",
    )

    assert "data_status: LIMITED" in digest
    assert "missing_sheet:pnl_by_exit_reason" in digest
    assert "missing_sheet:summary_reconciliation" in digest


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
