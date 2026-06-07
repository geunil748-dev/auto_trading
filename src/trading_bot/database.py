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
        connection.cursor().execute(DAILY_TARGET_REPAIR_SQL)
        connection.commit()
    return [
        {
            "name": "daily_target_numeric_columns",
            "action": "executed_if_table_exists",
            "detail": "volume_ratio and price_change are repaired to DECIMAL(12, 2) NULL",
        }
    ]
