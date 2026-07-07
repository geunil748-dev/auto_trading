from __future__ import annotations

from collections.abc import Callable

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import BuyIntent, SellIntent
from trading_bot.real_trading_guard import (
    RealOrderCheck,
    ensure_real_trading_allowed,
    validate_real_order_limits,
)

OrderIntent = BuyIntent | SellIntent
OrderValueKrw = Callable[[OrderIntent], int]


class KisRealBuySubmitter:
    def __init__(
        self,
        kis: KisOverseasClient,
        kis_settings: KisSettings,
        trading_settings: TradingSettings,
        *,
        manual_enabled: bool,
        order_value_krw: OrderValueKrw | None = None,
        daily_order_value_krw: OrderValueKrw | None = None,
        allow_real_api_call: bool = False,
        require_auto_trading: bool = False,
    ) -> None:
        self.kis = kis
        self.kis_settings = kis_settings
        self.trading_settings = trading_settings
        self.manual_enabled = manual_enabled
        self.order_value_krw = order_value_krw or _fail_closed_order_value_krw
        self.daily_order_value_krw = daily_order_value_krw or _fail_closed_daily_value_krw
        self.allow_real_api_call = allow_real_api_call
        self.require_auto_trading = require_auto_trading

    def submit(self, intent: BuyIntent) -> dict[str, object]:
        _validate_real_submit_allowed(
            self.trading_settings,
            self.manual_enabled,
            RealOrderCheck(
                order_value_krw=self.order_value_krw(intent),
                daily_order_value_krw=self.daily_order_value_krw(intent),
            ),
            allow_real_api_call=self.allow_real_api_call,
            require_auto_trading=self.require_auto_trading,
        )
        return _ensure_success(self.kis.limit_order(
            self.kis_settings.account_no,
            self.kis_settings.account_product,
            intent.ticker,
            intent.quantity,
            intent.limit_price_usd,
            "buy",
            mock=False,
        ))


class KisRealSellSubmitter:
    def __init__(
        self,
        kis: KisOverseasClient,
        kis_settings: KisSettings,
        trading_settings: TradingSettings,
        *,
        manual_enabled: bool,
        order_value_krw: OrderValueKrw | None = None,
        daily_order_value_krw: OrderValueKrw | None = None,
        allow_real_api_call: bool = False,
        require_auto_trading: bool = False,
    ) -> None:
        self.kis = kis
        self.kis_settings = kis_settings
        self.trading_settings = trading_settings
        self.manual_enabled = manual_enabled
        self.order_value_krw = order_value_krw or _fail_closed_order_value_krw
        self.daily_order_value_krw = daily_order_value_krw or _fail_closed_daily_value_krw
        self.allow_real_api_call = allow_real_api_call
        self.require_auto_trading = require_auto_trading

    def submit(self, intent: SellIntent) -> dict[str, object]:
        _validate_real_submit_allowed(
            self.trading_settings,
            self.manual_enabled,
            RealOrderCheck(
                order_value_krw=self.order_value_krw(intent),
                daily_order_value_krw=self.daily_order_value_krw(intent),
            ),
            allow_real_api_call=self.allow_real_api_call,
            require_auto_trading=self.require_auto_trading,
        )
        return _ensure_success(self.kis.limit_order(
            self.kis_settings.account_no,
            self.kis_settings.account_product,
            intent.ticker,
            intent.quantity,
            intent.limit_price_usd,
            "sell",
            mock=False,
        ))


class KisRealOrderCanceller:
    def __init__(
        self,
        kis: KisOverseasClient,
        kis_settings: KisSettings,
        trading_settings: TradingSettings,
        *,
        manual_enabled: bool,
        allow_real_api_call: bool = False,
        require_auto_trading: bool = False,
    ) -> None:
        self.kis = kis
        self.kis_settings = kis_settings
        self.trading_settings = trading_settings
        self.manual_enabled = manual_enabled
        self.allow_real_api_call = allow_real_api_call
        self.require_auto_trading = require_auto_trading

    def cancel(self, request: dict[str, object]) -> dict[str, object]:
        _validate_real_submit_allowed(
            self.trading_settings,
            self.manual_enabled,
            RealOrderCheck(order_value_krw=0, daily_order_value_krw=0),
            allow_real_api_call=self.allow_real_api_call,
            require_auto_trading=self.require_auto_trading,
        )
        return _ensure_success(self.kis.cancel_order(
            self.kis_settings.account_no,
            self.kis_settings.account_product,
            str(request["ticker"]),
            str(request["order_no"]),
            int(request["quantity"]),
            appointed_order_no=str(request.get("appointed_order_no", "")),
            mock=False,
        ))


def _validate_real_submit_allowed(
    settings: TradingSettings,
    manual_enabled: bool,
    check: RealOrderCheck,
    *,
    allow_real_api_call: bool,
    require_auto_trading: bool,
) -> None:
    ensure_real_trading_allowed(settings, manual_enabled=manual_enabled)
    if not settings.real_order_execution_enabled:
        raise PermissionError("REAL_ORDER_EXECUTION_ENABLED=false 상태라 실투자 주문 API 호출을 차단합니다.")
    if require_auto_trading and not settings.real_auto_trading_enabled:
        raise PermissionError("REAL_AUTO_TRADING_ENABLED=false 상태라 자동 실투자 주문을 차단합니다.")
    if not allow_real_api_call:
        raise PermissionError("실투자 주문 API 호출은 현재 단계에서 비활성화되어 있습니다.")
    validate_real_order_limits(settings, check, manual_enabled=manual_enabled)


def _fail_closed_order_value_krw(intent: OrderIntent) -> int:
    return 10**18


def _fail_closed_daily_value_krw(intent: OrderIntent) -> int:
    return 10**18


def _ensure_success(response: dict[str, object]) -> dict[str, object]:
    if str(response.get("rt_cd", "0")) not in ("", "0"):
        message = response.get("msg1") or response.get("msg_cd") or "KIS order failed"
        raise RuntimeError(str(message))
    return response
