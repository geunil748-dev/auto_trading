from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any

from trading_bot.models import (
    BotLog,
    BuyIntent,
    CandidateEvaluation,
    FillRecord,
    SellIntent,
    TradeRecord,
    TradingEvent,
)
from trading_bot.trading_date import current_trade_date


SENSITIVE_KEYWORDS = (
    "token",
    "secret",
    "app_key",
    "appkey",
    "appsecret",
    "approval",
    "account_no",
    "accountno",
    "cano",
    "acnt_prdt_cd",
    "password",
    "passwd",
    "dsn",
    "bearer",
    "chat_id",
    "chatid",
)


def sanitize_event_details(details: Any) -> Any:
    if isinstance(details, Mapping):
        return {
            str(key): (
                "<redacted>"
                if _is_sensitive_key(str(key))
                else sanitize_event_details(value)
            )
            for key, value in details.items()
        }
    if isinstance(details, list):
        return [sanitize_event_details(item) for item in details]
    if isinstance(details, tuple):
        return [sanitize_event_details(item) for item in details]
    return details


def record_trading_event(
    repository: object | None,
    event: TradingEvent,
    *,
    fallback_bot_log: bool = False,
) -> bool:
    """Best-effort append-only event save.

    The trading flow must keep running even if the analytical event table is
    temporarily unavailable.
    """
    if repository is None:
        return False
    safe_event = _sanitized_event(event)
    saved = False
    if hasattr(repository, "save_trading_events"):
        try:
            repository.save_trading_events([safe_event])
            saved = True
        except Exception as exc:
            _safe_save_log(
                repository,
                BotLog(
                    "WARNING",
                    "trading_event_log",
                    f"TRADING_EVENT_LOG_SAVE_FAILED: {type(exc).__name__}",
                    symbol=safe_event.ticker or "",
                    reject_reason="TRADING_EVENT_LOG_SAVE_FAILED",
                ),
            )
    if fallback_bot_log:
        _safe_save_log(repository, _event_to_bot_log(safe_event))
    return saved


def record_candidate_evaluation_event(
    repository: object | None,
    evaluation: CandidateEvaluation,
    *,
    fallback_bot_log: bool = False,
) -> bool:
    reason = evaluation.buy_block_reason or evaluation.final_decision or ""
    event_type = "BUY_ALLOWED" if evaluation.buy_allowed else "BUY_BLOCKED"
    details = {
        "buy_block_reasons": _json_or_text(evaluation.buy_block_reasons),
        "condition_result": _json_or_text(evaluation.condition_result_json),
        "hard_filter_failed_count": evaluation.hard_filter_failed_count,
        "soft_condition_failed_count": evaluation.soft_condition_failed_count,
        "source": evaluation.source,
    }
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=evaluation.evaluation_time,
            trade_date=evaluation.trading_date,
            run_id=evaluation.run_id,
            ticker=evaluation.symbol,
            ticker_name=evaluation.symbol_name,
            side="BUY",
            stage="ENTRY_PLANNER",
            event_type=event_type,
            severity="INFO" if evaluation.buy_allowed else "WARNING",
            decision="BUY_ALLOWED" if evaluation.buy_allowed else reason,
            reason_code=None if evaluation.buy_allowed else reason,
            is_blocking=not evaluation.buy_allowed,
            is_final_decision=True,
            order_submitted=evaluation.order_submitted,
            buy_allowed=evaluation.buy_allowed,
            price_usd=evaluation.current_price,
            actual_value=evaluation.final_score,
            threshold_value=evaluation.min_selection_score,
            candidate_source=evaluation.source,
            message=f"candidate_evaluated symbol={evaluation.symbol} decision={event_type}",
            details_json=details,
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_buy_not_submitted(
    repository: object | None,
    *,
    ticker: str,
    trade_date: date | None = None,
    reason_code: str,
    stage: str = "INTRADAY_RECHECK",
    source: str | None = None,
    run_id: str | None = None,
    order_id: str | None = None,
    actual_value: float | None = None,
    threshold_value: float | None = None,
    details: Mapping[str, Any] | None = None,
    candidate_source: str | None = None,
    ranking_selection_mode: str | None = None,
    fallback_bot_log: bool = False,
    update_candidate_evaluation: bool = True,
) -> bool:
    target_date = trade_date or current_trade_date()
    if update_candidate_evaluation:
        _safe_mark_candidate_not_submitted(repository, ticker, target_date, reason_code)
    event_details = dict(details or {})
    event_details.update(
        {
            "reason_family": "NO_ORDER" if reason_code.startswith("NO_ORDER_") else "BUY_BLOCK",
            "no_order_reason": reason_code if reason_code.startswith("NO_ORDER_") else None,
            "source": source,
        }
    )
    event_saved = record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            run_id=run_id,
            correlation_id=_correlation_id(target_date, ticker, run_id),
            order_id=order_id,
            ticker=ticker,
            side="BUY",
            stage=stage,
            event_type="BUY_NOT_SUBMITTED",
            severity="WARNING",
            decision=reason_code,
            reason_code=reason_code,
            is_blocking=True,
            is_final_decision=True,
            order_submitted=False,
            buy_allowed=False,
            actual_value=actual_value,
            threshold_value=threshold_value,
            candidate_source=candidate_source or source,
            ranking_selection_mode=ranking_selection_mode,
            message=f"candidate_order_not_submitted symbol={ticker} reason={reason_code}",
            details_json=event_details,
        ),
        fallback_bot_log=False,
    )
    if fallback_bot_log:
        _safe_save_log(
            repository,
            BotLog(
                "INFO",
                "candidate_evaluation",
                f"candidate_order_not_submitted symbol={ticker} reason={reason_code}",
                symbol=ticker,
                reject_reason=reason_code,
                actual_value=actual_value,
                threshold_value=threshold_value,
            ),
        )
    return event_saved


def record_order_protection_blocked(
    repository: object | None,
    intent: BuyIntent,
    protection_log: BotLog,
    *,
    trade_date: date | None = None,
    blocking: bool = True,
    fallback_bot_log: bool = False,
) -> bool:
    target_date = trade_date or current_trade_date()
    reason = protection_log.reject_reason or "ORDER_PROTECTION_BLOCKED"
    if blocking:
        _safe_mark_candidate_not_submitted(repository, intent.ticker, target_date, reason)
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            correlation_id=_correlation_id(target_date, intent.ticker, None),
            ticker=intent.ticker,
            side="BUY",
            stage="ORDER_PROTECTION",
            event_type="ORDER_PROTECTION_BLOCKED",
            severity=protection_log.level or "WARNING",
            decision=reason,
            reason_code=reason,
            is_blocking=blocking,
            is_final_decision=blocking,
            order_submitted=False if blocking else None,
            buy_allowed=False if blocking else None,
            quantity=intent.quantity,
            price_usd=intent.limit_price_usd,
            order_value_usd=intent.order_value_usd,
            actual_value=protection_log.actual_value,
            threshold_value=protection_log.threshold_value,
            message=protection_log.message,
            details_json={"entry_reason": intent.entry_reason},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_order_submit_failed(
    repository: object | None,
    intent: BuyIntent | SellIntent,
    *,
    trade_date: date | None = None,
    side: str,
    reason_code: str,
    severity: str = "ERROR",
    attempt: int | None = None,
    max_retries: int | None = None,
    message: str | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    target_date = trade_date or current_trade_date()
    is_final = reason_code == "ORDER_FAILED"
    if side.upper() == "BUY" and is_final:
        _safe_mark_candidate_not_submitted(repository, intent.ticker, target_date, reason_code)
    event_type = "ORDER_RETRY" if reason_code == "RETRY" else "ORDER_SUBMIT_FAILED"
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            correlation_id=_correlation_id(target_date, intent.ticker, None),
            ticker=intent.ticker,
            side=side.upper(),
            stage="ORDER_SUBMISSION" if side.upper() == "BUY" else "SELL_EXECUTION",
            event_type=event_type,
            severity=severity,
            decision=reason_code,
            reason_code=reason_code,
            is_blocking=is_final,
            is_final_decision=is_final,
            order_submitted=False if is_final else None,
            quantity=intent.quantity,
            price_usd=intent.limit_price_usd,
            order_value_usd=getattr(intent, "order_value_usd", None),
            actual_value=float(attempt) if attempt is not None else None,
            threshold_value=float(max_retries) if max_retries is not None else None,
            message=message or f"order_submit_failed symbol={intent.ticker} reason={reason_code}",
            details_json={"attempt": attempt, "max_retries": max_retries},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_order_submitted(
    repository: object | None,
    intent: BuyIntent,
    *,
    trade_date: date | None = None,
    order_id: str | None = None,
    response: Mapping[str, Any] | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    target_date = trade_date or current_trade_date()
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            correlation_id=_correlation_id(target_date, intent.ticker, None),
            order_id=order_id,
            order_no=order_id,
            ticker=intent.ticker,
            side="BUY",
            stage="ORDER_SUBMISSION",
            event_type="ORDER_SUBMIT_SUCCEEDED",
            severity="INFO",
            decision="ORDER_SUBMIT_SUCCEEDED",
            order_submitted=True,
            buy_allowed=True,
            quantity=intent.quantity,
            price_usd=intent.limit_price_usd,
            order_value_usd=intent.order_value_usd,
            message=f"order_submit_succeeded symbol={intent.ticker}",
            details_json={"response_keys": sorted(str(key) for key in (response or {}).keys())},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_exit_signal(
    repository: object | None,
    intent: SellIntent,
    *,
    trade_date: date | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    target_date = trade_date or current_trade_date()
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            correlation_id=_correlation_id(target_date, intent.ticker, None),
            ticker=intent.ticker,
            side="SELL",
            stage="EXIT_PLANNER",
            event_type="EXIT_SIGNAL",
            severity="INFO",
            decision=intent.exit_reason,
            reason_code=intent.exit_reason,
            sell_allowed=True,
            quantity=intent.quantity,
            price_usd=intent.limit_price_usd,
            message=f"exit_signal symbol={intent.ticker} reason={intent.exit_reason}",
            details_json={"entry_price_usd": intent.entry_price_usd},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_sell_order_submitted(
    repository: object | None,
    intent: SellIntent,
    *,
    trade_date: date | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    target_date = trade_date or current_trade_date()
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=target_date,
            correlation_id=_correlation_id(target_date, intent.ticker, None),
            ticker=intent.ticker,
            side="SELL",
            stage="SELL_EXECUTION",
            event_type="SELL_ORDER_SUBMITTED",
            severity="INFO",
            decision="SELL_ORDER_SUBMITTED",
            order_submitted=True,
            sell_allowed=True,
            quantity=intent.quantity,
            price_usd=intent.limit_price_usd,
            message=f"sell_order_submitted symbol={intent.ticker} reason={intent.exit_reason}",
            details_json={"exit_reason": intent.exit_reason},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_notification_event(
    repository: object | None,
    *,
    event_type: str,
    severity: str = "INFO",
    reason_code: str | None = None,
    ticker: str | None = None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=current_trade_date(),
            ticker=ticker,
            stage="NOTIFICATION",
            event_type=event_type,
            severity=severity,
            decision=event_type,
            reason_code=reason_code or event_type,
            is_blocking=False,
            message=message or event_type,
            details_json=dict(details or {}),
        ),
        fallback_bot_log=fallback_bot_log,
    )


def record_fill_saved_event(
    repository: object | None,
    record: FillRecord,
    *,
    fallback_bot_log: bool = False,
) -> bool:
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=record.trade_date,
            order_no=record.order_no or None,
            ticker=record.ticker,
            ticker_name=record.ticker_name,
            side=record.side.upper(),
            stage="ORDER_FILL",
            event_type="FILL_SAVED",
            severity="INFO",
            decision="FILL_SAVED",
            quantity=record.quantity,
            price_usd=record.fill_price_usd,
            order_value_usd=record.fill_amount_usd,
            profit_rate=record.profit_rate,
            message=f"fill_saved symbol={record.ticker} side={record.side}",
            details_json={"fill_time": record.fill_time, "profit_usd": record.profit_usd},
        ),
        fallback_bot_log=fallback_bot_log,
    )


def _sanitized_event(event: TradingEvent) -> TradingEvent:
    details = event.details_json
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {"text": details}
    safe_details = sanitize_event_details(_details_with_correlation(event, details))
    return replace(
        event,
        correlation_id=event.correlation_id or _event_correlation_id(event),
        app_mode=event.app_mode or _app_mode(),
        details_json=safe_details if safe_details not in ({}, [], None) else None,
    )


def record_order_reconciliation(
    repository: object | None,
    *,
    trade_date: date,
    side: str,
    planned: Iterable[BuyIntent | SellIntent],
    trades: Iterable[TradeRecord],
    fallback_bot_log: bool = False,
) -> None:
    planned_items = list(planned)
    trade_items = list(trades)
    submitted = {item.ticker.upper() for item in trade_items}
    for intent in planned_items:
        ticker = intent.ticker.upper()
        matched = ticker in submitted
        reason = (
            "ORDER_RECONCILIATION_MATCHED"
            if matched
            else "ORDER_RECONCILIATION_MISSING_TRADE_RECORD"
        )
        record_trading_event(
            repository,
            TradingEvent(
                event_time=_utcnow(),
                trade_date=trade_date,
                ticker=ticker,
                side=side.upper(),
                stage="ORDER_SUBMISSION" if side.upper() == "BUY" else "SELL_EXECUTION",
                event_type=reason,
                severity="INFO" if matched else "WARNING",
                decision=reason,
                reason_code=reason,
                is_blocking=not matched,
                is_final_decision=not matched,
                order_submitted=matched,
                quantity=intent.quantity,
                price_usd=intent.limit_price_usd,
                order_value_usd=getattr(intent, "order_value_usd", None),
                message=f"order_reconciliation symbol={ticker} matched={matched}",
                details_json={
                    "planned_count": len(planned_items),
                    "trade_record_count": len(trade_items),
                    "submitted_tickers": sorted(submitted),
                },
            ),
            fallback_bot_log=fallback_bot_log,
        )


def record_data_quality_event(
    repository: object | None,
    *,
    reason_code: str,
    stage: str = "MONITOR",
    severity: str = "WARNING",
    ticker: str | None = None,
    trade_date: date | None = None,
    message: str | None = None,
    details: Mapping[str, Any] | None = None,
    fallback_bot_log: bool = False,
) -> bool:
    return record_trading_event(
        repository,
        TradingEvent(
            event_time=_utcnow(),
            trade_date=trade_date or current_trade_date(),
            ticker=ticker,
            stage=stage,
            event_type="DATA_QUALITY_EVENT",
            severity=severity,
            decision=reason_code,
            reason_code=reason_code,
            is_blocking=False,
            message=message or reason_code,
            details_json=dict(details or {}),
        ),
        fallback_bot_log=fallback_bot_log,
    )


def _details_with_correlation(event: TradingEvent, details: Any) -> dict[str, Any]:
    if isinstance(details, Mapping):
        result = dict(details)
    elif details in (None, "", [], {}):
        result = {}
    else:
        result = {"value": details}
    result["correlation"] = {
        "correlation_id": event.correlation_id or _event_correlation_id(event),
        "flow_key": _flow_key(event),
        "ticker_day_key": _ticker_day_key(event),
        "order_key": event.order_no or event.order_id or None,
        "fill_key": _fill_key(event),
        "run_id": event.run_id,
        "stage": event.stage,
        "event_type": event.event_type,
    }
    return result


def _event_correlation_id(event: TradingEvent) -> str | None:
    trade_date = event.trade_date or _date_from_event_time(event.event_time)
    ticker = _ticker(event.ticker)
    if not trade_date or not ticker:
        return None
    return _correlation_id(trade_date, ticker, event.run_id)


def _flow_key(event: TradingEvent) -> str | None:
    trade_date = event.trade_date or _date_from_event_time(event.event_time)
    ticker = _ticker(event.ticker)
    if not trade_date or not ticker:
        return None
    return f"{trade_date.isoformat()}:{ticker}"


def _ticker_day_key(event: TradingEvent) -> str | None:
    return _flow_key(event)


def _fill_key(event: TradingEvent) -> str | None:
    trade_date = event.trade_date or _date_from_event_time(event.event_time)
    ticker = _ticker(event.ticker)
    side = (event.side or "").upper()
    if not trade_date or not ticker or not side:
        return None
    pieces = [
        trade_date.isoformat(),
        ticker,
        side,
        str(event.quantity or ""),
        "" if event.price_usd is None else f"{float(event.price_usd):.6f}",
        event.order_no or event.order_id or "",
    ]
    return ":".join(pieces)


def _event_to_bot_log(event: TradingEvent) -> BotLog:
    return BotLog(
        event.severity or "INFO",
        "trading_event",
        event.message
        or f"{event.stage}/{event.event_type}: {event.ticker or ''} {event.reason_code or ''}",
        symbol=event.ticker or "",
        name=event.ticker_name or "",
        reject_reason=event.reason_code or event.decision or event.event_type,
        actual_value=event.actual_value,
        threshold_value=event.threshold_value,
    )


def _safe_mark_candidate_not_submitted(
    repository: object | None,
    ticker: str,
    trade_date: date,
    reason: str,
) -> None:
    if repository is None or not hasattr(repository, "mark_candidate_evaluation_order_not_submitted"):
        return
    try:
        repository.mark_candidate_evaluation_order_not_submitted(ticker, trade_date, reason)
    except Exception as exc:
        _safe_save_log(
            repository,
            BotLog(
                "WARNING",
                "candidate_evaluation",
                f"CANDIDATE_NO_ORDER_REASON_SAVE_FAILED: {type(exc).__name__}",
                symbol=ticker,
                reject_reason="CANDIDATE_NO_ORDER_REASON_SAVE_FAILED",
            ),
        )


def _safe_save_log(repository: object | None, log: BotLog) -> None:
    if repository is None or not hasattr(repository, "save_log"):
        return
    try:
        repository.save_log(log)
    except Exception:
        pass


def _json_or_text(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return any(keyword in normalized for keyword in SENSITIVE_KEYWORDS)


def _ticker(value: str | None) -> str:
    return (value or "").strip().upper()


def _date_from_event_time(value: datetime | None) -> date | None:
    if value is None:
        return None
    return value.date()


def _correlation_id(trade_date: date, ticker: str, run_id: str | None) -> str:
    pieces = [trade_date.isoformat(), ticker.upper()]
    if run_id:
        pieces.append(str(run_id))
    return ":".join(pieces)


def _app_mode() -> str | None:
    return os.getenv("APP_MODE", "").strip() or None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
