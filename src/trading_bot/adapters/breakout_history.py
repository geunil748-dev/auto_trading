from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

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
        current_volume, previous_average, recent_close, missing_reason = (
            self._five_minute_volume_data(ticker)
        )
        return BreakoutInput(
            last_price_usd=_required_float(quote, "last", "LAST"),
            open_price_usd=_opening_price(self.kis, ticker, quote, daily),
            previous_high_usd=_required_float(previous, "high", "HIGH", "high_price", "HIGH_PRICE"),
            previous_low_usd=_required_float(previous, "low", "LOW", "low_price", "LOW_PRICE"),
            recent_5m_close_usd=recent_close,
            current_5m_volume=current_volume,
            previous_5m_average_volume=previous_average,
            volume_data_missing_reason=missing_reason,
        )

    def _five_minute_volume_data(
        self,
        ticker: str,
    ) -> tuple[float | None, float | None, float | None, str | None]:
        reader = getattr(self.kis, "intraday_prices", None)
        if not callable(reader):
            return None, None, None, "MARKET_DATA_API_UNAVAILABLE"
        try:
            rows = list(reader(ticker, interval_minutes=5))
        except Exception:
            return None, None, None, "MARKET_DATA_API_ERROR"
        if not rows:
            return None, None, None, "PREVIOUS_VOLUME_HISTORY_EMPTY"

        ordered = sorted(rows, key=_intraday_sort_key, reverse=True)
        current_volume = _optional_nonnegative_float(ordered[0], "evol", "EVOL", "volume", "VOLUME")
        if current_volume is None:
            return None, None, None, "CURRENT_5M_VOLUME_NULL"
        completed = ordered[1:]
        completed_volumes = [
            value
            for row in completed
            if (value := _optional_nonnegative_float(row, "evol", "EVOL", "volume", "VOLUME"))
            is not None
        ]
        if not completed_volumes:
            return current_volume, None, None, "INSUFFICIENT_COMPLETED_BARS"
        recent_close = _optional_nonnegative_float(completed[0], "last", "LAST", "close", "CLOSE")
        return current_volume, sum(completed_volumes) / len(completed_volumes), recent_close, None


def _intraday_sort_key(row: Mapping[str, Any]) -> str:
    day = _first_text(row, "xymd", "XYMD", "tymd", "TYMD", "date", "DATE")
    time = _first_text(row, "xhms", "XHMS", "time", "TIME")
    return f"{day}{time}" if day or time else ""


def _first_text(row: Mapping[str, Any], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _optional_nonnegative_float(
    row: Mapping[str, Any],
    *fields: str,
) -> float | None:
    raw = _first_text(row, *fields).replace(",", "")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if isfinite(value) and value >= 0 else None
