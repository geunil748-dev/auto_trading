from __future__ import annotations

from dataclasses import replace

from trading_bot.config import TradingSettings
from trading_bot.models import PositionState


def update_high(position: PositionState, last_price_usd: float) -> PositionState:
    if last_price_usd <= 0:
        raise ValueError("last price must be positive")
    return replace(
        position,
        last_price_usd=last_price_usd,
        high_price_usd=max(position.high_price_usd, last_price_usd),
    )


def trailing_stop_price(position: PositionState, settings: TradingSettings) -> float:
    if position.high_price_usd <= 0:
        raise ValueError("high price must be positive")
    return position.high_price_usd * (1 - settings.trailing_stop_drop)


def trailing_stop_triggered(
    position: PositionState,
    settings: TradingSettings,
) -> bool:
    return trailing_stop_activated(position, settings) and (
        position.last_price_usd <= trailing_stop_price(position, settings)
    )


def trailing_stop_activated(position: PositionState, settings: TradingSettings) -> bool:
    if settings.trailing_stop_activation_rate <= 0:
        return True
    if position.entry_price_usd <= 0:
        return False
    high_profit_rate = (position.high_price_usd - position.entry_price_usd) / position.entry_price_usd
    return high_profit_rate >= settings.trailing_stop_activation_rate
