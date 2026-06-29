from __future__ import annotations

from datetime import datetime, timedelta

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, BuyIntent
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.trading_date import current_trade_date
from trading_bot.trading_event_logger import record_buy_not_submitted

NO_ORDER_RECENT_STOP_LOSS = "NO_ORDER_RECENT_STOP_LOSS"


def apply_stop_loss_entry_guards(
    intents: list[BuyIntent],
    repository,
    settings: TradingSettings,
) -> list[BuyIntent]:
    if not intents:
        return []
    stop_loss_count = consecutive_stop_loss_count(repository)
    if stop_loss_count >= settings.max_consecutive_stop_loss_count:
        repository.save_log(
            BotLog(
                "WARNING",
                "risk",
                "연속 손절 제한에 도달해 신규 매수를 중단했습니다.",
                reject_reason="CONSECUTIVE_STOP_LOSS_LIMIT",
                actual_value=float(stop_loss_count),
                threshold_value=float(settings.max_consecutive_stop_loss_count),
            )
        )
        for intent in intents:
            record_buy_not_submitted(
                repository,
                ticker=intent.ticker,
                trade_date=current_trade_date(),
                reason_code="CONSECUTIVE_STOP_LOSS_LIMIT",
                stage="RISK_GUARD",
                actual_value=float(stop_loss_count),
                threshold_value=float(settings.max_consecutive_stop_loss_count),
                details={"guard": "max_consecutive_stop_loss"},
                fallback_bot_log=False,
            )
        return []
    allowed: list[BuyIntent] = []
    for intent in intents:
        last_stop_loss = last_stop_loss_at(repository, intent.ticker)
        if last_stop_loss is not None:
            repository.save_log(
                BotLog(
                    "WARNING",
                    "risk",
                    f"당일 손절 이력이 있어 재진입을 차단했습니다: {intent.ticker}",
                    symbol=intent.ticker,
                    reject_reason=NO_ORDER_RECENT_STOP_LOSS,
                    actual_value=1.0,
                    threshold_value=0.0,
                )
            )
            record_buy_not_submitted(
                repository,
                ticker=intent.ticker,
                trade_date=current_trade_date(),
                reason_code=NO_ORDER_RECENT_STOP_LOSS,
                stage="RISK_GUARD",
                actual_value=1.0,
                threshold_value=0.0,
                details={"guard": "same_day_stop_loss"},
                fallback_bot_log=False,
            )
            continue
        if cooldown_active(last_stop_loss, settings.stop_loss_cooldown_minutes):
            repository.save_log(
                BotLog(
                    "WARNING",
                    "risk",
                    f"손절 후 쿨다운으로 신규 매수를 차단했습니다: {intent.ticker}",
                    symbol=intent.ticker,
                    reject_reason="STOP_LOSS_COOLDOWN",
                    actual_value=float(settings.stop_loss_cooldown_minutes),
                    threshold_value=float(settings.stop_loss_cooldown_minutes),
                )
            )
            record_buy_not_submitted(
                repository,
                ticker=intent.ticker,
                trade_date=current_trade_date(),
                reason_code="STOP_LOSS_COOLDOWN",
                stage="RISK_GUARD",
                actual_value=float(settings.stop_loss_cooldown_minutes),
                threshold_value=float(settings.stop_loss_cooldown_minutes),
                details={"guard": "stop_loss_cooldown"},
                fallback_bot_log=False,
            )
            continue
        allowed.append(intent)
    return allowed


def consecutive_stop_loss_count(repository) -> int:
    try:
        if hasattr(repository, "consecutive_stop_loss_count"):
            return int(repository.consecutive_stop_loss_count(current_trade_date()))
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "risk",
            f"STOP_LOSS_COUNT_LOOKUP_FAILED: {safe_exception_summary(exc)}",
            reject_reason="STOP_LOSS_COUNT_LOOKUP_FAILED",
        )
        return 0
    return 0


def last_stop_loss_at(repository, ticker: str):
    try:
        if hasattr(repository, "last_stop_loss_at"):
            return repository.last_stop_loss_at(current_trade_date(), ticker)
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "risk",
            f"STOP_LOSS_COOLDOWN_LOOKUP_FAILED: {safe_exception_summary(exc)}",
            symbol=ticker,
            reject_reason="STOP_LOSS_COOLDOWN_LOOKUP_FAILED",
        )
        return None
    return None


def cooldown_active(last_stop_loss_at_value, cooldown_minutes: int) -> bool:
    if last_stop_loss_at_value is None or cooldown_minutes <= 0:
        return False
    if isinstance(last_stop_loss_at_value, str):
        try:
            last_stop_loss_at_value = datetime.fromisoformat(last_stop_loss_at_value)
        except ValueError:
            return False
    now = (
        datetime.now(last_stop_loss_at_value.tzinfo)
        if last_stop_loss_at_value.tzinfo
        else datetime.now()
    )
    return now - last_stop_loss_at_value < timedelta(minutes=cooldown_minutes)


def saved_partial_take_profit_tickers(repository) -> set[str]:
    try:
        if hasattr(repository, "partial_take_profit_tickers"):
            return set(repository.partial_take_profit_tickers(current_trade_date()))
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "risk",
            f"PARTIAL_TAKE_PROFIT_LOOKUP_FAILED: {safe_exception_summary(exc)}",
            reject_reason="PARTIAL_TAKE_PROFIT_LOOKUP_FAILED",
        )
        return set()
    return set()
