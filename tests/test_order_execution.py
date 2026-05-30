from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, BuyIntent, TradeRecord
from trading_bot.order_execution import BuyIntentExecutor


class Repository:
    def __init__(self) -> None:
        self.trades: list[TradeRecord] = []
        self.logs: list[BotLog] = []

    def save_trades(self, trades: list[TradeRecord]) -> None:
        self.trades.extend(trades)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)


def test_buy_intent_executor_submits_and_records_mock_orders() -> None:
    submitted: list[BuyIntent] = []
    repository = Repository()
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
        )
    ]
    assert repository.trades == trades
    assert repository.logs == [
        BotLog(
            "INFO",
            "execution",
            "매수 주문 1건: AAA 2주 @ $10.50 (주문금액 $21.00, 배분 5.0%, 사유 OPENING_BREAKOUT)",
        )
    ]


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
