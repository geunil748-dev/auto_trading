from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import APP_MODE_REAL, TradingSettings


@dataclass(frozen=True)
class RealOrderCheck:
    order_value_krw: int
    daily_order_value_krw: int


def ensure_real_trading_allowed(
    settings: TradingSettings,
    manual_enabled: bool = False,
) -> None:
    if settings.app_mode != APP_MODE_REAL:
        raise PermissionError("실투자 주문은 APP_MODE=real에서만 허용됩니다.")
    if settings.real_emergency_stop:
        raise PermissionError("실투자 비상정지가 켜져 있습니다.")
    if not settings.real_trading_enabled:
        raise PermissionError("실투자 주문 기능이 비활성화되어 있습니다.")
    if not manual_enabled:
        raise PermissionError("화면에서 실투자 주문 허용이 켜져 있지 않습니다.")


def validate_real_order_limits(
    settings: TradingSettings,
    check: RealOrderCheck,
    manual_enabled: bool = False,
) -> None:
    ensure_real_trading_allowed(settings, manual_enabled=manual_enabled)
    if check.order_value_krw > settings.real_max_order_krw:
        raise ValueError("실투자 1회 주문 한도를 초과했습니다.")
    if check.daily_order_value_krw > settings.real_max_daily_order_krw:
        raise ValueError("실투자 일일 주문 한도를 초과했습니다.")
