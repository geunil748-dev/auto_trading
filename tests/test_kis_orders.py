import pytest

from trading_bot.adapters.kis_orders_mock import KisMockBuySubmitter, KisMockSellSubmitter
from trading_bot.adapters.kis_orders_real import KisRealBuySubmitter, KisRealSellSubmitter
from trading_bot.config import APP_MODE_REAL, APP_MODE_TEST, KisSettings, TradingSettings
from trading_bot.models import BuyIntent, SellIntent


class FakeKis:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def limit_order(self, *args: object, **kwargs: object) -> dict[str, object]:
        self.calls.append(args + (kwargs,))
        return {"rt_cd": "0", "output": {"ODNO": "1"}}


def _kis_settings() -> KisSettings:
    return KisSettings("app", "secret", "12345678", "01", "https://kis.example")


def _buy_intent() -> BuyIntent:
    return BuyIntent("AAA", 2, 10.5, 21, 0.05)


def _sell_intent() -> SellIntent:
    return SellIntent("AAA", 2, 10.1, "TRAILING_STOP")


def _real_settings(**overrides) -> TradingSettings:
    values = {
        "app_mode": APP_MODE_REAL,
        "real_trading_enabled": True,
        "real_emergency_stop": False,
        "real_order_execution_enabled": True,
    }
    values.update(overrides)
    return TradingSettings(**values)


def _real_buy_submitter(
    kis: FakeKis,
    settings: TradingSettings,
    *,
    manual_enabled: bool = True,
    order_value_krw: int = 10000,
    daily_order_value_krw: int = 10000,
    allow_real_api_call: bool = True,
    require_auto_trading: bool = False,
) -> KisRealBuySubmitter:
    return KisRealBuySubmitter(
        kis,
        _kis_settings(),
        settings,
        manual_enabled=manual_enabled,
        order_value_krw=lambda intent: order_value_krw,
        daily_order_value_krw=lambda intent: daily_order_value_krw,
        allow_real_api_call=allow_real_api_call,
        require_auto_trading=require_auto_trading,
    )


def test_mock_submitters_always_call_kis_with_mock_true_even_in_real_app_mode() -> None:
    kis = FakeKis()
    settings = _kis_settings()
    TradingSettings(app_mode=APP_MODE_REAL)

    KisMockBuySubmitter(kis, settings).submit(_buy_intent())
    KisMockSellSubmitter(kis, settings).submit(_sell_intent())

    assert kis.calls[0][-1] == {"mock": True}
    assert kis.calls[1][-1] == {"mock": True}


@pytest.mark.parametrize(
    ("settings", "manual_enabled", "match"),
    (
        (
            TradingSettings(
                app_mode=APP_MODE_TEST,
                real_trading_enabled=True,
                real_emergency_stop=False,
                real_order_execution_enabled=True,
            ),
            True,
            "APP_MODE=real",
        ),
        (_real_settings(real_trading_enabled=False), True, "비활성화"),
        (_real_settings(real_emergency_stop=True), True, "비상정지"),
        (_real_settings(), False, "화면"),
        (_real_settings(real_order_execution_enabled=False), True, "REAL_ORDER_EXECUTION_ENABLED"),
    ),
)
def test_real_buy_submitter_blocks_guard_failures_without_api_call(
    settings: TradingSettings,
    manual_enabled: bool,
    match: str,
) -> None:
    kis = FakeKis()
    submitter = _real_buy_submitter(kis, settings, manual_enabled=manual_enabled)

    with pytest.raises(PermissionError, match=match):
        submitter.submit(_buy_intent())

    assert kis.calls == []


def test_real_buy_submitter_blocks_order_limit_without_api_call() -> None:
    kis = FakeKis()
    submitter = _real_buy_submitter(
        kis,
        _real_settings(real_max_order_krw=100000),
        order_value_krw=100001,
    )

    with pytest.raises(ValueError, match="1회 주문 한도"):
        submitter.submit(_buy_intent())

    assert kis.calls == []


def test_real_buy_submitter_blocks_when_code_level_api_gate_is_closed() -> None:
    kis = FakeKis()
    submitter = _real_buy_submitter(
        kis,
        _real_settings(),
        allow_real_api_call=False,
    )

    with pytest.raises(PermissionError, match="현재 단계"):
        submitter.submit(_buy_intent())

    assert kis.calls == []


def test_real_buy_submitter_blocks_auto_order_without_auto_switch() -> None:
    kis = FakeKis()
    submitter = _real_buy_submitter(
        kis,
        _real_settings(real_auto_trading_enabled=False),
        require_auto_trading=True,
    )

    with pytest.raises(PermissionError, match="REAL_AUTO_TRADING_ENABLED"):
        submitter.submit(_buy_intent())

    assert kis.calls == []


def test_real_buy_submitter_can_call_mock_false_only_for_enabled_fake_client() -> None:
    kis = FakeKis()
    submitter = _real_buy_submitter(kis, _real_settings())

    submitter.submit(_buy_intent())

    assert kis.calls[0][:6] == ("12345678", "01", "AAA", 2, 10.5, "buy")
    assert kis.calls[0][-1] == {"mock": False}


def test_real_sell_submitter_can_call_mock_false_only_for_enabled_fake_client() -> None:
    kis = FakeKis()
    submitter = KisRealSellSubmitter(
        kis,
        _kis_settings(),
        _real_settings(),
        manual_enabled=True,
        order_value_krw=lambda intent: 10000,
        daily_order_value_krw=lambda intent: 10000,
        allow_real_api_call=True,
    )

    submitter.submit(_sell_intent())

    assert kis.calls[0][:6] == ("12345678", "01", "AAA", 2, 10.1, "sell")
    assert kis.calls[0][-1] == {"mock": False}
