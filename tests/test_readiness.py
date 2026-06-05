from datetime import date

from trading_bot import readiness


def test_next_us_trading_day_skips_memorial_day_2026() -> None:
    assert readiness.next_us_trading_day(date(2026, 5, 25)) == date(2026, 5, 26)


def test_mock_trading_readiness_accepts_target_market_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(readiness, "_kis_config_status", lambda: {"configured": True})
    monkeypatch.setattr(readiness, "_mssql_status", lambda **_: {"connected": True})

    state = readiness.mock_trading_readiness(
        tmp_path / "missing.json",
        market_date=date(2026, 5, 25),
    )

    assert not state["ready_for_live_mock_session"]
    assert state["next_us_trading_day"] == "2026-05-26"


class SchemaCursor:
    def __init__(
        self,
        tables: set[str],
        columns: dict[str, set[str]],
    ) -> None:
        self.tables = tables
        self.columns = columns
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []
        self._rows: list[tuple[object, ...]] = []

    def execute(
        self,
        sql: str,
        row: tuple[object, ...] | None = None,
    ) -> "SchemaCursor":
        self.calls.append((sql, row))
        if "INFORMATION_SCHEMA.TABLES" in sql:
            self._rows = [(table,) for table in sorted(self.tables)]
            return self
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            self._rows = [
                (table, column)
                for table in sorted(self.columns)
                for column in sorted(self.columns[table])
            ]
            return self
        for table, column_types in readiness.AUTO_ENSURE_COLUMNS.items():
            for column in column_types:
                if f"dbo.{table}" in sql and f"ADD {column}" in sql:
                    self.columns.setdefault(table, set()).add(column)
        self._rows = []
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class SchemaConnection:
    def __init__(self, cursor: SchemaCursor) -> None:
        self.cursor_value = cursor
        self.commits = 0
        self.closed = False

    def cursor(self) -> SchemaCursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def test_preflight_read_only_reports_trade_and_fill_metadata_columns(monkeypatch) -> None:
    tables = set(readiness.REQUIRED_TABLES)
    columns = {
        table: set(required)
        for table, required in readiness.REQUIRED_COLUMNS.items()
    }
    for table in ("trade_history", "fill_history"):
        columns[table] -= {
            "strategy_version",
            "settings_snapshot_hash",
            "settings_snapshot_json",
        }
    cursor = SchemaCursor(tables, columns)
    connection = SchemaConnection(cursor)

    monkeypatch.setattr(readiness, "pyodbc_connect_factory", lambda: lambda: connection)

    status = readiness._mssql_status()

    assert status["connected"] is True
    assert status["required_columns_ready"] is False
    assert status["schema_column_check"]["repair_schema"] is False
    assert len(
        [
            action
            for action in status["schema_column_check"]["actions"]
            if action["action"] == "read_only_missing"
        ]
    ) == 6
    assert connection.commits == 0
    assert connection.closed is True


def test_repair_schema_adds_trade_and_fill_metadata_columns(monkeypatch) -> None:
    tables = set(readiness.REQUIRED_TABLES)
    columns = {
        table: set(required)
        for table, required in readiness.REQUIRED_COLUMNS.items()
    }
    for table in ("trade_history", "fill_history"):
        columns[table] -= {
            "strategy_version",
            "settings_snapshot_hash",
            "settings_snapshot_json",
        }
    cursor = SchemaCursor(tables, columns)
    connection = SchemaConnection(cursor)

    monkeypatch.setattr(readiness, "pyodbc_connect_factory", lambda: lambda: connection)

    status = readiness._mssql_status(repair_schema=True)

    assert status["connected"] is True
    assert status["required_columns_ready"] is True
    assert status["missing_columns"] == {}
    assert status["schema_column_check"]["before_missing_columns"] == {
        "trade_history": [
            "strategy_version",
            "settings_snapshot_hash",
            "settings_snapshot_json",
        ],
        "fill_history": [
            "strategy_version",
            "settings_snapshot_hash",
            "settings_snapshot_json",
        ],
    }
    assert status["schema_column_check"]["after_missing_columns"] == {}
    assert status["schema_column_check"]["repair_schema"] is True
    assert len(
        [
            action
            for action in status["schema_column_check"]["actions"]
            if action["action"] == "added"
        ]
    ) == 6
    assert connection.commits == 1
    assert connection.closed is True


def test_preflight_reports_required_columns_that_cannot_be_added(monkeypatch) -> None:
    tables = set(readiness.REQUIRED_TABLES)
    columns = {
        table: set(required)
        for table, required in readiness.REQUIRED_COLUMNS.items()
    }
    columns["entry_profit_snapshot"].remove("final_profit_rate")
    cursor = SchemaCursor(tables, columns)
    connection = SchemaConnection(cursor)

    monkeypatch.setattr(readiness, "pyodbc_connect_factory", lambda: lambda: connection)

    status = readiness._mssql_status()

    assert status["required_columns_ready"] is False
    assert status["missing_columns"] == {
        "entry_profit_snapshot": ["final_profit_rate"],
    }
    assert status["warnings"] == [
        "Missing required MSSQL columns in entry_profit_snapshot: final_profit_rate",
    ]


def test_mssql_status_masks_sensitive_error(monkeypatch) -> None:
    monkeypatch.setenv("MSSQL_PASSWORD", "secret-password")

    def connect() -> object:
        raise RuntimeError("Login failed for secret-password")

    monkeypatch.setattr(readiness, "pyodbc_connect_factory", lambda: connect)

    status = readiness._mssql_status()

    assert status == {"connected": False, "error": "Login failed for ***"}
