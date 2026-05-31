from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from trading_bot.intraday_backtest import IntradayBar


class IntradayPriceSource(Protocol):
    def history(
        self,
        ticker: str,
        interval: str = "5m",
        period_days: int = 60,
    ) -> list[IntradayBar]: ...


class YahooIntradayPriceSource:
    """Yahoo Finance 5분봉 데이터를 백테스트용 IntradayBar로 변환한다."""

    def history(
        self,
        ticker: str,
        interval: str = "5m",
        period_days: int = 60,
    ) -> list[IntradayBar]:
        _prepare_yfinance_cache()
        yf = _yfinance()
        frame = yf.Ticker(ticker).history(
            period=f"{period_days}d",
            interval=interval,
            auto_adjust=False,
        )
        if frame is None or getattr(frame, "empty", False):
            return []
        return _bars_from_frame(ticker, frame)


def load_intraday_history(
    tickers: list[str],
    source: IntradayPriceSource,
    interval: str = "5m",
    period_days: int = 60,
) -> tuple[dict[str, list[IntradayBar]], list[str]]:
    history: dict[str, list[IntradayBar]] = {}
    failed: list[str] = []
    for ticker in [item.upper() for item in tickers]:
        try:
            bars = source.history(ticker, interval=interval, period_days=period_days)
        except Exception:
            bars = []
        if not bars:
            failed.append(ticker)
        history[ticker] = bars
    return history, failed


def _bars_from_frame(ticker: str, frame: Any) -> list[IntradayBar]:
    rows: list[IntradayBar] = []
    closes_by_ticker_day: dict[tuple[str, str], list[float]] = {}
    vwap_state: dict[tuple[str, str], tuple[float, float]] = {}
    for index, row in frame.iterrows():
        try:
            bar_time = _row_datetime(index)
            day_key = (ticker.upper(), bar_time.date().isoformat())
            open_price = float(row["Open"])
            high_price = float(row["High"])
            low_price = float(row["Low"])
            close_price = float(row["Close"])
            volume = float(row["Volume"])
        except (KeyError, TypeError, ValueError):
            continue
        typical_price = (high_price + low_price + close_price) / 3
        cumulative_value, cumulative_volume = vwap_state.get(day_key, (0.0, 0.0))
        cumulative_value += typical_price * max(volume, 0.0)
        cumulative_volume += max(volume, 0.0)
        vwap_state[day_key] = (cumulative_value, cumulative_volume)
        vwap = cumulative_value / cumulative_volume if cumulative_volume > 0 else None
        closes = closes_by_ticker_day.setdefault(day_key, [])
        closes.append(close_price)
        ma20 = sum(closes[-20:]) / min(len(closes), 20)
        rows.append(
            IntradayBar(
                ticker=ticker.upper(),
                bar_time=bar_time,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
                vwap=vwap,
                ma20=ma20,
            )
        )
    return rows


def _row_datetime(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _prepare_yfinance_cache() -> None:
    try:
        import yfinance as yf
    except ImportError:
        return
    if hasattr(yf, "set_tz_cache_location"):
        yf.set_tz_cache_location(str(Path(".yfinance-cache").resolve()))


def _yfinance() -> Any:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - 선택 의존성 안내 분기.
        raise RuntimeError("5분봉 백테스트를 실행하려면 yfinance가 필요합니다.") from exc
    return yf
