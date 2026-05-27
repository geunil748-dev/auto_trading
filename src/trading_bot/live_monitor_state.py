from __future__ import annotations

from datetime import date, datetime

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
    include_holdings: bool = True,
) -> dict[str, object]:
    trade_date = current_us_market_date(now)
    rows = _safe_order_rows(kis, settings, trade_date, include_orders)
    account = _safe_account(accounts)
    holdings = _safe_holdings(accounts) if include_holdings else []
    return {
        "account": _account(account),
        "targets": [_target(row) for row in rows],
        "positions": [],
        "holdings": holdings,
        "orders": [_order(row, trade_date) for row in rows],
        "fills": [_fill(row, trade_date) for row in rows if _int(row, "ft_ccld_qty") > 0],
        "gates": [
            ["계좌 현금", _usd(account.cash_usd)],
            ["평가 금액", _usd(account.equity_usd)],
            ["보유 종목 수", str(account.open_positions)],
        ],
        "logs": [_attempt(row) for row in rows],
        "trades": [],
        "chart": {"closes": [], "movingAverage": []},
    }


def _safe_order_rows(
    kis: KisOverseasClient,
    settings: KisSettings,
    trade_date: date,
    include_orders: bool,
) -> list[dict[str, object]]:
    if not include_orders:
        return []
    try:
        return kis.mock_order_history(
            settings.account_no,
            settings.account_product,
            trade_date.strftime("%Y%m%d"),
        )
    except Exception:
        return []


def _safe_account(accounts: KisAccountReader) -> AccountState:
    try:
        return accounts.current_account()
    except Exception:
        return AccountState(0.0, 0.0, 0.0, 0, 0.0)


def _safe_holdings(accounts: KisAccountReader) -> list[dict[str, str]]:
    try:
        return accounts.holdings()
    except Exception:
        return []


def _account(account: AccountState) -> dict[str, str]:
    return {
        "cashUsd": _usd(account.cash_usd),
        "equityUsd": _usd(account.equity_usd),
        "investedUsd": _usd(account.invested_usd),
        "openPositions": str(account.open_positions),
        "dailyProfitRate": f"{account.daily_profit_rate * 100:.2f}%",
    }


def _order(row: dict[str, object], trade_date: date) -> dict[str, str]:
    return {
        "date": _row_date(row, trade_date),
        "time": _row_time(row, "ord_tmd"),
        "ticker": str(row.get("pdno", "")),
        "name": str(row.get("prdt_name", "")),
        "side": str(row.get("sll_buy_dvsn_cd_name", "")),
        "quantity": str(row.get("ft_ord_qty", "0")),
        "price": _usd(_float(row, "ft_ord_unpr3")),
        "unfilled": str(row.get("nccs_qty", "0")),
        "orderNo": _first_text(row, "odno", "ODNO", "orgn_odno"),
    }


def _target(row: dict[str, object]) -> list[str]:
    return [
        str(row.get("pdno", "")),
        str(row.get("prdt_name", "")) or "-",
        _usd(_float(row, "ft_ord_unpr3")),
        "-",
        "-",
        "-",
        "주문 접수",
    ]


def _fill(row: dict[str, object], trade_date: date) -> dict[str, str]:
    fill_date = _row_date(row, trade_date)
    fill_time = _row_time(row, "ft_ccld_tmd", "ccld_tmd", "ord_tmd")
    return {
        "date": fill_date,
        "time": fill_time,
        "filledAt": f"{fill_date} {fill_time}".strip(),
        "ticker": str(row.get("pdno", "")),
        "name": str(row.get("prdt_name", "")),
        "side": str(row.get("sll_buy_dvsn_cd_name", "")),
        "quantity": str(row.get("ft_ccld_qty", "0")),
        "price": _usd(_float(row, "ft_ccld_unpr3")),
        "total": _usd(_float(row, "ft_ccld_amt3")),
        "orderNo": _first_text(row, "odno", "ODNO", "orgn_odno"),
    }


def _attempt(row: dict[str, object]) -> list[str]:
    return [
        str(row.get("ord_tmd", "")),
        "주문",
        f"{row.get('pdno', '')} {row.get('sll_buy_dvsn_cd_name', '')} "
        f"{row.get('ft_ord_qty', '0')}주 시도",
    ]


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _row_date(row: dict[str, object], fallback: date) -> str:
    raw = _first_text(row, "ft_ccld_dt", "ccld_dt", "ord_dt", "trad_dt")
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    if raw:
        return raw
    return fallback.isoformat()


def _row_time(row: dict[str, object], *fields: str) -> str:
    raw = _first_text(row, *fields)
    if len(raw) == 6 and raw.isdigit():
        return f"{raw[:2]}:{raw[2:4]}:{raw[4:]}"
    return raw


def _first_text(row: dict[str, object], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field, "")).strip()
        if value:
            return value
    return ""


def _float(row: dict[str, object], field: str) -> float:
    return float(str(row.get(field, 0)).replace(",", "") or 0)


def _int(row: dict[str, object], field: str) -> int:
    return int(float(str(row.get(field, 0)).replace(",", "") or 0))
