from __future__ import annotations

import argparse
import math
import re
import sys
import zipfile
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trading_bot.database import pyodbc_connect_factory  # noqa: E402

TARGET_TABLES = (
    "fill_history",
    "trade_history",
    "daily_run_summary",
    "daily_trade_summary_report",
    "candidate_evaluations",
    "trading_event_log",
    "bot_log",
    "order_snapshot",
    "holding_snapshot",
    "account_snapshot",
    "entry_profit_snapshot",
)

DEFAULT_DATE_FROM = "2026-05-20"

SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[^\s,;\"'}]+"),
    re.compile(
        r"(?i)\b([A-Z_]*(TOKEN|SECRET|PASSWORD|API_KEY|APP_KEY|APPSECRET|"
        r"ACCOUNT_NO|ACCOUNT_PRODUCT|CANO|ACNT_PRDT_CD|DB_PASSWORD|DSN|"
        r"BEARER|CHAT_ID)[A-Z_]*)\s*[:=]\s*[^,\s;\"'}]+"
    ),
    re.compile(r"(?i)\b(authorization)\s*[:=]\s*[^,\s;\"'}]+"),
)


@dataclass
class SheetResult:
    name: str
    rows: list[dict[str, Any]]
    error: str = ""


class SimpleXlsxWriter:
    def __init__(self) -> None:
        self.sheets: list[tuple[str, list[list[Any]]]] = []

    def add_sheet(self, name: str, rows: list[dict[str, Any]]) -> None:
        sheet_name = _sheet_name(name, [item[0] for item in self.sheets])
        headers: list[str] = []
        for row in rows:
            for key in row:
                if key not in headers:
                    headers.append(key)
        values: list[list[Any]] = [headers] if headers else [["message"]]
        if rows:
            values.extend([[row.get(header) for header in headers] for row in rows])
        elif not headers:
            values.append(["no rows"])
        self.sheets.append((sheet_name, values))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types())
            archive.writestr("_rels/.rels", self._root_rels())
            archive.writestr("xl/workbook.xml", self._workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels())
            archive.writestr("xl/styles.xml", self._styles())
            for index, (_, rows) in enumerate(self.sheets, start=1):
                archive.writestr(
                    f"xl/worksheets/sheet{index}.xml",
                    self._worksheet(rows),
                )

    def _content_types(self) -> str:
        sheet_overrides = "\n".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(self.sheets) + 1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheet_overrides}
</Types>"""

    def _root_rels(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    def _workbook(self) -> str:
        sheets = "\n".join(
            f'<sheet name="{_xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(self.sheets, start=1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>{sheets}</sheets>
</workbook>"""

    def _workbook_rels(self) -> str:
        rels = "\n".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(self.sheets) + 1)
        )
        style_id = len(self.sheets) + 1
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels}
<Relationship Id="rId{style_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    def _styles(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>"""

    def _worksheet(self, rows: list[list[Any]]) -> str:
        worksheet_rows = "\n".join(
            f'<row r="{row_index}">'
            + "".join(
                _cell_xml(row_index, col_index, value)
                for col_index, value in enumerate(row, start=1)
            )
            + "</row>"
            for row_index, row in enumerate(rows[:1_048_576], start=1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetData>{worksheet_rows}</sheetData>
</worksheet>"""


def export_strategy_review_workbook(
    date_from: date | str = DEFAULT_DATE_FROM,
    date_to: date | str | None = None,
    output: Path | str | None = None,
    include_real: bool = False,
) -> Path:
    output_path, _, _ = export_strategy_review_workbook_with_results(
        date_from=date_from,
        date_to=date_to,
        output=output,
        include_real=include_real,
    )
    return output_path


def export_strategy_review_workbook_with_results(
    date_from: date | str = DEFAULT_DATE_FROM,
    date_to: date | str | None = None,
    output: Path | str | None = None,
    include_real: bool = False,
) -> tuple[Path, list[SheetResult], list[tuple[str, str]]]:
    return _create_strategy_review_workbook(
        date_from=date_from,
        date_to=date_to,
        output=output,
        include_real=include_real,
    )


def _create_strategy_review_workbook(
    *,
    date_from: date | str = DEFAULT_DATE_FROM,
    date_to: date | str | None = None,
    output: Path | str | None = None,
    include_real: bool = False,
) -> tuple[Path, list[SheetResult], list[tuple[str, str]]]:
    parsed_date_from = _coerce_date(date_from)
    parsed_date_to = _coerce_date(date_to) if date_to is not None else date.today()
    output_path = (
        Path(output)
        if output is not None
        else ROOT / "exports" / f"strategy_review_{parsed_date_to:%Y%m%d}.xlsx"
    )
    connect = pyodbc_connect_factory()
    results: list[SheetResult] = []
    failures: list[tuple[str, str]] = []
    with closing(connect()) as connection:
        columns_by_table = load_columns(connection)
        results.append(schema_columns_sheet(connection))
        for result in export_sheets(
            connection,
            columns_by_table,
            parsed_date_from,
            parsed_date_to,
            include_real,
        ):
            if result.error:
                failures.append((result.name, result.error))
            results.append(result)

    writer = SimpleXlsxWriter()
    for result in results:
        rows = result.rows if not result.error else [{"error": result.error}]
        writer.add_sheet(result.name, rows)
    writer.save(output_path)
    return output_path, results, failures


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    output, results, failures = _create_strategy_review_workbook(
        date_from=args.date_from,
        date_to=args.date_to if args.date_to else None,
        output=Path(args.output) if args.output else None,
        include_real=args.include_real,
    )

    metrics = final_metrics(results)
    print(f"output={output}")
    for result in results:
        print(f"sheet={result.name} rows={len(result.rows)} error={result.error or '-'}")
    print(f"duplicate_suspects={metrics['duplicate_suspects']}")
    print(f"fill_history_sell_count={metrics['fill_history_sell_count']}")
    print(f"fill_history_sell_profit_usd={metrics['fill_history_sell_profit_usd']:.2f}")
    print(f"daily_run_summary_realized_profit_usd={metrics['daily_run_summary_realized_profit_usd']:.2f}")
    print(f"trading_event_log_count={metrics['trading_event_log_count']}")
    print("event_summary_top10=")
    for item in metrics["event_summary_top10"]:
        print(
            f"  {item.get('event_type') or '-'} / {item.get('reason_code') or '-'}: "
            f"{item.get('count')}"
        )
    if failures:
        print("failures=")
        for sheet, error in failures:
            print(f"  {sheet}: {error}")
    return 0 if output.exists() else 1


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export strategy review workbook from MSSQL.")
    parser.add_argument("--date-from", default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", default=date.today().isoformat())
    parser.add_argument("--output", default="")
    parser.add_argument(
        "--include-real",
        action="store_true",
        help="Do not apply default is_mock=1 / mode=mock filters.",
    )
    return parser.parse_args(argv)


def export_sheets(
    connection: Any,
    columns_by_table: dict[str, list[str]],
    date_from: date,
    date_to: date,
    include_real: bool,
) -> Iterable[SheetResult]:
    raw_specs = [
        ("fill_history", "fill_history", "trade_date", FILL_HISTORY_COLUMNS, RAW_ORDERS["fill_history"]),
        ("trade_history", "trade_history", "trade_date", TRADE_HISTORY_COLUMNS, RAW_ORDERS["trade_history"]),
        ("order_snapshot", "order_snapshot", "trade_date", ORDER_SNAPSHOT_COLUMNS, RAW_ORDERS["order_snapshot"]),
        ("daily_run_summary", "daily_run_summary", "trade_date", DAILY_RUN_SUMMARY_COLUMNS, RAW_ORDERS["daily_run_summary"]),
        ("daily_trade_summary_report", "daily_trade_summary_report", "trade_date", DAILY_TRADE_SUMMARY_REPORT_COLUMNS, RAW_ORDERS["daily_trade_summary_report"]),
        ("candidate_evaluations", "candidate_evaluations", "trading_date", CANDIDATE_EVALUATION_COLUMNS, RAW_ORDERS["candidate_evaluations"]),
        ("trading_event_log", "trading_event_log", "trade_date", TRADING_EVENT_LOG_COLUMNS, RAW_ORDERS["trading_event_log"]),
        ("bot_log", "bot_log", "trade_date", BOT_LOG_COLUMNS, RAW_ORDERS["bot_log"]),
        ("holding_snapshot", "holding_snapshot", "trade_date", HOLDING_SNAPSHOT_COLUMNS, RAW_ORDERS["holding_snapshot"]),
        ("account_snapshot", "account_snapshot", "trade_date", ACCOUNT_SNAPSHOT_COLUMNS, RAW_ORDERS["account_snapshot"]),
        ("entry_profit_snapshot", "entry_profit_snapshot", "trade_date", ENTRY_PROFIT_SNAPSHOT_COLUMNS, RAW_ORDERS["entry_profit_snapshot"], True),
    ]
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "fill_history_dedup_check",
        fill_history_dedup_sql(columns_by_table),
        (date_from, date_to),
        DEDUP_COLUMNS,
    )
    for spec in raw_specs:
        include_rest = bool(spec[5]) if len(spec) > 5 else False
        yield raw_table_sheet(connection, columns_by_table, *spec[:5], date_from, date_to, include_real, include_rest)
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "candidate_orders_matched",
        candidate_orders_sql(columns_by_table),
        (
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
        ),
        CANDIDATE_ORDERS_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "event_summary",
        event_summary_sql(columns_by_table),
        (date_from, date_to),
        EVENT_SUMMARY_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "pnl_by_day",
        pnl_by_day_sql(columns_by_table),
        (date_from, date_to),
        PNL_BY_DAY_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "pnl_by_ticker",
        pnl_by_ticker_sql(columns_by_table),
        (date_from, date_to, date_from, date_to),
        PNL_BY_TICKER_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "pnl_by_exit_reason",
        pnl_by_exit_reason_sql(columns_by_table),
        (date_from, date_to),
        PNL_BY_EXIT_REASON_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "pnl_by_score_bucket",
        pnl_by_score_bucket_sql(columns_by_table),
        (
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
        ),
        PNL_BY_SCORE_BUCKET_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "pnl_by_source",
        pnl_by_source_sql(columns_by_table),
        (
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
            date_from,
            date_to,
        ),
        PNL_BY_SOURCE_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "summary_reconciliation",
        summary_reconciliation_sql(columns_by_table),
        (date_from, date_to, date_from, date_to, date_from, date_to),
        SUMMARY_RECONCILIATION_COLUMNS,
    )
    yield query_raw_sheet(
        connection,
        columns_by_table,
        "duplicate_suspects",
        fill_history_dedup_sql(columns_by_table),
        (date_from, date_to),
        DEDUP_COLUMNS,
    )


def load_columns(connection: Any) -> dict[str, list[str]]:
    placeholders = ", ".join("?" for _ in TARGET_TABLES)
    rows = fetch_rows(
        connection,
        f"""
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        TARGET_TABLES,
        ["table_name", "column_name"],
    )
    result: dict[str, list[str]] = {table: [] for table in TARGET_TABLES}
    for row in rows:
        result.setdefault(str(row["table_name"]), []).append(str(row["column_name"]))
    return result


def schema_columns_sheet(connection: Any) -> SheetResult:
    placeholders = ", ".join("?" for _ in TARGET_TABLES)
    rows = fetch_rows(
        connection,
        f"""
        SELECT TABLE_NAME AS table_name,
               COLUMN_NAME AS column_name,
               DATA_TYPE AS data_type,
               ORDINAL_POSITION AS ordinal_position,
               IS_NULLABLE AS is_nullable
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME IN ({placeholders})
        ORDER BY TABLE_NAME, ORDINAL_POSITION
        """,
        TARGET_TABLES,
        ["table_name", "column_name", "data_type", "ordinal_position", "is_nullable"],
    )
    return SheetResult("schema_columns", rows)


def raw_table_sheet(
    connection: Any,
    columns_by_table: dict[str, list[str]],
    sheet_name: str,
    table: str,
    date_column: str,
    preferred_columns: Sequence[str],
    order_columns: Sequence[str],
    date_from: date,
    date_to: date,
    include_real: bool,
    include_rest: bool = False,
) -> SheetResult:
    columns = select_columns(columns_by_table, table, preferred_columns, include_rest)
    if not columns:
        return SheetResult(sheet_name, [], f"{table}: no requested columns or table missing")
    if date_column not in columns_by_table.get(table, []):
        return SheetResult(sheet_name, [], f"{table}.{date_column}: date column missing")
    where = [f"{q(date_column)} BETWEEN ? AND ?"]
    params: list[Any] = [date_from, date_to]
    if not include_real and table in MOCK_FILTER_TABLES and "is_mock" in columns_by_table.get(table, []):
        where.append("[is_mock] = 1")
    if not include_real and table == "daily_trade_summary_report" and "mode" in columns_by_table.get(table, []):
        where.append("([mode] = 'mock' OR [mode] IS NULL)")
    order_by = ", ".join(q(col) for col in order_columns if col in columns_by_table.get(table, []))
    sql = (
        f"SELECT {', '.join(q(col) for col in columns)} FROM dbo.{q(table)} "
        f"WHERE {' AND '.join(where)}"
    )
    if order_by:
        sql += f" ORDER BY {order_by}"
    return query_raw_sheet(connection, columns_by_table, sheet_name, sql, tuple(params), columns)


def query_raw_sheet(
    connection: Any,
    columns_by_table: dict[str, list[str]],
    sheet_name: str,
    sql: str,
    params: Sequence[Any],
    columns: Sequence[str],
) -> SheetResult:
    if not sql:
        return SheetResult(sheet_name, [], "required table or columns missing")
    try:
        return SheetResult(sheet_name, fetch_rows(connection, sql, params, columns))
    except Exception as exc:
        return SheetResult(sheet_name, [], f"{type(exc).__name__}: {_safe_error(str(exc))}")


def fetch_rows(
    connection: Any,
    sql: str,
    params: Sequence[Any],
    columns: Sequence[str],
) -> list[dict[str, Any]]:
    cursor = connection.cursor()
    cursor.execute(sql, tuple(params))
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(
            {
                column: sanitize_value(value)
                for column, value in zip(columns, row, strict=False)
            }
        )
    return result


def select_columns(
    columns_by_table: dict[str, list[str]],
    table: str,
    preferred: Sequence[str],
    include_rest: bool = False,
) -> list[str]:
    existing = columns_by_table.get(table, [])
    selected = [column for column in preferred if column in existing]
    if include_rest:
        selected.extend(column for column in existing if column not in selected)
    return selected


def fill_history_dedup_sql(columns_by_table: dict[str, list[str]]) -> str:
    required = {"trade_date", "ticker", "side", "order_no", "fill_time", "fill_price", "quantity"}
    columns = set(columns_by_table.get("fill_history", []))
    if not required.issubset(columns):
        return ""
    created = "created_at" if "created_at" in columns else "fill_date" if "fill_date" in columns else "trade_date"
    id_expr = "STRING_AGG(CONVERT(NVARCHAR(50), [id]), ',')" if "id" in columns else "CAST(NULL AS NVARCHAR(MAX))"
    profit_expr = "SUM(COALESCE([profit_usd], 0))" if "profit_usd" in columns else "CAST(NULL AS FLOAT)"
    return f"""
        SELECT [trade_date], [ticker], [side], [order_no], [fill_time], [fill_price],
               COUNT(*) AS row_count,
               SUM(COALESCE([quantity], 0)) AS sum_quantity,
               MIN([quantity]) AS min_quantity,
               MAX([quantity]) AS max_quantity,
               {profit_expr} AS sum_profit_usd,
               MIN([{created}]) AS min_created_at,
               MAX([{created}]) AS max_created_at,
               STRING_AGG(CONVERT(NVARCHAR(50), [quantity]), ',') AS quantity_list,
               {id_expr} AS id_list
        FROM dbo.[fill_history]
        WHERE [trade_date] BETWEEN ? AND ?
        GROUP BY [trade_date], [ticker], [side], [order_no], [fill_time], [fill_price]
        HAVING COUNT(*) > 1
            OR (MAX([quantity]) > MIN([quantity]) AND COALESCE([order_no], '') <> '')
        ORDER BY [trade_date], row_count DESC, [ticker], [order_no]
    """


def candidate_orders_sql(
    columns_by_table: dict[str, list[str]],
    *,
    include_order_by: bool = True,
) -> str:
    ce = set(columns_by_table.get("candidate_evaluations", []))
    fh = set(columns_by_table.get("fill_history", []))
    th = set(columns_by_table.get("trade_history", []))
    if not {"trading_date", "symbol"}.issubset(ce) or not {"trade_date", "ticker", "side"}.issubset(fh):
        return ""
    ce_id_order = "[id] DESC" if "id" in ce else "[evaluation_time] DESC"
    ce_cols = {
        "source": "source",
        "final_score": "final_score",
        "selection_score": "selection_score",
        "soft_score_adjustment": "soft_score_adjustment",
        "buy_allowed": "buy_allowed",
        "order_submitted": "order_submitted",
        "final_decision": "final_decision",
        "buy_block_reason": "buy_block_reason",
        "strategy_version": "strategy_version",
        "settings_snapshot_hash": "settings_snapshot_hash",
    }
    ce_select = ", ".join(
        f"{q(col)} AS {q(alias)}" if col in ce else f"CAST(NULL AS NVARCHAR(MAX)) AS {q(alias)}"
        for alias, col in ce_cols.items()
    )
    fill_profit = "SUM(COALESCE([profit_usd], 0))" if "profit_usd" in fh else "CAST(NULL AS FLOAT)"
    fill_rate = "AVG([profit_rate])" if "profit_rate" in fh else "CAST(NULL AS FLOAT)"
    fill_entry_reason = "MAX([entry_reason])" if "entry_reason" in fh else "CAST(NULL AS NVARCHAR(MAX))"
    fill_entry_detail = "MAX([entry_reason_detail])" if "entry_reason_detail" in fh else "CAST(NULL AS NVARCHAR(MAX))"
    exit_reasons = (
        "STRING_AGG(CONVERT(NVARCHAR(100), [exit_reason]), ',')"
        if {"trade_date", "ticker", "order_type", "exit_reason"}.issubset(th)
        else "CAST(NULL AS NVARCHAR(MAX))"
    )
    order_clause = "ORDER BY ce_latest.[trading_date], ce_latest.[symbol]" if include_order_by else ""
    return f"""
        SELECT ce_latest.[trading_date] AS trade_date,
               ce_latest.[symbol] AS ticker,
               ce_latest.[source],
               ce_latest.[final_score],
               ce_latest.[selection_score],
               ce_latest.[soft_score_adjustment],
               ce_latest.[buy_allowed],
               ce_latest.[order_submitted],
               ce_latest.[final_decision],
               ce_latest.[buy_block_reason],
               buy_fills.entry_reason,
               buy_fills.entry_reason_detail,
               COALESCE(buy_fills.buy_count, 0) AS buy_fill_count,
               CASE
                 WHEN COALESCE(CONVERT(INT, ce_latest.[order_submitted]), 0) = 1
                      OR COALESCE(buy_fills.buy_count, 0) > 0
                 THEN COALESCE(fills.sell_count, 0)
                 ELSE 0
               END AS sell_count,
               CASE
                 WHEN COALESCE(CONVERT(INT, ce_latest.[order_submitted]), 0) = 1
                      OR COALESCE(buy_fills.buy_count, 0) > 0
                 THEN fills.sell_profit_usd
                 ELSE NULL
               END AS sell_profit_usd,
               CASE
                 WHEN COALESCE(CONVERT(INT, ce_latest.[order_submitted]), 0) = 1
                      OR COALESCE(buy_fills.buy_count, 0) > 0
                 THEN fills.avg_sell_profit_rate
                 ELSE NULL
               END AS avg_sell_profit_rate,
               exits.exit_reasons,
               ce_latest.[strategy_version],
               ce_latest.[settings_snapshot_hash]
        FROM (
            SELECT *
            FROM (
                SELECT [trading_date], [symbol], {ce_select},
                       ROW_NUMBER() OVER (
                           PARTITION BY [trading_date], [symbol]
                           ORDER BY [evaluation_time] DESC, {ce_id_order}
                       ) AS rn
                FROM dbo.[candidate_evaluations]
                WHERE [trading_date] BETWEEN ? AND ?
                  AND (
                    COALESCE(CONVERT(INT, [buy_allowed]), 0) = 1
                    OR COALESCE(CONVERT(INT, [order_submitted]), 0) = 1
                  )
            ) AS ranked_ce
            WHERE rn = 1
        ) AS ce_latest
        LEFT JOIN (
            SELECT [trade_date], [ticker],
                   COUNT(*) AS buy_count,
                   {fill_entry_reason} AS entry_reason,
                   {fill_entry_detail} AS entry_reason_detail
            FROM dbo.[fill_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([side], '')) IN ('BUY', 'B') OR COALESCE([side], '') LIKE N'%留ㅼ닔%')
            GROUP BY [trade_date], [ticker]
        ) AS buy_fills
          ON buy_fills.[trade_date] = ce_latest.[trading_date]
         AND buy_fills.[ticker] = ce_latest.[symbol]
        LEFT JOIN (
            SELECT [trade_date], [ticker],
                   COUNT(*) AS sell_count,
                   {fill_profit} AS sell_profit_usd,
                   {fill_rate} AS avg_sell_profit_rate,
                   {fill_entry_reason} AS entry_reason,
                   {fill_entry_detail} AS entry_reason_detail
            FROM dbo.[fill_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([side], '')) IN ('SELL', 'S') OR COALESCE([side], '') LIKE N'%매도%')
            GROUP BY [trade_date], [ticker]
        ) AS fills
          ON fills.[trade_date] = ce_latest.[trading_date]
         AND fills.[ticker] = ce_latest.[symbol]
        LEFT JOIN (
            SELECT [trade_date], [ticker], {exit_reasons} AS exit_reasons
            FROM dbo.[trade_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([order_type], '')) IN ('SELL', 'S') OR COALESCE([order_type], '') LIKE N'%매도%')
            GROUP BY [trade_date], [ticker]
        ) AS exits
          ON exits.[trade_date] = ce_latest.[trading_date]
         AND exits.[ticker] = ce_latest.[symbol]
        {order_clause}
    """


def event_summary_sql(columns_by_table: dict[str, list[str]]) -> str:
    columns = set(columns_by_table.get("trading_event_log", []))
    required = {"trade_date", "event_type", "reason_code", "severity"}
    if not required.issubset(columns):
        return ""
    return """
        SELECT [trade_date], [event_type], [reason_code], [severity], COUNT(*) AS count
        FROM dbo.[trading_event_log]
        WHERE [trade_date] BETWEEN ? AND ?
        GROUP BY [trade_date], [event_type], [reason_code], [severity]
        ORDER BY [trade_date], count DESC
    """


def pnl_by_day_sql(columns_by_table: dict[str, list[str]]) -> str:
    columns = set(columns_by_table.get("fill_history", []))
    if not {"trade_date", "side", "profit_usd"}.issubset(columns):
        return ""
    return """
        SELECT [trade_date],
               COUNT(*) AS sell_count,
               SUM(COALESCE([profit_usd], 0)) AS total_profit_usd,
               AVG(COALESCE([profit_usd], 0)) AS avg_profit_usd,
               SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS win_count,
               SUM(CASE WHEN COALESCE([profit_usd], 0) < 0 THEN 1 ELSE 0 END) AS loss_count,
               CAST(SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(COUNT(*), 0) AS win_rate,
               AVG(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN [profit_usd] END) AS avg_win,
               AVG(CASE WHEN COALESCE([profit_usd], 0) < 0 THEN [profit_usd] END) AS avg_loss,
               SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN [profit_usd] ELSE 0 END)
                    / NULLIF(ABS(SUM(CASE WHEN COALESCE([profit_usd], 0) < 0 THEN [profit_usd] ELSE 0 END)), 0) AS profit_factor,
               MAX([profit_usd]) AS max_win,
               MIN([profit_usd]) AS max_loss
        FROM dbo.[fill_history]
        WHERE [trade_date] BETWEEN ? AND ?
          AND (UPPER(COALESCE([side], '')) IN ('SELL', 'S') OR COALESCE([side], '') LIKE N'%매도%')
        GROUP BY [trade_date]
        ORDER BY [trade_date]
    """


def pnl_by_ticker_sql(columns_by_table: dict[str, list[str]]) -> str:
    fh = set(columns_by_table.get("fill_history", []))
    th = set(columns_by_table.get("trade_history", []))
    if not {"trade_date", "ticker", "side", "profit_usd"}.issubset(fh):
        return ""
    exit_summary = (
        "STRING_AGG(CONVERT(NVARCHAR(100), [exit_reason]), ',')"
        if {"trade_date", "ticker", "order_type", "exit_reason"}.issubset(th)
        else "CAST(NULL AS NVARCHAR(MAX))"
    )
    return f"""
        SELECT fills.[ticker],
               COUNT(*) AS sell_count,
               SUM(COALESCE(fills.[profit_usd], 0)) AS total_profit_usd,
               AVG(COALESCE(fills.[profit_usd], 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE(fills.[profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(COUNT(*), 0) AS win_rate,
               AVG(COALESCE(fills.[profit_rate], 0)) AS avg_profit_rate,
               exits.exit_reasons
        FROM dbo.[fill_history] AS fills
        LEFT JOIN (
            SELECT [ticker], {exit_summary} AS exit_reasons
            FROM dbo.[trade_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([order_type], '')) IN ('SELL', 'S') OR COALESCE([order_type], '') LIKE N'%매도%')
            GROUP BY [ticker]
        ) AS exits
          ON exits.[ticker] = fills.[ticker]
        WHERE fills.[trade_date] BETWEEN ? AND ?
          AND (UPPER(COALESCE(fills.[side], '')) IN ('SELL', 'S') OR COALESCE(fills.[side], '') LIKE N'%매도%')
        GROUP BY fills.[ticker], exits.exit_reasons
        ORDER BY total_profit_usd ASC
    """


def pnl_by_exit_reason_sql(columns_by_table: dict[str, list[str]]) -> str:
    fh = set(columns_by_table.get("fill_history", []))
    th = set(columns_by_table.get("trade_history", []))
    if not {"trade_date", "ticker", "side", "profit_usd", "profit_rate"}.issubset(fh):
        return ""
    if {"trade_date", "ticker", "order_type", "exit_reason"}.issubset(th):
        fallback_order = "th.[created_at] DESC" if "created_at" in th else "th.[trade_date] DESC"
        time_order = fallback_order
        if "last_fill_time" in th and "fill_time" in fh:
            time_order = f"""
                CASE WHEN ISNULL(th.[last_fill_time], '') = ISNULL(fills.[fill_time], '') THEN 0 ELSE 1 END,
                ABS(DATEDIFF(SECOND, TRY_CONVERT(time, th.[last_fill_time]), TRY_CONVERT(time, fills.[fill_time]))),
                {fallback_order}
            """
        return f"""
            SELECT fills.[trade_date],
                   COALESCE(matched.[exit_reason], 'UNKNOWN') AS exit_reason,
                   COUNT(*) AS sell_count,
                   SUM(COALESCE(fills.[profit_usd], 0)) AS total_profit_usd,
                   AVG(COALESCE(fills.[profit_usd], 0)) AS avg_profit_usd,
                   CAST(SUM(CASE WHEN COALESCE(fills.[profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                        / NULLIF(COUNT(*), 0) AS win_rate,
                   AVG(COALESCE(fills.[profit_rate], 0)) AS avg_profit_rate
            FROM dbo.[fill_history] AS fills
            OUTER APPLY (
                SELECT TOP (1) th.[exit_reason]
                FROM dbo.[trade_history] AS th
                WHERE th.[trade_date] = fills.[trade_date]
                  AND th.[ticker] = fills.[ticker]
                  AND th.[exit_reason] IS NOT NULL
                ORDER BY {time_order}
            ) AS matched
            WHERE fills.[trade_date] BETWEEN ? AND ?
              AND fills.[profit_usd] IS NOT NULL
            GROUP BY fills.[trade_date], COALESCE(matched.[exit_reason], 'UNKNOWN')
            ORDER BY fills.[trade_date], total_profit_usd ASC
        """
    return """
        SELECT [trade_date],
               'UNKNOWN' AS exit_reason,
               COUNT(*) AS sell_count,
               SUM(COALESCE([profit_usd], 0)) AS total_profit_usd,
               AVG(COALESCE([profit_usd], 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(COUNT(*), 0) AS win_rate,
               AVG(COALESCE([profit_rate], 0)) AS avg_profit_rate
        FROM dbo.[fill_history]
        WHERE [trade_date] BETWEEN ? AND ?
          AND [profit_usd] IS NOT NULL
        GROUP BY [trade_date]
        ORDER BY [trade_date]
    """
    if not {"trade_date", "ticker", "order_type", "exit_reason"}.issubset(th):
        return """
            SELECT 'UNKNOWN' AS exit_reason,
                   COUNT(*) AS sell_count,
                   SUM(COALESCE([profit_usd], 0)) AS total_profit_usd,
                   AVG(COALESCE([profit_usd], 0)) AS avg_profit_usd,
                   CAST(SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                        / NULLIF(COUNT(*), 0) AS win_rate,
                   AVG(COALESCE([profit_rate], 0)) AS avg_profit_rate
            FROM dbo.[fill_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([side], '')) IN ('SELL', 'S') OR COALESCE([side], '') LIKE N'%留ㅻ룄%')
        """
    fallback_order = "th.[created_at] DESC" if "created_at" in th else "th.[trade_date] DESC"
    time_order = fallback_order
    if "last_fill_time" in th and "fill_time" in fh:
        time_order = f"""
            CASE WHEN ISNULL(th.[last_fill_time], '') = ISNULL(fills.[fill_time], '') THEN 0 ELSE 1 END,
            ABS(DATEDIFF(SECOND, TRY_CONVERT(time, th.[last_fill_time]), TRY_CONVERT(time, fills.[fill_time]))),
            {fallback_order}
        """
    return f"""
        SELECT COALESCE(matched.[exit_reason], 'UNKNOWN') AS exit_reason,
               COUNT(*) AS sell_count,
               SUM(COALESCE(fills.[profit_usd], 0)) AS total_profit_usd,
               AVG(COALESCE(fills.[profit_usd], 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE(fills.[profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(COUNT(*), 0) AS win_rate,
               AVG(COALESCE(fills.[profit_rate], 0)) AS avg_profit_rate
        FROM dbo.[fill_history] AS fills
        OUTER APPLY (
            SELECT TOP (1) th.[exit_reason]
            FROM dbo.[trade_history] AS th
            WHERE th.[trade_date] = fills.[trade_date]
              AND th.[ticker] = fills.[ticker]
              AND (UPPER(COALESCE(th.[order_type], '')) IN ('SELL', 'S') OR COALESCE(th.[order_type], '') LIKE N'%留ㅻ룄%')
            ORDER BY {time_order}
        ) AS matched
        WHERE fills.[trade_date] BETWEEN ? AND ?
          AND (UPPER(COALESCE(fills.[side], '')) IN ('SELL', 'S') OR COALESCE(fills.[side], '') LIKE N'%留ㅻ룄%')
        GROUP BY COALESCE(matched.[exit_reason], 'UNKNOWN')
        ORDER BY total_profit_usd ASC
    """
    return """
        SELECT COALESCE([exit_reason], 'UNKNOWN') AS exit_reason,
               COUNT(*) AS sell_count,
               SUM(COALESCE([profit_usd], 0)) AS total_profit_usd,
               AVG(COALESCE([profit_usd], 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE([profit_usd], 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(COUNT(*), 0) AS win_rate,
               AVG(COALESCE([profit_rate], 0)) AS avg_profit_rate
        FROM dbo.[trade_history]
        WHERE [trade_date] BETWEEN ? AND ?
          AND (UPPER(COALESCE([order_type], '')) IN ('SELL', 'S') OR COALESCE([order_type], '') LIKE N'%매도%')
        GROUP BY COALESCE([exit_reason], 'UNKNOWN')
        ORDER BY total_profit_usd ASC
    """


def pnl_by_score_bucket_sql(columns_by_table: dict[str, list[str]]) -> str:
    base = candidate_orders_sql(columns_by_table, include_order_by=False)
    if not base:
        return ""
    return f"""
        SELECT trade_date,
               CASE
                 WHEN final_score IS NULL THEN 'unknown'
                 WHEN final_score < 40 THEN '<40'
                 WHEN final_score < 50 THEN '40~50'
                 WHEN final_score < 60 THEN '50~60'
                 WHEN final_score < 70 THEN '60~70'
                 WHEN final_score < 80 THEN '70~80'
                 ELSE '80+'
               END AS score_bucket,
               SUM(sell_count) AS sell_count,
               SUM(COALESCE(sell_profit_usd, 0)) AS total_profit_usd,
               AVG(COALESCE(sell_profit_usd, 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE(sell_profit_usd, 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(SUM(CASE WHEN sell_count > 0 THEN 1 ELSE 0 END), 0) AS win_rate
        FROM ({base}) AS matched
        GROUP BY trade_date,
                 CASE
                 WHEN final_score IS NULL THEN 'unknown'
                 WHEN final_score < 40 THEN '<40'
                 WHEN final_score < 50 THEN '40~50'
                 WHEN final_score < 60 THEN '50~60'
                 WHEN final_score < 70 THEN '60~70'
                 WHEN final_score < 80 THEN '70~80'
                 ELSE '80+'
               END
        ORDER BY trade_date, score_bucket
    """


def pnl_by_source_sql(columns_by_table: dict[str, list[str]]) -> str:
    base = candidate_orders_sql(columns_by_table, include_order_by=False)
    if not base:
        return ""
    return f"""
        SELECT trade_date,
               COALESCE(source, 'unknown') AS source,
               SUM(sell_count) AS sell_count,
               SUM(COALESCE(sell_profit_usd, 0)) AS total_profit_usd,
               AVG(COALESCE(sell_profit_usd, 0)) AS avg_profit_usd,
               CAST(SUM(CASE WHEN COALESCE(sell_profit_usd, 0) > 0 THEN 1 ELSE 0 END) AS FLOAT)
                    / NULLIF(SUM(CASE WHEN sell_count > 0 THEN 1 ELSE 0 END), 0) AS win_rate
        FROM ({base}) AS matched
        GROUP BY trade_date, COALESCE(source, 'unknown')
        ORDER BY trade_date, total_profit_usd ASC
    """


def summary_reconciliation_sql(columns_by_table: dict[str, list[str]]) -> str:
    fh = set(columns_by_table.get("fill_history", []))
    drs = set(columns_by_table.get("daily_run_summary", []))
    dtr = set(columns_by_table.get("daily_trade_summary_report", []))
    if not {"trade_date", "side", "profit_usd"}.issubset(fh):
        return ""
    daily_run = (
        """
        SELECT [trade_date],
               SUM(COALESCE([realized_profit_usd], 0)) AS daily_run_realized_profit_usd
        FROM dbo.[daily_run_summary]
        WHERE [trade_date] BETWEEN ? AND ?
        GROUP BY [trade_date]
        """
        if {"trade_date", "realized_profit_usd"}.issubset(drs)
        else """
        SELECT CAST(NULL AS date) AS [trade_date],
               CAST(NULL AS FLOAT) AS daily_run_realized_profit_usd
        WHERE ? IS NULL AND ? IS NULL AND 1 = 0
        """
    )
    trade_summary = (
        """
        SELECT [trade_date],
               SUM(COALESCE([total_profit_usd], 0)) AS trade_summary_profit_usd
        FROM dbo.[daily_trade_summary_report]
        WHERE [trade_date] BETWEEN ? AND ?
          AND ([mode] = 'mock' OR [mode] IS NULL)
        GROUP BY [trade_date]
        """
        if {"trade_date", "total_profit_usd", "mode"}.issubset(dtr)
        else """
        SELECT CAST(NULL AS date) AS [trade_date],
               CAST(NULL AS FLOAT) AS trade_summary_profit_usd
        WHERE ? IS NULL AND ? IS NULL AND 1 = 0
        """
    )
    return f"""
        SELECT COALESCE(fills.[trade_date], run_summary.[trade_date], trade_summary.[trade_date]) AS trade_date,
               fills.sell_count,
               fills.fill_history_sell_profit_usd,
               run_summary.daily_run_realized_profit_usd,
               trade_summary.trade_summary_profit_usd,
               COALESCE(fills.fill_history_sell_profit_usd, 0)
                    - COALESCE(run_summary.daily_run_realized_profit_usd, 0) AS fill_vs_daily_run_diff,
               COALESCE(fills.fill_history_sell_profit_usd, 0)
                    - COALESCE(trade_summary.trade_summary_profit_usd, 0) AS fill_vs_trade_summary_diff
        FROM (
            SELECT [trade_date],
                   COUNT(*) AS sell_count,
                   SUM(COALESCE([profit_usd], 0)) AS fill_history_sell_profit_usd
            FROM dbo.[fill_history]
            WHERE [trade_date] BETWEEN ? AND ?
              AND (UPPER(COALESCE([side], '')) IN ('SELL', 'S') OR COALESCE([side], '') LIKE N'%留ㅻ룄%')
            GROUP BY [trade_date]
        ) AS fills
        FULL OUTER JOIN ({daily_run}) AS run_summary
          ON run_summary.[trade_date] = fills.[trade_date]
        FULL OUTER JOIN ({trade_summary}) AS trade_summary
          ON trade_summary.[trade_date] = COALESCE(fills.[trade_date], run_summary.[trade_date])
        ORDER BY trade_date
    """


def final_metrics(results: list[SheetResult]) -> dict[str, Any]:
    by_name = {result.name: result for result in results}
    fill_rows = by_name.get("fill_history", SheetResult("fill_history", [])).rows
    sell_rows = [row for row in fill_rows if _is_sell(row.get("side"))]
    daily_rows = by_name.get("daily_run_summary", SheetResult("daily_run_summary", [])).rows
    event_rows = by_name.get("trading_event_log", SheetResult("trading_event_log", [])).rows
    event_summary = by_name.get("event_summary", SheetResult("event_summary", [])).rows
    return {
        "duplicate_suspects": len(by_name.get("duplicate_suspects", SheetResult("", [])).rows),
        "fill_history_sell_count": len(sell_rows),
        "fill_history_sell_profit_usd": sum(_num(row.get("profit_usd")) for row in sell_rows),
        "daily_run_summary_realized_profit_usd": sum(
            _num(row.get("realized_profit_usd")) for row in daily_rows
        ),
        "trading_event_log_count": len(event_rows),
        "event_summary_top10": sorted(
            event_summary,
            key=lambda row: _num(row.get("count")),
            reverse=True,
        )[:10],
    }


def sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    text = str(value)
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(lambda match: _redacted_match(match), text)
    return text


def _redacted_match(match: re.Match[str]) -> str:
    text = match.group(0)
    if "=" in text:
        return text.split("=", 1)[0] + "=<redacted>"
    if ":" in text:
        return text.split(":", 1)[0] + ":<redacted>"
    return "<redacted>"


def _safe_error(text: str) -> str:
    return str(sanitize_value(text))


def _cell_xml(row: int, col: int, value: Any) -> str:
    ref = f"{_column_name(col)}{row}"
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f'<c r="{ref}" t="n"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(str(value))}</t></is></c>'


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _sheet_name(name: str, existing: Sequence[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "sheet"
    if cleaned not in existing:
        return cleaned
    base = cleaned[:27]
    suffix = 1
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"[:31]


def _xml_text(text: str) -> str:
    cleaned = "".join(
        char
        for char in text
        if char in "\t\n\r" or ord(char) >= 32
    )
    return escape(cleaned, {'"': "&quot;"})


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _coerce_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return _parse_date(str(value))


def q(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def _is_sell(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return text in {"SELL", "S"} or "매도" in str(value or "")


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


FILL_HISTORY_COLUMNS = (
    "id", "trade_date", "fill_date", "fill_time", "ticker", "ticker_name", "side",
    "quantity", "fill_price", "fill_amount", "profit_usd", "profit_rate", "order_no",
    "entry_reason", "entry_reason_detail", "is_mock", "strategy_version",
    "settings_snapshot_hash", "created_at", "updated_at", "fill_notification_sent",
    "fill_notification_sent_at",
)
TRADE_HISTORY_COLUMNS = (
    "id", "trade_date", "ticker", "ticker_name", "order_type", "order_price",
    "exec_price", "entry_price", "quantity", "profit_usd", "profit_krw",
    "profit_rate", "exit_reason", "entry_reason", "entry_reason_detail", "is_mock",
    "order_status", "retry_count", "order_qty", "filled_qty", "remaining_qty",
    "avg_fill_price", "last_fill_time", "reject_reason", "actual_value",
    "threshold_value", "strategy_version", "settings_snapshot_hash", "created_at",
    "updated_at",
)
ORDER_SNAPSHOT_COLUMNS = (
    "trade_date", "order_date", "order_time", "ticker", "ticker_name", "side",
    "quantity", "order_price", "unfilled_quantity", "order_no", "is_mock",
    "order_status", "order_qty", "filled_qty", "remaining_qty", "avg_fill_price",
    "last_fill_time", "created_at", "updated_at",
)
DAILY_RUN_SUMMARY_COLUMNS = (
    "trade_date", "candidate_selection_mode", "realized_profit_usd",
    "realized_profit_rate", "eod_sell_count", "cancelled_order_count",
    "buy_fill_count", "sell_fill_count", "is_mock", "strategy_version",
    "settings_snapshot_hash", "settings_snapshot_json", "created_at", "updated_at",
)
DAILY_TRADE_SUMMARY_REPORT_COLUMNS = (
    "trade_date", "mode", "strategy_version", "settings_snapshot_hash",
    "summary_json", "summary_text", "total_profit_usd", "total_profit_rate",
    "trade_count", "buy_count", "sell_count", "win_rate", "stop_loss_count",
    "take_profit_count", "trailing_stop_count", "eod_count", "sample_sufficient",
    "created_at", "updated_at",
)
CANDIDATE_EVALUATION_COLUMNS = (
    "id", "run_id", "evaluation_time", "trading_date", "source", "symbol",
    "symbol_name", "current_price", "volume", "dollar_volume",
    "price_change_percent", "opening_gap_percent", "price_rank", "volume_rank",
    "relaxation_level", "min_price", "max_price", "price_change_top",
    "volume_top", "min_selection_score", "min_opening_price_change_percent",
    "min_volume_ratio", "max_opening_gap_percent", "selection_score",
    "soft_score_adjustment", "final_score", "overheat_condition_mode",
    "breakout_close_condition_mode", "volume_increase_condition_mode",
    "vwap_ma20_condition_mode", "vwap_ma20_condition_type",
    "pullback_rebreak_condition_mode", "overheat_pass", "breakout_close_pass",
    "volume_increase_pass", "vwap_pass", "ma20_pass", "vwap_ma20_pass",
    "pullback_rebreak_pass", "final_score_pass", "buy_allowed", "order_submitted",
    "order_id", "buy_block_reason", "buy_block_reasons",
    "hard_filter_failed_count", "soft_condition_failed_count", "final_decision",
    "settings_snapshot_json", "condition_result_json", "raw_candidate_json",
    "created_at", "updated_at",
)
TRADING_EVENT_LOG_COLUMNS = (
    "id", "event_time", "trade_date", "mode", "app_mode", "run_id",
    "correlation_id", "order_id", "order_no", "ticker", "ticker_name", "side",
    "stage", "event_type", "severity", "decision", "reason_code", "reason_label",
    "is_blocking", "is_final_decision", "order_submitted", "buy_allowed",
    "sell_allowed", "quantity", "price_usd", "order_value_usd", "actual_value",
    "threshold_value", "profit_rate", "candidate_source", "ranking_selection_mode",
    "strategy_version", "settings_snapshot_hash", "message", "details_json",
    "created_at",
)
BOT_LOG_COLUMNS = (
    "id", "trade_date", "log_level", "module", "message", "symbol", "ticker_name",
    "reject_reason", "actual_value", "threshold_value", "created_at", "logged_at",
)
HOLDING_SNAPSHOT_COLUMNS = (
    "trade_date", "snapshot_date", "ticker", "ticker_name", "quantity",
    "average_price", "open_price", "close_price", "total_price", "is_mock",
    "created_at", "updated_at",
)
ACCOUNT_SNAPSHOT_COLUMNS = (
    "trade_date", "snapshot_date", "cash_usd", "equity_usd", "invested_usd",
    "open_positions", "daily_profit_rate", "realized_profit_usd", "is_mock",
    "created_at", "updated_at",
)
ENTRY_PROFIT_SNAPSHOT_COLUMNS = (
    "trade_date", "ticker", "ticker_name", "entry_time", "entry_price",
    "strategy_version", "created_at", "updated_at",
)
RAW_ORDERS = {
    "fill_history": ("trade_date", "ticker", "fill_time", "side", "order_no"),
    "trade_history": ("trade_date", "ticker", "order_type", "created_at"),
    "order_snapshot": ("trade_date", "order_time", "ticker", "order_no"),
    "daily_run_summary": ("trade_date",),
    "daily_trade_summary_report": ("trade_date",),
    "candidate_evaluations": ("trading_date", "evaluation_time", "symbol"),
    "trading_event_log": ("trade_date", "event_time", "ticker"),
    "bot_log": ("trade_date", "created_at"),
    "holding_snapshot": ("trade_date", "ticker", "created_at"),
    "account_snapshot": ("trade_date", "created_at"),
    "entry_profit_snapshot": ("trade_date", "ticker", "entry_time"),
}
MOCK_FILTER_TABLES = {
    "fill_history",
    "trade_history",
    "order_snapshot",
    "holding_snapshot",
    "account_snapshot",
    "daily_run_summary",
}
DEDUP_COLUMNS = (
    "trade_date", "ticker", "side", "order_no", "fill_time", "fill_price",
    "row_count", "sum_quantity", "min_quantity", "max_quantity", "sum_profit_usd",
    "min_created_at", "max_created_at", "quantity_list", "id_list",
)
CANDIDATE_ORDERS_COLUMNS = (
    "trade_date", "ticker", "source", "final_score", "selection_score",
    "soft_score_adjustment", "buy_allowed", "order_submitted", "final_decision",
    "buy_block_reason", "entry_reason", "entry_reason_detail", "buy_fill_count",
    "sell_count", "sell_profit_usd", "avg_sell_profit_rate", "exit_reasons",
    "strategy_version", "settings_snapshot_hash",
)
EVENT_SUMMARY_COLUMNS = ("trade_date", "event_type", "reason_code", "severity", "count")
PNL_BY_DAY_COLUMNS = (
    "trade_date", "sell_count", "total_profit_usd", "avg_profit_usd", "win_count",
    "loss_count", "win_rate", "avg_win", "avg_loss", "profit_factor", "max_win",
    "max_loss",
)
PNL_BY_TICKER_COLUMNS = (
    "ticker", "sell_count", "total_profit_usd", "avg_profit_usd", "win_rate",
    "avg_profit_rate", "exit_reasons",
)
PNL_BY_EXIT_REASON_COLUMNS = (
    "trade_date", "exit_reason", "sell_count", "total_profit_usd", "avg_profit_usd", "win_rate",
    "avg_profit_rate",
)
PNL_BY_SCORE_BUCKET_COLUMNS = (
    "trade_date", "score_bucket", "sell_count", "total_profit_usd", "avg_profit_usd", "win_rate",
)
PNL_BY_SOURCE_COLUMNS = (
    "trade_date", "source", "sell_count", "total_profit_usd", "avg_profit_usd", "win_rate",
)
SUMMARY_RECONCILIATION_COLUMNS = (
    "trade_date", "sell_count", "fill_history_sell_profit_usd",
    "daily_run_realized_profit_usd", "trade_summary_profit_usd",
    "fill_vs_daily_run_diff", "fill_vs_trade_summary_diff",
)


if __name__ == "__main__":
    raise SystemExit(main())
