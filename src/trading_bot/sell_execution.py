from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.models import BotLog, SellIntent, TradeRecord
from trading_bot.ports import DailyRepository

SellSubmitter = Callable[[SellIntent], dict[str, object]]


class SellIntentExecutor:
    def __init__(
        self,
        submit_order: SellSubmitter,
        repository: DailyRepository,
        today: Callable[[], date],
        mock: bool = True,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock

    def execute(self, intents: Iterable[SellIntent]) -> list[TradeRecord]:
        trades: list[TradeRecord] = []
        for intent in intents:
            self.submit_order(intent)
            trades.append(
                TradeRecord(
                    trade_date=self.today(),
                    ticker=intent.ticker,
                    order_type="SELL",
                    order_price_usd=intent.limit_price_usd,
                    exec_price_usd=None,
                    quantity=intent.quantity,
                    exit_reason=intent.exit_reason,
                    is_mock=self.mock,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(
            BotLog("INFO", "execution", f"Submitted {len(trades)} sell orders.")
        )
        return trades
