from __future__ import annotations

from datetime import date

from trading_bot.performance_digest import build_strategy_review_digest
from trading_bot.performance_digest_candidate_matching import (
    build_candidate_matching_diagnostics,
    resolve_active_candidate,
)


def test_multiple_candidates_with_explicit_order_id_match_high_confidence() -> None:
    result = resolve_active_candidate(
        _ledger_row(buy_order_id="BO1"),
        [
            _candidate("1", order_id="OTHER", evaluation_time="09:00:00"),
            _candidate("2", order_id="BO1", evaluation_time="09:10:00"),
        ],
    )

    assert result["match_method"] == "EXPLICIT_ORDER_ID"
    assert result["active_candidate_confidence"] == "HIGH"
    assert result["active_candidate_candidate_id"] == "2"


def test_unique_submitted_candidate_before_buy_matches_high_confidence() -> None:
    result = resolve_active_candidate(
        _ledger_row(),
        [
            _candidate("1", evaluation_time="09:00:00"),
            _candidate("2", evaluation_time="09:10:00", order_submitted=1, final_decision="ORDER_SUBMITTED"),
        ],
    )

    assert result["match_method"] == "UNIQUE_SUBMITTED_CANDIDATE"
    assert result["active_candidate_confidence"] == "HIGH"


def test_candidate_created_after_buy_is_excluded() -> None:
    result = resolve_active_candidate(
        _ledger_row(buy_time="09:30:00"),
        [_candidate("1", evaluation_time="09:45:00", order_submitted=1)],
    )

    assert result["candidate_after_buy_count"] == 1
    assert result["active_candidate_confidence"] == "NONE"
    assert result["ambiguity_reason"] == "NO_ACTIVE_CANDIDATE_FOUND"


def test_multiple_active_candidates_before_buy_stays_ambiguous() -> None:
    result = resolve_active_candidate(
        _ledger_row(),
        [_candidate("1", evaluation_time="09:00:00"), _candidate("2", evaluation_time="09:10:00")],
    )

    assert result["active_candidate_confidence"] == "NONE"
    assert result["ambiguity_reason"] == "AMBIGUOUS_MULTIPLE_ACTIVE_CANDIDATES"


def test_buy_block_reason_candidate_is_not_active() -> None:
    result = resolve_active_candidate(
        _ledger_row(),
        [_candidate("1", evaluation_time="09:00:00", buy_block_reason="VWAP_MA20_FAILED")],
    )

    assert result["active_candidate_confidence"] == "NONE"
    assert result["ambiguity_reason"] == "NO_ACTIVE_CANDIDATE_FOUND"


def test_blocked_final_decision_candidate_is_not_active() -> None:
    result = resolve_active_candidate(
        _ledger_row(),
        [_candidate("1", evaluation_time="09:00:00", final_decision="ORDER_NOT_SUBMITTED")],
    )

    assert result["active_candidate_confidence"] == "NONE"
    assert result["ambiguity_reason"] == "NO_ACTIVE_CANDIDATE_FOUND"


def test_nearest_candidate_before_buy_single_candidate_is_medium() -> None:
    result = resolve_active_candidate(_ledger_row(), [_candidate("1", evaluation_time="09:00:00")])

    assert result["match_method"] == "NEAREST_CANDIDATE_BEFORE_BUY"
    assert result["active_candidate_confidence"] == "MEDIUM"


def test_source_entry_reason_assist_never_gives_high_confidence() -> None:
    result = resolve_active_candidate(
        _ledger_row(buy_entry_reason="fixed_recheck"),
        [
            _candidate("1", source="auto", evaluation_time="09:00:00"),
            _candidate("2", source="fixed_recheck", evaluation_time="09:10:00"),
        ],
    )

    assert result["match_method"] == "SOURCE_ENTRY_REASON_ASSISTED"
    assert result["active_candidate_confidence"] == "LOW"


def test_low_and_none_confidence_are_excluded_from_score_source_analysis() -> None:
    diagnostics = build_candidate_matching_diagnostics(
        [
            _ledger_row(row_no=1, buy_entry_reason="fixed_recheck"),
            _ledger_row(row_no=2, buy_time="09:30:00"),
        ],
        [
            _candidate("1", source="auto", evaluation_time="09:00:00"),
            _candidate("2", source="fixed_recheck", evaluation_time="09:10:00"),
            _candidate("3", symbol="BBB", evaluation_time="09:45:00", order_submitted=1),
        ],
    )

    assert diagnostics["candidate_matching_quality"]["score_source_analysis_eligible_count"] == 0
    assert all(row["is_included_in_score_source_analysis"] is False for row in diagnostics["ledger_v2"])


def test_still_ambiguous_keeps_strategy_change_signal_on_hold(tmp_path) -> None:
    digest = build_strategy_review_digest(
        [
            Result("fill_history", [_fill("BUY"), _fill("SELL", profit_usd=-10)]),
            Result("pnl_by_day", [{"trade_date": "2026-07-02", "sell_count": 1, "total_profit_usd": -10}]),
            Result("pnl_by_exit_reason", [{"trade_date": "2026-07-02", "exit_reason": "STOP_LOSS", "sell_count": 1, "total_profit_usd": -10}]),
            Result("pnl_by_score_bucket", []),
            Result("pnl_by_source", []),
            Result("duplicate_suspects", []),
            Result("summary_reconciliation", [{"trade_date": "2026-07-02", "daily_run_realized_profit_usd": 0, "fill_vs_daily_run_diff": -10}]),
            Result("candidate_evaluations", [_candidate("1"), _candidate("2")]),
        ],
        report_date=date(2026, 7, 2),
        date_from="2026-07-02",
        date_to="2026-07-02",
        source_xlsx=tmp_path / "strategy_review_20260702.xlsx",
    )

    assert "- cumulative_strategy_change_signal: HOLD_STRATEGY_CHANGE_UNTIL_DATA_QUALITY_FIXED" in digest
    assert "- still_ambiguous_count: 1" in digest


def test_linkage_limitation_reported_when_ambiguity_remains() -> None:
    diagnostics = build_candidate_matching_diagnostics(
        [_ledger_row()],
        [_candidate("1", evaluation_time="09:00:00"), _candidate("2", evaluation_time="09:10:00")],
    )

    limitation = diagnostics["linkage_limitations"]
    assert limitation["explicit_candidate_order_link_available"] is False
    assert limitation["still_ambiguous_count"] == 1


def test_matching_ledger_v2_diagnostic_detail_is_never_empty() -> None:
    diagnostics = build_candidate_matching_diagnostics(
        [_ledger_row(row_no=1), _ledger_row(row_no=2, buy_time="09:30:00")],
        [_candidate("1", evaluation_time="09:00:00"), _candidate("2", symbol="BBB", evaluation_time="09:45:00")],
    )

    assert all(row["diagnostic_detail"] for row in diagnostics["ledger_v2"])


class Result:
    def __init__(self, name: str, rows: list[dict[str, object]], error: str = "") -> None:
        self.name = name
        self.rows = rows
        self.error = error


def _ledger_row(**overrides: object) -> dict[str, object]:
    row = {
        "row_no": 1,
        "trade_date": "2026-07-02",
        "symbol": "AAA",
        "sell_time": "10:00:00",
        "buy_time": "09:30:00",
        "sell_order_id": "SO1",
        "buy_order_id": "BO1",
        "sell_fill_id": "S1",
        "buy_fill_id": "B1",
        "realized_pnl": -1,
        "exit_reason": "STOP_LOSS",
        "unmatched_reason": "MULTIPLE_CANDIDATE_ROWS_AMBIGUOUS",
    }
    row.update(overrides)
    return row


def _candidate(candidate_id: str, **overrides: object) -> dict[str, object]:
    row = {
        "id": candidate_id,
        "trading_date": "2026-07-02",
        "symbol": "AAA",
        "evaluation_time": "09:00:00",
        "source": "auto",
        "final_score": 60,
        "buy_allowed": 1,
        "order_submitted": 0,
        "final_decision": "BUY_ALLOWED",
        "buy_block_reason": "BUY_ALLOWED",
    }
    row.update(overrides)
    return row


def _fill(side: str, **overrides: object) -> dict[str, object]:
    row = {
        "trade_date": "2026-07-02",
        "ticker": "AAA",
        "side": side,
        "id": f"{side}1",
        "order_no": f"{side}O1",
        "fill_time": "09:30:00" if side == "BUY" else "10:00:00",
        "profit_usd": 0,
    }
    row.update(overrides)
    return row
