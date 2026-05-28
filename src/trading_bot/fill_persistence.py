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
    entries = {key.upper(): (0, value) for key, value in (entry_prices or {}).items()}
    rows = sorted(fills, key=_sort_key)
    for row in rows:
        ticker = _text(row.get("ticker")).upper()
        quantity = _int(row.get("quantity"))
        trade_date = _date(row.get("date"))
        if not ticker or quantity <= 0 or trade_date is None:
            continue
        side = _text(row.get("side"))
        fill_price = _number(row.get("price"))
        if _is_buy(side):
            entries[ticker] = _next_entry(entries.get(ticker), quantity, fill_price)
        entry_price = entries.get(ticker, (0, None))[1]
        profit_usd, profit_rate = _realized_profit(side, fill_price, quantity, entry_price)
        if _is_sell(side):
            entries[ticker] = _remaining_entry(entries.get(ticker), quantity)
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


def _sort_key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    # 미국장은 한국 시간 기준으로 자정을 넘겨 이어진다. 00~11시는 22~23시 이후로 정렬한다.
    raw_time = _text(row.get("time"))
    return (_text(row.get("date"))[:10], _session_minute(raw_time), _text(row.get("orderNo")))


def _session_minute(raw_time: str) -> int:
    try:
        hour = int(raw_time[:2])
        minute = int(raw_time[3:5])
        second = int(raw_time[6:8])
    except (TypeError, ValueError):
        return 0
    if hour < 12:
        hour += 24
    return hour * 3600 + minute * 60 + second


def _next_entry(
    current: tuple[int, float | None] | None,
    quantity: int,
    fill_price: float,
) -> tuple[int, float]:
    current_qty, current_price = current or (0, None)
    if current_qty <= 0 or current_price is None:
        return quantity, fill_price
    total_qty = current_qty + quantity
    average = ((current_price * current_qty) + (fill_price * quantity)) / total_qty
    return total_qty, average


def _remaining_entry(
    current: tuple[int, float | None] | None,
    quantity: int,
) -> tuple[int, float | None]:
    if current is None:
        return (0, None)
    current_qty, current_price = current
    if current_qty <= 0:
        return current
    remaining = max(0, current_qty - quantity)
    return (remaining, current_price if remaining > 0 else None)


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


def _is_buy(side: str) -> bool:
    normalized = side.strip().upper()
    return "매수" in side or normalized in {"BUY", "B"}


def _is_sell(side: str) -> bool:
    normalized = side.strip().upper()
    return "매도" in side or normalized in {"SELL", "S"}
