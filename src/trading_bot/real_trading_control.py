from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from trading_bot.config import APP_MODE_REAL, TradingSettings

CONTROL_PATH = Path("monitor/real_trading_control.json")


@dataclass(frozen=True)
class RealTradingControl:
    app_mode: str
    mock_trading: bool
    env_enabled: bool
    emergency_stop: bool
    auto_trading_enabled: bool
    order_execution_enabled: bool
    order_protection_fail_closed: bool
    manual_enabled: bool
    max_order_krw: int
    max_daily_order_krw: int

    @property
    def orders_unlocked(self) -> bool:
        return (
            self.app_mode == APP_MODE_REAL
            and self.env_enabled
            and not self.emergency_stop
            and self.manual_enabled
        )

    @property
    def mode_label(self) -> str:
        return "실투자 대기" if self.orders_unlocked else "모의투자"

    def to_dict(self) -> dict[str, object]:
        return {
            "appMode": self.app_mode,
            "mockTrading": self.mock_trading,
            "envEnabled": self.env_enabled,
            "realTradingEnabled": self.env_enabled,
            "emergencyStop": self.emergency_stop,
            "realEmergencyStop": self.emergency_stop,
            "realAutoTradingEnabled": self.auto_trading_enabled,
            "realOrderExecutionEnabled": self.order_execution_enabled,
            "realOrderProtectionFailClosed": self.order_protection_fail_closed,
            "manualEnabled": self.manual_enabled,
            "ordersUnlocked": self.orders_unlocked,
            "maxOrderKrw": self.max_order_krw,
            "maxDailyOrderKrw": self.max_daily_order_krw,
        }


def load_real_trading_control(
    settings: TradingSettings,
    path: Path = CONTROL_PATH,
) -> RealTradingControl:
    return RealTradingControl(
        app_mode=settings.app_mode,
        mock_trading=settings.mock_trading,
        env_enabled=settings.real_trading_enabled,
        emergency_stop=settings.real_emergency_stop,
        auto_trading_enabled=settings.real_auto_trading_enabled,
        order_execution_enabled=settings.real_order_execution_enabled,
        order_protection_fail_closed=settings.real_order_protection_fail_closed,
        manual_enabled=_read_manual_enabled(path),
        max_order_krw=settings.real_max_order_krw,
        max_daily_order_krw=settings.real_max_daily_order_krw,
    )


def save_manual_enabled(enabled: bool, path: Path = CONTROL_PATH) -> RealTradingControl:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"manualEnabled": enabled}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    from trading_bot.config import load_settings

    return load_real_trading_control(load_settings(), path)


def _read_manual_enabled(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return bool(payload.get("manualEnabled", False))
