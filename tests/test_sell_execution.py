from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, SellIntent, TradeRecord
from trading_bot.sell_execution import SellIntentExecutor
from trading_bot.strategy_metadata import strategy_metadata_from_settings


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
    metadata = strategy_metadata_from_settings(TradingSettings())
    trades = SellIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([SellIntent("AAA", 2, 9.7, "TRAILING_STOP")])

    assert submitted == [SellIntent("AAA", 2, 9.7, "TRAILING_STOP")]
    assert trades == [
        TradeRecord(
            date(2026, 5, 22),
            "AAA",
            "SELL",
            9.7,
            None,
            2,
            exit_reason="TRAILING_STOP",
            order_status="SUCCESS",
            order_qty=2,
            filled_qty=0,
            remaining_qty=2,
            strategy_version=metadata.strategy_version,
            settings_snapshot_hash=metadata.settings_snapshot_hash,
            settings_snapshot_json=metadata.settings_snapshot_json,
        )
    ]
    assert repository.logs == [
        BotLog("INFO", "execution", "매도 주문 1건: AAA 2주 @ $9.70 (사유 트레일링 스탑)")
    ]


def test_sell_intent_executor_records_entry_price_for_later_fill_profit() -> None:
    repository = Repository()
    trades = SellIntentExecutor(
        submit_order=lambda intent: {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([SellIntent("AAA", 3, 12.0, "EOD", entry_price_usd=10.0)])

    assert trades[0].entry_price_usd == 10.0
    assert trades[0].profit_usd is None
    assert trades[0].profit_rate is None


def test_sell_intent_executor_handles_empty_intents() -> None:
    submitted: list[SellIntent] = []
    repository = Repository()

    trades = SellIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: date(2026, 5, 22),
    ).execute([])

    assert submitted == []
    assert trades == []
    assert repository.trades == []
    assert repository.logs == [
        BotLog("INFO", "execution", "매도 주문 0건: 매도 조건을 만족한 보유 종목이 없습니다.")
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
        settings=TradingSettings(max_order_retry_count=0),
    ).execute(
        [
            SellIntent("FAIL", 1, 9.1, "STOP_LOSS"),
            SellIntent("OK", 2, 10.2, "TAKE_PROFIT"),
        ]
    )

    assert [item.ticker for item in trades] == ["OK"]
    assert repository.logs[0].level == "ERROR"
    assert "FAIL" in repository.logs[0].message
    assert repository.logs[1].reject_reason == "ORDER_FAILED"
    assert repository.logs[2].level == "INFO"
    assert "OK" in repository.logs[2].message
    assert "FAIL" not in repository.logs[2].message
