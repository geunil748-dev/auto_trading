from __future__ import annotations

from datetime import date, timedelta

from trading_bot.backtest import BacktestBar, run_chart_backtest
from trading_bot.backtest_service import run_backtest_from_monitor_state
from trading_bot.config import TradingSettings


class FakePriceSource:
    def __init__(self, bars: list[BacktestBar]) -> None:
        self.bars = bars

    def history(self, ticker: str, years: int) -> list[BacktestBar]:
        return self.bars


class PartiallyFailingPriceSource:
    def __init__(self, bars: list[BacktestBar]) -> None:
        self.bars = bars

    def history(self, ticker: str, years: int) -> list[BacktestBar]:
        if ticker == "BAD":
            raise RuntimeError("history failed")
        return self.bars


def test_chart_backtest_runs_one_to_ten_years_without_news() -> None:
    bars = _momentum_bars(date(2024, 1, 1), 760)
    settings = TradingSettings(
        min_price_usd=1,
        max_price_usd=1000000,
        min_opening_price_change=0.01,
        min_volume_ratio=0.5,
        min_total_score=20,
        take_profit_rate=0.08,
    )

    results = run_chart_backtest(["AAA"], {"AAA": bars}, settings, max_years=2)

    assert [item.years for item in results] == [1, 2]
    assert results[0].trades > 0
    assert results[0].return_rate > 0
    assert results[0].take_profit_count > 0
    assert results[0].eod_count == 0


def test_chart_backtest_marks_periods_without_enough_history() -> None:
    bars = _momentum_bars(date(2025, 1, 1), 460)
    settings = TradingSettings(
        min_price_usd=1,
        max_price_usd=1000000,
        min_opening_price_change=0.01,
        min_volume_ratio=0.5,
        min_total_score=20,
        take_profit_rate=0.08,
    )

    results = run_chart_backtest(["AAA"], {"AAA": bars}, settings, max_years=3)

    assert results[0].data_sufficient is True
    assert results[1].data_sufficient is False
    assert results[2].data_sufficient is False


def test_backtest_service_uses_current_monitor_candidates() -> None:
    bars = _momentum_bars(date(2025, 1, 1), 90)
    state = {"accounts": {"mock": {"targets": [["AAA", "테스트", "$10.00"]]}}}

    payload = run_backtest_from_monitor_state(state, FakePriceSource(bars), years=1)

    assert payload["ok"] is True
    assert payload["tickers"] == ["AAA"]
    assert payload["candidates"] == [{"ticker": "AAA", "name": "테스트"}]
    assert len(payload["results"]) == 1
    assert "zeroEntryDays" in payload["results"][0]
    assert "eodRate" in payload["results"][0]


def test_backtest_service_can_run_single_selected_candidate() -> None:
    bars = _momentum_bars(date(2025, 1, 1), 90)
    state = {
        "targets": [
            ["AAA", "에이"],
            ["BBB", "비"],
        ]
    }

    payload = run_backtest_from_monitor_state(
        state,
        FakePriceSource(bars),
        years=1,
        selected_tickers=["BBB"],
    )

    assert payload["ok"] is True
    assert payload["tickers"] == ["BBB"]
    assert payload["candidates"] == [
        {"ticker": "AAA", "name": "에이"},
        {"ticker": "BBB", "name": "비"},
    ]


def test_chart_backtest_compares_relaxed_and_strict_filters() -> None:
    bars = _momentum_bars(date(2024, 1, 1), 760, open_change=0.02)
    strict = TradingSettings(
        min_price_usd=5,
        max_price_usd=50,
        min_opening_price_change=0.03,
        min_volume_ratio=0.5,
        min_total_score=20,
        allow_relaxed_candidate_filter=False,
    )
    relaxed = TradingSettings(
        min_price_usd=5,
        max_price_usd=50,
        min_opening_price_change=0.03,
        min_volume_ratio=1.5,
        min_total_score=20,
        allow_relaxed_candidate_filter=True,
    )

    strict_result = run_chart_backtest(["AAA"], {"AAA": bars}, strict, max_years=1)[0]
    relaxed_result = run_chart_backtest(["AAA"], {"AAA": bars}, relaxed, max_years=1)[0]

    assert strict_result.trades == 0
    assert relaxed_result.trades > 0
    assert strict_result.zero_entry_days > relaxed_result.zero_entry_days


def test_chart_backtest_can_relax_only_opening_change() -> None:
    bars = _momentum_bars(date(2024, 1, 1), 760, open_change=0.02)
    settings = TradingSettings(
        min_price_usd=5,
        max_price_usd=50,
        min_opening_price_change=0.03,
        min_volume_ratio=0.5,
        min_total_score=20,
        allow_relaxed_candidate_filter=False,
        relax_opening_change_only=True,
    )

    result = run_chart_backtest(["AAA"], {"AAA": bars}, settings, max_years=1)[0]

    assert result.trades > 0


def test_chart_backtest_opening_relax_keeps_volume_strict() -> None:
    bars = _momentum_bars(date(2024, 1, 1), 760, open_change=0.02, volume=1000)
    settings = TradingSettings(
        min_price_usd=5,
        max_price_usd=50,
        min_opening_price_change=0.03,
        min_volume_ratio=1.5,
        min_total_score=20,
        allow_relaxed_candidate_filter=False,
        relax_opening_change_only=True,
    )

    result = run_chart_backtest(["AAA"], {"AAA": bars}, settings, max_years=1)[0]

    assert result.trades == 0


def test_backtest_service_can_run_custom_ticker_outside_candidates() -> None:
    bars = _momentum_bars(date(2024, 1, 1), 400)
    state = {"targets": [["AAA", "에이"]]}

    payload = run_backtest_from_monitor_state(
        state,
        FakePriceSource(bars),
        years=1,
        selected_tickers=["MSFT"],
    )

    assert payload["ok"] is True
    assert payload["tickers"] == ["MSFT"]
    assert payload["candidates"] == [{"ticker": "AAA", "name": "에이"}]


def test_backtest_service_skips_ticker_history_failures() -> None:
    bars = _momentum_bars(date(2025, 1, 1), 90)
    state = {"targets": [["GOOD", "정상"], ["BAD", "오류"]]}

    payload = run_backtest_from_monitor_state(
        state,
        PartiallyFailingPriceSource(bars),
        years=1,
    )

    assert payload["ok"] is True
    assert payload["tickers"] == ["GOOD", "BAD"]
    assert payload["results"][0]["tickers"] == 2


def test_backtest_service_displays_insufficient_data() -> None:
    bars = _momentum_bars(date(2025, 1, 1), 90)
    state = {"targets": [["AAA", "테스트"]]}

    payload = run_backtest_from_monitor_state(state, FakePriceSource(bars), years=1)

    assert payload["results"][0]["profitUsd"] == "데이터 부족"


def test_backtest_service_reports_empty_candidates() -> None:
    payload = run_backtest_from_monitor_state({"accounts": {"mock": {"targets": []}}})

    assert payload["ok"] is False
    assert payload["results"] == []


def _momentum_bars(
    start: date,
    count: int,
    open_change: float = 0.02,
    volume: float | None = None,
) -> list[BacktestBar]:
    bars: list[BacktestBar] = []
    for offset in range(count):
        base = 10.0 + (offset % 40) * 0.03
        opened = base * (1 + open_change)
        high = opened * 1.10
        low = opened * 0.99
        close = base
        bars.append(
            BacktestBar(
                trade_date=start + timedelta(days=offset),
                open=opened,
                high=high,
                low=low,
                close=close,
                volume=volume if volume is not None else 100000 + offset * 1000,
            )
        )
    return bars
