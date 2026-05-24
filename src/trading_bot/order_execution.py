from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date

from trading_bot.models import BotLog, BuyIntent, TradeRecord
from trading_bot.ports import DailyRepository

OrderSubmitter = Callable[[BuyIntent], dict[str, object]]


class BuyIntentExecutor:
    def __init__(
        self,
        submit_order: OrderSubmitter,
        repository: DailyRepository,
        today: Callable[[], date],
        mock: bool = True,
    ) -> None:
        self.submit_order = submit_order
        self.repository = repository
        self.today = today
        self.mock = mock

    def execute(self, intents: Iterable[BuyIntent]) -> list[TradeRecord]:
        trades: list[TradeRecord] = []
        for intent in intents:
            self.submit_order(intent)
            trades.append(
                TradeRecord(
                    trade_date=self.today(),
                    ticker=intent.ticker,
                    order_type="BUY",
                    order_price_usd=intent.limit_price_usd,
                    exec_price_usd=None,
                    quantity=intent.quantity,
                    is_mock=self.mock,
                )
            )
        self.repository.save_trades(trades)
        self.repository.save_log(
            BotLog("INFO", "execution", f"Submitted {len(trades)} buy orders.")
        )
        return trades
