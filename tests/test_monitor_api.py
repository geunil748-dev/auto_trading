import json
import os
import time

from trading_bot.monitor_api import MonitorStateReader, authorize_bearer
from trading_bot.monitor_server import _health_state, _setting_float
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


def test_health_state_is_read_only_and_reports_components(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(state, (now, now))

    monkeypatch.setattr("trading_bot.monitor_server._database_health", lambda: {"connected": True})
    payload = _health_state(state)

    assert payload["ok"] is True
    assert payload["database"] == {"connected": True}
    assert payload["monitor"]["ok"] is True
    assert payload["scheduler"]["monitor_state_exists"] is True
    assert payload["scheduler"]["status"] == "recent"


def test_monitor_repository_has_trade_history_schema_guard() -> None:
    repository = SqlServerMonitorRepository(lambda: object())

    repository._ensure_trade_history_columns()
