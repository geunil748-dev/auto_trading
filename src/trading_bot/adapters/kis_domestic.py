from __future__ import annotations

from typing import Any

from trading_bot.adapters.kis_http import KisJsonClient

BALANCE_PATH = "/uapi/domestic-stock/v1/trading/inquire-balance"
REAL_BALANCE_TR_ID = "TTTC8434R"


class KisDomesticClient:
    def __init__(self, http: KisJsonClient) -> None:
        self.http = http

    def balance(self, account_no: str, account_product: str) -> dict[str, Any]:
        return self.http.get(
            BALANCE_PATH,
            REAL_BALANCE_TR_ID,
            {
                "CANO": account_no,
                "ACNT_PRDT_CD": account_product,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
