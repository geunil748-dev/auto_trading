from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_bot.models import MarketContext


class CallableMarketContextSource:
    def __init__(
        self,
        nasdaq_price: Callable[[], float],
        nasdaq_ma20: Callable[[], float],
        fx_change_rate: Callable[[], float],
    ) -> None:
        self.nasdaq_price = nasdaq_price
        self.nasdaq_ma20 = nasdaq_ma20
        self.fx_change_rate = fx_change_rate

    def market_context(self) -> MarketContext:
        return MarketContext(
            nasdaq_price_usd=self.nasdaq_price(),
            nasdaq_ma20_usd=self.nasdaq_ma20(),
            fx_change_rate=self.fx_change_rate(),
        )


class YahooMarketContextSource:
    def __init__(self, ticker_factory: Callable[[str], Any] | None = None) -> None:
        self.ticker_factory = ticker_factory or _yfinance_ticker

    def market_context(self) -> MarketContext:
        nasdaq_closes = _close_values(self.ticker_factory("^IXIC").history(period="1mo"))
        fx_closes = _close_values(self.ticker_factory("USDKRW=X").history(period="5d"))
        if len(nasdaq_closes) < 20:
            raise ValueError("Nasdaq history requires at least 20 closing prices")
        if len(fx_closes) < 2:
            raise ValueError("USD/KRW history requires at least two closing prices")
        return MarketContext(
            nasdaq_price_usd=nasdaq_closes[-1],
            nasdaq_ma20_usd=sum(nasdaq_closes[-20:]) / 20,
            fx_change_rate=(fx_closes[-1] - fx_closes[-2]) / fx_closes[-2],
        )


def _close_values(history: Any) -> list[float]:
    closes = history["Close"]
    if hasattr(closes, "tolist"):
        return [float(value) for value in closes.tolist()]
    return [float(value) for value in closes]


def _yfinance_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)
