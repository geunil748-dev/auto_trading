from __future__ import annotations

import pytest

from tools.strategy_review_fill_normalization import (
    AMBIGUOUS_EXCLUDED,
    build_normalized_review,
    normalized_side_sql,
)


def _fill(
    source_id: int | None,
    ticker: str,
    order_no: str,
    quantity: int,
    *,
    side: str = "SELL",
    fill_time: str = "10:00:00",
    profit_usd: float | None = -1.0,
) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": "2026-07-10",
        "fill_time": fill_time,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "fill_price": 10,
        "fill_amount": quantity * 10,
        "profit_usd": profit_usd,
        "profit_rate": None if profit_usd is None or quantity == 0 else profit_usd / (quantity * 100),
        "order_no": order_no,
        "is_mock": True,
        "created_at": f"2026-07-10 10:00:{source_id or 0:02d}",
    }
    if source_id is not None:
        row["id"] = source_id
    return row


def test_lineage_unknown_side_and_invalid_quantity_emit_warnings_without_stopping() -> None:
    result = build_normalized_review(
        [
            _fill(1, "AAA", "O1", 1), _fill(1, "BBB", "O2", 1),
            _fill(None, "CCC", "O3", 1), _fill(4, "DDD", "O4", 1, side="구매"),
            _fill(5, "EEE", "O5", 0),
        ]
    )
    assert len(result.normalized_rows) == 5
    assert all(row["normalization_method"] == AMBIGUOUS_EXCLUDED for row in result.normalized_rows)
    assert {
        "AMBIGUOUS_FILLS_EXCLUDED", "DUPLICATE_SOURCE_ID_LINEAGE",
        "SOURCE_ID_LINEAGE_MISSING", "UNKNOWN_SIDE", "UNKNOWN_KOREAN_SIDE",
        "NON_POSITIVE_NORMALIZED_QUANTITY",
    }.issubset(result.warning_codes)
    lineage = [
        source_id
        for row in result.audit_rows
        for source_id in row["source_id_list"].split(",")
        if source_id
    ]
    assert lineage.count("4") == 1
    assert lineage.count("5") == 1


def test_exit_matching_prefers_order_then_nearest_time_and_marks_ties_ambiguous() -> None:
    fills = [
        _fill(1, "ORD", "O1", 1, fill_time="10:00:00", profit_usd=-2),
        _fill(2, "TIM", "NO_MATCH", 1, fill_time="10:09:00", profit_usd=3),
        _fill(3, "TIE", "NO_MATCH", 1, fill_time="10:05:00", profit_usd=-1),
    ]
    trades = [
        {"id": 1, "trade_date": "2026-07-10", "ticker": "ORD", "order_type": "매도",
         "order_no": "O1", "last_fill_time": "10:20:00", "exit_reason": "STOP_LOSS"},
        {"id": 2, "trade_date": "2026-07-10", "ticker": "TIM", "order_type": "SELL",
         "last_fill_time": "10:00:00", "exit_reason": "STOP_LOSS"},
        {"id": 3, "trade_date": "2026-07-10", "ticker": "TIM", "order_type": "S",
         "last_fill_time": "10:10:00", "exit_reason": "TAKE_PROFIT"},
        {"id": 4, "trade_date": "2026-07-10", "ticker": "TIE", "order_type": "SELL",
         "last_fill_time": "10:00:00", "exit_reason": "STOP_LOSS"},
        {"id": 5, "trade_date": "2026-07-10", "ticker": "TIE", "order_type": "SELL",
         "last_fill_time": "10:10:00", "exit_reason": "TAKE_PROFIT"},
    ]
    rows = {row["ticker"]: row for row in build_normalized_review(fills, trade_rows=trades).normalized_rows}
    assert rows["ORD"]["exit_reason"] == "STOP_LOSS"
    assert rows["ORD"]["match_method"] == "ORDER_NO"
    assert rows["TIM"]["exit_reason"] == "TAKE_PROFIT"
    assert rows["TIM"]["match_method"] == "TIME_NEAREST"
    assert rows["TIM"]["match_distance_seconds"] == 60
    assert rows["TIE"]["exit_reason"] == "AMBIGUOUS"
    assert rows["TIE"]["match_ambiguous"] is True


def test_exit_matching_does_not_cross_mock_and_real_modes() -> None:
    fill = _fill(1, "AAA", "O1", 1, profit_usd=-2)
    trades = [
        {
            "id": 1,
            "trade_date": "2026-07-10",
            "ticker": "AAA",
            "order_type": "SELL",
            "order_no": "O1",
            "last_fill_time": "10:00:00",
            "exit_reason": "REAL_EXIT",
            "is_mock": False,
        },
        {
            "id": 2,
            "trade_date": "2026-07-10",
            "ticker": "AAA",
            "order_type": "SELL",
            "order_no": "O1",
            "last_fill_time": "10:00:00",
            "exit_reason": "MOCK_EXIT",
            "is_mock": True,
        },
    ]

    row = build_normalized_review([fill], trade_rows=trades).normalized_rows[0]

    assert row["exit_reason"] == "MOCK_EXIT"
    assert row["match_method"] == "ORDER_NO"
    assert row["match_ambiguous"] is False


def test_trusted_best_effort_candidate_pnl_and_reconciliation_are_separate() -> None:
    fills = [
        _fill(1, "AAA", "S1", 1, profit_usd=10),
        _fill(2, "AAA", "S2", 1, profit_usd=-5, fill_time="10:01:00"),
        _fill(3, "AAA", "", 1, profit_usd=3, fill_time="10:02:00"),
        _fill(4, "AMB", "A1", 100, profit_usd=2),
        _fill(5, "AMB", "A1", 150, profit_usd=7, fill_time="10:03:00"),
    ]
    candidates = [{
        "id": 1, "trading_date": "2026-07-10", "evaluation_time": "2026-07-10 09:30:00",
        "symbol": "AAA", "source": "ranked", "final_score": 55,
        "buy_allowed": True, "order_submitted": True,
    }]
    result = build_normalized_review(
        fills,
        candidate_rows=candidates,
        daily_summary_rows=[{"trade_date": "2026-07-10", "realized_profit_usd": 5}],
        trade_summary_rows=[{"trade_date": "2026-07-10", "total_profit_usd": 5}],
    )
    day = result.pnl_by_day[0]
    assert (day["sell_count"], day["total_profit_usd"], day["profit_factor"]) == (2, 5, 2)
    assert (day["best_effort_sell_count"], day["best_effort_total_profit_usd"]) == (3, 8)
    candidate = result.candidate_rows[0]
    assert (candidate["sell_count"], candidate["sell_profit_usd"]) == (2, 5)
    assert (candidate["best_effort_sell_count"], candidate["best_effort_sell_profit_usd"]) == (3, 8)
    assert result.pnl_by_score_bucket[0]["score_bucket"] == "50~60"
    assert result.pnl_by_score_bucket[0]["total_profit_usd"] == 5
    assert result.pnl_by_source[0]["source"] == "ranked"
    reconciliation = result.reconciliation_rows[0]
    assert reconciliation["raw_sell_row_count"] == 5
    assert reconciliation["normalized_sell_order_count"] == 2
    assert reconciliation["best_effort_sell_order_count"] == 3
    assert reconciliation["raw_profit_usd"] == 17
    assert reconciliation["normalized_profit_usd"] == 5
    assert reconciliation["best_effort_profit_usd"] == 8
    assert reconciliation["profit_difference"] == 12
    assert reconciliation["ambiguous_order_count"] == 1
    assert reconciliation["ambiguous_profit_usd"] == 9
    assert reconciliation["normalized_vs_daily_run_diff"] == 0
    assert "NORMALIZED_DAILY_SUMMARY_MISMATCH" not in result.warning_codes


def test_empty_and_missing_optional_inputs_still_produce_all_outputs() -> None:
    result = build_normalized_review([])
    assert result.normalized_rows == []
    assert result.audit_rows == []
    assert result.pnl_by_day == []
    assert result.pnl_by_ticker == []
    assert result.pnl_by_exit_reason == []
    assert result.candidate_rows == []
    assert result.reconciliation_rows == []
    assert result.warning_codes == []


def test_empty_sql_expression_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalized_side_sql("  ")
