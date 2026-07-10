from dataclasses import replace
from datetime import date, datetime, timezone

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, BuyIntent, CandidateEvaluation, TradeRecord, TradingEvent
from trading_bot.order_execution import BuyIntentExecutor
from trading_bot.strategy_metadata import strategy_metadata_from_settings


class Repository:
    def __init__(self) -> None:
        self.trades: list[TradeRecord] = []
        self.logs: list[BotLog] = []
        self.candidate_evaluations: list[CandidateEvaluation] = []
        self.trading_events: list[TradingEvent] = []

    def save_trades(self, trades: list[TradeRecord]) -> None:
        self.trades.extend(trades)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)

    def save_trading_events(self, events: list[TradingEvent]) -> None:
        self.trading_events.extend(events)

    def mark_candidate_evaluation_order_submitted(
        self,
        ticker: str,
        trade_date: date,
        order_id: str | None = None,
    ) -> None:
        for index, item in enumerate(self.candidate_evaluations):
            if item.symbol == ticker and item.trading_date == trade_date:
                self.candidate_evaluations[index] = replace(
                    item,
                    order_submitted=True,
                    order_id=order_id,
                    final_decision="ORDER_SUBMITTED",
                )


def test_buy_intent_executor_submits_and_records_mock_orders() -> None:
    submitted: list[BuyIntent] = []
    repository = Repository()
    metadata = strategy_metadata_from_settings(TradingSettings())
    executor = BuyIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    )

    trades = executor.execute([BuyIntent("AAA", 2, 10.5, 21, 0.05)])

    assert submitted == [BuyIntent("AAA", 2, 10.5, 21, 0.05)]
    assert trades == [
        TradeRecord(
            date(2026, 5, 22),
            "AAA",
            "BUY",
            10.5,
            None,
            2,
            entry_reason="OPENING_BREAKOUT",
            entry_reason_detail="",
            order_status="SUCCESS",
            order_qty=2,
            filled_qty=0,
            remaining_qty=2,
            strategy_version=metadata.strategy_version,
            settings_snapshot_hash=metadata.settings_snapshot_hash,
            settings_snapshot_json=metadata.settings_snapshot_json,
        )
    ]
    assert repository.trades == trades
    assert repository.logs == [
        BotLog(
            "INFO",
            "execution",
            "매수 주문 1건: AAA 2주 @ $10.50 (주문금액 $21.00, 배분 5.0%, 사유 장초반 돌파)",
        )
    ]


def test_buy_intent_executor_marks_candidate_evaluation_order_submitted() -> None:
    repository = Repository()
    repository.candidate_evaluations = [
        CandidateEvaluation(
            run_id=None,
            evaluation_time=datetime(2026, 5, 22, 13, 30, tzinfo=timezone.utc),
            trading_date=date(2026, 5, 22),
            source="test",
            symbol="AAA",
            buy_allowed=True,
        )
    ]

    BuyIntentExecutor(
        submit_order=lambda intent: {"output": {"ODNO": "1001"}},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([BuyIntent("AAA", 1, 10, 10, 0.05)])

    assert repository.candidate_evaluations[0].order_submitted is True
    assert repository.candidate_evaluations[0].order_id == "1001"
    assert [event.event_type for event in repository.trading_events] == [
        "EXECUTOR_ENTERED",
        "SUBMIT_ORDER_CALLED",
        "ORDER_SUBMIT_SUCCEEDED",
        "ORDER_RECONCILIATION_MATCHED",
    ]
    assert repository.trading_events[2].order_no == "1001"
    assert len(repository.logs) == 1
    assert repository.logs[0].module == "execution"


def test_buy_intent_executor_handles_empty_intents() -> None:
    submitted: list[BuyIntent] = []
    repository = Repository()

    trades = BuyIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([])

    assert submitted == []
    assert trades == []
    assert repository.trades == []
    assert repository.logs == [
        BotLog("INFO", "execution", "매수 주문 0건: 실행할 매수 후보가 없습니다.")
    ]


def test_buy_intent_executor_records_failures_and_continues() -> None:
    repository = Repository()

    def submit_order(intent: BuyIntent) -> dict[str, object]:
        if intent.ticker == "FAIL":
            raise RuntimeError("order rejected")
        return {"ok": True}

    trades = BuyIntentExecutor(
        submit_order=submit_order,
        repository=repository,
        today=lambda: date(2026, 5, 22),
        settings=TradingSettings(max_order_retry_count=0),
    ).execute(
        [
            BuyIntent("FAIL", 1, 9.1, 9.1, 0.01),
            BuyIntent("OK", 2, 10.2, 20.4, 0.02),
        ]
    )

    assert [item.ticker for item in trades] == ["OK"]
    assert repository.trades == trades
    assert repository.logs[0].level == "ERROR"
    assert "FAIL" in repository.logs[0].message
    assert repository.logs[1].reject_reason == "ORDER_FAILED"
    assert repository.logs[2].level == "INFO"
    assert "OK" in repository.logs[2].message
    assert "FAIL" not in repository.logs[2].message
    failures = [
        item
        for item in repository.trading_events
        if item.event_type in {"ORDER_SUBMIT_EXCEPTION", "ORDER_SUBMIT_FAILED"}
    ]
    assert [item.reason_code for item in failures] == [
        "API_ERROR",
        "ORDER_FAILED",
    ]
    assert [item.event_type for item in repository.trading_events] == [
        "EXECUTOR_ENTERED",
        "SUBMIT_ORDER_CALLED",
        "ORDER_SUBMIT_EXCEPTION",
        "ORDER_SUBMIT_FAILED",
        "EXECUTOR_ENTERED",
        "SUBMIT_ORDER_CALLED",
        "ORDER_SUBMIT_SUCCEEDED",
        "ORDER_RECONCILIATION_MISSING_TRADE_RECORD",
        "ORDER_RECONCILIATION_MATCHED",
    ]


def test_buy_intent_executor_retries_temporary_api_errors() -> None:
    repository = Repository()
    calls = 0

    def submit_order(intent: BuyIntent) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary")
        return {"ok": True}

    trades = BuyIntentExecutor(
        submit_order=submit_order,
        repository=repository,
        today=lambda: date(2026, 5, 22),
        settings=TradingSettings(max_order_retry_count=2, order_retry_delay_seconds=0),
        retry_sleep=lambda _: None,
    ).execute([BuyIntent("AAA", 1, 10, 10, 0.01)])

    assert calls == 2
    assert trades[0].retry_count == 1
    assert [item.reject_reason for item in repository.logs[:2]] == ["API_ERROR", "RETRY"]
    failures = [
        item
        for item in repository.trading_events
        if item.event_type in {"ORDER_SUBMIT_EXCEPTION", "ORDER_RETRY"}
    ]
    assert [item.reason_code for item in failures] == [
        "API_ERROR",
        "RETRY",
    ]
    assert [item.event_type for item in repository.trading_events] == [
        "EXECUTOR_ENTERED",
        "SUBMIT_ORDER_CALLED",
        "ORDER_SUBMIT_EXCEPTION",
        "ORDER_RETRY",
        "SUBMIT_ORDER_CALLED",
        "ORDER_SUBMIT_SUCCEEDED",
        "ORDER_RECONCILIATION_MATCHED",
    ]
    assert repository.logs[-1].module == "execution"


def test_buy_intent_executor_blocks_wide_bid_ask_spread() -> None:
    submitted: list[BuyIntent] = []
    repository = Repository()

    trades = BuyIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
        settings=TradingSettings(max_bid_ask_spread_rate=1.0),
        quote_reader=lambda _: {"bid": "9.00", "ask": "10.50", "last": "10.00"},
    ).execute([BuyIntent("AAA", 1, 10, 10, 0.01)])

    assert submitted == []
    assert trades == []
    assert repository.logs[0].reject_reason == "BID_ASK_SPREAD_TOO_WIDE"
    assert repository.trading_events[1].event_type == "ORDER_PROTECTION_BLOCKED"
    assert repository.trading_events[1].is_blocking is True


def test_buy_intent_executor_records_broker_rejection_separately() -> None:
    repository = Repository()

    trades = BuyIntentExecutor(
        submit_order=lambda intent: {
            "rt_cd": "1",
            "msg_cd": "APBK0919",
            "msg1": "주문이 거절되었습니다.",
        },
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([BuyIntent("AAA", 1, 10, 10, 0.01, run_id="run-1")])

    assert trades == []
    assert [event.event_type for event in repository.trading_events[:3]] == [
        "EXECUTOR_ENTERED",
        "SUBMIT_ORDER_CALLED",
        "BROKER_ORDER_REJECTED",
    ]
    assert repository.trading_events[2].reason_code == "APBK0919"
    assert repository.trading_events[2].run_id == "run-1"
