from __future__ import annotations

from datetime import datetime, timedelta

from trading_bot.backtest import BacktestResult
from trading_bot.cli import (
    _backtest_base_settings,
    _reset_runtime_settings,
    _run_backtest_compare,
    _run_intraday_backtest_compare,
)
from trading_bot.config import TradingSettings
from trading_bot.intraday_backtest import IntradayBar


def test_backtest_compare_uses_fixed_baseline_by_default() -> None:
    settings = _backtest_base_settings()

    assert settings.min_price_usd == 5.0
    assert settings.max_price_usd == 50.0
    assert settings.min_opening_price_change == 0.03
    assert settings.min_volume_ratio == 1.5
    assert settings.max_opening_gap == 0.20
    assert settings.min_total_score == 40.0
    assert settings.max_position_loss == -0.05
    assert settings.take_profit_rate == 0.05


def test_backtest_compare_can_use_runtime_settings(monkeypatch) -> None:
    runtime = TradingSettings(
        min_price_usd=1.0,
        max_price_usd=150.0,
        min_opening_price_change=0.0,
        min_volume_ratio=0.5,
        max_opening_gap=0.5,
    )
    monkeypatch.setattr("trading_bot.cli.load_settings", lambda: runtime)

    settings = _backtest_base_settings(use_runtime_settings=True)

    assert settings.min_price_usd == 1.0
    assert settings.max_price_usd == 150.0
    assert settings.min_opening_price_change == 0.0
    assert settings.min_volume_ratio == 0.5
    assert settings.max_opening_gap == 0.5


def test_backtest_compare_reports_applied_settings_and_reproducible_baseline(
    monkeypatch,
) -> None:
    captured: list[TradingSettings] = []

    def fake_run_chart_backtest(*args, **kwargs):
        settings = args[2]
        captured.append(settings)
        trades = 80 if settings.strategy_preset == "current" else 80
        return [
            BacktestResult(
                years=10,
                tickers=19,
                trades=trades,
                wins=25,
                return_rate=-0.0771,
                profit_usd=-771.0,
                ending_equity_usd=9229.0,
                average_trade_return=-0.0137,
                max_drawdown=-0.0902,
                zero_entry_days=2439,
                stop_loss_count=47,
                take_profit_count=25,
                trailing_stop_count=4,
                eod_count=4,
            )
        ]

    monkeypatch.setattr("trading_bot.cli._latest_candidate_tickers", lambda: ("2026-05-29", ["AAA"]))
    monkeypatch.setattr("trading_bot.cli._prepare_yfinance_cache", lambda: None)
    monkeypatch.setattr("trading_bot.cli.load_history", lambda tickers, source, years: {"AAA": []})
    monkeypatch.setattr("trading_bot.cli.run_chart_backtest", fake_run_chart_backtest)

    payload = _run_backtest_compare(10, 10000.0)

    assert payload["settings_source"] == "fixed_baseline"
    assert payload["baseline_settings"]["min_price_usd"] == 5.0
    assert payload["baseline_settings"]["min_total_score"] == 40.0
    strict = payload["strategies"]["strict_filter"]
    modes = payload["candidateModeComparison"]
    assert strict["trades"] == 80
    assert strict["settings"]["min_price_usd"] == 5.0
    assert strict["settings"]["max_price_usd"] == 50.0
    assert strict["settings"]["min_opening_price_change"] == 0.03
    assert strict["settings"]["min_volume_ratio"] == 1.5
    assert strict["settings"]["max_opening_gap"] == 0.20
    assert captured[0].allow_relaxed_candidate_filter is False
    assert modes["fixed"]["settings"]["candidate_selection_mode"] == "fixed"
    assert modes["fixed"]["settings"]["refresh_intraday_candidates"] is False
    assert modes["refresh"]["settings"]["candidate_selection_mode"] == "refresh"
    assert modes["refresh"]["settings"]["refresh_intraday_candidates"] is True
    assert modes["hybrid"]["settings"]["candidate_selection_mode"] == "hybrid"
    assert modes["hybrid"]["settings"]["refresh_intraday_candidates"] is True


def test_reset_runtime_settings_writes_strict_baseline(monkeypatch) -> None:
    calls = {}
    before_after = [
        TradingSettings(min_price_usd=1.0, max_price_usd=150.0),
        TradingSettings(
            min_price_usd=5.0,
            max_price_usd=50.0,
            min_opening_price_change=0.03,
            min_volume_ratio=1.5,
            max_opening_gap=0.20,
            min_total_score=40.0,
        ),
    ]

    def fake_load_settings():
        return before_after.pop(0)

    def fake_save_runtime_risk_settings(**kwargs):
        calls.update(kwargs)
        return {"saved": True}

    monkeypatch.setattr("trading_bot.cli.load_settings", fake_load_settings)
    monkeypatch.setattr(
        "trading_bot.cli.save_runtime_risk_settings",
        fake_save_runtime_risk_settings,
    )

    payload = _reset_runtime_settings("strict_baseline")

    assert payload["before"]["min_price_usd"] == 1.0
    assert payload["after"]["min_price_usd"] == 5.0
    assert calls["stop_loss_percent"] == 5.0
    assert calls["take_profit_percent"] == 5.0
    assert calls["min_total_score"] == 40.0
    assert calls["min_opening_price_change_percent"] == 3.0
    assert calls["allow_relaxed_candidate_filter"] is False
    assert calls["enable_pyramiding"] is False


def test_intraday_recent_candidate_days_reports_daily_and_aggregate(monkeypatch) -> None:
    monkeypatch.setattr(
        "trading_bot.cli._recent_candidate_tickers",
        lambda limit: [
            ("2026-05-29", ["AAA"]),
            ("2026-05-28", ["AAA"]),
        ][:limit],
    )
    monkeypatch.setattr("trading_bot.cli._prepare_yfinance_cache", lambda: None)
    monkeypatch.setattr(
        "trading_bot.cli.load_intraday_history",
        lambda tickers, source, interval, period_days: (
            {"AAA": _intraday_history()},
            [],
        ),
    )

    payload = _run_intraday_backtest_compare("5m", 60, 10000.0, recent_candidate_days=2)

    assert payload["requested_candidate_days"] == 2
    assert len(payload["dailyResults"]) == 2
    assert payload["dailyResults"][0]["candidate_date"] == "2026-05-29"
    assert payload["aggregate"]["tested_candidate_days"] == 2
    assert payload["aggregate"]["sample_sufficient"] is False
    assert payload["aggregate"]["minimum_required_candidate_days"] == 10
    assert payload["aggregate"]["minimum_required_trade_count"] == 30
    assert "INSUFFICIENT_SAMPLE_FOR_STRATEGY_DECISION" in payload["aggregate"]["sample_warning"]
    assert payload["aggregate"]["total_ticker_count"] == 2
    assert "total_trade_count" in payload["aggregate"]


def _intraday_history() -> list[IntradayBar]:
    history: list[IntradayBar] = []
    for day in (27, 28, 29):
        previous = datetime(2026, 5, day, 9, 30)
        high = 10.6 if day in (28, 29) else 10.0
        history.extend(
            [
                _intraday_bar(previous, 9.5, 10.0, 9.0, 9.5, 100),
                _intraday_bar(previous + timedelta(minutes=5), 10.0, high, 9.9, 10.4, 300),
                _intraday_bar(previous + timedelta(minutes=10), 10.4, 10.7, 10.3, 10.5, 300),
            ]
        )
    return history


def _intraday_bar(
    bar_time: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float,
) -> IntradayBar:
    return IntradayBar(
        ticker="AAA",
        bar_time=bar_time,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )
