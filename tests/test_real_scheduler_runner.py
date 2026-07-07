from trading_bot.config import APP_MODE_REAL, TradingSettings
from trading_bot.real_scheduler_runner import run_real_scheduler, real_scheduler_status


def test_real_scheduler_skeleton_is_read_only_by_default() -> None:
    status = real_scheduler_status(
        TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=False,
        )
    )

    assert status["readOnly"] is True
    assert status["orderStage"] == "skipped"
    assert status["reason"] == "REAL_AUTO_TRADING_DISABLED"


def test_run_real_scheduler_writes_separate_heartbeat(monkeypatch, tmp_path, capsys) -> None:
    heartbeat = tmp_path / "real_scheduler_heartbeat.json"
    mock_heartbeat = tmp_path / "scheduler_heartbeat.json"
    monkeypatch.setattr(
        "trading_bot.real_scheduler_runner.REAL_SCHEDULER_HEARTBEAT_PATH",
        heartbeat,
    )
    monkeypatch.setattr(
        "trading_bot.real_scheduler_runner.load_settings",
        lambda: TradingSettings(app_mode=APP_MODE_REAL),
    )

    run_real_scheduler(tmp_path / "real_state.json")

    assert heartbeat.exists()
    assert not mock_heartbeat.exists()
    assert "real_scheduler_heartbeat" in capsys.readouterr().out
