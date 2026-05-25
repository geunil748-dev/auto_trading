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
    assert trades == [TradeRecord(date(2026, 5, 22), "AAA", "BUY", 10.5, None, 2)]
    assert repository.trades == trades
    assert repository.logs == [
        BotLog(
            "INFO",
            "execution",
            "매수 주문 1건: AAA 2주 @ $10.50 (주문금액 $21.00, 배분 5.0%)",
        )
    ]
