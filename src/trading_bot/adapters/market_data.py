from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.models import CandidateSnapshot, MarketContext, RankedStock
from trading_bot.ports import CandidateHistorySource, ScreeningContextSource


class KisScreeningMarketData:
    def __init__(
        self,
        kis: KisOverseasClient,
        context: ScreeningContextSource,
        history: CandidateHistorySource,
    ) -> None:
        self.kis = kis
        self.context = context
        self.history = history
        self._gain_ranks: dict[str, int] = {}
        self._volume_ranks: dict[str, int] = {}

    def market_context(self) -> MarketContext:
        return self.context.market_context()

    def ranked_gainers(self) -> list[RankedStock]:
        rows = self.kis.ranked_gainers()
        self._gain_ranks = {item.ticker: item.rank for item in rows}
        return rows

    def ranked_turnover(self) -> list[RankedStock]:
        # 현재 사용 가능한 해외 랭킹 API는 거래량 기준이므로 거래대금 대용으로 사용한다.
        rows = self.kis.ranked_trade_volume()
        self._volume_ranks = {item.ticker: item.rank for item in rows}
        return rows

    def candidate_snapshots(
        self,
        tickers: Iterable[str],
    ) -> Mapping[str, CandidateSnapshot]:
        snapshots: dict[str, CandidateSnapshot] = {}
        for ticker in tickers:
            try:
                quote = self.kis.quote(ticker)
                opening_volume = _required_float(
                    quote,
                    "tvol",
                    "TVOL",
                    "acml_vol",
                    "ACML_VOL",
                )
                average_volume = self.history.average_daily_volume(ticker, 20)
                snapshots[ticker] = CandidateSnapshot(
                    ticker=ticker,
                    price_usd=_required_float(quote, "last", "LAST"),
                    open_price_usd=_opening_price(self.kis, ticker, quote),
                    previous_close_usd=_required_float(quote, "base", "BASE", "pcls", "PCLS"),
                    opening_price_change=_price_change_rate(quote),
                    opening_volume_ratio=_ratio(opening_volume, average_volume),
                    turnover_rank=self._volume_ranks[ticker],
                    gain_rank=self._gain_ranks[ticker],
                )
            except ValueError:
                continue
        return snapshots


class KisDailyVolumeHistory:
    def __init__(self, kis: KisOverseasClient) -> None:
        self.kis = kis

    def average_daily_volume(self, ticker: str, sessions: int) -> float:
        volumes = [
            _required_float(row, "tvol", "TVOL", "acml_vol", "ACML_VOL")
            for row in self.kis.daily_prices(ticker)
        ][:sessions]
        if len(volumes) < sessions:
            raise ValueError(f"{ticker} has fewer than {sessions} volume rows")
        return sum(volumes) / len(volumes)


def _price_change_rate(quote: dict[str, Any]) -> float:
    explicit = _optional_float(quote, "rate", "RATE", "prdy_ctrt", "PRDY_CTRT")
    if explicit is not None:
        return explicit / 100 if abs(explicit) > 1 else explicit
    base = _required_float(quote, "base", "BASE", "pcls", "PCLS")
    last = _required_float(quote, "last", "LAST")
    return _ratio(last - base, base)


def _opening_price(
    kis: KisOverseasClient,
    ticker: str,
    quote: dict[str, Any],
    daily: list[dict[str, Any]] | None = None,
) -> float:
    current_quote = _optional_float(quote, "open", "OPEN")
    if current_quote is not None:
        return current_quote

    daily = daily if daily is not None else kis.daily_prices(ticker)
    if not daily:
        raise ValueError(f"{ticker} has no daily price history")
    return _required_float(daily[0], "open", "OPEN")


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        raise ValueError("ratio denominator must be positive")
    return numerator / denominator


def _required_float(row: dict[str, Any], *fields: str) -> float:
    value = _optional_float(row, *fields)
    if value is None:
        raise ValueError(f"missing numeric field from {fields}")
    return value


def _optional_float(row: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return float(str(value).replace(",", ""))
    return None
