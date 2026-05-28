import json

from trading_bot.monitor_api import MonitorStateReader, authorize_bearer
from trading_bot.monitor_server import _setting_float


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
