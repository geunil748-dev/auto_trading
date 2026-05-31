from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trading_bot.config import load_kis_settings
from trading_bot.database import pyodbc_connect_factory
from trading_bot.market_calendar import (
    current_us_market_date,
    is_current_us_regular_session,
    is_us_trading_day,
)


REQUIRED_TABLES = {
    "bot_log",
    "account_current",
    "account_snapshot",
    "daily_target",
    "daily_run_summary",
    "entry_profit_snapshot",
    "fill_history",
    "holding_snapshot",
    "listed_target_snapshot",
    "order_snapshot",
    "runtime_setting",
    "scoring",
    "trade_history",
}

REQUIRED_COLUMNS = {
    "trade_history": (
        "strategy_version",
        "settings_snapshot_hash",
        "settings_snapshot_json",
    ),
    "fill_history": (
        "strategy_version",
        "settings_snapshot_hash",
        "settings_snapshot_json",
    ),
    "daily_run_summary": (
        "strategy_version",
        "settings_snapshot_hash",
        "settings_snapshot_json",
    ),
    "entry_profit_snapshot": (
        "final_exit_reason",
        "final_profit_rate",
        "strategy_version",
    ),
}

AUTO_ENSURE_COLUMNS = {
    "trade_history": {
        "strategy_version": "VARCHAR(60) NULL",
        "settings_snapshot_hash": "VARCHAR(64) NULL",
        "settings_snapshot_json": "NVARCHAR(MAX) NULL",
    },
    "fill_history": {
        "strategy_version": "VARCHAR(60) NULL",
        "settings_snapshot_hash": "VARCHAR(64) NULL",
        "settings_snapshot_json": "NVARCHAR(MAX) NULL",
    },
}


def mock_trading_readiness(
    monitor_state: Path = Path("monitor/state.json"),
    now: datetime | None = None,
    market_date: date | None = None,
) -> dict[str, Any]:
    target_date = market_date or current_us_market_date(now)
    # 실투자 전환 전에는 이 결과를 먼저 보고 휴장/DB/API 준비 상태를 분리해서 판단한다.
    return {
        "us_market_date": target_date.isoformat(),
        "is_us_trading_day": is_us_trading_day(target_date),
        "is_regular_session_now": is_current_us_regular_session(now),
        "next_us_trading_day": next_us_trading_day(target_date).isoformat(),
        "kis_config": _kis_config_status(),
        "mssql": _mssql_status(),
        "monitor_state_exists": monitor_state.exists(),
        "ready_for_live_mock_session": is_us_trading_day(target_date),
    }


def next_us_trading_day(start: date) -> date:
    candidate = start
    for _ in range(14):
        if is_us_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError("No US trading day found in the next 14 days")


def _kis_config_status() -> dict[str, bool]:
    try:
        settings = load_kis_settings()
    except Exception:
        return {
            "configured": False,
            "app_key": False,
            "app_secret": False,
            "account_no": False,
            "account_product": False,
        }
    return {
        "configured": True,
        "app_key": bool(settings.app_key),
        "app_secret": bool(settings.app_secret),
        "account_no": bool(settings.account_no),
        "account_product": bool(settings.account_product),
    }


def _mssql_status() -> dict[str, Any]:
    try:
        connection = pyodbc_connect_factory()()
        cursor = connection.cursor()
        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = ?", ("BASE TABLE",))
        tables = {str(row[0]) for row in cursor.fetchall()}
        columns_before = _read_columns(cursor)
        column_actions = _ensure_trade_fill_metadata_columns(cursor, tables, columns_before)
        connection.commit()
        columns_after = _read_columns(cursor)
        connection.close()
    except Exception as error:
        return {"connected": False, "error": str(error)}

    missing = sorted(REQUIRED_TABLES - tables)
    missing_before = _missing_columns(tables, columns_before)
    missing_after = _missing_columns(tables, columns_after)
    return {
        "connected": True,
        "required_tables_ready": not missing,
        "missing_tables": missing,
        "required_columns_ready": not missing_after,
        "missing_columns": missing_after,
        "schema_column_check": {
            "before_missing_columns": missing_before,
            "after_missing_columns": missing_after,
            "actions": column_actions,
        },
        "warnings": _schema_warnings(missing, missing_after),
    }


def _read_columns(cursor: Any) -> dict[str, set[str]]:
    cursor.execute(
        """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME IN (?, ?, ?, ?)
        """,
        tuple(REQUIRED_COLUMNS),
    )
    columns = {table: set() for table in REQUIRED_COLUMNS}
    for table, column in cursor.fetchall():
        table_name = str(table)
        if table_name in columns:
            columns[table_name].add(str(column))
    return columns


def _ensure_trade_fill_metadata_columns(
    cursor: Any,
    tables: set[str],
    columns_before: dict[str, set[str]],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for table, column_types in AUTO_ENSURE_COLUMNS.items():
        for column, column_type in column_types.items():
            before = _column_status(table, column, tables, columns_before)
            if before == "missing":
                _execute_statement(
                    cursor,
                    f"""
                    IF OBJECT_ID(N'dbo.{table}', N'U') IS NOT NULL
                       AND COL_LENGTH('dbo.{table}', '{column}') IS NULL
                    BEGIN
                        ALTER TABLE dbo.{table} ADD {column} {column_type}
                    END
                    """,
                )
                action = "added"
            elif before == "present":
                action = "skipped_present"
            else:
                action = "skipped_missing_table"
            actions.append(
                {
                    "table": table,
                    "column": column,
                    "before": before,
                    "action": action,
                }
            )
    return actions


def _execute_statement(cursor: Any, sql: str) -> None:
    try:
        cursor.execute(sql, ())
    except TypeError:
        cursor.execute(sql)


def _column_status(
    table: str,
    column: str,
    tables: set[str],
    columns: dict[str, set[str]],
) -> str:
    if table not in tables:
        return "missing_table"
    if column in columns.get(table, set()):
        return "present"
    return "missing"


def _missing_columns(
    tables: set[str],
    columns: dict[str, set[str]],
) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            missing[table] = list(required)
            continue
        table_columns = columns.get(table, set())
        missing_columns = [column for column in required if column not in table_columns]
        if missing_columns:
            missing[table] = missing_columns
    return missing


def _schema_warnings(
    missing_tables: list[str],
    missing_columns: dict[str, list[str]],
) -> list[str]:
    warnings = []
    if missing_tables:
        warnings.append(f"Missing required MSSQL tables: {', '.join(missing_tables)}")
    for table, columns in missing_columns.items():
        warnings.append(f"Missing required MSSQL columns in {table}: {', '.join(columns)}")
    return warnings
