from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_bot.chart_models import PriceBar
from trading_bot.chart_scoring import chart_pattern_score


class YahooChartScorer:
    def __init__(self, ticker_factory: Callable[[str], Any] | None = None) -> None:
        self.ticker_factory = ticker_factory or _yfinance_ticker

    def score(self, ticker: str) -> float:
        history = self.ticker_factory(ticker).history(period="3mo", interval="1d")
        return chart_pattern_score(_price_bars(history))


def _price_bars(history: Any) -> list[PriceBar]:
    closes = _values(history["Close"])
    highs = _values(history["High"])
    lows = _values(history["Low"])
    return [
        PriceBar(close=close, high=high, low=low)
        for close, high, low in zip(closes, highs, lows)
    ]


def _values(column: Any) -> list[float]:
    if hasattr(column, "tolist"):
        return [float(value) for value in column.tolist()]
    return [float(value) for value in column]


def _yfinance_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)
