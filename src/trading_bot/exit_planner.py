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
    partial_take_profit_tickers: Iterable[str] = (),
) -> list[SellIntent]:
    intents: list[SellIntent] = []
    partial_done = {_ticker(ticker) for ticker in partial_take_profit_tickers}
    for position in positions:
        reason = _exit_reason(position, settings, end_of_day, partial_done)
        if reason is None:
            continue
        quantity = position.quantity
        if reason == "PARTIAL_TAKE_PROFIT":
            quantity = max(1, position.quantity // 2)
        intents.append(
            SellIntent(
                ticker=position.ticker,
                quantity=quantity,
                limit_price_usd=position.last_price_usd,
                exit_reason=reason,
                entry_price_usd=position.entry_price_usd,
            )
        )
    return intents


def _exit_reason(
    position: PositionState,
    settings: TradingSettings,
    end_of_day: bool,
    partial_done: set[str],
) -> str | None:
    if end_of_day:
        return "EOD"
    if hard_stop_triggered(position, settings):
        return "STOP_LOSS"
    if take_profit_triggered(position, settings):
        if not settings.partial_take_profit_enabled:
            return "TAKE_PROFIT"
        if _ticker(position.ticker) not in partial_done:
            return "PARTIAL_TAKE_PROFIT"
    if trailing_stop_triggered(position, settings):
        return "TRAILING_STOP"
    return None


def take_profit_triggered(position: PositionState, settings: TradingSettings) -> bool:
    return position.profit_rate >= settings.take_profit_rate


def _ticker(value: str) -> str:
    return value.strip().upper()
