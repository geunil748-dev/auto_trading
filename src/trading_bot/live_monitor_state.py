from __future__ import annotations

from datetime import datetime

from trading_bot.adapters.kis_account import KisAccountReader
from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.config import KisSettings
from trading_bot.market_calendar import current_us_market_date
from trading_bot.models import AccountState


def live_kis_monitor_state(
    kis: KisOverseasClient,
    accounts: KisAccountReader,
    settings: KisSettings,
    now: datetime | None = None,
    include_orders: bool = True,
) -> dict[str, object]:
    rows = []
    if include_orders:
        rows = kis.mock_order_history(
            settings.account_no,
            settings.account_product,
            current_us_market_date(now).strftime("%Y%m%d"),
        )
    account = accounts.current_account()
    return {
        "account": _account(account),
        "targets": [_target(row) for row in rows],
        "positions": [],
        "holdings": accounts.holdings(),
        "orders": [_order(row) for row in rows],
        "fills": [_fill(row) for row in rows if _int(row, "ft_ccld_qty") > 0],
        "gates": [
            ["계좌 현금", _usd(account.cash_usd)],
            ["평가 금액", _usd(account.equity_usd)],
            ["보유 종목 수", str(account.open_positions)],
        ],
        "logs": [_attempt(row) for row in rows],
        "trades": [],
        "chart": {"closes": [], "movingAverage": []},
    }


def _account(account: AccountState) -> dict[str, str]:
    return {
        "cashUsd": _usd(account.cash_usd),
        "equityUsd": _usd(account.equity_usd),
        "investedUsd": _usd(account.invested_usd),
        "openPositions": str(account.open_positions),
        "dailyProfitRate": f"{account.daily_profit_rate * 100:.2f}%",
    }


def _order(row: dict[str, object]) -> dict[str, str]:
    return {
        "time": str(row.get("ord_tmd", "")),
        "ticker": str(row.get("pdno", "")),
        "name": str(row.get("prdt_name", "")),
        "side": str(row.get("sll_buy_dvsn_cd_name", "")),
        "quantity": str(row.get("ft_ord_qty", "0")),
        "price": _usd(_float(row, "ft_ord_unpr3")),
        "unfilled": str(row.get("nccs_qty", "0")),
    }


def _target(row: dict[str, object]) -> list[str]:
    return [
        str(row.get("pdno", "")),
        _usd(_float(row, "ft_ord_unpr3")),
        "-",
        "-",
        "-",
        "주문 접수",
    ]


def _fill(row: dict[str, object]) -> dict[str, str]:
    return {
        "ticker": str(row.get("pdno", "")),
        "name": str(row.get("prdt_name", "")),
        "side": str(row.get("sll_buy_dvsn_cd_name", "")),
        "quantity": str(row.get("ft_ccld_qty", "0")),
        "price": _usd(_float(row, "ft_ccld_unpr3")),
        "total": _usd(_float(row, "ft_ccld_amt3")),
    }


def _attempt(row: dict[str, object]) -> list[str]:
    return [
        str(row.get("ord_tmd", "")),
        "주문",
        f"{row.get('pdno', '')} {row.get('sll_buy_dvsn_cd_name', '')} "
        f"{row.get('ft_ord_qty', '0')}주 시도",
    ]


def _usd(value: float) -> str:
    return f"${value:.2f}"


def _float(row: dict[str, object], field: str) -> float:
    return float(str(row.get(field, 0)).replace(",", "") or 0)


def _int(row: dict[str, object], field: str) -> int:
    return int(float(str(row.get(field, 0)).replace(",", "") or 0))
