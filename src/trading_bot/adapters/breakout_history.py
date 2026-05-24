from __future__ import annotations

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import _opening_price, _required_float


class KisBreakoutHistory:
    def __init__(self, kis: KisOverseasClient) -> None:
        self.kis = kis

    def breakout_input(self, ticker: str) -> tuple[float, float, float, float]:
        quote = self.kis.quote(ticker)
        daily = self.kis.daily_prices(ticker)
        if not daily:
            raise ValueError(f"{ticker} has no daily price history")
        previous = daily[1] if len(daily) > 1 else daily[0]
        return (
            _required_float(quote, "last", "LAST"),
            _opening_price(self.kis, ticker, quote, daily),
            _required_float(previous, "high", "HIGH", "high_price", "HIGH_PRICE"),
            _required_float(previous, "low", "LOW", "low_price", "LOW_PRICE"),
        )
