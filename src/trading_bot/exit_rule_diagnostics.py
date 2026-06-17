from __future__ import annotations

from collections.abc import Iterable

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, PositionState


DIAGNOSTIC_MODULE = "exit_rule_diagnostics"
DIAGNOSTIC_REASON = "EXIT_RULE_DIAGNOSTIC"


def build_exit_rule_diagnostics(
    positions: Iterable[PositionState],
    settings: TradingSettings,
) -> list[BotLog]:
    if not settings.early_exit_diagnostics_enabled:
        return []
    logs: list[BotLog] = []
    for position in positions:
        if settings.profit_protection_exit_enabled:
            logs.append(_profit_protection_log(position, settings))
        if settings.early_negative_exit_enabled:
            logs.append(_time_based_log(position, settings, "EARLY_NEGATIVE_10M"))
        if settings.time_stop_exit_enabled:
            logs.append(_time_based_log(position, settings, "TIME_STOP_30M_NEGATIVE"))
        if settings.low_profit_60m_exit_enabled:
            logs.append(_time_based_log(position, settings, "LOW_PROFIT_60M"))
    return logs


def _profit_protection_log(position: PositionState, settings: TradingSettings) -> BotLog:
    current_profit = _profit_rate(position)
    max_profit_seen = _max_profit_seen(position)
    triggered = (
        max_profit_seen is not None
        and max_profit_seen >= settings.profit_protection_trigger_rate
    )
    would_exit = (
        triggered
        and current_profit is not None
        and current_profit < settings.profit_protection_floor_rate
    )
    message = (
        f"EXIT_RULE_DIAGNOSTIC ticker={_ticker(position.ticker)} "
        "rule=PROFIT_PROTECTION_2PCT "
        f"triggered={_bool_text(triggered)} "
        f"max_profit_seen={_rate_text(max_profit_seen)} "
        f"current_profit={_rate_text(current_profit)} "
        f"would_exit={_bool_text(would_exit)} "
        "actual_exit_not_changed=true"
    )
    return BotLog(
        "INFO",
        DIAGNOSTIC_MODULE,
        message,
        symbol=_ticker(position.ticker),
        reject_reason=DIAGNOSTIC_REASON,
        actual_value=current_profit,
        threshold_value=settings.profit_protection_floor_rate,
    )


def _time_based_log(
    position: PositionState,
    settings: TradingSettings,
    rule: str,
) -> BotLog:
    current_profit = _profit_rate(position)
    threshold = _time_rule_threshold(settings, rule)
    minutes = _time_rule_minutes(settings, rule)
    below_threshold = current_profit is not None and current_profit < threshold
    message = (
        f"EXIT_RULE_DIAGNOSTIC ticker={_ticker(position.ticker)} "
        f"rule={rule} "
        f"current_profit={_rate_text(current_profit)} "
        f"threshold={_rate_text(threshold)} "
        f"required_minutes={minutes} "
        f"current_below_threshold={_bool_text(below_threshold)} "
        "holding_minutes_available=false "
        "would_exit=false "
        "actual_exit_not_changed=true"
    )
    return BotLog(
        "INFO",
        DIAGNOSTIC_MODULE,
        message,
        symbol=_ticker(position.ticker),
        reject_reason=DIAGNOSTIC_REASON,
        actual_value=current_profit,
        threshold_value=threshold,
    )


def _time_rule_threshold(settings: TradingSettings, rule: str) -> float:
    if rule == "LOW_PROFIT_60M":
        return settings.low_profit_60m_min_profit_rate
    if rule == "EARLY_NEGATIVE_10M":
        return settings.early_negative_exit_rate
    return settings.time_stop_min_profit_rate


def _time_rule_minutes(settings: TradingSettings, rule: str) -> int:
    if rule == "LOW_PROFIT_60M":
        return settings.low_profit_60m_minutes
    if rule == "EARLY_NEGATIVE_10M":
        return settings.early_negative_exit_minutes
    return settings.time_stop_minutes


def _profit_rate(position: PositionState) -> float | None:
    try:
        return position.profit_rate
    except ValueError:
        return None


def _max_profit_seen(position: PositionState) -> float | None:
    if position.entry_price_usd <= 0:
        return None
    return (position.high_price_usd - position.entry_price_usd) / position.entry_price_usd


def _ticker(value: str) -> str:
    return value.strip().upper()


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _rate_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"
