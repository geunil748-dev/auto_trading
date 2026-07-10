from datetime import date, datetime, timezone

from tools.weekly_trade_audit import (
    data_quality_status,
    normalize_trading_date,
    order_fill_metrics,
    representative_block_reasons,
    shadow_pass_counts,
)


def test_normalize_trading_date_accepts_database_and_python_shapes() -> None:
    expected = "2026-07-06"
    assert normalize_trading_date("2026-07-06") == expected
    assert normalize_trading_date("2026-07-06 00:00:00") == expected
    assert normalize_trading_date("2026-07-06 00:00:00 UTC") == expected
    assert normalize_trading_date(date(2026, 7, 6)) == expected
    assert normalize_trading_date(datetime(2026, 7, 6, tzinfo=timezone.utc)) == expected


def test_block_reason_sum_excludes_buy_allowed() -> None:
    rows = ([{"decision": "BUY_BLOCKED", "representative_reason": "FILTER"}] * 44
            + [{"decision": "BUY_ALLOWED", "representative_reason": "BUY_ALLOWED"}] * 10)
    reasons = representative_block_reasons(rows)
    assert sum(reasons.values()) == 44


def test_july_6_order_fill_metrics_do_not_treat_reconciliation_as_submit() -> None:
    events = [
        {"event_type": "BUY_ALLOWED"} for _ in range(10)
    ] + [
        {"event_type": "ORDER_SUBMITTED", "side": "BUY", "order_submitted": True},
        {"event_type": "ORDER_SUBMITTED", "side": "BUY", "order_submitted": True},
        {"event_type": "ORDER_SUBMITTED", "side": "SELL", "order_submitted": True},
        {"event_type": "ORDER_RECONCILIATION", "side": "BUY", "order_submitted": False},
    ]
    metrics = order_fill_metrics(events, [{}] * 4,
                                 [{"ticker": "RIVN", "side": "BUY"}, {"ticker": "RIVN", "side": "SELL"}],
                                 [{}] * 3)
    assert metrics["order_snapshot_row_count"] == 4
    assert metrics["actual_buy_fill_count"] == 1
    assert metrics["actual_sell_fill_count"] == 1
    assert metrics["buy_order_submit_success_count"] == 2
    assert metrics["sell_order_submit_success_count"] == 1
    assert metrics["completed_round_trip_count"] == 1
    assert metrics["trade_submission_record_count"] == 3


def test_shadow_soft_score_applies_configured_penalty() -> None:
    rows = ([{"trading_date": "2026-07-07", "ticker": "FISV", "selection_score": 65}] * 1
            + [{"trading_date": "2026-07-08", "ticker": "PDD", "selection_score": 65}] * 8
            + [{"trading_date": "2026-07-09", "ticker": "RIVN", "selection_score": 65}] * 25
            + [{"trading_date": "2026-07-10", "ticker": "VOD", "selection_score": 65}] * 8
            + [{"trading_date": "2026-07-09", "ticker": "BBIO", "selection_score": 61}] * 24)
    assert shadow_pass_counts(rows, threshold=60, soft_penalty=-5) == {
        "soft_score_pass_rows": 42, "soft_score_unique_candidates": 4,
        "log_only_pass_rows": 66, "log_only_unique_candidates": 5,
    }


def test_quality_cannot_pass_when_a_required_reconciliation_fails() -> None:
    assert data_quality_status({"raw_rows_match": True, "orders_match": False}) == "FAIL"
    assert data_quality_status({"raw_rows_match": True}, ["all_volume_data_missing"]) == "PASS_WITH_WARNINGS"
