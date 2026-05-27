from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_domestic import KisDomesticClient
from trading_bot.adapters.kis_http import KisJsonClient
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings, load_kis_settings, load_real_kis_settings
from trading_bot.live_monitor_state import live_kis_monitor_state


def account_dashboard_state(
    mock_loader: Callable[[], KisSettings] = load_kis_settings,
    real_loader: Callable[[], KisSettings] = load_real_kis_settings,
) -> dict[str, object]:
    return {
        "accounts": {
            "mock": _account_state("모의투자", mock_loader, mock=True, include_orders=True),
            "real": _account_state("실투자", real_loader, mock=False, include_orders=False),
        }
    }


def _account_state(
    label: str,
    loader: Callable[[], KisSettings],
    mock: bool,
    include_orders: bool,
) -> dict[str, Any]:
    try:
        settings = loader()
        kis = KisOverseasClient(KisJsonClient(settings))
        accounts = KisAccountReader(kis, settings, mock=mock)
        state = live_kis_monitor_state(
            kis,
            accounts,
            settings,
            include_orders=include_orders,
            include_holdings=False,
        )
        if not mock:
            state["account"].update(_real_krw_summary(settings))
    except Exception as error:
        return {
            "label": label,
            "connected": False,
            "error": str(error),
            "account": _empty_account(),
            "targets": [],
            "holdings": [],
            "orders": [],
            "fills": [],
            "logs": [],
            "trades": [],
        }
    return {
        "label": label,
        "connected": True,
        "error": "",
        **state,
    }


def _real_krw_summary(settings: KisSettings) -> dict[str, str]:
    client = KisDomesticClient(KisJsonClient(settings))
    payload = client.balance(settings.account_no, settings.account_product)
    summary = _first_object(payload.get("output2"))
    return {
        "cashKrw": _krw(_float(summary, "dnca_tot_amt")),
        "equityKrw": _krw(_float(summary, "tot_evlu_amt")),
    }


def _empty_account() -> dict[str, str]:
    return {
        "cashUsd": "-",
        "equityUsd": "-",
        "investedUsd": "-",
        "cashKrw": "-",
        "equityKrw": "-",
        "openPositions": "-",
        "dailyProfitRate": "-",
    }


def _first_object(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), {})
    return value if isinstance(value, dict) else {}


def _float(row: dict[str, Any], field: str) -> float:
    value = row.get(field, 0)
    return float(str(value).replace(",", "") or 0)


def _krw(value: float) -> str:
    return f"{value:,.0f}원"
