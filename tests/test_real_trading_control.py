import json

from trading_bot.config import APP_MODE_REAL, APP_MODE_TEST, TradingSettings
from trading_bot.real_trading_control import (
    load_real_trading_control,
    save_manual_enabled,
)


def test_real_trading_control_stays_locked_without_all_switches(tmp_path) -> None:
    control = load_real_trading_control(
        TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=True,
        ),
        tmp_path / "control.json",
    )

    assert control.mode_label == "모의투자"
    assert control.orders_unlocked is False


def test_real_trading_control_stays_locked_in_test_mode_even_when_switches_open(
    tmp_path,
) -> None:
    path = tmp_path / "control.json"
    path.write_text(json.dumps({"manualEnabled": True}), encoding="utf-8")

    control = load_real_trading_control(
        TradingSettings(
            app_mode=APP_MODE_TEST,
            real_trading_enabled=True,
            real_emergency_stop=False,
        ),
        path,
    )

    assert control.orders_unlocked is False
    assert control.to_dict()["appMode"] == "test"
    assert control.to_dict()["mockTrading"] is True


def test_real_trading_control_reads_manual_unlock(tmp_path, monkeypatch) -> None:
    path = tmp_path / "control.json"
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")

    control = save_manual_enabled(True, path)

    assert control.manual_enabled is True
    assert control.orders_unlocked is True
    assert control.mode_label == "실투자 대기"
    assert control.to_dict()["appMode"] == "real"


def test_save_manual_enabled_cannot_unlock_test_mode(tmp_path, monkeypatch) -> None:
    path = tmp_path / "control.json"
    monkeypatch.setattr("trading_bot.config.load_dotenv", None)
    monkeypatch.setenv("APP_MODE", "test")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")

    control = save_manual_enabled(True, path)

    assert control.app_mode == "test"
    assert control.env_enabled is False
    assert control.emergency_stop is True
    assert control.manual_enabled is True
    assert control.orders_unlocked is False
