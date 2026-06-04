import json
import os
import time

from trading_bot.monitor_api import MonitorStateReader, authorize_bearer
from trading_bot.monitor_server import _DashboardStateReader, _health_state, _setting_float
from trading_bot.repositories import SqlServerMonitorRepository


def test_monitor_state_reader_and_bearer_gate(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"targets": [["AAA"]]}), encoding="utf-8")

    assert MonitorStateReader(state).read() == {"targets": [["AAA"]]}
    assert authorize_bearer("Bearer secret", "secret")
    assert not authorize_bearer("Bearer other", "secret")
    assert not authorize_bearer(None, "")


def test_setting_float_preserves_current_value_when_partial_payload() -> None:
    current = {"stopLossPercent": 5.0, "takeProfitPercent": 10.0}

    assert _setting_float({}, "stopLossPercent", current) == 5.0
    assert _setting_float({"takeProfitPercent": "12.5"}, "takeProfitPercent", current) == 12.5


def test_dashboard_reader_falls_back_to_cached_state_when_sql_fails(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "account": {"cashUsd": "$1.00"},
                "targets": [["AAA"]],
                "logs": [["09:00:00", "INFO", "cached"]],
            }
        ),
        encoding="utf-8",
    )

    class BrokenSqlReader:
        def read(self) -> dict[str, object]:
            raise RuntimeError("No module named 'clr'")

    payload = _DashboardStateReader(BrokenSqlReader(), MonitorStateReader(state)).read()

    assert payload["accounts"]["mock"]["account"]["cashUsd"] == "$1.00"
    assert payload["accounts"]["mock"]["targets"] == [["AAA"]]
    assert payload["sql"] == {"connected": False, "error": "No module named 'clr'"}


def test_health_state_is_read_only_and_reports_components(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    heartbeat = tmp_path / "scheduler_heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(state, (now, now))
    os.utime(heartbeat, (now, now))

    monkeypatch.setattr("trading_bot.monitor_server._database_health", lambda: {"connected": True})
    monkeypatch.setattr(
        "trading_bot.monitor_server._dependency_health",
        lambda: {"dependency_status": "ok", "clr_import": "ok", "clr_error": None},
    )
    payload = _health_state(state)

    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["dependency_status"] == "ok"
    assert payload["clr_import"] == "ok"
    assert payload["db_connected"] is True
    assert payload["monitor_state_status"] == "fresh"
    assert payload["database"] == {"connected": True}
    assert payload["monitor"]["ok"] is True
    assert payload["scheduler"]["monitor_state_exists"] is True
    assert payload["scheduler"]["status"] == "running"


def test_health_state_reports_degraded_dependency(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    heartbeat = tmp_path / "scheduler_heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(state, (now, now))
    os.utime(heartbeat, (now, now))

    monkeypatch.setattr("trading_bot.monitor_server._database_health", lambda: {"connected": False, "configured": True})
    monkeypatch.setattr(
        "trading_bot.monitor_server._dependency_health",
        lambda: {
            "dependency_status": "fail",
            "clr_import": "fail",
            "clr_error": "No module named 'clr'",
        },
    )

    payload = _health_state(state)

    assert payload["ok"] is False
    assert payload["status"] == "degraded"
    assert payload["dependency_status"] == "fail"
    assert payload["clr_import"] == "fail"
    assert payload["db_connected"] is False


def test_scheduler_health_uses_recent_heartbeat_when_monitor_state_is_stale(
    tmp_path,
    monkeypatch,
) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    heartbeat = tmp_path / "scheduler_heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(state, (now - 3600, now - 3600))
    os.utime(heartbeat, (now, now))

    monkeypatch.setattr("trading_bot.monitor_server._database_health", lambda: {"connected": True})
    payload = _health_state(state)

    assert payload["scheduler"]["status"] == "running"
    assert payload["scheduler"]["heartbeat_status"] == "recent"
    assert payload["scheduler"]["monitor_state_status"] == "stale"


def test_scheduler_health_reports_stale_heartbeat(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    heartbeat = tmp_path / "scheduler_heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(state, (now, now))
    os.utime(heartbeat, (now - 3600, now - 3600))

    monkeypatch.setattr("trading_bot.monitor_server._database_health", lambda: {"connected": True})
    payload = _health_state(state)

    assert payload["scheduler"]["status"] == "stale_heartbeat"
    assert payload["scheduler"]["heartbeat_status"] == "stale"
    assert payload["scheduler"]["monitor_state_status"] == "recent"


def test_monitor_repository_has_trade_history_schema_guard() -> None:
    repository = SqlServerMonitorRepository(lambda: object())

    repository._ensure_trade_history_columns()
