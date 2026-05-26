from datetime import date

from trading_bot.models import BotLog, SellIntent, TradeRecord
from trading_bot.sell_execution import SellIntentExecutor


class Repository:
    def __init__(self) -> None:
        self.trades: list[TradeRecord] = []
        self.logs: list[BotLog] = []

    def save_trades(self, trades: list[TradeRecord]) -> None:
        self.trades.extend(trades)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)


def test_sell_intent_executor_records_exit_reason() -> None:
    submitted: list[SellIntent] = []
    repository = Repository()
    trades = SellIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([SellIntent("AAA", 2, 9.7, "TRAILING_STOP")])

    assert submitted == [SellIntent("AAA", 2, 9.7, "TRAILING_STOP")]
    assert trades == [
        TradeRecord(date(2026, 5, 22), "AAA", "SELL", 9.7, None, 2, exit_reason="TRAILING_STOP")
    ]
    assert repository.logs == [
        BotLog("INFO", "execution", "매도 주문 1건: AAA 2주 @ $9.70 (사유 TRAILING_STOP)")
    ]


def test_sell_intent_executor_records_failures_and_continues() -> None:
    repository = Repository()

    def submit_order(intent: SellIntent) -> dict[str, object]:
        if intent.ticker == "FAIL":
            raise RuntimeError("order rejected")
        return {"ok": True}

    trades = SellIntentExecutor(
        submit_order=submit_order,
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute(
        [
            SellIntent("FAIL", 1, 9.1, "STOP_LOSS"),
            SellIntent("OK", 2, 10.2, "TAKE_PROFIT"),
        ]
    )

    assert [item.ticker for item in trades] == ["OK"]
    assert repository.logs[0].level == "ERROR"
    assert "FAIL" in repository.logs[0].message
    assert repository.logs[1].level == "INFO"
    assert "OK" in repository.logs[1].message
    assert "FAIL" not in repository.logs[1].message
