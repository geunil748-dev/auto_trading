from __future__ import annotations

from collections.abc import Callable, Iterable

from trading_bot.config import TradingSettings
from trading_bot.execution import update_high
from trading_bot.exit_planner import plan_position_exits
from trading_bot.models import PositionState, SellIntent

PriceReader = Callable[[str], float]


class PollingExitMonitor:
    def __init__(self, price_reader: PriceReader, settings: TradingSettings) -> None:
        self.price_reader = price_reader
        self.settings = settings

    def poll(
        self,
        positions: Iterable[PositionState],
        end_of_day: bool = False,
        partial_take_profit_tickers: Iterable[str] = (),
    ) -> tuple[list[PositionState], list[SellIntent]]:
        refreshed: list[PositionState] = []
        for position in positions:
            try:
                refreshed.append(update_high(position, self.price_reader(position.ticker)))
            except Exception:
                refreshed.append(position)
        return refreshed, plan_position_exits(
            refreshed,
            self.settings,
            end_of_day,
            partial_take_profit_tickers,
        )
