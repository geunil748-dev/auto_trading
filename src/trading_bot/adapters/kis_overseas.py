from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.models import RankedStock

PRICE_FLUCT_PATH = "/uapi/overseas-stock/v1/ranking/price-fluct"
PRICE_FLUCT_TR_ID = "HHDFS76260000"
TRADE_VOLUME_PATH = "/uapi/overseas-stock/v1/ranking/trade-vol"
TRADE_VOLUME_TR_ID = "HHDFS76310010"
QUOTE_PATH = "/uapi/overseas-price/v1/quotations/price"
QUOTE_TR_ID = "HHDFS00000300"
DAILY_PRICE_PATH = "/uapi/overseas-price/v1/quotations/dailyprice"
DAILY_PRICE_TR_ID = "HHDFS76240000"
BALANCE_PATH = "/uapi/overseas-stock/v1/trading/inquire-balance"
ORDER_PATH = "/uapi/overseas-stock/v1/trading/order"
ORDER_CANCEL_PATH = "/uapi/overseas-stock/v1/trading/order-rvsecncl"
BUYABLE_AMOUNT_PATH = "/uapi/overseas-stock/v1/trading/inquire-psamount"
ORDER_HISTORY_PATH = "/uapi/overseas-stock/v1/trading/inquire-ccnl"
ORDER_HISTORY_TR_ID = "VTTS3035R"


class KisOverseasClient:
    def __init__(self, http: KisJsonClient, exchange_code: str = "NAS") -> None:
        self.http = http
        self.exchange_code = exchange_code

    def ranked_gainers(self, limit: int = 200) -> list[RankedStock]:
        payload = self.http.get(
            PRICE_FLUCT_PATH,
            PRICE_FLUCT_TR_ID,
            {
                "EXCD": self.exchange_code,
                "GUBN": "1",
                "MINX": "3",
                "VOL_RANG": "0",
                "KEYB": "",
                "AUTH": "",
            },
        )
        return _rank_rows(_output_rows(payload), limit)

    def ranked_trade_volume(self, limit: int = 200) -> list[RankedStock]:
        payload = self.http.get(
            TRADE_VOLUME_PATH,
            TRADE_VOLUME_TR_ID,
            {
                "EXCD": self.exchange_code,
                "NDAY": "0",
                "VOL_RANG": "0",
                "KEYB": "",
                "AUTH": "",
                "PRC1": "",
                "PRC2": "",
            },
        )
        return _rank_rows(_output_rows(payload), limit)

    def quote(self, ticker: str) -> dict[str, Any]:
        payload = self.http.get(
            QUOTE_PATH,
            QUOTE_TR_ID,
            {"AUTH": "", "EXCD": self.exchange_code, "SYMB": ticker},
        )
        output = payload.get("output", {})
        if not isinstance(output, dict):
            raise ValueError("KIS quote response output must be an object")
        return output

    def daily_prices(self, ticker: str, bymd: str = "") -> list[dict[str, Any]]:
        payload = self.http.get(
            DAILY_PRICE_PATH,
            DAILY_PRICE_TR_ID,
            {
                "AUTH": "",
                "EXCD": self.exchange_code,
                "SYMB": ticker,
                "GUBN": "0",
                "BYMD": bymd,
                "MODP": "0",
            },
        )
        return list(_output_rows(payload))

    def balance(
        self,
        account_no: str,
        account_product: str,
        exchange_code: str = "NASD",
        currency_code: str = "USD",
        mock: bool = True,
    ) -> dict[str, Any]:
        tr_id = "VTTS3012R" if mock else "TTTS3012R"
        return self.http.get(
            BALANCE_PATH,
            tr_id,
            {
                "CANO": account_no,
                "ACNT_PRDT_CD": account_product,
                "OVRS_EXCG_CD": exchange_code,
                "TR_CRCY_CD": currency_code,
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )

    def limit_order(
        self,
        account_no: str,
        account_product: str,
        ticker: str,
        quantity: int,
        limit_price_usd: float,
        side: str,
        exchange_code: str = "NASD",
        mock: bool = True,
    ) -> dict[str, Any]:
        tr_id = _us_order_tr_id(side, mock)
        order_ticker = ticker.strip().upper()
        order_exchange = exchange_code.strip().upper()
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product,
            "OVRS_EXCG_CD": order_exchange,
            "PDNO": order_ticker,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{limit_price_usd:.2f}",
            "ORD_UNPR": f"{limit_price_usd:.2f}",
            "CTAC_TLNO": "",
            "MGCO_APTM_ODNO": "",
            "ORD_GRNT_DVSN_CD": "0",
            "SLL_TYPE": "00" if side == "sell" else "",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",
        }
        return self.http.post(ORDER_PATH, tr_id, body)

    def cancel_order(
        self,
        account_no: str,
        account_product: str,
        ticker: str,
        original_order_no: str,
        quantity: int,
        exchange_code: str = "NASD",
        appointed_order_no: str = "",
        mock: bool = True,
    ) -> dict[str, Any]:
        tr_id = "VTTT1004U" if mock else "TTTT1004U"
        order_ticker = ticker.strip().upper()
        order_exchange = exchange_code.strip().upper()
        body = {
            "CANO": account_no,
            "ACNT_PRDT_CD": account_product,
            "OVRS_EXCG_CD": order_exchange,
            "PDNO": order_ticker,
            "ORGN_ODNO": original_order_no,
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": "0",
            "MGCO_APTM_ODNO": appointed_order_no,
            "ORD_SVR_DVSN_CD": "0",
        }
        return self.http.post(ORDER_CANCEL_PATH, tr_id, body)

    def buyable_amount(
        self,
        account_no: str,
        account_product: str,
        ticker: str,
        price_usd: float = 1.0,
        exchange_code: str = "NASD",
        mock: bool = True,
    ) -> dict[str, Any]:
        tr_id = "VTTS3007R" if mock else "TTTS3007R"
        order_ticker = ticker.strip().upper()
        order_exchange = exchange_code.strip().upper()
        return self.http.get(
            BUYABLE_AMOUNT_PATH,
            tr_id,
            {
                "CANO": account_no,
                "ACNT_PRDT_CD": account_product,
                "OVRS_EXCG_CD": order_exchange,
                "OVRS_ORD_UNPR": f"{price_usd:.2f}",
                "ITEM_CD": order_ticker,
            },
        )

    def mock_order_history(self, account_no: str, account_product: str, day: str) -> list[dict[str, Any]]:
        payload = self.http.get(
            ORDER_HISTORY_PATH,
            ORDER_HISTORY_TR_ID,
            {
                "CANO": account_no,
                "ACNT_PRDT_CD": account_product,
                "PDNO": "",
                "ORD_STRT_DT": day,
                "ORD_END_DT": day,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )
        output = payload.get("output", [])
        if not isinstance(output, list):
            raise ValueError("KIS order history response output must be a list")
        return [row for row in output if isinstance(row, dict)]


def _output_rows(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    rows = payload.get("output2", [])
    if not isinstance(rows, list):
        raise ValueError("KIS ranking response output2 must be a list")
    return (row for row in rows if isinstance(row, dict))


def _rank_rows(rows: Iterable[dict[str, Any]], limit: int) -> list[RankedStock]:
    ranked: list[RankedStock] = []
    for row in rows:
        ticker = _ticker_from_row(row)
        if ticker:
            ranked.append(RankedStock(ticker, len(ranked) + 1, _name_from_row(row)))
        if len(ranked) == limit:
            break
    return ranked


def _ticker_from_row(row: dict[str, Any]) -> str:
    for field in ("symb", "SYMB", "rsym", "RSYM"):
        value = row.get(field)
        if value:
            return str(value).strip()
    return ""


def _name_from_row(row: dict[str, Any]) -> str:
    for field in (
        "name",
        "NAME",
        "prdt_name",
        "PRDT_NAME",
        "ovrs_item_name",
        "OVRS_ITEM_NAME",
        "hts_kor_isnm",
        "HTS_KOR_ISNM",
        "knam",
        "KNAM",
        "enam",
        "ENAM",
    ):
        value = row.get(field)
        if value:
            return str(value).strip()
    return ""


def _us_order_tr_id(side: str, mock: bool) -> str:
    if mock:
        tr_id = {"buy": "VTTT1002U", "sell": "VTTT1001U"}.get(side)
    else:
        tr_id = {"buy": "TTTT1002U", "sell": "TTTT1001U"}.get(side)
    if tr_id is None:
        raise ValueError("side must be buy or sell")
    return tr_id
