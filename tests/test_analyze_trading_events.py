from __future__ import annotations

from datetime import date, datetime

from trading_bot.trading_event_analysis import (
    analyze_trading_events,
    load_trading_events_from_mssql,
    render_trading_events_text,
)


class Cursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.calls = []

    def execute(self, sql: str, params) -> None:
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self.cursor_value = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_value

    def close(self) -> None:
        self.closed = True


def test_load_trading_events_from_mssql_uses_read_only_select() -> None:
    row = (
        datetime(2026, 6, 18, 1, 2, 3),
        date(2026, 6, 18),
        "mock",
        "test",
        "run-1",
        "corr-1",
        "order-1",
        "order-1",
        "AAA",
        "AAA Inc",
        "BUY",
        "ORDER_PROTECTION",
        "ORDER_PROTECTION_BLOCKED",
        "WARNING",
        "BID_ASK_SPREAD_TOO_WIDE",
        "BID_ASK_SPREAD_TOO_WIDE",
        None,
        1,
        1,
        0,
        0,
        None,
        10,
        12.5,
        125.0,
        1.2,
        1.0,
        None,
        "manual_buy_list",
        "composite",
        "v1",
        "hash",
        "blocked",
        '{"메모": "한글"}',
    )
    cursor = Cursor([row])
    connection = Connection(cursor)

    rows, warnings = load_trading_events_from_mssql(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 18),
        ticker="aaa",
        event_type="ORDER_PROTECTION_BLOCKED",
        reason_code="BID_ASK_SPREAD_TOO_WIDE",
        connect_factory=lambda: connection,
    )

    assert warnings == []
    assert rows[0]["ticker"] == "AAA"
    assert rows[0]["details_json"] == {"메모": "한글"}
    assert cursor.calls
    assert cursor.calls[0][0].lstrip().upper().startswith("SELECT")
    assert "FROM trading_event_log" in cursor.calls[0][0]
    assert cursor.calls[0][1][4:10] == (
        "AAA",
        "AAA",
        "ORDER_PROTECTION_BLOCKED",
        "ORDER_PROTECTION_BLOCKED",
        "BID_ASK_SPREAD_TOO_WIDE",
        "BID_ASK_SPREAD_TOO_WIDE",
    )
    assert connection.closed


def test_analyze_trading_events_summarizes_and_filters_text() -> None:
    rows = [
        {
            "ticker": "AAA",
            "stage": "INTRADAY_RECHECK",
            "event_type": "BUY_NOT_SUBMITTED",
            "reason_code": "NO_ORDER_UNFILLED_ORDER",
            "is_blocking": 1,
            "candidate_source": "auto",
            "ranking_selection_mode": "intersection",
        },
        {
            "ticker": "AAA",
            "stage": "ORDER_SUBMISSION",
            "event_type": "ORDER_SUBMIT_FAILED",
            "reason_code": "API_ERROR",
            "is_blocking": 0,
        },
        {
            "ticker": "BBB",
            "stage": "EXIT_PLANNER",
            "event_type": "EXIT_SIGNAL",
            "reason_code": "STOP_LOSS",
            "is_blocking": False,
        },
        {
            "ticker": "CCC",
            "stage": "NOTIFICATION",
            "event_type": "FILL_NOTIFICATION_FAILED",
            "reason_code": "FILL_NOTIFICATION_FAILED",
            "is_blocking": False,
        },
    ]

    payload = analyze_trading_events(
        rows,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 18),
        ticker="AAA",
        event_type="BUY_NOT_SUBMITTED",
        reason_code="NO_ORDER_UNFILLED_ORDER",
    )
    text = render_trading_events_text(payload)

    assert payload["summary"]["eventCount"] == 4
    assert payload["summary"]["blockingEventCount"] == 1
    assert payload["summary"]["buyBlockedCount"] == 1
    assert payload["summary"]["orderFailedCount"] == 1
    assert payload["summary"]["sellSignalCount"] == 1
    assert payload["summary"]["notificationFailedCount"] == 1
    assert payload["byReasonCode"]["NO_ORDER_UNFILLED_ORDER"] == 1
    assert "통합 매매 이벤트 분석" in text
    assert "NO_ORDER_UNFILLED_ORDER" in text
