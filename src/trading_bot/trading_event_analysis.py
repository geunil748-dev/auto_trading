from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date, datetime, timezone
from typing import Any

from trading_bot.database import pyodbc_connect_factory


EVENT_COLUMNS = (
    "event_time",
    "trade_date",
    "mode",
    "app_mode",
    "run_id",
    "correlation_id",
    "order_id",
    "order_no",
    "ticker",
    "ticker_name",
    "side",
    "stage",
    "event_type",
    "severity",
    "decision",
    "reason_code",
    "reason_label",
    "is_blocking",
    "is_final_decision",
    "order_submitted",
    "buy_allowed",
    "sell_allowed",
    "quantity",
    "price_usd",
    "order_value_usd",
    "actual_value",
    "threshold_value",
    "profit_rate",
    "candidate_source",
    "ranking_selection_mode",
    "strategy_version",
    "settings_snapshot_hash",
    "message",
    "details_json",
)


def load_trading_events_from_mssql(
    *,
    date_from: date | None,
    date_to: date | None,
    ticker: str | None = None,
    event_type: str | None = None,
    reason_code: str | None = None,
    connect_factory: Callable[[], Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    connect = connect_factory or pyodbc_connect_factory()
    ticker_filter = (ticker or "").strip().upper()
    event_type_filter = (event_type or "").strip().upper()
    reason_code_filter = (reason_code or "").strip().upper()
    try:
        with closing(connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(
                """
                SELECT event_time, trade_date, mode, app_mode, run_id, correlation_id,
                       order_id, order_no, ticker, ticker_name, side, stage, event_type,
                       severity, decision, reason_code, reason_label, is_blocking,
                       is_final_decision, order_submitted, buy_allowed, sell_allowed,
                       quantity, price_usd, order_value_usd, actual_value,
                       threshold_value, profit_rate, candidate_source,
                       ranking_selection_mode, strategy_version, settings_snapshot_hash,
                       message, details_json
                FROM trading_event_log
                WHERE (? IS NULL OR trade_date >= ?)
                  AND (? IS NULL OR trade_date <= ?)
                  AND (? = '' OR UPPER(ticker) = ?)
                  AND (? = '' OR UPPER(event_type) = ?)
                  AND (? = '' OR UPPER(reason_code) = ?)
                ORDER BY event_time ASC, id ASC
                """,
                (
                    date_from,
                    date_from,
                    date_to,
                    date_to,
                    ticker_filter,
                    ticker_filter,
                    event_type_filter,
                    event_type_filter,
                    reason_code_filter,
                    reason_code_filter,
                ),
            )
            rows = list(cursor.fetchall())
    except Exception as exc:
        return [], [f"trading_event_log query failed: {type(exc).__name__}"]
    return [_event_row(row) for row in rows], []


def analyze_trading_events(
    rows: Iterable[dict[str, Any]],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    ticker: str | None = None,
    event_type: str | None = None,
    reason_code: str | None = None,
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    items = list(rows)
    summary = {
        "eventCount": len(items),
        "blockingEventCount": sum(1 for item in items if _bool(item.get("is_blocking"))),
        "buyBlockedCount": _event_count(items, "BUY_BLOCKED") + _event_count(items, "BUY_NOT_SUBMITTED"),
        "orderProtectionBlockedCount": _event_count(items, "ORDER_PROTECTION_BLOCKED"),
        "orderFailedCount": _reason_count(items, "ORDER_FAILED") + _reason_count(items, "API_ERROR"),
        "sellSignalCount": _event_count(items, "EXIT_SIGNAL"),
        "notificationFailedCount": sum(
            1
            for item in items
            if _text(item.get("stage")).upper() == "NOTIFICATION"
            and "FAILED" in _text(item.get("event_type")).upper()
        ),
    }
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "dateFrom": date_from.isoformat() if date_from else None,
        "dateTo": date_to.isoformat() if date_to else None,
        "filters": {
            "ticker": ticker,
            "eventType": event_type,
            "reasonCode": reason_code,
        },
        "summary": summary,
        "byStage": _counter(items, "stage"),
        "byEventType": _counter(items, "event_type"),
        "byReasonCode": _counter(items, "reason_code"),
        "byTicker": _counter(items, "ticker"),
        "byCorrelationId": _counter(items, "correlation_id"),
        "byCandidateSource": _counter(items, "candidate_source"),
        "byRankingSelectionMode": _counter(items, "ranking_selection_mode"),
        "events": items,
        "warnings": list(warnings),
    }


def render_trading_events_text(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "통합 매매 이벤트 분석",
        "",
        f"기간: {payload.get('dateFrom') or '-'} ~ {payload.get('dateTo') or '-'}",
        f"전체 이벤트 수: {summary.get('eventCount', 0)}",
        f"차단 이벤트 수: {summary.get('blockingEventCount', 0)}",
        f"매수 차단/미주문: {summary.get('buyBlockedCount', 0)}",
        f"주문보호 차단: {summary.get('orderProtectionBlockedCount', 0)}",
        f"주문 실패/API 오류: {summary.get('orderFailedCount', 0)}",
        f"매도 신호: {summary.get('sellSignalCount', 0)}",
        f"알림 실패: {summary.get('notificationFailedCount', 0)}",
        "",
        "stage별 이벤트 수",
        *_top_lines(payload.get("byStage", {}), limit=20),
        "",
        "reason_code 상위 10개",
        *_top_lines(payload.get("byReasonCode", {}), limit=10),
        "",
        "ticker별 blocking 이벤트 상위 10개",
        *_blocking_ticker_lines(payload),
        "",
        "BUY_NOT_SUBMITTED 사유별 카운트",
        *_event_reason_lines(payload, "BUY_NOT_SUBMITTED"),
        "",
        "ORDER_PROTECTION_BLOCKED 사유별 카운트",
        *_event_reason_lines(payload, "ORDER_PROTECTION_BLOCKED"),
        "",
        "ORDER_FAILED/API_ERROR 카운트",
        f"- ORDER_FAILED: {_reason_count(payload.get('events', []), 'ORDER_FAILED')}",
        f"- API_ERROR: {_reason_count(payload.get('events', []), 'API_ERROR')}",
    ]
    warnings = payload.get("warnings") or []
    if warnings:
        lines.extend(["", "경고", *[f"- {item}" for item in warnings]])
    return "\n".join(lines)


def write_trading_events_output(payload: dict[str, Any], output_format: str = "json") -> str:
    if output_format == "text":
        return render_trading_events_text(payload)
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _event_row(row: Any) -> dict[str, Any]:
    return {
        column: _json_details(value) if column == "details_json" else value
        for column, value in zip(EVENT_COLUMNS, tuple(row), strict=False)
    }


def _counter(items: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(_text(item.get(field)) or "unknown" for item in items)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _event_count(items: Iterable[dict[str, Any]], event_type: str) -> int:
    expected = event_type.upper()
    return sum(1 for item in items if _text(item.get("event_type")).upper() == expected)


def _reason_count(items: Iterable[dict[str, Any]], reason_code: str) -> int:
    expected = reason_code.upper()
    return sum(1 for item in items if _text(item.get("reason_code")).upper() == expected)


def _top_lines(counts: dict[str, int], *, limit: int) -> list[str]:
    if not counts:
        return ["- 없음"]
    return [f"- {key}: {value}" for key, value in list(counts.items())[:limit]]


def _blocking_ticker_lines(payload: dict[str, Any]) -> list[str]:
    events = [
        item
        for item in payload.get("events", [])
        if _bool(item.get("is_blocking"))
    ]
    return _top_lines(_counter(events, "ticker"), limit=10)


def _event_reason_lines(payload: dict[str, Any], event_type: str) -> list[str]:
    events = [
        item
        for item in payload.get("events", [])
        if _text(item.get("event_type")).upper() == event_type
    ]
    return _top_lines(_counter(events, "reason_code"), limit=20)


def _json_details(value: Any) -> Any:
    if not value:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return _text(value).lower() in {"1", "true", "yes"}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
