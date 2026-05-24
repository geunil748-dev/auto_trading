from __future__ import annotations

from collections.abc import Iterable

from trading_bot.config import TradingSettings
from trading_bot.execution import trailing_stop_triggered
from trading_bot.models import PositionState, SellIntent
from trading_bot.risk import hard_stop_triggered


def plan_position_exits(
    positions: Iterable[PositionState],
    settings: TradingSettings,
    end_of_day: bool = False,
) -> list[SellIntent]:
    intents: list[SellIntent] = []
    for position in positions:
        reason = _exit_reason(position, settings, end_of_day)
        if reason is None:
            continue
        intents.append(
            SellIntent(
                ticker=position.ticker,
                quantity=position.quantity,
                limit_price_usd=position.last_price_usd,
                exit_reason=reason,
            )
        )
    return intents


def _exit_reason(
    position: PositionState,
    settings: TradingSettings,
    end_of_day: bool,
) -> str | None:
    if end_of_day:
        return "EOD"
    if hard_stop_triggered(position, settings):
        return "STOP_LOSS"
    if trailing_stop_triggered(position, settings):
        return "TRAILING_STOP"
    return None
