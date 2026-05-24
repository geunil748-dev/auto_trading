import json

from trading_bot.monitor_api import MonitorStateReader, authorize_bearer


def test_monitor_state_reader_and_bearer_gate(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"targets": [["AAA"]]}), encoding="utf-8")

    assert MonitorStateReader(state).read() == {"targets": [["AAA"]]}
    assert authorize_bearer("Bearer secret", "secret")
    assert not authorize_bearer("Bearer other", "secret")
    assert not authorize_bearer(None, "")
