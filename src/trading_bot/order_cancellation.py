from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

CancelSubmitter = Callable[[dict[str, object]], dict[str, object]]
KST = ZoneInfo("Asia/Seoul")


def cancel_unfilled_orders(
    rows: Iterable[dict[str, object]],
    submit_cancel: CancelSubmitter,
) -> list[dict[str, object]]:
    cancelled: list[dict[str, object]] = []
    for request in unfilled_cancel_requests(rows):
        submit_cancel(request)
        cancelled.append(request)
    return cancelled


def unfilled_cancel_requests(
    rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    requests: list[dict[str, object]] = []
    for row in rows:
        ticker = _first_text(row, "pdno", "PDNO")
        order_no = _first_text(row, "odno", "ODNO")
        quantity = _first_int(row, "nccs_qty", "NCCS_QTY")
        if not ticker or not order_no or quantity <= 0:
            continue
        requests.append(
            {
                "ticker": ticker,
                "order_no": order_no,
                "quantity": quantity,
                "appointed_order_no": _first_text(
                    row,
                    "mgco_aptm_odno",
                    "MGCO_APTM_ODNO",
                ),
            }
        )
    return requests


def stale_unfilled_buy_cancel_requests(
    rows: Iterable[dict[str, object]],
    max_age_minutes: int,
    retried_tickers: Iterable[str] = (),
    now: datetime | None = None,
) -> list[dict[str, object]]:
    current = now or datetime.now(KST)
    retried = {_ticker(item) for item in retried_tickers}
    requests: list[dict[str, object]] = []
    for row in rows:
        ticker = _first_text(row, "pdno", "PDNO")
        if not ticker or _ticker(ticker) in retried:
            continue
        if not _is_buy_order(row):
            continue
        quantity = _first_int(row, "nccs_qty", "NCCS_QTY")
        order_no = _first_text(row, "odno", "ODNO")
        if quantity <= 0 or not order_no:
            continue
        ordered_at = _ordered_at(row, current)
        if ordered_at is None:
            continue
        if current - ordered_at < timedelta(minutes=max_age_minutes):
            continue
        requests.append(
            {
                "ticker": ticker,
                "order_no": order_no,
                "quantity": quantity,
                "appointed_order_no": _first_text(
                    row,
                    "mgco_aptm_odno",
                    "MGCO_APTM_ODNO",
                ),
            }
        )
    return requests


def _first_text(row: dict[str, object], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field, "")).strip()
        if value:
            return value
    return ""


def _first_int(row: dict[str, object], *fields: str) -> int:
    for field in fields:
        value = str(row.get(field, "")).replace(",", "").strip()
        if value:
            return int(float(value))
    return 0


def _ordered_at(row: dict[str, object], now: datetime) -> datetime | None:
    raw_time = _first_text(row, "ord_tmd", "ORD_TMD")
    if len(raw_time) != 6 or not raw_time.isdigit():
        return None
    raw_date = _first_text(row, "ord_dt", "ORD_DT", "trad_dt", "TRAD_DT")
    order_date = _parse_date(raw_date) or now.date()
    value = datetime.combine(
        order_date,
        time(int(raw_time[:2]), int(raw_time[2:4]), int(raw_time[4:])),
        tzinfo=now.tzinfo or KST,
    )
    if value - now > timedelta(hours=1):
        value -= timedelta(days=1)
    return value


def _parse_date(raw: str) -> date | None:
    if len(raw) == 8 and raw.isdigit():
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    return None


def _is_buy_order(row: dict[str, object]) -> bool:
    side_name = _first_text(row, "sll_buy_dvsn_cd_name", "SLL_BUY_DVSN_CD_NAME").upper()
    if "SELL" in side_name or "매도" in side_name:
        return False
    if "BUY" in side_name or "매수" in side_name:
        return True
    side_code = _first_text(row, "sll_buy_dvsn_cd", "SLL_BUY_DVSN_CD").upper()
    if side_code in {"01", "1", "SELL"}:
        return False
    if side_code in {"02", "2", "BUY"}:
        return True
    return True


def _ticker(value: str) -> str:
    return value.strip().upper()
