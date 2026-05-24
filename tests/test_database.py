from trading_bot.database import (
    initialize_database,
    mssql_dsn_from_env,
    mssql_sqlclient_connection_string_from_env,
)


class Cursor:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def execute(self, script: str) -> None:
        self.scripts.append(script)


class Connection:
    def __init__(self) -> None:
        self.cursor_value = Cursor()
        self.commits = 0
        self.closed = False

    def cursor(self) -> Cursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def test_initialize_database_executes_schema_and_commits(tmp_path) -> None:
    schema = tmp_path / "schema.sql"
    schema.write_text("CREATE TABLE sample (id INT);", encoding="utf-8")
    connection = Connection()

    initialize_database(lambda: connection, schema)

    assert connection.cursor_value.scripts == ["CREATE TABLE sample (id INT);"]
    assert connection.commits == 1
    assert connection.closed


def test_mssql_dsn_from_env_builds_connection_string(monkeypatch) -> None:
    monkeypatch.delenv("MSSQL_DSN", raising=False)
    monkeypatch.setenv("MSSQL_HOST", "localhost")
    monkeypatch.setenv("MSSQL_PORT", "1433")
    monkeypatch.setenv("MSSQL_DATABASE", "TradingBot")
    monkeypatch.setenv("MSSQL_USERNAME", "sa")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")
    monkeypatch.setenv("MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
    monkeypatch.setenv("MSSQL_ENCRYPT", "no")
    monkeypatch.setenv("MSSQL_TRUST_SERVER_CERTIFICATE", "yes")

    assert mssql_dsn_from_env() == (
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=localhost,1433;"
        "Database=TradingBot;"
        "Uid=sa;"
        "Pwd=secret;"
        "Encrypt=no;"
        "TrustServerCertificate=yes;"
    )


def test_mssql_dsn_ignores_zero_port(monkeypatch) -> None:
    monkeypatch.delenv("MSSQL_DSN", raising=False)
    monkeypatch.setenv("MSSQL_HOST", "localhost")
    monkeypatch.setenv("MSSQL_PORT", "0")
    monkeypatch.setenv("MSSQL_DATABASE", "TradingBot")
    monkeypatch.setenv("MSSQL_USERNAME", "sa")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")

    assert "Server=localhost;" in mssql_dsn_from_env()


def test_mssql_sqlclient_connection_string_from_env(monkeypatch) -> None:
    monkeypatch.delenv("MSSQL_DSN", raising=False)
    monkeypatch.setenv("MSSQL_HOST", "localhost")
    monkeypatch.setenv("MSSQL_PORT", "1433")
    monkeypatch.setenv("MSSQL_DATABASE", "TradingBot")
    monkeypatch.setenv("MSSQL_USERNAME", "sa")
    monkeypatch.setenv("MSSQL_PASSWORD", "secret")
    monkeypatch.setenv("MSSQL_ENCRYPT", "no")
    monkeypatch.setenv("MSSQL_TRUST_SERVER_CERTIFICATE", "yes")

    assert mssql_sqlclient_connection_string_from_env() == (
        "Server=localhost,1433;"
        "Database=TradingBot;"
        "User ID=sa;"
        "Password=secret;"
        "Encrypt=False;"
        "TrustServerCertificate=True;"
        "Connection Timeout=5"
    )
