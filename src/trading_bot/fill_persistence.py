from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from trading_bot.models import FillRecord


def fill_records_from_monitor_rows(
    fills: Iterable[Mapping[str, Any]],
    entry_prices: Mapping[str, float] | None = None,
    is_mock: bool = True,
) -> list[FillRecord]:
    records: list[FillRecord] = []
    entries = {key.upper(): value for key, value in (entry_prices or {}).items()}
    for row in fills:
        ticker = _text(row.get("ticker")).upper()
        quantity = _int(row.get("quantity"))
        trade_date = _date(row.get("date"))
        if not ticker or quantity <= 0 or trade_date is None:
            continue
        side = _text(row.get("side"))
        fill_price = _number(row.get("price"))
        profit_usd, profit_rate = _realized_profit(side, fill_price, quantity, entries.get(ticker))
        records.append(
            FillRecord(
                trade_date=trade_date,
                fill_time=_text(row.get("time")),
                ticker=ticker,
                ticker_name=_text(row.get("name")),
                side=side,
                quantity=quantity,
                fill_price_usd=fill_price,
                fill_amount_usd=_number(row.get("total")),
                order_no=_text(row.get("orderNo")),
                profit_usd=profit_usd,
                profit_rate=profit_rate,
                is_mock=is_mock,
            )
        )
    return records


def _date(value: Any) -> date | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _number(value: Any) -> float:
    raw = _text(value).replace("$", "").replace(",", "")
    return float(raw or 0)


def _int(value: Any) -> int:
    raw = _text(value).replace(",", "").replace("주", "")
    return int(float(raw or 0))


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _realized_profit(
    side: str,
    fill_price: float,
    quantity: int,
    entry_price: float | None,
) -> tuple[float | None, float | None]:
    if not _is_sell(side) or entry_price is None or entry_price <= 0:
        return None, None
    return (fill_price - entry_price) * quantity, (fill_price - entry_price) / entry_price


def _is_sell(side: str) -> bool:
    normalized = side.strip().upper()
    return "매도" in side or normalized == "SELL"
