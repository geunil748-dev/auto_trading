import os
import sys
import time
import types

from trading_bot.scheduler_guard import (
    guarded_trading_skip,
    state_age_seconds,
    trading_cycle_skip_reason,
)


class Cursor:
    def __init__(self) -> None:
        self.executed = []

    def execute(self, query: str) -> None:
        self.executed.append(query)

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class Connection:
    def __init__(self) -> None:
        self.closed = False
        self.cursor_obj = Cursor()

    def cursor(self) -> Cursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def _stub_ready_environment(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "clr", types.ModuleType("clr"))
    monkeypatch.setattr("trading_bot.scheduler_guard.mssql_dsn_from_env", lambda: "dsn")
    monkeypatch.setattr(
        "trading_bot.scheduler_guard.pyodbc_connect_factory",
        lambda: lambda: Connection(),
    )


def test_guarded_trading_skip_returns_none_without_guard() -> None:
    assert guarded_trading_skip(None) is None


def test_guarded_trading_skip_returns_none_when_guard_allows() -> None:
    assert guarded_trading_skip(lambda: None) is None


def test_guarded_trading_skip_returns_guard_reason() -> None:
    reason = "SKIP trading cycle: monitor degraded reason=db_connected=false"

    assert guarded_trading_skip(lambda: reason) == reason


def test_state_age_seconds_returns_none_for_missing_file(tmp_path) -> None:
    assert state_age_seconds(tmp_path / "missing.json") is None


def test_state_age_seconds_uses_file_mtime(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    old_time = time.time() - 42
    os.utime(state_path, (old_time, old_time))

    age = state_age_seconds(state_path)

    assert age is not None
    assert 40 <= age <= 45


def test_trading_cycle_skip_reason_returns_none_for_ready_state(monkeypatch, tmp_path) -> None:
    _stub_ready_environment(monkeypatch)
    state_path = tmp_path / "state.json"
    state_path.write_text("not-json-but-existing", encoding="utf-8")

    assert trading_cycle_skip_reason(state_path) is None


def test_trading_cycle_skip_reason_reports_missing_state(monkeypatch, tmp_path) -> None:
    _stub_ready_environment(monkeypatch)

    assert (
        trading_cycle_skip_reason(tmp_path / "missing.json")
        == "SKIP trading cycle: monitor degraded reason=state=missing"
    )


def test_trading_cycle_skip_reason_reports_stale_state(monkeypatch, tmp_path) -> None:
    _stub_ready_environment(monkeypatch)
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    old_time = time.time() - 700
    os.utime(state_path, (old_time, old_time))

    reason = trading_cycle_skip_reason(state_path)

    assert reason is not None
    assert reason.startswith("SKIP trading cycle: monitor degraded reason=state=stale age_seconds=")
    assert "recovery=inspect_scheduler_state_write" in reason


def test_trading_cycle_skip_reason_reports_missing_db_config(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "clr", types.ModuleType("clr"))
    monkeypatch.setattr("trading_bot.scheduler_guard.mssql_dsn_from_env", lambda: "")
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    assert (
        trading_cycle_skip_reason(state_path)
        == "SKIP trading cycle: monitor degraded reason=db_configured=false"
    )


def test_trading_cycle_skip_reason_reports_db_connection_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "clr", types.ModuleType("clr"))
    monkeypatch.setattr("trading_bot.scheduler_guard.mssql_dsn_from_env", lambda: "dsn")
    monkeypatch.setattr(
        "trading_bot.scheduler_guard.pyodbc_connect_factory",
        lambda: lambda: (_ for _ in ()).throw(RuntimeError("MSSQL_PASSWORD=secret")),
    )
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    assert (
        trading_cycle_skip_reason(state_path)
        == "SKIP trading cycle: monitor degraded reason=db_connected=false"
    )


def test_trading_cycle_skip_reason_reports_clr_import_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "clr", None)
    monkeypatch.setattr("trading_bot.scheduler_guard.mssql_dsn_from_env", lambda: "dsn")
    monkeypatch.setattr(
        "trading_bot.scheduler_guard.pyodbc_connect_factory",
        lambda: lambda: Connection(),
    )
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    assert (
        trading_cycle_skip_reason(state_path)
        == "SKIP trading cycle: monitor degraded reason=clr_import=fail"
    )
