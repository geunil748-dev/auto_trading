from __future__ import annotations

from copy import deepcopy
from datetime import date
from zipfile import ZipFile

import pytest

from tools.export_strategy_review import (
    NORMALIZED_SHEET_NAMES,
    SheetResult,
    SimpleXlsxWriter,
    _assert_select_only,
    _normalized_sheet_results,
    _safe_error,
    candidate_orders_sql,
    event_summary_sql,
    export_sheets,
    fill_history_dedup_sql,
    final_metrics,
    pnl_by_day_sql,
    pnl_by_exit_reason_sql,
    pnl_by_score_bucket_sql,
    pnl_by_source_sql,
    pnl_by_ticker_sql,
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
            "id",
            "trade_date",
            "ticker",
            "side",
            "fill_time",
            "fill_price",
            "fill_amount",
            "quantity",
            "order_no",
            "is_mock",
            "created_at",
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
        "order_snapshot": [
            "trade_date",
            "ticker",
            "side",
            "quantity",
            "unfilled_quantity",
            "order_no",
            "is_mock",
        ],
        "trading_event_log": [
            "trade_date",
            "event_type",
            "reason_code",
            "severity",
        ],
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
    assert "N'매수'" in sql
    assert "N'매도'" in sql
    mojibake_buy = "".join(chr(codepoint) for codepoint in (0xF9CD, 0x317C, 0xB2D4))
    mojibake_sell = "".join(chr(codepoint) for codepoint in (0xF9CD, 0x317B, 0xB8C4))
    assert mojibake_buy not in sql
    assert mojibake_sell not in sql


def test_fill_history_dedup_groups_by_order_instead_of_fill_snapshot() -> None:
    sql = fill_history_dedup_sql(_columns())
    group_by = sql.split("GROUP BY", maxsplit=1)[1].split("HAVING", maxsplit=1)[0]

    assert "[order_no]" in group_by
    assert "[is_mock]" in group_by
    assert "[fill_time]" not in group_by
    assert "[fill_price]" not in group_by
    assert "normalized_side" in sql


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
        return SheetResult(name, [])

    monkeypatch.setattr(
        "tools.export_strategy_review.query_raw_sheet",
        fake_query_raw_sheet,
    )
    monkeypatch.setattr(
        "tools.export_strategy_review.raw_table_sheet",
        lambda connection, columns, sheet_name, *args, **kwargs: SheetResult(sheet_name, []),
    )

    results = list(
        export_sheets(None, _columns(), date(2026, 6, 1), date(2026, 6, 29), False)
    )

    assert "summary_reconciliation" in names
    assert "candidate_orders_matched_raw" in names
    assert "fill_history_normalized" in [result.name for result in results]
    assert "summary_reconciliation_normalized" in [result.name for result in results]


def test_final_metrics_prefers_trusted_normalized_profit() -> None:
    metrics = final_metrics(
        [
            SheetResult(
                "fill_history",
                [
                    {"side": "SELL", "profit_usd": 10},
                    {"side": "매도", "profit_usd": 20},
                ],
            ),
            SheetResult(
                "fill_history_normalized",
                [
                    {
                        "normalized_side": "SELL",
                        "normalized_profit_usd": 12,
                        "raw_profit_usd_sum": 30,
                        "normalization_method": "LEGACY_CUMULATIVE_LATEST",
                        "normalization_confidence": "HIGH",
                        "is_mock": True,
                        "excluded_from_trusted_pnl": False,
                        "excluded_from_best_effort_pnl": False,
                    }
                ],
            ),
            SheetResult("fill_normalization_warnings", []),
            SheetResult("duplicate_suspects", []),
        ]
    )

    assert metrics["headline_pnl_basis"] == "TRUSTED_NORMALIZED"
    assert metrics["fill_history_sell_count"] == 1
    assert metrics["fill_history_sell_profit_usd"] == 12
    assert metrics["raw_sell_row_count"] == 2
    assert metrics["raw_profit_usd"] == 30
    assert metrics["normalized_pnl_by_mode"] == {
        "MOCK": {"sell_order_count": 1, "profit_usd": 12}
    }


def test_final_metrics_excludes_medium_confidence_from_trusted_headline() -> None:
    metrics = final_metrics(
        [
            SheetResult("fill_history", [{"side": "SELL", "profit_usd": 14}]),
            SheetResult(
                "fill_history_normalized",
                [
                    {
                        "normalized_side": "SELL",
                        "normalized_profit_usd": 14,
                        "normalization_method": "DELTA_ROWS_SUMMED",
                        "normalization_confidence": "MEDIUM",
                        "is_mock": True,
                        "excluded_from_trusted_pnl": False,
                        "excluded_from_best_effort_pnl": False,
                    }
                ],
            ),
            SheetResult("fill_normalization_warnings", []),
            SheetResult("duplicate_suspects", []),
        ]
    )

    assert metrics["headline_pnl_basis"] == "TRUSTED_NORMALIZED"
    assert metrics["normalized_sell_order_count"] == 0
    assert metrics["normalized_profit_usd"] == 0
    assert metrics["best_effort_sell_order_count"] == 1
    assert metrics["best_effort_profit_usd"] == 14
    assert metrics["normalized_pnl_by_mode"] == {}
    assert metrics["best_effort_pnl_by_mode"] == {
        "MOCK": {"sell_order_count": 1, "profit_usd": 14}
    }


def test_normalized_sheet_build_keeps_raw_fill_rows_unchanged() -> None:
    raw_rows = [
        {
            "id": 1,
            "trade_date": "2026-07-10",
            "ticker": "AAA",
            "side": "SELL",
            "quantity": 100,
            "fill_price": 10,
            "fill_amount": 1000,
            "profit_usd": -10,
            "order_no": "O1",
            "is_mock": True,
            "fill_time": "10:00:00",
            "created_at": "2026-07-10 10:00:01",
        },
        {
            "id": 2,
            "trade_date": "2026-07-10",
            "ticker": "AAA",
            "side": "SELL",
            "quantity": 150,
            "fill_price": 9.5,
            "fill_amount": 1425,
            "profit_usd": -75,
            "order_no": "O1",
            "is_mock": True,
            "fill_time": "10:00:00",
            "created_at": "2026-07-10 10:00:02",
        },
    ]
    original = deepcopy(raw_rows)
    raw_by_name = {
        "fill_history": SheetResult("fill_history", raw_rows),
        "order_snapshot": SheetResult(
            "order_snapshot",
            [
                {
                    "trade_date": "2026-07-10",
                    "ticker": "AAA",
                    "side": "SELL",
                    "order_no": "O1",
                    "is_mock": True,
                    "filled_qty": 150,
                }
            ],
        ),
    }

    results = list(
        _normalized_sheet_results(
            raw_by_name,
            SheetResult("candidate_orders_matched_raw", []),
        )
    )
    normalized = next(result for result in results if result.name == "fill_history_normalized")

    assert raw_rows == original
    assert len(normalized.rows) == 1
    assert normalized.rows[0]["source_id_list"] == "1,2"
    assert normalized.rows[0]["normalization_method"] == "LEGACY_CUMULATIVE_LATEST"


def test_candidate_mode_default_applies_only_to_mock_only_export() -> None:
    raw_by_name = {
        "fill_history": SheetResult(
            "fill_history",
            [
                {
                    "id": 1,
                    "trade_date": "2026-07-10",
                    "ticker": "AAA",
                    "side": "SELL",
                    "quantity": 1,
                    "fill_price": 10,
                    "fill_amount": 10,
                    "profit_usd": 2,
                    "order_no": "O1",
                    "is_mock": True,
                    "fill_time": "10:00:00",
                }
            ],
        )
    }
    candidates = SheetResult(
        "candidate_orders_matched_raw",
        [
            {
                "id": 1,
                "trading_date": "2026-07-10",
                "symbol": "AAA",
                "source": "ranked",
                "final_score": 55,
                "order_submitted": True,
            }
        ],
    )

    mock_results = list(_normalized_sheet_results(raw_by_name, candidates))
    mixed_results = list(
        _normalized_sheet_results(raw_by_name, candidates, include_real=True)
    )
    mock_candidate = next(
        result for result in mock_results if result.name == "candidate_orders_matched"
    ).rows[0]
    mixed_candidate = next(
        result for result in mixed_results if result.name == "candidate_orders_matched"
    ).rows[0]

    assert (mock_candidate["mode"], mock_candidate["trusted_sell_count"]) == ("MOCK", 1)
    assert mock_candidate["mode_match_method"] == "EXPORT_SCOPE_DEFAULT"
    assert (mixed_candidate["mode"], mixed_candidate["trusted_sell_count"]) == (
        "UNKNOWN",
        0,
    )
    assert mixed_candidate["mode_match_method"] == "UNKNOWN_NOT_ASSIGNED"


def test_normalized_sheets_fail_closed_when_raw_fill_query_failed() -> None:
    raw_by_name = {
        "fill_history": SheetResult(
            "fill_history",
            [],
            "ProgrammingError: missing column password=secret",
        )
    }

    results = list(
        _normalized_sheet_results(
            raw_by_name,
            SheetResult("candidate_orders_matched_raw", []),
        )
    )
    metrics = final_metrics([raw_by_name["fill_history"], *results])

    assert [result.name for result in results] == list(NORMALIZED_SHEET_NAMES)
    assert all(result.rows == [] for result in results)
    assert all(result.error and "fill_history unavailable" in result.error for result in results)
    assert all("secret" not in result.error for result in results)
    assert metrics["headline_pnl_basis"] == "RAW_FALLBACK"
    assert {
        "NORMALIZED_PNL_UNAVAILABLE_RAW_FALLBACK",
        "RAW_FILL_HISTORY_UNAVAILABLE",
    }.issubset(metrics["data_quality_warning_codes"])


def test_final_metrics_marks_explicit_raw_fallback_when_normalization_is_unavailable() -> None:
    metrics = final_metrics(
        [SheetResult("fill_history", [{"side": "S", "profit_usd": -5}])]
    )

    assert metrics["headline_pnl_basis"] == "RAW_FALLBACK"
    assert metrics["fill_history_sell_profit_usd"] == -5
    assert metrics["data_quality_warning"] is True
    assert "NORMALIZED_PNL_UNAVAILABLE_RAW_FALLBACK" in metrics[
        "data_quality_warning_codes"
    ]


def test_exporter_rejects_non_select_sql() -> None:
    _assert_select_only("SELECT * FROM dbo.fill_history")
    _assert_select_only("WITH rows AS (SELECT 1 AS id) SELECT * FROM rows")

    with pytest.raises(ValueError, match="read-only SELECT"):
        _assert_select_only("DELETE FROM dbo.fill_history")
    with pytest.raises(ValueError):
        _assert_select_only("SELECT 1; UPDATE dbo.fill_history SET quantity = 0")
    with pytest.raises(ValueError, match="non-SELECT SQL keyword"):
        _assert_select_only("SELECT * INTO dbo.fill_copy FROM dbo.fill_history")


def test_all_generated_analysis_sql_is_select_only() -> None:
    columns = _columns()
    statements = [
        fill_history_dedup_sql(columns),
        candidate_orders_sql(columns),
        event_summary_sql(columns),
        pnl_by_day_sql(columns),
        pnl_by_ticker_sql(columns),
        pnl_by_exit_reason_sql(columns),
        pnl_by_score_bucket_sql(columns),
        pnl_by_source_sql(columns),
        summary_reconciliation_sql(columns),
    ]

    for sql in statements:
        assert sql
        _assert_select_only(sql)


def test_xlsx_writer_formats_analysis_sheets_without_changing_rows(tmp_path) -> None:
    rows = [
        {
            "id": 1,
            "ticker": "AAA",
            "profit_usd": -10.5,
            "profit_rate": -0.01,
            "source_id_list": "1,2,3",
        }
    ]
    original = deepcopy(rows)
    output = tmp_path / "review.xlsx"
    writer = SimpleXlsxWriter()
    writer.add_sheet("fill_history_normalized", rows)
    writer.save(output)

    assert rows == original
    with ZipFile(output) as archive:
        styles = archive.read("xl/styles.xml").decode("utf-8")
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert 'rgb="FF1F4E78"' in styles
    assert '<cols><col ' in sheet
    assert '<autoFilter ref="A1:E2"/>' in sheet
    assert 'r="A1" s="1"' in sheet
    assert 'r="C2" s="2" t="n"><v>-10.5</v>' in sheet
    assert 'r="D2" s="3" t="n"><v>-0.01</v>' in sheet
