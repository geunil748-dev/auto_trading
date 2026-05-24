from __future__ import annotations

from collections.abc import Iterable
from statistics import pstdev

from trading_bot.chart_models import PriceBar


def chart_pattern_score(bars: Iterable[PriceBar]) -> float:
    series = list(bars)
    if len(series) < 35:
        raise ValueError("chart scoring requires at least 35 bars")

    closes = [item.close for item in series]
    signals = [
        _moving_average_signal(closes),
        _rsi_signal(closes),
        _macd_signal(closes),
        _bollinger_signal(closes),
    ]
    return round(sum(signals) / len(signals), 2)


def _moving_average_signal(closes: list[float]) -> float:
    fast_previous = _mean(closes[-6:-1])
    fast_current = _mean(closes[-5:])
    slow_previous = _mean(closes[-21:-1])
    slow_current = _mean(closes[-20:])
    if fast_previous <= slow_previous and fast_current > slow_current:
        return 100
    return 75 if fast_current > slow_current else 25


def _rsi_signal(closes: list[float]) -> float:
    previous = _rsi(closes[:-1])
    current = _rsi(closes)
    if previous < 35 <= current:
        return 100
    if current >= 80 and current < previous:
        return 0
    if 50 <= current < 80:
        return 70
    return 40


def _macd_signal(closes: list[float]) -> float:
    previous_macd, previous_signal = _macd(closes[:-1])
    current_macd, current_signal = _macd(closes)
    if previous_macd <= previous_signal and current_macd > current_signal:
        return 100
    return 75 if current_macd > current_signal else 25


def _bollinger_signal(closes: list[float]) -> float:
    window = closes[-20:]
    middle = _mean(window)
    deviation = pstdev(window)
    lower = middle - deviation * 2
    upper = middle + deviation * 2
    if closes[-2] <= lower and closes[-1] > closes[-2]:
        return 100
    if closes[-2] >= upper and closes[-1] < closes[-2]:
        return 0
    return 70 if closes[-1] >= middle else 35


def _rsi(closes: list[float], period: int = 14) -> float:
    changes = [current - previous for previous, current in zip(closes, closes[1:])]
    window = changes[-period:]
    gains = [max(change, 0) for change in window]
    losses = [abs(min(change, 0)) for change in window]
    average_gain = _mean(gains)
    average_loss = _mean(losses)
    if average_loss == 0:
        return 100
    relative_strength = average_gain / average_loss
    return 100 - 100 / (1 + relative_strength)


def _macd(closes: list[float]) -> tuple[float, float]:
    macd_series = [
        fast - slow
        for fast, slow in zip(_ema_series(closes, 12), _ema_series(closes, 26))
    ]
    return macd_series[-1], _ema_series(macd_series, 9)[-1]


def _ema_series(values: list[float], period: int) -> list[float]:
    multiplier = 2 / (period + 1)
    ema = values[0]
    results = [ema]
    for value in values[1:]:
        ema = value * multiplier + ema * (1 - multiplier)
        results.append(ema)
    return results


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)
