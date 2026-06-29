from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from trading_bot.config import TradingSettings
from trading_bot.execution import trailing_stop_triggered
from trading_bot.models import PositionState, SellIntent
from trading_bot.risk import hard_stop_triggered


def plan_position_exits(
    positions: Iterable[PositionState],
    settings: TradingSettings,
    end_of_day: bool = False,
    partial_take_profit_tickers: Iterable[str] = (),
    now: datetime | None = None,
) -> list[SellIntent]:
    intents: list[SellIntent] = []
    partial_done = {_ticker(ticker) for ticker in partial_take_profit_tickers}
    for position in positions:
        reason = _exit_reason(position, settings, end_of_day, partial_done, now)
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
    now: datetime | None,
) -> str | None:
    if end_of_day:
        return "EOD"
    if hard_stop_triggered(position, settings):
        return "STOP_LOSS"
    if profit_protection_triggered(position, settings):
        return "PROFIT_PROTECTION"
    if early_negative_exit_triggered(position, settings, now):
        return "EARLY_NEGATIVE_EXIT"
    if time_stop_exit_triggered(position, settings, now):
        return "TIME_STOP_EXIT"
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


def profit_protection_triggered(
    position: PositionState,
    settings: TradingSettings,
) -> bool:
    if not settings.profit_protection_exit_enabled:
        return False
    if position.entry_price_usd <= 0:
        return False
    high_profit_rate = (
        position.high_price_usd - position.entry_price_usd
    ) / position.entry_price_usd
    return (
        high_profit_rate >= settings.profit_protection_trigger_rate
        and position.profit_rate <= settings.profit_protection_floor_rate
    )


def early_negative_exit_triggered(
    position: PositionState,
    settings: TradingSettings,
    now: datetime | None = None,
) -> bool:
    if not settings.early_negative_exit_enabled:
        return False
    holding_minutes = position_holding_minutes(position, now)
    return (
        holding_minutes is not None
        and holding_minutes >= settings.early_negative_exit_minutes
        and position.profit_rate <= settings.early_negative_exit_rate
    )


def time_stop_exit_triggered(
    position: PositionState,
    settings: TradingSettings,
    now: datetime | None = None,
) -> bool:
    if not settings.time_stop_exit_enabled:
        return False
    holding_minutes = position_holding_minutes(position, now)
    return (
        holding_minutes is not None
        and holding_minutes >= settings.time_stop_minutes
        and position.profit_rate < settings.time_stop_min_profit_rate
    )


def position_holding_minutes(
    position: PositionState,
    now: datetime | None = None,
) -> float | None:
    entry_time = _entry_datetime(position.entry_time)
    if entry_time is None:
        return None
    reference = now or datetime.now(entry_time.tzinfo)
    if entry_time.tzinfo is None and reference.tzinfo is not None:
        reference = reference.replace(tzinfo=None)
    if entry_time.tzinfo is not None and reference.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=None)
    return max((reference - entry_time).total_seconds() / 60, 0.0)


def _entry_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text, text.replace("T", " ").replace("Z", "")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _ticker(value: str) -> str:
    return value.strip().upper()
