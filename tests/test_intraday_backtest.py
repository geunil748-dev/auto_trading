from __future__ import annotations

from datetime import datetime, timedelta

from trading_bot.config import TradingSettings
from trading_bot.intraday_backtest import (
    IntradayBar,
    run_fixed_intraday_backtest,
    run_intraday_backtest,
)


def test_stop_loss_when_low_reaches_stop_price() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.0, high=10.7, close=10.4)},
        _settings(),
    )

    assert result.stop_loss_count == 1
    assert result.trades[0].exit_reason == "STOP_LOSS"


def test_take_profit_when_high_reaches_take_profit_price() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.3, high=11.3, close=11.0)},
        _settings(),
    )

    assert result.take_profit_count == 1
    assert result.trades[0].exit_reason == "TAKE_PROFIT"


def test_stop_loss_has_priority_when_stop_and_take_profit_hit_same_bar() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.0, high=11.3, close=10.8)},
        _settings(),
    )

    assert result.stop_loss_count == 1
    assert result.take_profit_count == 0
    assert result.trades[0].exit_reason == "STOP_LOSS"


def test_trailing_stop_after_activation_and_pullback() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.6, high=11.0, close=10.8)},
        _settings(),
    )

    assert result.trailing_stop_count == 1
    assert result.trades[0].exit_reason == "TRAILING_STOP"


def test_eod_when_no_exit_condition_is_hit() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.4, high=10.8, close=10.7)},
        _settings(),
    )

    assert result.eod_count == 1
    assert result.trades[0].exit_reason == "EOD"


def test_entry_price_uses_next_open_with_slippage() -> None:
    result = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.4, high=10.8, close=10.7)},
        _settings(),
        intraday_slippage_rate=0.001,
    )

    assert result.trades[0].entry_price == 10.6 * 1.001


def test_commission_is_reflected_in_trade_return() -> None:
    result_without_fee = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.4, high=10.8, close=10.7)},
        _settings(),
        intraday_commission_rate=0.0,
    )
    result_with_fee = run_fixed_intraday_backtest(
        ["AAA"],
        {"AAA": _history_with_exit_bar(low=10.4, high=10.8, close=10.7)},
        _settings(),
        intraday_commission_rate=0.0005,
    )

    assert result_with_fee.trades[0].return_rate < result_without_fee.trades[0].return_rate


def test_fixed_mode_does_not_add_intraday_candidates() -> None:
    history = {
        "AAA": _history_with_exit_bar(low=10.4, high=10.8, close=10.7, start_minute=10),
        "BBB": _history_with_exit_bar(low=10.4, high=10.8, close=10.7, start_minute=0),
    }

    result = run_fixed_intraday_backtest(["AAA"], history, _settings())

    assert result.trade_count == 1
    assert result.trades[0].ticker == "AAA"


def test_refresh_mode_replaces_candidates_every_15_minutes() -> None:
    history = {
        "AAA": _refresh_history("AAA", early_breakout=True, late_breakout=False),
        "BBB": _refresh_history("BBB", early_breakout=False, late_breakout=True),
    }

    result = run_intraday_backtest(["AAA", "BBB"], history, _settings(), mode="refresh")

    assert result.trade_count == 1
    assert result.trades[0].ticker == "BBB"


def test_hybrid_mode_combines_opening_and_refresh_candidates() -> None:
    history = {
        "AAA": _refresh_history("AAA", early_breakout=True, late_breakout=False),
        "BBB": _refresh_history("BBB", early_breakout=False, late_breakout=True),
    }

    result = run_intraday_backtest(
        ["AAA", "BBB"],
        history,
        _settings(opening_fixed_candidate_limit=1, hybrid_candidate_limit=2),
        mode="hybrid",
    )

    assert result.trade_count == 1
    assert result.trades[0].ticker == "AAA"


def test_refresh_and_hybrid_keep_one_entry_per_day() -> None:
    history = {
        "AAA": _refresh_history("AAA", early_breakout=False, late_breakout=True),
        "BBB": _refresh_history("BBB", early_breakout=False, late_breakout=True),
    }

    refresh = run_intraday_backtest(["AAA", "BBB"], history, _settings(), mode="refresh")
    hybrid = run_intraday_backtest(["AAA", "BBB"], history, _settings(), mode="hybrid")

    assert refresh.trade_count == 1
    assert hybrid.trade_count == 1


def _settings(**overrides: object) -> TradingSettings:
    values = {
        "allow_relaxed_candidate_filter": False,
        "enable_pyramiding": False,
        "min_price_usd": 5.0,
        "max_price_usd": 50.0,
        "min_opening_price_change": 0.03,
        "min_volume_ratio": 1.5,
        "max_opening_gap": 0.20,
        "max_position_loss": -0.05,
        "take_profit_rate": 0.05,
        "trailing_stop_activation_rate": 0.03,
        "trailing_stop_drop": 0.03,
    }
    values.update(overrides)
    return TradingSettings(
        **values,
    )


def _history_with_exit_bar(
    low: float,
    high: float,
    close: float,
    start_minute: int = 0,
) -> list[IntradayBar]:
    previous_day = datetime(2026, 5, 28, 9, 30)
    trade_day = datetime(2026, 5, 29, 9, 30) + timedelta(minutes=start_minute)
    return [
        _bar(previous_day, 9.5, 10.0, 9.0, 9.5, 100),
        _bar(previous_day + timedelta(minutes=5), 9.5, 9.8, 9.2, 9.5, 100),
        _bar(previous_day + timedelta(minutes=10), 9.5, 9.7, 9.3, 9.5, 100),
        _bar(trade_day, 10.0, 10.6, 9.9, 10.5, 300),
        _bar(trade_day + timedelta(minutes=5), 10.6, high, low, close, 300),
        _bar(trade_day + timedelta(minutes=10), close, close + 0.1, close - 0.1, close, 300),
    ]


def _bar(
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


def _refresh_history(
    ticker: str,
    early_breakout: bool,
    late_breakout: bool,
) -> list[IntradayBar]:
    previous_day = datetime(2026, 5, 28, 9, 30)
    trade_day = datetime(2026, 5, 29, 9, 30)
    early_high = 10.6 if early_breakout else 10.2
    late_probe = 10.4 if late_breakout else 10.2
    late_high = 10.6 if late_breakout else 10.2
    return [
        _ticker_bar(ticker, previous_day, 9.5, 10.0, 9.0, 9.5, 100),
        _ticker_bar(ticker, previous_day + timedelta(minutes=5), 9.5, 9.8, 9.2, 9.5, 100),
        _ticker_bar(ticker, previous_day + timedelta(minutes=10), 9.5, 9.7, 9.3, 9.5, 100),
        _ticker_bar(ticker, trade_day, 10.0, 10.2, 9.9, 10.1, 300),
        _ticker_bar(ticker, trade_day + timedelta(minutes=5), 10.1, early_high, 10.0, 10.2, 300),
        _ticker_bar(ticker, trade_day + timedelta(minutes=10), 10.2, 10.2, 10.0, 10.1, 300),
        _ticker_bar(ticker, trade_day + timedelta(minutes=15), 10.1, late_probe, 10.0, 10.3, 300),
        _ticker_bar(ticker, trade_day + timedelta(minutes=20), 10.3, late_high, 10.2, 10.4, 300),
        _ticker_bar(ticker, trade_day + timedelta(minutes=25), 10.4, 10.6, 10.3, 10.5, 300),
    ]


def _ticker_bar(
    ticker: str,
    bar_time: datetime,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    volume: float,
) -> IntradayBar:
    return IntradayBar(
        ticker=ticker,
        bar_time=bar_time,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )
