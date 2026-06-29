from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from trading_bot.config import TradingSettings
from trading_bot.models import FillRecord
from trading_bot.strategy_metadata import strategy_metadata_from_settings

FillCumulativeKey = tuple[str, str, str, bool]


def fill_records_from_monitor_rows(
    fills: Iterable[Mapping[str, Any]],
    entry_prices: Mapping[str, float] | None = None,
    entry_reasons: Mapping[str, tuple[str, str]] | None = None,
    is_mock: bool = True,
    settings: TradingSettings | None = None,
    existing_cumulative_quantities: Mapping[FillCumulativeKey, int] | None = None,
) -> list[FillRecord]:
    records: list[FillRecord] = []
    strategy_metadata = strategy_metadata_from_settings(settings) if settings is not None else None
    entries = {key.upper(): (0, value) for key, value in (entry_prices or {}).items()}
    reasons = {key.upper(): value for key, value in (entry_reasons or {}).items()}
    cumulative_quantities = dict(existing_cumulative_quantities or {})
    rows = sorted(fills, key=_sort_key)
    for row in rows:
        ticker = _text(row.get("ticker")).upper()
        quantity = _int(row.get("quantity"))
        trade_date = _date(row.get("date"))
        if not ticker or quantity <= 0 or trade_date is None:
            continue
        side = _text(row.get("side"))
        fill_price = _number(row.get("price"))
        order_no = _text(row.get("orderNo"))
        if order_no:
            key = fill_cumulative_key(order_no, ticker, side, is_mock)
            saved_quantity = cumulative_quantities.get(key, 0)
            delta_quantity = quantity - saved_quantity
            cumulative_quantities[key] = max(saved_quantity, quantity)
            if delta_quantity <= 0:
                continue
            quantity = delta_quantity
            fill_amount = fill_price * quantity
        else:
            fill_amount = _number(row.get("total"))
        if _is_buy(side):
            entries[ticker] = _next_entry(entries.get(ticker), quantity, fill_price)
        entry_price = entries.get(ticker, (0, None))[1]
        profit_usd, profit_rate = _realized_profit(side, fill_price, quantity, entry_price)
        if _is_sell(side):
            entries[ticker] = _remaining_entry(entries.get(ticker), quantity)
        entry_reason, entry_reason_detail = reasons.get(ticker, (None, None))
        records.append(
            FillRecord(
                trade_date=trade_date,
                fill_time=_text(row.get("time")),
                ticker=ticker,
                ticker_name=_text(row.get("name")),
                side=side,
                quantity=quantity,
                fill_price_usd=fill_price,
                fill_amount_usd=fill_amount,
                order_no=order_no,
                profit_usd=profit_usd,
                profit_rate=profit_rate,
                entry_reason=entry_reason,
                entry_reason_detail=entry_reason_detail,
                is_mock=is_mock,
                strategy_version=strategy_metadata.strategy_version if strategy_metadata else "",
                settings_snapshot_hash=strategy_metadata.settings_snapshot_hash if strategy_metadata else "",
                settings_snapshot_json=strategy_metadata.settings_snapshot_json if strategy_metadata else "",
            )
        )
    return records


def valid_fill_monitor_row_count(fills: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    for row in fills:
        ticker = _text(row.get("ticker")).upper()
        quantity = _int(row.get("quantity"))
        trade_date = _date(row.get("date"))
        if ticker and quantity > 0 and trade_date is not None:
            count += 1
    return count


def fill_cumulative_key(
    order_no: str,
    ticker: str,
    side: str,
    is_mock: bool = True,
) -> FillCumulativeKey:
    return (_text(order_no), _text(ticker).upper(), _normalized_side(side), bool(is_mock))


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


def _normalized_side(side: str) -> str:
    if _is_buy(side):
        return "BUY"
    if _is_sell(side):
        return "SELL"
    return _text(side).upper()


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
