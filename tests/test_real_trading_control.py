from trading_bot.config import TradingSettings
from trading_bot.real_trading_control import (
    load_real_trading_control,
    save_manual_enabled,
)


def test_real_trading_control_stays_locked_without_all_switches(tmp_path) -> None:
    control = load_real_trading_control(
        TradingSettings(real_trading_enabled=True, real_emergency_stop=True),
        tmp_path / "control.json",
    )

    assert control.mode_label == "모의투자"
    assert control.orders_unlocked is False


def test_real_trading_control_reads_manual_unlock(tmp_path, monkeypatch) -> None:
    path = tmp_path / "control.json"
    monkeypatch.setenv("APP_MODE", "real")
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")

    control = save_manual_enabled(True, path)

    assert control.manual_enabled is True
    assert control.orders_unlocked is True
    assert control.mode_label == "실투자 대기"
