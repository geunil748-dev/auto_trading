from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.models import CandidateSnapshot, MarketContext, RankedStock
from trading_bot.ports import CandidateHistorySource, ScreeningContextSource


class KisScreeningMarketData:
    def __init__(
        self,
        kis: KisOverseasClient,
        context: ScreeningContextSource,
        history: CandidateHistorySource,
        on_snapshot_error: Callable[[str, str], None] | None = None,
    ) -> None:
        self.kis = kis
        self.context = context
        self.history = history
        self.on_snapshot_error = on_snapshot_error
        self._gain_ranks: dict[str, int] = {}
        self._volume_ranks: dict[str, int] = {}
        self._names: dict[str, str] = {}

    def market_context(self) -> MarketContext:
        return self.context.market_context()

    def ranked_gainers(self, limit: int | None = None) -> list[RankedStock]:
        rows = self.kis.ranked_gainers(limit or 200)
        self._gain_ranks = {item.ticker: item.rank for item in rows}
        self._names.update({item.ticker: item.name for item in rows if item.name})
        return rows

    def ranked_turnover(self, limit: int | None = None) -> list[RankedStock]:
        # 현재 사용 가능한 해외 랭킹 API는 거래량 기준이므로 거래대금 대용으로 사용한다.
        rows = self.kis.ranked_trade_volume(limit or 200)
        self._volume_ranks = {item.ticker: item.rank for item in rows}
        self._names.update({item.ticker: item.name for item in rows if item.name})
        return rows

    def candidate_snapshots(
        self,
        tickers: Iterable[str],
    ) -> Mapping[str, CandidateSnapshot]:
        snapshots: dict[str, CandidateSnapshot] = {}
        for ticker in tickers:
            stage = "quote"
            try:
                quote = self.kis.quote(ticker)
                stage = "opening_volume"
                opening_volume = _required_float(
                    quote,
                    "tvol",
                    "TVOL",
                    "acml_vol",
                    "ACML_VOL",
                )
                stage = "daily_prices"
                average_volume = self.history.average_daily_volume(ticker, 20)
                stage = "snapshot_fields"
                snapshots[ticker] = CandidateSnapshot(
                    ticker=ticker,
                    price_usd=_required_float(quote, "last", "LAST"),
                    open_price_usd=_opening_price(self.kis, ticker, quote),
                    previous_close_usd=_required_float(quote, "base", "BASE", "pcls", "PCLS"),
                    opening_price_change=_price_change_rate(quote),
                    opening_volume_ratio=_opening_volume_ratio(opening_volume, average_volume),
                    turnover_rank=self._volume_ranks[ticker],
                    gain_rank=self._gain_ranks[ticker],
                    name=_candidate_name(ticker, quote, self._names),
                    opening_volume=opening_volume,
                    average_volume_20d=average_volume,
                )
            except Exception as exc:
                self._report_snapshot_error(ticker, _snapshot_failure_reason(stage, exc))
                continue
        return snapshots

    def _report_snapshot_error(self, ticker: str, reason: str) -> None:
        if self.on_snapshot_error is None:
            return
        try:
            self.on_snapshot_error(ticker, reason)
        except Exception:
            return


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


def _candidate_name(
    ticker: str,
    quote: dict[str, Any],
    names: Mapping[str, str],
) -> str:
    explicit = _first_text(
        quote,
        "name",
        "NAME",
        "prdt_name",
        "PRDT_NAME",
        "ovrs_item_name",
        "OVRS_ITEM_NAME",
        "hts_kor_isnm",
        "HTS_KOR_ISNM",
    )
    return explicit or names.get(ticker, "")


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


def _opening_volume_ratio(opening_volume: float, average_volume: float) -> float:
    elapsed_fraction = max(_regular_session_elapsed_fraction(), 30 / 390)
    return _ratio(opening_volume, average_volume * elapsed_fraction)


def _regular_session_elapsed_fraction() -> float:
    now = datetime.now(ZoneInfo("America/New_York"))
    start = datetime.combine(now.date(), time(9, 30), tzinfo=now.tzinfo)
    end = datetime.combine(now.date(), time(16, 0), tzinfo=now.tzinfo)
    if now <= start:
        return 30 / 390
    if now >= end:
        return 1.0
    elapsed = (now - start).total_seconds() / 60
    return min(1.0, elapsed / 390)


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


def _first_text(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _snapshot_failure_reason(stage: str, exc: Exception) -> str:
    message = str(exc)
    code = getattr(exc, "code", None)
    if code is not None:
        return f"{stage}_http_error_{code}"
    if isinstance(exc, TimeoutError):
        return f"{stage}_timeout"
    if "has fewer than" in message:
        return "daily_prices_insufficient"
    if "no daily price history" in message:
        return "daily_prices_empty"
    if "missing numeric field" in message:
        return f"{stage}_missing_field"
    return f"{stage}_{_compact_reason(message)}"


def _compact_reason(message: str) -> str:
    cleaned = "_".join(message.strip().split())
    return cleaned[:120] or "unknown_error"
