from __future__ import annotations

from datetime import date

from tools.export_strategy_review import (
    candidate_orders_sql,
    export_sheets,
    pnl_by_exit_reason_sql,
    summary_reconciliation_sql,
)


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
