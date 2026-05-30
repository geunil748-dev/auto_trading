from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from trading_bot.backtest import BacktestBar


class BacktestPriceSource(Protocol):
    def history(self, ticker: str, years: int) -> list[BacktestBar]: ...


class YahooBacktestPriceSource:
    """야후파이낸스 일봉 데이터를 백테스트용 OHLCV로 변환한다."""

    def history(self, ticker: str, years: int) -> list[BacktestBar]:
        yf = _yfinance()
        frame = yf.Ticker(ticker).history(period=f"{years}y", interval="1d", auto_adjust=False)
        if frame is None or getattr(frame, "empty", False):
            return []
        return _bars_from_frame(frame)


def load_history(
    tickers: list[str],
    source: BacktestPriceSource,
    years: int = 10,
) -> dict[str, list[BacktestBar]]:
    history: dict[str, list[BacktestBar]] = {}
    for ticker in tickers:
        try:
            history[ticker] = source.history(ticker, years)
        except Exception:
            # 일부 티커의 과거 데이터가 실패해도 다른 후보의 백테스트는 계속 진행한다.
            history[ticker] = []
    return history


def _bars_from_frame(frame: Any) -> list[BacktestBar]:
    rows: list[BacktestBar] = []
    for index, row in frame.iterrows():
        try:
            rows.append(
                BacktestBar(
                    trade_date=_row_date(index),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def _row_date(value: Any) -> date:
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _yfinance() -> Any:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - 선택 의존성 안내용 분기.
        raise RuntimeError("백테스트를 실행하려면 yfinance가 필요합니다.") from exc
    return yf
