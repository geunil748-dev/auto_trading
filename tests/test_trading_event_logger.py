from __future__ import annotations

import json
from datetime import date, datetime

from trading_bot.models import BotLog, BuyIntent, CandidateEvaluation, TradeRecord, TradingEvent
from trading_bot.trading_event_logger import (
    record_data_quality_event,
    record_buy_not_submitted,
    record_candidate_evaluation_event,
    record_order_reconciliation,
    record_order_protection_blocked,
    record_trading_event,
    sanitize_event_details,
)


class FakeRepository:
    def __init__(self) -> None:
        self.events: list[TradingEvent] = []
        self.logs: list[BotLog] = []
        self.not_submitted: list[tuple[str, date, str]] = []
        self.fail_events = False
        self.fail_candidate = False

    def save_trading_events(self, events) -> None:
        if self.fail_events:
            raise RuntimeError("event db down")
        self.events.extend(events)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)

    def mark_candidate_evaluation_order_not_submitted(
        self,
        ticker: str,
        trade_date: date,
        reason: str,
    ) -> None:
        if self.fail_candidate:
            raise RuntimeError("candidate db down")
        self.not_submitted.append((ticker, trade_date, reason))


def test_sanitize_event_details_redacts_sensitive_keys() -> None:
    details = sanitize_event_details(
        {
            "token": "abc",
            "nested": {"appSecret": "def", "chat_id": "123", "value": 1},
            "rows": [{"account_no": "999", "symbol": "AAA"}],
        }
    )

    assert details["token"] == "<redacted>"
    assert details["nested"]["appSecret"] == "<redacted>"
    assert details["nested"]["chat_id"] == "<redacted>"
    assert details["nested"]["value"] == 1
    assert details["rows"][0]["account_no"] == "<redacted>"
    assert details["rows"][0]["symbol"] == "AAA"


def test_record_trading_event_sanitizes_without_default_bot_log() -> None:
    repository = FakeRepository()

    saved = record_trading_event(
        repository,
        TradingEvent(
            event_time=datetime(2026, 6, 18, 1, 2, 3),
            trade_date=date(2026, 6, 18),
            ticker="AAA",
            stage="NOTIFICATION",
            event_type="NOTIFICATION_SENT",
            reason_code="CANDIDATE_LIST_TELEGRAM_SENT",
            details_json={"telegram_token": "secret", "메모": "한글"},
        ),
    )

    assert saved is True
    assert repository.logs == []
    assert repository.events[0].details_json["telegram_token"] == "<redacted>"
    assert repository.events[0].details_json["메모"] == "한글"
    assert repository.events[0].details_json["correlation"]["event_type"] == "NOTIFICATION_SENT"


def test_record_trading_event_writes_bot_log_when_explicitly_enabled() -> None:
    repository = FakeRepository()

    saved = record_trading_event(
        repository,
        TradingEvent(
            event_time=datetime(2026, 6, 18, 1, 2, 3),
            trade_date=date(2026, 6, 18),
            ticker="AAA",
            stage="NOTIFICATION",
            event_type="NOTIFICATION_SENT",
            reason_code="OPERATOR_VISIBLE_EVENT",
        ),
        fallback_bot_log=True,
    )

    assert saved is True
    assert repository.logs[-1].reject_reason == "OPERATOR_VISIBLE_EVENT"


def test_record_buy_not_submitted_updates_candidate_event_without_default_bot_log() -> None:
    repository = FakeRepository()

    record_buy_not_submitted(
        repository,
        ticker="AAA",
        trade_date=date(2026, 6, 18),
        reason_code="NO_ORDER_UNFILLED_ORDER",
        details={"order_no": "1001"},
    )

    assert repository.not_submitted == [
        ("AAA", date(2026, 6, 18), "NO_ORDER_UNFILLED_ORDER")
    ]
    assert repository.events[0].event_type == "BUY_NOT_SUBMITTED"
    assert repository.events[0].reason_code == "NO_ORDER_UNFILLED_ORDER"
    assert repository.events[0].details_json["reason_family"] == "NO_ORDER"
    assert repository.events[0].details_json["correlation"]["flow_key"] == "2026-06-18:AAA"
    assert repository.logs == []


def test_record_buy_not_submitted_writes_bot_log_when_explicitly_enabled() -> None:
    repository = FakeRepository()

    record_buy_not_submitted(
        repository,
        ticker="AAA",
        trade_date=date(2026, 6, 18),
        reason_code="NO_ORDER_UNFILLED_ORDER",
        fallback_bot_log=True,
    )

    assert repository.logs[-1].message == (
        "candidate_order_not_submitted symbol=AAA reason=NO_ORDER_UNFILLED_ORDER"
    )


def test_record_buy_not_submitted_survives_candidate_update_failure() -> None:
    repository = FakeRepository()
    repository.fail_candidate = True

    record_buy_not_submitted(
        repository,
        ticker="AAA",
        trade_date=date(2026, 6, 18),
        reason_code="STOP_LOSS_COOLDOWN",
    )

    assert repository.events[0].reason_code == "STOP_LOSS_COOLDOWN"
    assert any(log.reject_reason == "CANDIDATE_NO_ORDER_REASON_SAVE_FAILED" for log in repository.logs)


def test_record_trading_event_failure_does_not_raise() -> None:
    repository = FakeRepository()
    repository.fail_events = True

    saved = record_trading_event(
        repository,
        TradingEvent(
            event_time=datetime(2026, 6, 18, 1, 2, 3),
            stage="ORDER_SUBMISSION",
            event_type="ORDER_SUBMIT_FAILED",
        ),
        fallback_bot_log=False,
    )

    assert saved is False
    assert repository.logs[-1].reject_reason == "TRADING_EVENT_LOG_SAVE_FAILED"


def test_candidate_evaluation_records_buy_allowed_and_blocked() -> None:
    repository = FakeRepository()

    record_candidate_evaluation_event(
        repository,
        CandidateEvaluation(
            run_id="run-1",
            evaluation_time=datetime(2026, 6, 18, 1, 2, 3),
            trading_date=date(2026, 6, 18),
            source="manual_buy_list",
            symbol="AAA",
            buy_allowed=True,
            final_decision="BUY_ALLOWED",
            condition_result_json=json.dumps({"조건": "통과"}, ensure_ascii=False),
        ),
    )
    record_candidate_evaluation_event(
        repository,
        CandidateEvaluation(
            run_id="run-1",
            evaluation_time=datetime(2026, 6, 18, 1, 3, 3),
            trading_date=date(2026, 6, 18),
            source="auto",
            symbol="BBB",
            buy_allowed=False,
            buy_block_reason="BREAKOUT_NOT_TRIGGERED",
        ),
    )

    assert repository.events[0].event_type == "BUY_ALLOWED"
    assert repository.events[0].candidate_source == "manual_buy_list"
    assert repository.events[1].event_type == "BUY_BLOCKED"
    assert repository.events[1].reason_code == "BREAKOUT_NOT_TRIGGERED"
    assert repository.logs == []


def test_order_protection_blocked_marks_candidate_not_submitted() -> None:
    repository = FakeRepository()
    intent = BuyIntent("AAA", 10, 12.5, 125.0, 0.1)

    record_order_protection_blocked(
        repository,
        intent,
        BotLog(
            "WARNING",
            "execution",
            "blocked",
            symbol="AAA",
            reject_reason="BID_ASK_SPREAD_TOO_WIDE",
            actual_value=1.2,
            threshold_value=1.0,
        ),
        trade_date=date(2026, 6, 18),
    )

    assert repository.not_submitted == [
        ("AAA", date(2026, 6, 18), "BID_ASK_SPREAD_TOO_WIDE")
    ]
    assert repository.events[0].event_type == "ORDER_PROTECTION_BLOCKED"


def test_order_reconciliation_records_matched_and_missing() -> None:
    repository = FakeRepository()

    record_order_reconciliation(
        repository,
        trade_date=date(2026, 6, 18),
        side="BUY",
        planned=[
            BuyIntent("AAA", 1, 10.0, 10.0, 0.01),
            BuyIntent("BBB", 1, 11.0, 11.0, 0.01),
        ],
        trades=[
            TradeRecord(
                trade_date=date(2026, 6, 18),
                ticker="AAA",
                order_type="BUY",
                order_price_usd=10.0,
                exec_price_usd=None,
                quantity=1,
            )
        ],
    )

    assert [event.event_type for event in repository.events] == [
        "ORDER_RECONCILIATION_MATCHED",
        "ORDER_RECONCILIATION_MISSING_TRADE_RECORD",
    ]
    assert repository.events[1].is_blocking is True
    assert repository.events[1].details_json["correlation"]["flow_key"] == "2026-06-18:BBB"


def test_data_quality_event_records_details_without_bot_log() -> None:
    repository = FakeRepository()

    record_data_quality_event(
        repository,
        reason_code="FILL_MONITOR_ROWS_SKIPPED",
        trade_date=date(2026, 6, 18),
        details={"raw_fill_count": 2, "saved_fill_count": 1},
    )

    assert repository.events[0].event_type == "DATA_QUALITY_EVENT"
    assert repository.events[0].reason_code == "FILL_MONITOR_ROWS_SKIPPED"
    assert repository.events[0].details_json["raw_fill_count"] == 2
    assert repository.logs == []
