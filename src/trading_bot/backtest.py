from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite

from trading_bot.chart_models import PriceBar
from trading_bot.chart_scoring import chart_pattern_score
from trading_bot.config import TradingSettings
from trading_bot.scoring import position_fraction_for_score


@dataclass(frozen=True)
class BacktestBar:
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class BacktestResult:
    years: int
    tickers: int
    trades: int
    wins: int
    return_rate: float
    profit_usd: float
    ending_equity_usd: float
    average_trade_return: float
    max_drawdown: float
    zero_entry_days: int = 0
    stop_loss_count: int = 0
    take_profit_count: int = 0
    trailing_stop_count: int = 0
    eod_count: int = 0
    data_sufficient: bool = True

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def eod_rate(self) -> float:
        return self.eod_count / self.trades if self.trades else 0.0


@dataclass(frozen=True)
class _Signal:
    ticker: str
    trade_date: date
    score: float
    entry: float
    high: float
    low: float
    close: float
    opening_change: float = 0.0
    volume_ratio: float = 0.0
    opening_gap: float = 0.0


@dataclass(frozen=True)
class _TradeOutcome:
    return_rate: float
    exit_reason: str


def run_chart_backtest(
    tickers: list[str],
    history: dict[str, list[BacktestBar]],
    settings: TradingSettings,
    max_years: int = 10,
    initial_equity_usd: float = 10000.0,
    end_date: date | None = None,
) -> list[BacktestResult]:
    """뉴스를 제외하고 차트/가격/거래량 조건만으로 1~10년 성과를 계산한다."""
    clean_history = {
        ticker.upper(): _sorted_valid_bars(bars)
        for ticker, bars in history.items()
        if ticker.upper() in {item.upper() for item in tickers}
    }
    latest_date = end_date or _latest_date(clean_history)
    if latest_date is None:
        return [_empty_result(year, len(tickers), initial_equity_usd) for year in range(1, max_years + 1)]
    return [
        _window_result(clean_history, settings, latest_date, year, initial_equity_usd)
        for year in range(1, max_years + 1)
    ]


def _window_result(
    history: dict[str, list[BacktestBar]],
    settings: TradingSettings,
    latest_date: date,
    years: int,
    initial_equity_usd: float,
) -> BacktestResult:
    start_date = latest_date - timedelta(days=365 * years)
    if not _has_full_window(history, start_date):
        return _empty_result(years, len(history), initial_equity_usd, data_sufficient=False)
    return _run_window_backtest(
        history,
        settings,
        start_date,
        latest_date,
        years,
        initial_equity_usd,
    )


def _run_window_backtest(
    history: dict[str, list[BacktestBar]],
    settings: TradingSettings,
    start_date: date,
    end_date: date,
    years: int,
    initial_equity_usd: float,
) -> BacktestResult:
    signals = _backtest_signals(history, settings, start_date, end_date)
    signal_days = {item.trade_date for item in signals}
    trade_dates = _window_trade_dates(history, start_date, end_date)
    equity = initial_equity_usd
    peak = initial_equity_usd
    max_drawdown = 0.0
    wins = 0
    returns: list[float] = []
    exit_counts = {
        "STOP_LOSS": 0,
        "TAKE_PROFIT": 0,
        "TRAILING_STOP": 0,
        "EOD": 0,
    }
    for day_signals in _signals_by_day(signals):
        day_exposure = 0.0
        for signal in day_signals:
            fraction = min(
                position_fraction_for_score(signal.score, settings),
                settings.max_position_exposure,
                max(0.0, settings.max_account_exposure - day_exposure),
            )
            if fraction <= 0:
                continue
            outcome = _same_day_exit(signal, settings)
            equity += equity * fraction * outcome.return_rate
            day_exposure += fraction
            wins += int(outcome.return_rate > 0)
            returns.append(outcome.return_rate)
            exit_counts[outcome.exit_reason] += 1
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, equity / peak - 1)
    profit = equity - initial_equity_usd
    return BacktestResult(
        years=years,
        tickers=len(history),
        trades=len(returns),
        wins=wins,
        return_rate=profit / initial_equity_usd if initial_equity_usd else 0.0,
        profit_usd=profit,
        ending_equity_usd=equity,
        average_trade_return=sum(returns) / len(returns) if returns else 0.0,
        max_drawdown=max_drawdown,
        zero_entry_days=len(trade_dates - signal_days),
        stop_loss_count=exit_counts["STOP_LOSS"],
        take_profit_count=exit_counts["TAKE_PROFIT"],
        trailing_stop_count=exit_counts["TRAILING_STOP"],
        eod_count=exit_counts["EOD"],
    )


def _backtest_signals(
    history: dict[str, list[BacktestBar]],
    settings: TradingSettings,
    start_date: date,
    end_date: date,
) -> list[_Signal]:
    raw = sorted(
        (
            signal
            for ticker, bars in history.items()
            for signal in _ticker_signals(ticker, bars, start_date, end_date)
        ),
        key=lambda item: (item.trade_date, -item.score, item.ticker),
    )
    signals: list[_Signal] = []
    for day_signals in _signals_by_day(raw):
        signals.extend(_selected_day_signals(day_signals, settings))
    return signals


def _ticker_signals(
    ticker: str,
    bars: list[BacktestBar],
    start_date: date,
    end_date: date,
) -> list[_Signal]:
    signals: list[_Signal] = []
    for index in range(35, len(bars)):
        bar = bars[index]
        if not start_date <= bar.trade_date <= end_date:
            continue
        previous = bars[index - 1]
        volume_base = _average_volume(bars[index - 20 : index])
        if volume_base <= 0:
            continue
        opening_change = (bar.open - previous.close) / previous.close
        opening_gap = opening_change
        volume_ratio = bar.volume / volume_base
        score = _chart_score(bars[index - 35 : index])
        signals.append(
            _Signal(
                ticker=ticker,
                trade_date=bar.trade_date,
                score=score,
                entry=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                opening_change=opening_change,
                volume_ratio=volume_ratio,
                opening_gap=opening_gap,
            )
        )
    return signals


def _selected_day_signals(signals: list[_Signal], settings: TradingSettings) -> list[_Signal]:
    candidates = _filter_day_signals(signals, settings)
    candidates = [item for item in candidates if item.score >= settings.min_total_score]
    candidates.sort(key=lambda item: (-item.score, item.ticker))
    return candidates[: settings.max_selected_candidates]


def _filter_day_signals(signals: list[_Signal], settings: TradingSettings) -> list[_Signal]:
    if not settings.allow_relaxed_candidate_filter:
        if settings.relax_opening_change_only:
            return [
                item
                for item in signals
                if _passes_required_filters(
                    item,
                    _opening_change(item),
                    _volume_ratio(item),
                    _opening_gap(item),
                    settings,
                    min_opening_change=_relaxed_opening_change_threshold(settings),
                )
            ]
        return [
            item
            for item in signals
            if _passes_required_filters(
                item,
                _opening_change(item),
                _volume_ratio(item),
                _opening_gap(item),
                settings,
            )
        ]
    min_count = min(settings.min_selected_candidates, settings.max_selected_candidates)
    candidates = _first_passing_stage(
        signals,
        _price_stages(settings),
        lambda item, stage: stage[0] <= item.entry <= stage[1],
        min_count,
    )
    candidates = _first_passing_stage(
        candidates,
        _opening_change_stages(settings),
        lambda item, stage: _opening_change(item) >= stage,
        min_count,
    )
    candidates = _first_passing_stage(
        candidates,
        _volume_stages(settings),
        lambda item, stage: _volume_ratio(item) >= stage,
        min_count,
    )
    return _first_passing_stage(
        candidates,
        _gap_stages(settings),
        lambda item, stage: _opening_gap(item) < stage,
        min_count,
    )


def _passes_required_filters(
    signal: _Signal,
    opening_change: float,
    volume_ratio: float,
    opening_gap: float,
    settings: TradingSettings,
    min_opening_change: float | None = None,
) -> bool:
    return (
        settings.min_price_usd <= signal.entry <= settings.max_price_usd
        and opening_change
        >= (
            settings.min_opening_price_change
            if min_opening_change is None
            else min_opening_change
        )
        and volume_ratio >= settings.min_volume_ratio
        and opening_gap < settings.max_opening_gap
    )


def _same_day_exit(signal: _Signal, settings: TradingSettings) -> _TradeOutcome:
    stop_price = signal.entry * (1 + settings.max_position_loss)
    take_profit_price = signal.entry * (1 + settings.take_profit_rate)
    if signal.low <= stop_price:
        exit_price = stop_price
        reason = "STOP_LOSS"
    elif signal.high >= take_profit_price:
        exit_price = take_profit_price
        reason = "TAKE_PROFIT"
    elif _trailing_stop_triggered(signal, settings):
        exit_price = signal.high * (1 - settings.trailing_stop_drop)
        reason = "TRAILING_STOP"
    else:
        exit_price = signal.close
        reason = "EOD"
    return _TradeOutcome(exit_price / signal.entry - 1, reason)


def _same_day_exit_return(signal: _Signal, settings: TradingSettings) -> float:
    return _same_day_exit(signal, settings).return_rate


def _trailing_stop_triggered(signal: _Signal, settings: TradingSettings) -> bool:
    activation_price = signal.entry * (1 + settings.trailing_stop_activation_rate)
    if signal.high < activation_price:
        return False
    return signal.low <= signal.high * (1 - settings.trailing_stop_drop)


def _chart_score(bars: list[BacktestBar]) -> float:
    price_bars = [PriceBar(close=item.close, high=item.high, low=item.low) for item in bars]
    try:
        return chart_pattern_score(price_bars)
    except ValueError:
        return 0.0


def _signals_by_day(signals: list[_Signal]) -> list[list[_Signal]]:
    grouped: list[list[_Signal]] = []
    for signal in signals:
        if not grouped or grouped[-1][0].trade_date != signal.trade_date:
            grouped.append([signal])
        else:
            grouped[-1].append(signal)
    return grouped


def _opening_change(signal: _Signal) -> float:
    return signal.opening_change


def _opening_gap(signal: _Signal) -> float:
    return signal.opening_gap


def _volume_ratio(signal: _Signal) -> float:
    return signal.volume_ratio


def _first_passing_stage(candidates: list[_Signal], stages, predicate, min_count: int) -> list[_Signal]:
    best: list[_Signal] = []
    for stage in stages:
        current = [item for item in candidates if predicate(item, stage)]
        if len(current) >= min_count:
            return current
        if len(current) > len(best):
            best = current
    return best


def _price_stages(settings: TradingSettings) -> tuple[tuple[float, float], ...]:
    return (
        (settings.min_price_usd, settings.max_price_usd),
        (3.0, 80.0),
        (1.0, 100.0),
        (0.5, 150.0),
    )


def _opening_change_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.min_opening_price_change,
        0.02,
        0.01,
        0.0,
        -0.05,
    )


def _volume_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.min_volume_ratio,
        1.2,
        1.0,
        0.7,
        0.5,
        0.0,
    )


def _gap_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.max_opening_gap,
        0.25,
        0.30,
        0.40,
        1.00,
    )


def _relaxed_opening_change_threshold(settings: TradingSettings) -> float:
    if settings.min_opening_price_change <= 0:
        return settings.min_opening_price_change
    return max(0.0001, settings.min_opening_price_change - 0.01)


def _window_trade_dates(
    history: dict[str, list[BacktestBar]],
    start_date: date,
    end_date: date,
) -> set[date]:
    return {
        item.trade_date
        for bars in history.values()
        for item in bars
        if start_date <= item.trade_date <= end_date
    }


def _average_volume(bars: list[BacktestBar]) -> float:
    valid = [item.volume for item in bars if item.volume > 0]
    return sum(valid) / len(valid) if valid else 0.0


def _sorted_valid_bars(bars: list[BacktestBar]) -> list[BacktestBar]:
    return sorted(
        (
            item
            for item in bars
            if all(isfinite(value) and value > 0 for value in (item.open, item.high, item.low, item.close))
            and item.volume >= 0
        ),
        key=lambda item: item.trade_date,
    )


def _latest_date(history: dict[str, list[BacktestBar]]) -> date | None:
    dates = [bars[-1].trade_date for bars in history.values() if bars]
    return max(dates) if dates else None


def _has_full_window(history: dict[str, list[BacktestBar]], start_date: date) -> bool:
    starts = [bars[0].trade_date for bars in history.values() if bars]
    return bool(starts) and min(starts) <= start_date


def _empty_result(
    years: int,
    tickers: int,
    initial_equity_usd: float,
    data_sufficient: bool = False,
) -> BacktestResult:
    return BacktestResult(
        years=years,
        tickers=tickers,
        trades=0,
        wins=0,
        return_rate=0.0,
        profit_usd=0.0,
        ending_equity_usd=initial_equity_usd,
        average_trade_return=0.0,
        max_drawdown=0.0,
        zero_entry_days=0,
        stop_loss_count=0,
        take_profit_count=0,
        trailing_stop_count=0,
        eod_count=0,
        data_sufficient=data_sufficient,
    )
