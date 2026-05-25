from __future__ import annotations

from typing import Any

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings
from trading_bot.models import AccountState, PositionState


class KisAccountReader:
    def __init__(
        self,
        kis: KisOverseasClient,
        settings: KisSettings,
        reference_ticker: str = "QQQ",
        mock: bool = True,
    ) -> None:
        self.kis = kis
        self.settings = settings
        self.reference_ticker = reference_ticker
        self.mock = mock

    def current_account(self) -> AccountState:
        balance = self._balance()
        buyable = self.kis.buyable_amount(
            self.settings.account_no,
            self.settings.account_product,
            self.reference_ticker,
            mock=self.mock,
        )
        rows = _rows(balance.get("output1"))
        summary = _object(balance.get("output2"))
        invested = sum(_float(row, "ovrs_stck_evlu_amt") for row in rows)
        purchase = sum(_float(row, "frcr_pchs_amt1") for row in rows)
        cash = _first_float(
            _object(buyable.get("output")),
            "ord_psbl_frcr_amt",
            "ovrs_ord_psbl_amt",
            "frcr_ord_psbl_amt1",
        )
        equity = cash + invested
        return AccountState(
            cash_usd=cash,
            equity_usd=equity,
            invested_usd=invested,
            open_positions=sum(_float(row, "ovrs_cblc_qty") > 0 for row in rows),
            daily_profit_rate=_profit_rate(summary, invested, purchase),
        )

    def positions(self) -> list[PositionState]:
        positions: list[PositionState] = []
        for row in _rows(self._balance().get("output1")):
            quantity = int(_float(row, "ovrs_cblc_qty"))
            if quantity < 1:
                continue
            last_price = _first_float(row, "now_pric2")
            entry_price = _first_float(row, "pchs_avg_pric")
            positions.append(
                PositionState(
                    ticker=str(row.get("ovrs_pdno", "")).strip(),
                    entry_price_usd=entry_price,
                    quantity=quantity,
                    last_price_usd=last_price,
                    high_price_usd=max(entry_price, last_price),
                )
            )
        return [item for item in positions if item.ticker and item.entry_price_usd > 0]

    def holdings(self) -> list[dict[str, str]]:
        holdings: list[dict[str, str]] = []
        for row in _rows(self._balance().get("output1")):
            quantity = int(_float(row, "ovrs_cblc_qty"))
            if quantity < 1:
                continue
            ticker = str(row.get("ovrs_pdno", "")).strip()
            prices = self._session_prices(ticker)
            holdings.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("ovrs_item_name", "")).strip(),
                    "quantity": str(quantity),
                    "averagePrice": _usd(_first_float(row, "pchs_avg_pric")),
                    "openPrice": prices["openPrice"],
                    "closePrice": prices["closePrice"],
                    "totalPrice": _usd(_first_float(row, "ovrs_stck_evlu_amt")),
                }
            )
        return [item for item in holdings if item["ticker"]]

    def _balance(self) -> dict[str, Any]:
        return self.kis.balance(
            self.settings.account_no,
            self.settings.account_product,
            mock=self.mock,
        )

    def _session_prices(self, ticker: str) -> dict[str, str]:
        if not ticker:
            return {"openPrice": "-", "closePrice": "-"}
        try:
            quote = self.kis.quote(ticker)
            daily = self.kis.daily_prices(ticker)
        except (AttributeError, ValueError):
            return {"openPrice": "-", "closePrice": "-"}
        row = daily[0] if daily else {}
        open_price = _first_float(row, "open", "OPEN", "ovrs_nmix_oprc")
        if open_price <= 0:
            open_price = _first_float(quote, "open", "OPEN")
        close_price = _first_float(
            row,
            "clos",
            "CLOS",
            "close",
            "CLOSE",
            "ovrs_nmix_prpr",
        )
        if close_price <= 0:
            close_price = _first_float(quote, "last", "LAST", "base", "BASE", "pcls")
        return {
            "openPrice": _optional_usd(open_price),
            "closePrice": _optional_usd(close_price),
        }


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(row: dict[str, Any], field: str) -> float:
    value = row.get(field, 0)
    return float(str(value).replace(",", "") or 0)


def _first_float(row: dict[str, Any], *fields: str) -> float:
    for field in fields:
        if row.get(field) not in (None, ""):
            return _float(row, field)
    return 0.0


def _profit_rate(summary: dict[str, Any], invested: float, purchase: float) -> float:
    total_rate = _first_float(summary, "tot_pftrt")
    if total_rate:
        return total_rate / 100
    if purchase <= 0:
        return 0.0
    return (invested - purchase) / purchase


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _optional_usd(value: float) -> str:
    return "-" if value <= 0 else _usd(value)
