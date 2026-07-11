from pathlib import Path

import pytest

from trading_bot.apscheduler_runner import run_scheduler


def test_scheduler_rejects_invalid_settings_before_runtime_side_effects(
    monkeypatch,
    tmp_path: Path,
) -> None:
    kis_loaded = False

    def invalid_settings():
        raise ValueError("INTRADAY_MISSING_DATA_POLICY")

    def load_kis():
        nonlocal kis_loaded
        kis_loaded = True
        raise AssertionError("KIS settings must not load after invalid strategy settings")

    monkeypatch.setattr("trading_bot.apscheduler_runner.load_settings", invalid_settings)
    monkeypatch.setattr("trading_bot.apscheduler_runner.load_kis_settings", load_kis)
    monitor_state = tmp_path / "monitor" / "live_state.json"

    with pytest.raises(ValueError, match="INTRADAY_MISSING_DATA_POLICY"):
        run_scheduler(monitor_state)

    assert kis_loaded is False
    assert not (monitor_state.parent / "scheduler_heartbeat.json").exists()
