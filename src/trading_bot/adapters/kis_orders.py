from __future__ import annotations

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings
from trading_bot.models import BuyIntent, SellIntent


class KisMockBuySubmitter:
    def __init__(self, kis: KisOverseasClient, settings: KisSettings) -> None:
        self.kis = kis
        self.settings = settings

    def submit(self, intent: BuyIntent) -> dict[str, object]:
        return self.kis.limit_order(
            self.settings.account_no,
            self.settings.account_product,
            intent.ticker,
            intent.quantity,
            intent.limit_price_usd,
            "buy",
            mock=True,
        )


class KisMockSellSubmitter:
    def __init__(self, kis: KisOverseasClient, settings: KisSettings) -> None:
        self.kis = kis
        self.settings = settings

    def submit(self, intent: SellIntent) -> dict[str, object]:
        return self.kis.limit_order(
            self.settings.account_no,
            self.settings.account_product,
            intent.ticker,
            intent.quantity,
            intent.limit_price_usd,
            "sell",
            mock=True,
        )


class KisMockOrderCanceller:
    def __init__(self, kis: KisOverseasClient, settings: KisSettings) -> None:
        self.kis = kis
        self.settings = settings

    def cancel(self, request: dict[str, object]) -> dict[str, object]:
        return self.kis.cancel_order(
            self.settings.account_no,
            self.settings.account_product,
            str(request["ticker"]),
            str(request["order_no"]),
            int(request["quantity"]),
            appointed_order_no=str(request.get("appointed_order_no", "")),
            mock=True,
        )
