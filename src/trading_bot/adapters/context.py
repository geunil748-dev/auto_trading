from __future__ import annotations

import logging
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trading_bot.models import MarketContext

NASDAQ_SYMBOL = "^IXIC"
FX_SYMBOL = "USDKRW=X"
NASDAQ_MA_WINDOW = 20
NASDAQ_HISTORY_PERIODS = ("1mo", "3mo", "6mo")
PROXY_SYMBOL_PERIODS = (("QQQ", ("3mo", "6mo")), ("^NDX", ("3mo", "6mo")))
LAST_GOOD_MARKET_CONTEXT_PATH = Path("monitor/last_good_market_context.json")
LAST_GOOD_MARKET_CONTEXT_TTL_HOURS = 36.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _MarketSeries:
    symbol: str
    closes: list[float]
    period: str
    source: str
    proxy_for: str | None = None
    status: str = "ok"
    confidence: str = "high"
    reason: str | None = None
    stale_age_hours: float | None = None


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
    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        cache_path: Path = LAST_GOOD_MARKET_CONTEXT_PATH,
        cache_ttl_hours: float = LAST_GOOD_MARKET_CONTEXT_TTL_HOURS,
    ) -> None:
        self.ticker_factory = ticker_factory or _yfinance_ticker
        self.cache_path = cache_path
        self.cache_ttl_hours = cache_ttl_hours

    def market_context(self) -> MarketContext:
        series = self._market_series()
        fx_closes = _close_values(self.ticker_factory(FX_SYMBOL).history(period="5d"))
        if len(fx_closes) < 2 or fx_closes[-2] <= 0:
            logger.warning(
                "MARKET_CONTEXT_DEGRADED_USED symbol=%s close_count=%s "
                "fallback_period=5d degraded=true reason=FX_HISTORY_INSUFFICIENT",
                FX_SYMBOL,
                len(fx_closes),
            )
            fx_change_rate = 0.0
        else:
            fx_change_rate = (fx_closes[-1] - fx_closes[-2]) / fx_closes[-2]
        context = MarketContext(
            nasdaq_price_usd=series.closes[-1],
            nasdaq_ma20_usd=sum(series.closes[-NASDAQ_MA_WINDOW:]) / NASDAQ_MA_WINDOW,
            fx_change_rate=fx_change_rate,
            status=series.status,
            source=series.source,
            symbol=series.symbol,
            proxy_for=series.proxy_for,
            period=series.period,
            close_count=len(series.closes),
            as_of=_utc_now_iso(),
            stale_age_hours=series.stale_age_hours,
            confidence=series.confidence,
            insufficient_history=series.status in {"degraded", "unknown"},
            reason=series.reason,
        )
        if series.source == "fresh" and series.symbol == NASDAQ_SYMBOL:
            _save_last_good_market_context(self.cache_path, context)
        return context

    def _market_series(self) -> _MarketSeries:
        primary = self._series_for_symbol(NASDAQ_SYMBOL, NASDAQ_HISTORY_PERIODS, source="fresh")
        if primary is not None:
            return primary
        cached = _load_last_good_market_context(self.cache_path, self.cache_ttl_hours)
        if cached is not None:
            return cached
        for symbol, periods in PROXY_SYMBOL_PERIODS:
            logger.warning("MARKET_CONTEXT_PROXY_ATTEMPT symbol=%s proxy_for=%s", symbol, NASDAQ_SYMBOL)
            proxy = self._series_for_symbol(
                symbol,
                periods,
                source="proxy",
                proxy_for=NASDAQ_SYMBOL,
                confidence="medium",
                reason="NASDAQ_PRIMARY_HISTORY_INSUFFICIENT_PROXY_USED",
            )
            if proxy is not None:
                logger.warning(
                    "MARKET_CONTEXT_PROXY_USED symbol=%s proxy_for=%s close_count=%s period=%s",
                    symbol,
                    NASDAQ_SYMBOL,
                    len(proxy.closes),
                    proxy.period,
                )
                return proxy
            logger.warning("MARKET_CONTEXT_PROXY_FAILED symbol=%s proxy_for=%s", symbol, NASDAQ_SYMBOL)
        return self._degraded_series()

    def _series_for_symbol(
        self,
        symbol: str,
        periods: tuple[str, ...],
        *,
        source: str,
        proxy_for: str | None = None,
        confidence: str = "high",
        reason: str | None = None,
    ) -> _MarketSeries | None:
        best_closes: list[float] = []
        best_period = periods[0]
        for period in periods:
            try:
                closes = _close_values(self.ticker_factory(symbol).history(period=period))
            except Exception as exc:
                logger.warning(
                    "MARKET_CONTEXT_HISTORY_FETCH_FAILED symbol=%s period=%s exception=%s",
                    symbol,
                    period,
                    type(exc).__name__,
                )
                closes = []
            if len(closes) >= NASDAQ_MA_WINDOW:
                if symbol == NASDAQ_SYMBOL and period != periods[0]:
                    logger.warning(
                        "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK symbol=%s "
                        "close_count=%s fallback_period=%s degraded=false",
                        symbol,
                        len(closes),
                        period,
                    )
                return _MarketSeries(
                    symbol=symbol,
                    closes=closes,
                    period=period,
                    source=source,
                    proxy_for=proxy_for,
                    confidence=confidence,
                    reason=reason,
                )
            logger.warning(
                "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK symbol=%s "
                "close_count=%s fallback_period=%s degraded=false",
                symbol,
                len(closes),
                period,
            )
            if len(closes) > len(best_closes):
                best_closes = closes
                best_period = period
        return None

    def _degraded_series(self) -> _MarketSeries:
        best_closes: list[float] = []
        best_period = NASDAQ_HISTORY_PERIODS[0]
        for period in NASDAQ_HISTORY_PERIODS:
            try:
                closes = _close_values(self.ticker_factory(NASDAQ_SYMBOL).history(period=period))
            except Exception:
                closes = []
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
        return _MarketSeries(
            symbol=NASDAQ_SYMBOL,
            closes=[neutral_price] * NASDAQ_MA_WINDOW,
            period=best_period,
            source="degraded",
            status="degraded",
            confidence="none",
            reason="NASDAQ_HISTORY_INSUFFICIENT",
        )


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


def _save_last_good_market_context(path: Path, context: MarketContext) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "ok",
            "source": "fresh",
            "symbol": context.symbol,
            "as_of": context.as_of,
            "saved_at": _utc_now_iso(),
            "close_count": context.close_count,
            "period": context.period,
            "ma20": context.nasdaq_ma20_usd,
            "last_close": context.nasdaq_price_usd,
            "fx_change_rate": context.fx_change_rate,
            "trend": "above_ma20"
            if context.nasdaq_price_usd >= context.nasdaq_ma20_usd
            else "below_ma20",
            "risk_on": context.nasdaq_price_usd >= context.nasdaq_ma20_usd,
            "reason": None,
        }
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_path.replace(path)
        logger.info(
            "LAST_GOOD_MARKET_CONTEXT_SAVED symbol=%s close_count=%s period=%s",
            context.symbol,
            context.close_count,
            context.period,
        )
    except Exception as exc:
        logger.warning("LAST_GOOD_MARKET_CONTEXT_INVALID write_failed=%s", type(exc).__name__)


def _load_last_good_market_context(path: Path, ttl_hours: float) -> _MarketSeries | None:
    if not path.exists():
        logger.warning("LAST_GOOD_MARKET_CONTEXT_MISSING path=%s", path)
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at = _parse_iso_datetime(str(payload.get("saved_at") or ""))
        age_hours = (datetime.now(UTC) - saved_at).total_seconds() / 3600
        if age_hours > ttl_hours:
            logger.warning(
                "LAST_GOOD_MARKET_CONTEXT_STALE age_hours=%.2f ttl_hours=%.2f",
                age_hours,
                ttl_hours,
            )
            return None
        last_close = float(payload["last_close"])
        ma20 = float(payload["ma20"])
        if last_close <= 0 or ma20 <= 0:
            raise ValueError("invalid cached prices")
        logger.warning(
            "LAST_GOOD_MARKET_CONTEXT_USED symbol=%s age_hours=%.2f period=%s",
            payload.get("symbol", NASDAQ_SYMBOL),
            age_hours,
            payload.get("period", "-"),
        )
        return _MarketSeries(
            symbol=str(payload.get("symbol") or NASDAQ_SYMBOL),
            closes=_closes_from_cached_values(last_close, ma20),
            period=str(payload.get("period") or "cached"),
            source="last_good_cache",
            status="cached",
            confidence="medium",
            reason="NASDAQ_PRIMARY_HISTORY_INSUFFICIENT_LAST_GOOD_USED",
            stale_age_hours=age_hours,
        )
    except Exception as exc:
        logger.warning("LAST_GOOD_MARKET_CONTEXT_INVALID exception=%s", type(exc).__name__)
        return None


def _closes_from_cached_values(last_close: float, ma20: float) -> list[float]:
    prior_close = ((ma20 * NASDAQ_MA_WINDOW) - last_close) / (NASDAQ_MA_WINDOW - 1)
    if prior_close <= 0:
        prior_close = ma20
    return [prior_close] * (NASDAQ_MA_WINDOW - 1) + [last_close]


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
        columns = getattr(history, "columns", None)
        if columns is not None:
            for level in (0, 1):
                try:
                    if "Close" in columns.get_level_values(level):
                        return history.xs("Close", axis=1, level=level)
                except Exception:
                    continue
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
