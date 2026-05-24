from __future__ import annotations

from collections.abc import Callable, Iterable

CancelSubmitter = Callable[[dict[str, object]], dict[str, object]]


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
