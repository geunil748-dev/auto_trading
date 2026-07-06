from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import Any

from trading_bot.models import MarketContext

NASDAQ_SYMBOL = "^IXIC"
FX_SYMBOL = "USDKRW=X"
NASDAQ_MA_WINDOW = 20
NASDAQ_HISTORY_PERIODS = ("1mo", "3mo", "6mo")

logger = logging.getLogger(__name__)


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
        nasdaq_closes, _nasdaq_period, _degraded = self._nasdaq_closes()
        fx_closes = _close_values(self.ticker_factory(FX_SYMBOL).history(period="5d"))
        if len(fx_closes) < 2:
            logger.warning(
                "MARKET_CONTEXT_DEGRADED_USED symbol=%s close_count=%s "
                "fallback_period=5d degraded=true reason=FX_HISTORY_INSUFFICIENT",
                FX_SYMBOL,
                len(fx_closes),
            )
            fx_change_rate = 0.0
        else:
            fx_change_rate = (fx_closes[-1] - fx_closes[-2]) / fx_closes[-2]
        return MarketContext(
            nasdaq_price_usd=nasdaq_closes[-1],
            nasdaq_ma20_usd=sum(nasdaq_closes[-NASDAQ_MA_WINDOW:]) / NASDAQ_MA_WINDOW,
            fx_change_rate=fx_change_rate,
        )

    def _nasdaq_closes(self) -> tuple[list[float], str, bool]:
        best_closes: list[float] = []
        best_period = NASDAQ_HISTORY_PERIODS[0]
        for period in NASDAQ_HISTORY_PERIODS:
            closes = _close_values(self.ticker_factory(NASDAQ_SYMBOL).history(period=period))
            if len(closes) >= NASDAQ_MA_WINDOW:
                if period != NASDAQ_HISTORY_PERIODS[0]:
                    logger.warning(
                        "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK symbol=%s "
                        "close_count=%s fallback_period=%s degraded=false",
                        NASDAQ_SYMBOL,
                        len(closes),
                        period,
                    )
                return closes, period, False
            logger.warning(
                "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK symbol=%s "
                "close_count=%s fallback_period=%s degraded=false",
                NASDAQ_SYMBOL,
                len(closes),
                period,
            )
            if len(closes) > len(best_closes):
                best_closes = closes
                best_period = period

        neutral_price = best_closes[-1] if best_closes else 1.0
        logger.warning(
            "MARKET_CONTEXT_DEGRADED_USED symbol=%s close_count=%s "
            "fallback_period=%s degraded=true reason=NASDAQ_HISTORY_INSUFFICIENT",
            NASDAQ_SYMBOL,
            len(best_closes),
            best_period,
        )
        return [neutral_price] * NASDAQ_MA_WINDOW, best_period, True


def _close_values(history: Any) -> list[float]:
    closes = _close_column(history)
    if closes is None:
        return []
    if hasattr(closes, "to_numpy"):
        values = closes.to_numpy().ravel().tolist()
    elif hasattr(closes, "tolist"):
        values = closes.tolist()
    else:
        values = list(closes)
    result: list[float] = []
    for value in _flatten(values):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def _close_column(history: Any) -> Any | None:
    if history is None:
        return None
    try:
        if hasattr(history, "empty") and history.empty:
            return None
    except Exception:
        return None
    try:
        return history["Close"]
    except Exception:
        if isinstance(history, dict):
            return history.get("Close")
    return None


def _flatten(values: Any):
    if isinstance(values, (list, tuple)):
        for value in values:
            if isinstance(value, (list, tuple)):
                yield from _flatten(value)
            else:
                yield value
        return
    yield values


def _yfinance_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)
