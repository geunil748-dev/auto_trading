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
    data_sufficient: bool = True

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0


@dataclass(frozen=True)
class _Signal:
    ticker: str
    trade_date: date
    score: float
    entry: float
    high: float
    low: float
    close: float


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
    signals = sorted(
        (
            signal
            for ticker, bars in history.items()
            for signal in _ticker_signals(ticker, bars, settings, start_date, end_date)
        ),
        key=lambda item: (item.trade_date, -item.score, item.ticker),
    )
    equity = initial_equity_usd
    peak = initial_equity_usd
    max_drawdown = 0.0
    wins = 0
    returns: list[float] = []
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
            trade_return = _same_day_exit_return(signal, settings)
            equity += equity * fraction * trade_return
            day_exposure += fraction
            wins += int(trade_return > 0)
            returns.append(trade_return)
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
    )


def _ticker_signals(
    ticker: str,
    bars: list[BacktestBar],
    settings: TradingSettings,
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
        if not _passes_required_filters(bar, opening_change, volume_ratio, opening_gap, settings):
            continue
        score = _chart_score(bars[index - 35 : index])
        if score >= settings.min_total_score:
            signals.append(
                _Signal(
                    ticker=ticker,
                    trade_date=bar.trade_date,
                    score=score,
                    entry=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                )
            )
    return signals


def _passes_required_filters(
    bar: BacktestBar,
    opening_change: float,
    volume_ratio: float,
    opening_gap: float,
    settings: TradingSettings,
) -> bool:
    return (
        settings.min_price_usd <= bar.open <= settings.max_price_usd
        and opening_change >= settings.min_opening_price_change
        and volume_ratio >= settings.min_volume_ratio
        and opening_gap < settings.max_opening_gap
    )


def _same_day_exit_return(signal: _Signal, settings: TradingSettings) -> float:
    stop_price = signal.entry * (1 + settings.max_position_loss)
    take_profit_price = signal.entry * (1 + settings.take_profit_rate)
    if signal.low <= stop_price:
        exit_price = stop_price
    elif signal.high >= take_profit_price:
        exit_price = take_profit_price
    else:
        exit_price = signal.close
    return exit_price / signal.entry - 1


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
        data_sufficient=data_sufficient,
    )
