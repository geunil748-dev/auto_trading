from __future__ import annotations

from datetime import date, datetime, timezone

from tools.export_strategy_review import (
    SheetResult,
    _daily_activity_sheet,
    _trade_date_key,
    _safe_error,
    candidate_orders_sql,
    event_summary_sql,
    export_sheets,
    export_strategy_review_workbook_with_results,
    final_metrics,
    pnl_by_exit_reason_sql,
    sanitize_value,
    summary_reconciliation_sql,
)
from tools.strategy_review_sanitize import sanitize_value as moved_sanitize_value


def _columns() -> dict[str, list[str]]:
    return {
        "candidate_evaluations": [
            "id",
            "evaluation_time",
            "trading_date",
            "symbol",
            "source",
            "final_score",
            "selection_score",
            "soft_score_adjustment",
            "buy_allowed",
            "order_submitted",
            "final_decision",
            "buy_block_reason",
            "strategy_version",
            "settings_snapshot_hash",
        ],
        "fill_history": [
            "trade_date",
            "ticker",
            "side",
            "fill_time",
            "profit_usd",
            "profit_rate",
            "entry_reason",
            "entry_reason_detail",
        ],
        "trade_history": [
            "trade_date",
            "ticker",
            "order_type",
            "exit_reason",
            "last_fill_time",
            "created_at",
        ],
        "daily_run_summary": ["trade_date", "realized_profit_usd"],
        "daily_trade_summary_report": ["trade_date", "mode", "total_profit_usd"],
        "trading_event_log": [
            "trade_date",
            "event_type",
            "reason_code",
            "severity",
            "stage",
            "side",
            "is_blocking",
            "order_submitted",
            "buy_allowed",
        ],
        "bot_log": ["trade_date", "created_at", "message", "reject_reason"],
    }


def test_pnl_by_exit_reason_uses_fill_history_profit_with_trade_exit_reason() -> None:
    sql = pnl_by_exit_reason_sql(_columns())

    assert "FROM dbo.[fill_history] AS fills" in sql
    assert "OUTER APPLY" in sql
    assert "th.[exit_reason]" in sql
    assert "SUM(COALESCE(fills.[profit_usd], 0))" in sql


def test_candidate_orders_matches_pnl_only_for_submitted_or_buy_filled_candidates() -> None:
    sql = candidate_orders_sql(_columns())

    assert "buy_fills.buy_count" in sql
    assert "COALESCE(CONVERT(INT, ce_latest.[order_submitted]), 0) = 1" in sql
    assert "THEN COALESCE(fills.sell_count, 0)" in sql
    assert "ELSE 0" in sql


def test_summary_reconciliation_sql_compares_fill_and_summary_totals() -> None:
    sql = summary_reconciliation_sql(_columns())

    assert "fill_history_sell_profit_usd" in sql
    assert "daily_run_realized_profit_usd" in sql
    assert "trade_summary_profit_usd" in sql
    assert "fill_vs_daily_run_diff" in sql
    assert "fill_vs_trade_summary_diff" in sql


def test_sanitize_helpers_remain_reexported_from_export_module() -> None:
    assert sanitize_value is moved_sanitize_value
    assert sanitize_value("API_KEY=secret token") == "API_KEY=<redacted> token"
    assert "secret" not in _safe_error("DB_PASSWORD=secret")


def test_export_sheets_includes_reconciliation_sheet(monkeypatch) -> None:
    names = []

    def fake_query_raw_sheet(connection, columns, name, sql, params, out_columns):
        names.append(name)
        return object()

    monkeypatch.setattr(
        "tools.export_strategy_review.query_raw_sheet",
        fake_query_raw_sheet,
    )
    monkeypatch.setattr(
        "tools.export_strategy_review.raw_table_sheet",
        lambda *args, **kwargs: object(),
    )

    list(export_sheets(None, _columns(), date(2026, 6, 1), date(2026, 6, 29), False))

    assert "summary_reconciliation" in names


def test_export_strategy_review_workbook_with_results_excludes_legacy_bot_log_by_default(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, object] = {}

    class FakeConnection:
        def close(self) -> None:
            pass

    def fake_export_sheets(
        connection,
        columns_by_table,
        date_from,
        date_to,
        include_real,
        include_legacy_bot_log=False,
    ):
        captured["include_legacy_bot_log"] = include_legacy_bot_log
        return [SheetResult("trading_event_log", [])]

    monkeypatch.setattr(
        "tools.export_strategy_review.pyodbc_connect_factory",
        lambda: lambda: FakeConnection(),
    )
    monkeypatch.setattr(
        "tools.export_strategy_review.load_columns",
        lambda connection, **kwargs: {},
    )
    monkeypatch.setattr(
        "tools.export_strategy_review.schema_columns_sheet",
        lambda connection, **kwargs: SheetResult("schema_columns", []),
    )
    monkeypatch.setattr("tools.export_strategy_review.export_sheets", fake_export_sheets)

    output, results, failures = export_strategy_review_workbook_with_results(
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 29),
        output=tmp_path / "strategy_review.xlsx",
    )

    assert output.exists()
    assert failures == []
    assert captured["include_legacy_bot_log"] is False
    assert "bot_log" not in {result.name for result in results}
    assert "legacy_bot_log" not in {result.name for result in results}


def test_export_sheets_excludes_legacy_bot_log_by_default(monkeypatch) -> None:
    raw_names = []

    def fake_query_raw_sheet(connection, columns, name, sql, params, out_columns):
        return SheetResult(name, [])

    def fake_raw_table_sheet(connection, columns, sheet_name, *args, **kwargs):
        raw_names.append(sheet_name)
        return SheetResult(sheet_name, [])

    monkeypatch.setattr("tools.export_strategy_review.query_raw_sheet", fake_query_raw_sheet)
    monkeypatch.setattr("tools.export_strategy_review.raw_table_sheet", fake_raw_table_sheet)

    list(export_sheets(None, _columns(), date(2026, 6, 1), date(2026, 6, 29), False))

    assert "bot_log" not in raw_names
    assert "legacy_bot_log" not in raw_names


def test_export_sheets_includes_legacy_bot_log_only_when_requested(monkeypatch) -> None:
    raw_names = []

    def fake_query_raw_sheet(connection, columns, name, sql, params, out_columns):
        return SheetResult(name, [])

    def fake_raw_table_sheet(connection, columns, sheet_name, *args, **kwargs):
        raw_names.append(sheet_name)
        return SheetResult(sheet_name, [])

    monkeypatch.setattr("tools.export_strategy_review.query_raw_sheet", fake_query_raw_sheet)
    monkeypatch.setattr("tools.export_strategy_review.raw_table_sheet", fake_raw_table_sheet)

    list(
        export_sheets(
            None,
            _columns(),
            date(2026, 6, 1),
            date(2026, 6, 29),
            False,
            include_legacy_bot_log=True,
        )
    )

    assert "legacy_bot_log" in raw_names
    assert "bot_log" not in raw_names


def test_event_summary_sql_uses_trading_event_log_only() -> None:
    sql = event_summary_sql(_columns())

    assert "FROM dbo.[trading_event_log]" in sql
    assert "bot_log" not in sql.lower()


def test_trade_date_key_normalizes_supported_values_without_timezone_day_shift() -> None:
    assert _trade_date_key(date(2026, 7, 6)) == "2026-07-06"
    assert _trade_date_key(datetime(2026, 7, 6, 23, 30)) == "2026-07-06"
    assert _trade_date_key(datetime(2026, 7, 6, 23, 30, tzinfo=timezone.utc)) == "2026-07-06"
    assert _trade_date_key("2026-07-06 00:00:00 UTC") == "2026-07-06"


def test_final_metrics_counts_orders_fills_and_trades_by_normalized_trade_date() -> None:
    results = [
            SheetResult(
                "order_snapshot",
                [{"trade_date": value} for value in (
                    date(2026, 7, 6),
                    datetime(2026, 7, 6, 1),
                    "2026-07-06",
                    "2026-07-06 23:59:59",
                )],
            ),
            SheetResult(
                "fill_history",
                [{"trade_date": "2026-07-06"}, {"trade_date": datetime(2026, 7, 6, 2)}],
            ),
            SheetResult(
                "trade_history",
                [{"trade_date": "2026-07-06"}, {"trade_date": date(2026, 7, 6)}, {"trade_date": datetime(2026, 7, 6, 3)}],
            ),
        ]
    metrics = final_metrics(results)

    assert metrics["daily_activity_counts"]["2026-07-06"] == {
        "orders": 4,
        "fills": 2,
        "trades": 3,
    }
    assert _daily_activity_sheet(results).rows == [
        {"trade_date": "2026-07-06", "orders": 4, "fills": 2, "trades": 3}
    ]
