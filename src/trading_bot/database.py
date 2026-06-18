from __future__ import annotations

import os
from datetime import date, datetime
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 실행 환경에 따라 선택 의존성을 허용한다.
    load_dotenv = None


def pyodbc_connect_factory() -> Callable[[], Any]:
    if load_dotenv is not None:
        load_dotenv()
    dsn = mssql_dsn_from_env()
    if not dsn:
        raise ValueError("MSSQL_DSN or split MSSQL connection settings are required")
    provider = os.getenv("MSSQL_PROVIDER", "auto").strip().lower()
    if provider == "dotnet":
        # 현재 PC는 ODBC TLS 오류가 있어 .NET SqlClient 경로를 우선 사용한다.
        connection_string = mssql_sqlclient_connection_string_from_env()

        def connect_dotnet() -> Any:
            return DotNetSqlConnection(connection_string)

        return connect_dotnet

    def connect() -> Any:
        import pyodbc

        if provider == "pyodbc":
            return pyodbc.connect(dsn)
        try:
            return pyodbc.connect(dsn)
        except Exception:
            # 배포 환경별 드라이버 차이를 흡수하기 위한 자동 대체 경로다.
            connection_string = mssql_sqlclient_connection_string_from_env()
            return DotNetSqlConnection(connection_string)

    return connect


def mssql_dsn_from_env() -> str:
    if load_dotenv is not None:
        load_dotenv()
    explicit = os.getenv("MSSQL_DSN", "").strip()
    if explicit:
        return explicit

    host = os.getenv("MSSQL_HOST", "").strip()
    database = os.getenv("MSSQL_DATABASE", "").strip()
    username = os.getenv("MSSQL_USERNAME", "").strip()
    password = os.getenv("MSSQL_PASSWORD", "").strip()
    if not all((host, database, username, password)):
        return ""

    driver = os.getenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server").strip()
    port = os.getenv("MSSQL_PORT", "").strip()
    trust = os.getenv("MSSQL_TRUST_SERVER_CERTIFICATE", "yes").strip() or "yes"
    encrypt = os.getenv("MSSQL_ENCRYPT", "no").strip() or "no"
    server = f"{host},{port}" if port and port != "0" else host
    return (
        f"Driver={{{driver}}};"
        f"Server={server};"
        f"Database={database};"
        f"Uid={username};"
        f"Pwd={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
    )


def mssql_sqlclient_connection_string_from_env(database: str | None = None) -> str:
    if load_dotenv is not None:
        load_dotenv()
    host = os.getenv("MSSQL_HOST", "").strip()
    target_database = database or os.getenv("MSSQL_DATABASE", "").strip()
    username = os.getenv("MSSQL_USERNAME", "").strip()
    password = os.getenv("MSSQL_PASSWORD", "").strip()
    if not all((host, target_database, username, password)):
        return ""

    port = os.getenv("MSSQL_PORT", "").strip()
    server = f"{host},{port}" if port and port != "0" else host
    encrypt = _dotnet_encrypt_value(os.getenv("MSSQL_ENCRYPT", "False"))
    trust = _dotnet_bool_value(os.getenv("MSSQL_TRUST_SERVER_CERTIFICATE", "True"))
    return (
        f"Server={server};"
        f"Database={target_database};"
        f"User ID={username};"
        f"Password={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
        "Connection Timeout=5"
    )


def ensure_mssql_database_exists() -> None:
    if load_dotenv is not None:
        load_dotenv()
    database = os.getenv("MSSQL_DATABASE", "").strip()
    if not database:
        raise ValueError("MSSQL_DATABASE is required")
    quoted_database = _quoted_database_name(database)
    # 대상 DB가 없을 때만 master에 접속해 최초 1회 생성한다.
    connection = DotNetSqlConnection(mssql_sqlclient_connection_string_from_env("master"))
    with closing(connection):
        connection.cursor().execute(
            f"IF DB_ID(N'{database}') IS NULL CREATE DATABASE {quoted_database}"
        )


class DotNetSqlConnection:
    def __init__(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("MSSQL split connection settings are required")
        import clr

        clr.AddReference("System.Data")
        from System.Data.SqlClient import SqlConnection

        self._connection = SqlConnection(connection_string)
        self._connection.Open()

    def cursor(self) -> "DotNetSqlCursor":
        return DotNetSqlCursor(self._connection)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        self._connection.Close()


class DotNetSqlCursor:
    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, sql: str, row: tuple[Any, ...] = ()) -> "DotNetSqlCursor":
        command_text, params = _sql_with_named_parameters(sql, row)
        command = self._connection.CreateCommand()
        command.CommandText = command_text
        for name, value in params:
            command.Parameters.AddWithValue(name, _dotnet_param_value(value))

        if _returns_result_set(command_text):
            self._rows = _read_rows(command.ExecuteReader())
        else:
            command.ExecuteNonQuery()
            self._rows = []
        return self

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> "DotNetSqlCursor":
        for row in rows:
            self.execute(sql, row)
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


def _sql_with_named_parameters(
    sql: str,
    row: tuple[Any, ...],
) -> tuple[str, list[tuple[str, Any]]]:
    command = sql
    params = []
    for index, value in enumerate(row):
        name = f"@p{index}"
        command = command.replace("?", name, 1)
        params.append((name, value))
    return command, params


def _read_rows(reader: Any) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    try:
        while reader.Read():
            rows.append(
                tuple(
                    None if reader.IsDBNull(index) else reader.GetValue(index)
                    for index in range(reader.FieldCount)
                )
            )
    finally:
        reader.Close()
    return rows


def _returns_result_set(command_text: str) -> bool:
    normalized = command_text.lstrip().upper()
    return normalized.startswith("SELECT") or "SELECT @RESULT" in normalized


def _dotnet_param_value(value: Any) -> Any:
    if value is None:
        from System import DBNull

        return DBNull.Value
    # pythonnet 값은 명시적인 .NET 타입으로 넘겨야 SqlParameter 추론 오류가 나지 않는다.
    if isinstance(value, bool):
        from System import Boolean

        return Boolean(value)
    if isinstance(value, int):
        from System import Int32, Int64

        if -(2**31) <= value <= 2**31 - 1:
            return Int32(value)
        return Int64(value)
    if isinstance(value, float):
        from System import Double

        return Double(value)
    if isinstance(value, datetime):
        from System import DateTime

        return DateTime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond // 1000,
        )
    if isinstance(value, date):
        from System import DateTime

        return DateTime(value.year, value.month, value.day)
    if isinstance(value, str):
        from System import String

        return String(value)
    return value


def _dotnet_encrypt_value(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"yes", "true", "mandatory"}:
        return "True"
    if normalized in {"optional"}:
        return "Optional"
    return "False"


def _dotnet_bool_value(value: str) -> str:
    return "True" if value.strip().lower() in {"yes", "true", "1"} else "False"


def _quoted_database_name(database: str) -> str:
    if not database.replace("_", "").isalnum():
        raise ValueError("MSSQL_DATABASE must contain only letters, numbers, or '_'")
    return f"[{database}]"


DAILY_TARGET_REPAIR_SQL = """
IF OBJECT_ID(N'dbo.daily_target', N'U') IS NOT NULL
BEGIN
    ALTER TABLE dbo.daily_target ALTER COLUMN volume_ratio DECIMAL(12, 2) NULL;
    ALTER TABLE dbo.daily_target ALTER COLUMN price_change DECIMAL(12, 2) NULL;
END
"""

TRADING_EVENT_LOG_REPAIR_SQL = """
IF OBJECT_ID(N'dbo.trading_event_log', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.trading_event_log (
        id BIGINT IDENTITY PRIMARY KEY,
        event_id UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID(),
        event_time DATETIME2 NOT NULL,
        created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
        trade_date DATE NULL,
        mode NVARCHAR(20) NULL,
        app_mode NVARCHAR(20) NULL,
        run_id NVARCHAR(100) NULL,
        correlation_id NVARCHAR(100) NULL,
        order_id NVARCHAR(100) NULL,
        order_no NVARCHAR(100) NULL,
        ticker NVARCHAR(32) NULL,
        ticker_name NVARCHAR(200) NULL,
        side NVARCHAR(20) NULL,
        stage NVARCHAR(50) NOT NULL,
        event_type NVARCHAR(80) NOT NULL,
        severity NVARCHAR(20) NOT NULL DEFAULT 'INFO',
        decision NVARCHAR(80) NULL,
        reason_code NVARCHAR(120) NULL,
        reason_label NVARCHAR(300) NULL,
        is_blocking BIT NULL,
        is_final_decision BIT NULL,
        order_submitted BIT NULL,
        buy_allowed BIT NULL,
        sell_allowed BIT NULL,
        quantity INT NULL,
        price_usd DECIMAL(19, 6) NULL,
        order_value_usd DECIMAL(19, 6) NULL,
        actual_value FLOAT NULL,
        threshold_value FLOAT NULL,
        profit_rate FLOAT NULL,
        candidate_source NVARCHAR(80) NULL,
        ranking_selection_mode NVARCHAR(40) NULL,
        strategy_version NVARCHAR(100) NULL,
        settings_snapshot_hash NVARCHAR(100) NULL,
        message NVARCHAR(MAX) NULL,
        details_json NVARCHAR(MAX) NULL
    );
END

IF COL_LENGTH('dbo.trading_event_log', 'event_id') IS NULL
    ALTER TABLE dbo.trading_event_log ADD event_id UNIQUEIDENTIFIER NOT NULL DEFAULT NEWID();

IF COL_LENGTH('dbo.trading_event_log', 'created_at') IS NULL
    ALTER TABLE dbo.trading_event_log ADD created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME();

IF COL_LENGTH('dbo.trading_event_log', 'trade_date') IS NULL
    ALTER TABLE dbo.trading_event_log ADD trade_date DATE NULL;

IF COL_LENGTH('dbo.trading_event_log', 'mode') IS NULL
    ALTER TABLE dbo.trading_event_log ADD mode NVARCHAR(20) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'app_mode') IS NULL
    ALTER TABLE dbo.trading_event_log ADD app_mode NVARCHAR(20) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'run_id') IS NULL
    ALTER TABLE dbo.trading_event_log ADD run_id NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'correlation_id') IS NULL
    ALTER TABLE dbo.trading_event_log ADD correlation_id NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'order_id') IS NULL
    ALTER TABLE dbo.trading_event_log ADD order_id NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'order_no') IS NULL
    ALTER TABLE dbo.trading_event_log ADD order_no NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'ticker') IS NULL
    ALTER TABLE dbo.trading_event_log ADD ticker NVARCHAR(32) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'ticker_name') IS NULL
    ALTER TABLE dbo.trading_event_log ADD ticker_name NVARCHAR(200) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'side') IS NULL
    ALTER TABLE dbo.trading_event_log ADD side NVARCHAR(20) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'stage') IS NULL
    ALTER TABLE dbo.trading_event_log ADD stage NVARCHAR(50) NOT NULL DEFAULT 'UNKNOWN';

IF COL_LENGTH('dbo.trading_event_log', 'event_type') IS NULL
    ALTER TABLE dbo.trading_event_log ADD event_type NVARCHAR(80) NOT NULL DEFAULT 'UNKNOWN';

IF COL_LENGTH('dbo.trading_event_log', 'severity') IS NULL
    ALTER TABLE dbo.trading_event_log ADD severity NVARCHAR(20) NOT NULL DEFAULT 'INFO';

IF COL_LENGTH('dbo.trading_event_log', 'decision') IS NULL
    ALTER TABLE dbo.trading_event_log ADD decision NVARCHAR(80) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'reason_code') IS NULL
    ALTER TABLE dbo.trading_event_log ADD reason_code NVARCHAR(120) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'reason_label') IS NULL
    ALTER TABLE dbo.trading_event_log ADD reason_label NVARCHAR(300) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'is_blocking') IS NULL
    ALTER TABLE dbo.trading_event_log ADD is_blocking BIT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'is_final_decision') IS NULL
    ALTER TABLE dbo.trading_event_log ADD is_final_decision BIT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'order_submitted') IS NULL
    ALTER TABLE dbo.trading_event_log ADD order_submitted BIT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'buy_allowed') IS NULL
    ALTER TABLE dbo.trading_event_log ADD buy_allowed BIT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'sell_allowed') IS NULL
    ALTER TABLE dbo.trading_event_log ADD sell_allowed BIT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'quantity') IS NULL
    ALTER TABLE dbo.trading_event_log ADD quantity INT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'price_usd') IS NULL
    ALTER TABLE dbo.trading_event_log ADD price_usd DECIMAL(19, 6) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'order_value_usd') IS NULL
    ALTER TABLE dbo.trading_event_log ADD order_value_usd DECIMAL(19, 6) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'actual_value') IS NULL
    ALTER TABLE dbo.trading_event_log ADD actual_value FLOAT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'threshold_value') IS NULL
    ALTER TABLE dbo.trading_event_log ADD threshold_value FLOAT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'profit_rate') IS NULL
    ALTER TABLE dbo.trading_event_log ADD profit_rate FLOAT NULL;

IF COL_LENGTH('dbo.trading_event_log', 'candidate_source') IS NULL
    ALTER TABLE dbo.trading_event_log ADD candidate_source NVARCHAR(80) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'ranking_selection_mode') IS NULL
    ALTER TABLE dbo.trading_event_log ADD ranking_selection_mode NVARCHAR(40) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'strategy_version') IS NULL
    ALTER TABLE dbo.trading_event_log ADD strategy_version NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'settings_snapshot_hash') IS NULL
    ALTER TABLE dbo.trading_event_log ADD settings_snapshot_hash NVARCHAR(100) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'message') IS NULL
    ALTER TABLE dbo.trading_event_log ADD message NVARCHAR(MAX) NULL;

IF COL_LENGTH('dbo.trading_event_log', 'details_json') IS NULL
    ALTER TABLE dbo.trading_event_log ADD details_json NVARCHAR(MAX) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_trade_date_time' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_trade_date_time ON dbo.trading_event_log (trade_date, event_time);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_ticker_date' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_ticker_date ON dbo.trading_event_log (ticker, trade_date);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_event_type' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_event_type ON dbo.trading_event_log (event_type, trade_date);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_reason_code' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_reason_code ON dbo.trading_event_log (reason_code, trade_date);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_stage' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_stage ON dbo.trading_event_log (stage, trade_date);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_correlation' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_correlation ON dbo.trading_event_log (correlation_id);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_trading_event_log_order_no' AND object_id = OBJECT_ID('dbo.trading_event_log'))
    CREATE INDEX IX_trading_event_log_order_no ON dbo.trading_event_log (order_no);
"""


def initialize_database(
    connect: Callable[[], Any],
    schema_path: Path | None = None,
) -> None:
    path = schema_path or Path(__file__).resolve().parents[2] / "db" / "schema.sql"
    schema = path.read_text(encoding="utf-8")
    with closing(connect()) as connection:
        connection.cursor().execute(schema)
        connection.commit()


def repair_database_schema(connect: Callable[[], Any]) -> list[dict[str, str]]:
    """Run explicit, idempotent schema repairs for an existing database.

    This function is intentionally separate from ``initialize_database``. It is
    called only by the explicit ``repair-db-schema`` CLI command and must not be
    used by read-only preflight checks.
    """
    with closing(connect()) as connection:
        cursor = connection.cursor()
        cursor.execute(DAILY_TARGET_REPAIR_SQL)
        cursor.execute(TRADING_EVENT_LOG_REPAIR_SQL)
        connection.commit()
    return [
        {
            "name": "daily_target_numeric_columns",
            "action": "executed_if_table_exists",
            "detail": "volume_ratio and price_change are repaired to DECIMAL(12, 2) NULL",
        },
        {
            "name": "trading_event_log",
            "action": "created_or_repaired_if_missing",
            "detail": "trading_event_log table and indexes are ensured idempotently",
        },
    ]
