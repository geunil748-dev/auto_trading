from __future__ import annotations

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import _opening_price, _required_float
from trading_bot.models import BreakoutInput


class KisBreakoutHistory:
    def __init__(self, kis: KisOverseasClient) -> None:
        self.kis = kis

    def breakout_input(self, ticker: str) -> BreakoutInput:
        quote = self.kis.quote(ticker)
        daily = self.kis.daily_prices(ticker)
        if not daily:
            raise ValueError(f"{ticker} has no daily price history")
        previous = daily[1] if len(daily) > 1 else daily[0]
        return BreakoutInput(
            last_price_usd=_required_float(quote, "last", "LAST"),
            open_price_usd=_opening_price(self.kis, ticker, quote, daily),
            previous_high_usd=_required_float(previous, "high", "HIGH", "high_price", "HIGH_PRICE"),
            previous_low_usd=_required_float(previous, "low", "LOW", "low_price", "LOW_PRICE"),
            volume_data_source="KIS_QUOTE_DAILY_ONLY",
            volume_data_missing_reason="INTRADAY_CANDLE_SOURCE_UNAVAILABLE",
        )
