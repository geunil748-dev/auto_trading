from __future__ import annotations

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import _opening_price, _required_float
from trading_bot.intraday_backtest_data import IntradayPriceSource
from trading_bot.models import BreakoutInput


class KisBreakoutHistory:
    def __init__(
        self,
        kis: KisOverseasClient,
        intraday_source: IntradayPriceSource | None = None,
        intraday_interval: str = "5m",
        intraday_period_days: int = 1,
    ) -> None:
        self.kis = kis
        self.intraday_source = intraday_source
        self.intraday_interval = intraday_interval
        self.intraday_period_days = intraday_period_days

    def breakout_input(self, ticker: str) -> BreakoutInput:
        quote = self.kis.quote(ticker)
        daily = self.kis.daily_prices(ticker)
        if not daily:
            raise ValueError(f"{ticker} has no daily price history")
        previous = daily[1] if len(daily) > 1 else daily[0]
        vwap_usd, intraday_ma20_usd = self._intraday_vwap_ma20(ticker)
        return BreakoutInput(
            last_price_usd=_required_float(quote, "last", "LAST"),
            open_price_usd=_opening_price(self.kis, ticker, quote, daily),
            previous_high_usd=_required_float(previous, "high", "HIGH", "high_price", "HIGH_PRICE"),
            previous_low_usd=_required_float(previous, "low", "LOW", "low_price", "LOW_PRICE"),
            vwap_usd=vwap_usd,
            intraday_ma20_usd=intraday_ma20_usd,
        )

    def _intraday_vwap_ma20(self, ticker: str) -> tuple[float | None, float | None]:
        if self.intraday_source is None:
            return None, None
        try:
            bars = self.intraday_source.history(
                ticker,
                interval=self.intraday_interval,
                period_days=self.intraday_period_days,
            )
        except Exception:
            return None, None
        for bar in reversed(bars):
            vwap = bar.vwap if bar.vwap and bar.vwap > 0 else None
            ma20 = bar.ma20 if bar.ma20 and bar.ma20 > 0 else None
            if vwap is not None or ma20 is not None:
                return vwap, ma20
        return None, None
