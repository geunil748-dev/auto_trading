import pytest

from trading_bot.config import TradingSettings
from trading_bot.real_trading_guard import RealOrderCheck, validate_real_order_limits


def test_real_trading_guard_blocks_disabled_ordering() -> None:
    with pytest.raises(PermissionError, match="비활성화"):
        validate_real_order_limits(
            TradingSettings(real_emergency_stop=False),
            RealOrderCheck(order_value_krw=10000, daily_order_value_krw=10000),
        )


def test_real_trading_guard_blocks_emergency_stop() -> None:
    with pytest.raises(PermissionError, match="비상정지"):
        validate_real_order_limits(
            TradingSettings(real_trading_enabled=True),
            RealOrderCheck(order_value_krw=10000, daily_order_value_krw=10000),
        )


def test_real_trading_guard_blocks_order_limit() -> None:
    settings = TradingSettings(real_trading_enabled=True, real_emergency_stop=False)

    with pytest.raises(ValueError, match="1회 주문 한도"):
        validate_real_order_limits(
            settings,
            RealOrderCheck(order_value_krw=100001, daily_order_value_krw=100001),
            manual_enabled=True,
        )


def test_real_trading_guard_requires_screen_unlock() -> None:
    settings = TradingSettings(real_trading_enabled=True, real_emergency_stop=False)

    with pytest.raises(PermissionError, match="화면"):
        validate_real_order_limits(
            settings,
            RealOrderCheck(order_value_krw=10000, daily_order_value_krw=10000),
        )


def test_real_trading_guard_allows_within_limits() -> None:
    settings = TradingSettings(real_trading_enabled=True, real_emergency_stop=False)

    validate_real_order_limits(
        settings,
        RealOrderCheck(order_value_krw=100000, daily_order_value_krw=300000),
        manual_enabled=True,
    )
