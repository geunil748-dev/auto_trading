from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import isfinite

from trading_bot.config import TradingSettings
from trading_bot.strategy import volatility_breakout_price


@dataclass(frozen=True)
class IntradayBar:
    ticker: str
    bar_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    vwap: float | None = None
    ma20: float | None = None


@dataclass(frozen=True)
class IntradayTrade:
    ticker: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    return_rate: float
    exit_reason: str
    holding_minutes: float


@dataclass(frozen=True)
class IntradayBacktestResult:
    mode: str
    interval: str
    period_days: int
    ticker_count: int
    failed_tickers: tuple[str, ...]
    total_return: float
    average_trade_return: float
    win_rate: float
    max_drawdown: float
    trade_count: int
    zero_trade_days: int
    stop_loss_count: int
    take_profit_count: int
    trailing_stop_count: int
    eod_count: int
    average_holding_minutes: float
    max_holding_minutes: float
    trades: tuple[IntradayTrade, ...]


@dataclass(frozen=True)
class _IntradaySignal:
    ticker: str
    trigger_time: datetime
    entry_index: int


def run_intraday_backtest(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    settings: TradingSettings,
    mode: str,
    interval: str = "5m",
    period_days: int = 60,
    initial_equity_usd: float = 10000.0,
    failed_tickers: list[str] | None = None,
    intraday_slippage_rate: float = 0.001,
    intraday_commission_rate: float = 0.0005,
) -> IntradayBacktestResult:
    if mode == "fixed":
        return run_fixed_intraday_backtest(
            tickers,
            history,
            settings,
            interval=interval,
            period_days=period_days,
            initial_equity_usd=initial_equity_usd,
            failed_tickers=failed_tickers,
            intraday_slippage_rate=intraday_slippage_rate,
            intraday_commission_rate=intraday_commission_rate,
        )
    if mode not in {"refresh", "hybrid"}:
        raise ValueError(f"unsupported intraday backtest mode: {mode}")
    clean_history = _clean_history(tickers, history)
    days = _all_trade_days(clean_history)
    equity = initial_equity_usd
    peak = initial_equity_usd
    max_drawdown = 0.0
    trades: list[IntradayTrade] = []
    traded_days: set[date] = set()
    for trade_date in sorted(days):
        trade = _first_mode_trade_for_day(
            tickers,
            clean_history,
            trade_date,
            settings,
            mode,
            intraday_slippage_rate,
            intraday_commission_rate,
        )
        if trade is None:
            continue
        fraction = min(settings.max_position_exposure, settings.max_account_exposure)
        equity += equity * fraction * trade.return_rate
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, equity / peak - 1)
        trades.append(trade)
        traded_days.add(trade_date)
    return _result(
        trades,
        mode=mode,
        interval=interval,
        period_days=period_days,
        ticker_count=len(tickers),
        failed_tickers=tuple(failed_tickers or ()),
        total_return=equity / initial_equity_usd - 1 if initial_equity_usd else 0.0,
        max_drawdown=max_drawdown,
        zero_trade_days=len(days - traded_days),
    )


def run_intraday_backtest_compare(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    settings: TradingSettings,
    interval: str = "5m",
    period_days: int = 60,
    initial_equity_usd: float = 10000.0,
    failed_tickers: list[str] | None = None,
) -> dict[str, IntradayBacktestResult]:
    return {
        mode: run_intraday_backtest(
            tickers,
            history,
            settings,
            mode,
            interval=interval,
            period_days=period_days,
            initial_equity_usd=initial_equity_usd,
            failed_tickers=failed_tickers,
        )
        for mode in ("fixed", "refresh", "hybrid")
    }


def run_fixed_intraday_backtest(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    settings: TradingSettings,
    interval: str = "5m",
    period_days: int = 60,
    initial_equity_usd: float = 10000.0,
    failed_tickers: list[str] | None = None,
    intraday_slippage_rate: float = 0.001,
    intraday_commission_rate: float = 0.0005,
    trade_dates: set[date] | None = None,
) -> IntradayBacktestResult:
    clean_history = _clean_history(tickers, history)
    days = _all_trade_days(clean_history)
    if trade_dates is not None:
        days &= trade_dates
    equity = initial_equity_usd
    peak = initial_equity_usd
    max_drawdown = 0.0
    trades: list[IntradayTrade] = []
    traded_days: set[date] = set()
    for trade_date in sorted(days):
        trade = _first_fixed_trade_for_day(
            tickers,
            clean_history,
            trade_date,
            settings,
            intraday_slippage_rate,
            intraday_commission_rate,
        )
        if trade is None:
            continue
        fraction = min(settings.max_position_exposure, settings.max_account_exposure)
        equity += equity * fraction * trade.return_rate
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, equity / peak - 1)
        trades.append(trade)
        traded_days.add(trade_date)
    return _result(
        trades,
        mode="fixed",
        interval=interval,
        period_days=period_days,
        ticker_count=len(tickers),
        failed_tickers=tuple(failed_tickers or ()),
        total_return=equity / initial_equity_usd - 1 if initial_equity_usd else 0.0,
        max_drawdown=max_drawdown,
        zero_trade_days=len(days - traded_days),
    )


def intraday_result_payload(result: IntradayBacktestResult) -> dict[str, object]:
    return {
        "mode": result.mode,
        "interval": result.interval,
        "period_days": result.period_days,
        "ticker_count": result.ticker_count,
        "failed_tickers": list(result.failed_tickers),
        "total_return": result.total_return,
        "average_trade_return": result.average_trade_return,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
        "trade_count": result.trade_count,
        "zero_trade_days": result.zero_trade_days,
        "stop_loss_count": result.stop_loss_count,
        "take_profit_count": result.take_profit_count,
        "trailing_stop_count": result.trailing_stop_count,
        "eod_count": result.eod_count,
        "average_holding_minutes": result.average_holding_minutes,
        "max_holding_minutes": result.max_holding_minutes,
    }


def _first_fixed_trade_for_day(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade | None:
    candidates: list[tuple[datetime, str, int, float]] = []
    for ticker in tickers:
        bars = _bars_for_day(history.get(ticker.upper(), []), trade_date)
        previous = _previous_day_bars(history.get(ticker.upper(), []), trade_date)
        if len(bars) < 2 or not previous:
            continue
        breakout = volatility_breakout_price(
            bars[0].open_price,
            max(item.high_price for item in previous),
            min(item.low_price for item in previous),
            settings.breakout_k,
        )
        if not _passes_opening_filters(bars, previous, settings):
            continue
        for index, bar in enumerate(bars[:-1]):
            if bar.high_price >= breakout:
                candidates.append((bar.bar_time, ticker.upper(), index + 1, breakout))
                break
    if not candidates:
        return None
    _, ticker, entry_index, _ = min(candidates, key=lambda item: (item[0], item[1]))
    bars = _bars_for_day(history[ticker], trade_date)
    return _simulate_trade(
        ticker,
        bars,
        entry_index,
        settings,
        slippage_rate,
        commission_rate,
    )


def _first_mode_trade_for_day(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    mode: str,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade | None:
    trade = None
    if mode == "refresh":
        trade = _first_refresh_trade_for_day(
            tickers,
            history,
            trade_date,
            settings,
            slippage_rate,
            commission_rate,
        )
    if mode == "hybrid":
        trade = _first_hybrid_trade_for_day(
            tickers,
            history,
            trade_date,
            settings,
            slippage_rate,
            commission_rate,
        )
    return trade


def _first_refresh_trade_for_day(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade | None:
    for start, end in _refresh_windows(history, trade_date):
        active = _refresh_candidate_tickers_at(
            tickers,
            history,
            trade_date,
            start,
            settings,
            settings.intraday_refresh_candidate_limit,
        )
        signal = _first_signal_in_window(active, history, trade_date, settings, start, end)
        if signal is not None:
            return _trade_from_signal(
                signal,
                history,
                trade_date,
                settings,
                slippage_rate,
                commission_rate,
            )
    return None


def _first_hybrid_trade_for_day(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade | None:
    fixed_candidates = _opening_candidate_tickers(
        tickers,
        history,
        trade_date,
        settings,
        settings.opening_fixed_candidate_limit,
    )
    for start, end in _refresh_windows(history, trade_date):
        refreshed = _refresh_candidate_tickers_at(
            tickers,
            history,
            trade_date,
            start,
            settings,
            settings.intraday_refresh_candidate_limit,
        )
        active = _merge_candidates(fixed_candidates, refreshed, settings.hybrid_candidate_limit)
        signal = _first_signal_in_window(active, history, trade_date, settings, start, end)
        if signal is not None:
            return _trade_from_signal(
                signal,
                history,
                trade_date,
                settings,
                slippage_rate,
                commission_rate,
            )
    return None


def _trade_from_signal(
    signal: _IntradaySignal,
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade:
    return _simulate_trade(
        signal.ticker,
        _bars_for_day(history[signal.ticker], trade_date),
        signal.entry_index,
        settings,
        slippage_rate,
        commission_rate,
    )


def _first_signal_in_window(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    start: datetime,
    end: datetime,
) -> _IntradaySignal | None:
    signals: list[_IntradaySignal] = []
    for ticker in tickers:
        bars = _bars_for_day(history.get(ticker.upper(), []), trade_date)
        previous = _previous_day_bars(history.get(ticker.upper(), []), trade_date)
        signal = _first_signal_for_ticker(ticker, bars, previous, settings, start, end)
        if signal is not None:
            signals.append(signal)
    if not signals:
        return None
    return min(signals, key=lambda item: (item.trigger_time, item.ticker))


def _first_signal_for_ticker(
    ticker: str,
    bars: list[IntradayBar],
    previous: list[IntradayBar],
    settings: TradingSettings,
    start: datetime,
    end: datetime,
) -> _IntradaySignal | None:
    if len(bars) < 2 or not previous or not _passes_opening_filters(bars, previous, settings):
        return None
    breakout = volatility_breakout_price(
        bars[0].open_price,
        max(item.high_price for item in previous),
        min(item.low_price for item in previous),
        settings.breakout_k,
    )
    for index, bar in enumerate(bars[:-1]):
        if start <= bar.bar_time < end and bar.high_price >= breakout:
            return _IntradaySignal(ticker.upper(), bar.bar_time, index + 1)
    return None


def _opening_candidate_tickers(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    settings: TradingSettings,
    limit: int,
) -> list[str]:
    candidates: list[tuple[float, str]] = []
    for ticker in tickers:
        bars = _bars_for_day(history.get(ticker.upper(), []), trade_date)
        previous = _previous_day_bars(history.get(ticker.upper(), []), trade_date)
        if len(bars) < 2 or not previous or not _passes_opening_filters(bars, previous, settings):
            continue
        candidates.append((_candidate_score(bars, previous, bars[0].bar_time), ticker.upper()))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [ticker for _, ticker in candidates[: max(0, limit)]]


def _refresh_candidate_tickers_at(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
    trade_date: date,
    checkpoint: datetime,
    settings: TradingSettings,
    limit: int,
) -> list[str]:
    candidates: list[tuple[float, str]] = []
    for ticker in tickers:
        bars = _bars_for_day(history.get(ticker.upper(), []), trade_date)
        previous = _previous_day_bars(history.get(ticker.upper(), []), trade_date)
        if len(bars) < 2 or not previous or not _passes_opening_filters(bars, previous, settings):
            continue
        visible = [item for item in bars if item.bar_time <= checkpoint]
        if not visible:
            continue
        breakout = volatility_breakout_price(
            bars[0].open_price,
            max(item.high_price for item in previous),
            min(item.low_price for item in previous),
            settings.breakout_k,
        )
        if max(item.high_price for item in visible) < breakout * 0.98:
            continue
        candidates.append((_candidate_score(bars, previous, checkpoint), ticker.upper()))
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [ticker for _, ticker in candidates[: max(0, limit)]]


def _candidate_score(
    bars: list[IntradayBar],
    previous: list[IntradayBar],
    checkpoint: datetime,
) -> float:
    visible = [item for item in bars if item.bar_time <= checkpoint]
    if not visible or bars[0].open_price <= 0:
        return 0.0
    price_change = visible[-1].close_price / bars[0].open_price - 1
    volume_ratio = _visible_volume_ratio(visible, previous)
    return price_change * 100 + volume_ratio


def _visible_volume_ratio(visible: list[IntradayBar], previous: list[IntradayBar]) -> float:
    count = max(1, len(visible))
    current_volume = sum(item.volume for item in visible)
    previous_volume = sum(item.volume for item in previous[:count])
    if previous_volume <= 0:
        return 0.0
    return current_volume / previous_volume


def _refresh_windows(
    history: dict[str, list[IntradayBar]],
    trade_date: date,
) -> list[tuple[datetime, datetime]]:
    day_times = sorted(
        {
            item.bar_time
            for bars in history.values()
            for item in bars
            if item.bar_time.date() == trade_date
        }
    )
    if not day_times:
        return []
    checkpoints = [item for index, item in enumerate(day_times[:-1]) if index % 3 == 0]
    return [(item, item + timedelta(minutes=15)) for item in checkpoints]


def _merge_candidates(fixed: list[str], refreshed: list[str], limit: int) -> list[str]:
    merged: list[str] = []
    for ticker in [*fixed, *refreshed]:
        if ticker not in merged:
            merged.append(ticker)
    return merged[: max(0, limit)]


def _simulate_trade(
    ticker: str,
    bars: list[IntradayBar],
    entry_index: int,
    settings: TradingSettings,
    slippage_rate: float,
    commission_rate: float,
) -> IntradayTrade:
    entry_bar = bars[entry_index]
    entry_price = entry_bar.open_price * (1 + slippage_rate)
    stop_price = entry_price * (1 + settings.max_position_loss)
    take_profit_price = entry_price * (1 + settings.take_profit_rate)
    trailing_active = False
    highest_price = entry_price
    for bar in bars[entry_index:]:
        highest_price = max(highest_price, bar.high_price)
        stop_hit = bar.low_price <= stop_price
        take_profit_hit = bar.high_price >= take_profit_price
        if stop_hit:
            return _trade(
                ticker,
                entry_bar.bar_time,
                bar.bar_time,
                entry_price,
                stop_price * (1 - slippage_rate),
                "STOP_LOSS",
                commission_rate,
            )
        if take_profit_hit:
            return _trade(
                ticker,
                entry_bar.bar_time,
                bar.bar_time,
                entry_price,
                take_profit_price * (1 - slippage_rate),
                "TAKE_PROFIT",
                commission_rate,
            )
        if highest_price >= entry_price * (1 + settings.trailing_stop_activation_rate):
            trailing_active = True
        trailing_price = highest_price * (1 - settings.trailing_stop_drop)
        if trailing_active and bar.low_price <= trailing_price:
            return _trade(
                ticker,
                entry_bar.bar_time,
                bar.bar_time,
                entry_price,
                trailing_price * (1 - slippage_rate),
                "TRAILING_STOP",
                commission_rate,
            )
    last_bar = bars[-1]
    return _trade(
        ticker,
        entry_bar.bar_time,
        last_bar.bar_time,
        entry_price,
        last_bar.close_price * (1 - slippage_rate),
        "EOD",
        commission_rate,
    )


def _trade(
    ticker: str,
    entry_time: datetime,
    exit_time: datetime,
    entry_price: float,
    exit_price: float,
    exit_reason: str,
    commission_rate: float,
) -> IntradayTrade:
    net_return = (exit_price * (1 - commission_rate)) / (
        entry_price * (1 + commission_rate)
    ) - 1
    return IntradayTrade(
        ticker=ticker,
        entry_time=entry_time,
        exit_time=exit_time,
        entry_price=entry_price,
        exit_price=exit_price,
        return_rate=net_return,
        exit_reason=exit_reason,
        holding_minutes=(exit_time - entry_time).total_seconds() / 60,
    )


def _passes_opening_filters(
    bars: list[IntradayBar],
    previous: list[IntradayBar],
    settings: TradingSettings,
) -> bool:
    open_price = bars[0].open_price
    previous_close = previous[-1].close_price
    if previous_close <= 0:
        return False
    opening_change = open_price / previous_close - 1
    opening_gap = opening_change
    return (
        settings.min_price_usd <= open_price <= settings.max_price_usd
        and opening_change >= settings.min_opening_price_change
        and _opening_volume_ratio(bars, previous) >= settings.min_volume_ratio
        and opening_gap < settings.max_opening_gap
    )


def _opening_volume_ratio(bars: list[IntradayBar], previous: list[IntradayBar]) -> float:
    current_volume = sum(item.volume for item in bars[:3])
    previous_volume = sum(item.volume for item in previous[:3])
    if previous_volume <= 0:
        return 0.0
    return current_volume / previous_volume


def _result(
    trades: list[IntradayTrade],
    mode: str,
    interval: str,
    period_days: int,
    ticker_count: int,
    failed_tickers: tuple[str, ...],
    total_return: float,
    max_drawdown: float,
    zero_trade_days: int,
) -> IntradayBacktestResult:
    return IntradayBacktestResult(
        mode=mode,
        interval=interval,
        period_days=period_days,
        ticker_count=ticker_count,
        failed_tickers=failed_tickers,
        total_return=total_return,
        average_trade_return=_average([item.return_rate for item in trades]),
        win_rate=_average([1.0 if item.return_rate > 0 else 0.0 for item in trades]),
        max_drawdown=max_drawdown,
        trade_count=len(trades),
        zero_trade_days=zero_trade_days,
        stop_loss_count=_exit_count(trades, "STOP_LOSS"),
        take_profit_count=_exit_count(trades, "TAKE_PROFIT"),
        trailing_stop_count=_exit_count(trades, "TRAILING_STOP"),
        eod_count=_exit_count(trades, "EOD"),
        average_holding_minutes=_average([item.holding_minutes for item in trades]),
        max_holding_minutes=max((item.holding_minutes for item in trades), default=0.0),
        trades=tuple(trades),
    )


def _exit_count(trades: list[IntradayTrade], reason: str) -> int:
    return sum(1 for item in trades if item.exit_reason == reason)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _clean_history(
    tickers: list[str],
    history: dict[str, list[IntradayBar]],
) -> dict[str, list[IntradayBar]]:
    ticker_set = {item.upper() for item in tickers}
    return {
        ticker.upper(): _sorted_valid_bars(bars)
        for ticker, bars in history.items()
        if ticker.upper() in ticker_set
    }


def _all_trade_days(history: dict[str, list[IntradayBar]]) -> set[date]:
    return {item.bar_time.date() for bars in history.values() for item in bars}


def _bars_for_day(bars: list[IntradayBar], trade_date: date) -> list[IntradayBar]:
    return [item for item in bars if item.bar_time.date() == trade_date]


def _previous_day_bars(bars: list[IntradayBar], trade_date: date) -> list[IntradayBar]:
    previous_days = sorted({item.bar_time.date() for item in bars if item.bar_time.date() < trade_date})
    if not previous_days:
        return []
    return _bars_for_day(bars, previous_days[-1])


def _sorted_valid_bars(bars: list[IntradayBar]) -> list[IntradayBar]:
    return sorted(
        (
            item
            for item in bars
            if all(
                isfinite(value) and value > 0
                for value in (
                    item.open_price,
                    item.high_price,
                    item.low_price,
                    item.close_price,
                )
            )
            and item.volume >= 0
        ),
        key=lambda item: item.bar_time,
    )
