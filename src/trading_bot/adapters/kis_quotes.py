from __future__ import annotations

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.market_data import _required_float


class KisLastPriceReader:
    def __init__(self, kis: KisOverseasClient) -> None:
        self.kis = kis

    def price(self, ticker: str) -> float:
        return _required_float(self.kis.quote(ticker), "last", "LAST")
