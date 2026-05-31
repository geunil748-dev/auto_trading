from __future__ import annotations

from datetime import datetime

from trading_bot.intraday_backtest import IntradayBar
from trading_bot.intraday_backtest_data import _bars_from_frame, load_intraday_history


def test_load_intraday_history_returns_failed_tickers_separately() -> None:
    source = _FakeSource(
        {
            "AAA": [
                IntradayBar(
                    ticker="AAA",
                    bar_time=datetime(2026, 5, 29, 9, 30),
                    open_price=10,
                    high_price=11,
                    low_price=9,
                    close_price=10.5,
                    volume=1000,
                )
            ],
            "BBB": [],
        }
    )

    history, failed = load_intraday_history(["AAA", "BBB"], source)

    assert history["AAA"]
    assert failed == ["BBB"]
    assert source.calls == [("AAA", "5m", 60), ("BBB", "5m", 60)]


def test_bars_from_frame_calculates_vwap_and_ma20() -> None:
    frame = _FakeFrame(
        [
            (
                datetime(2026, 5, 29, 9, 30),
                {"Open": 10, "High": 11, "Low": 9, "Close": 10, "Volume": 100},
            ),
            (
                datetime(2026, 5, 29, 9, 35),
                {"Open": 10, "High": 12, "Low": 10, "Close": 11, "Volume": 200},
            ),
        ]
    )

    bars = _bars_from_frame("aaa", frame)

    assert [bar.ticker for bar in bars] == ["AAA", "AAA"]
    assert bars[0].vwap == 10
    assert round(bars[1].vwap or 0, 4) == 10.6667
    assert bars[1].ma20 == 10.5


class _FakeSource:
    def __init__(self, data: dict[str, list[IntradayBar]]) -> None:
        self.data = data
        self.calls: list[tuple[str, str, int]] = []

    def history(
        self,
        ticker: str,
        interval: str = "5m",
        period_days: int = 60,
    ) -> list[IntradayBar]:
        self.calls.append((ticker, interval, period_days))
        return self.data[ticker]


class _FakeFrame:
    empty = False

    def __init__(self, rows: list[tuple[datetime, dict[str, float]]]) -> None:
        self._rows = rows

    def iterrows(self) -> list[tuple[datetime, dict[str, float]]]:
        return self._rows
