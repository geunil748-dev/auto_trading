from datetime import date

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
    assert repository.logs[1].level == "INFO"
    assert "OK" in repository.logs[1].message
    assert "FAIL" not in repository.logs[1].message
