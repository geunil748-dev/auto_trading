from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from trading_bot.models import FillRecord
from trading_bot.trade_notifier import MessageSender, TradeNotifier
from trading_bot.trade_notifier_messages import fmt_usd


FillKey = tuple[date, str, str, str, int, float]


def fill_key(record: FillRecord) -> FillKey:
    return (
        record.trade_date,
        record.fill_time,
        record.ticker.upper(),
        _side_key(record.side),
        int(record.quantity),
        round(float(record.fill_price_usd), 6),
    )


def fill_keys_from_history(rows: Iterable[Sequence[Any]]) -> set[FillKey]:
    keys: set[FillKey] = set()
    for row in rows:
        if len(row) < 7:
            continue
        try:
            keys.add(
                (
                    _date(row[0]),
                    _text(row[1]),
                    _text(row[2]).upper(),
                    _side_key(_text(row[4])),
                    int(_number(row[5])),
                    round(_number(row[6]), 6),
                )
            )
        except (TypeError, ValueError):
            continue
    return keys


def new_fill_records(
    records: Iterable[FillRecord],
    existing_keys: set[FillKey],
) -> list[FillRecord]:
    return [record for record in records if fill_key(record) not in existing_keys]


def send_fill_notifications(
    records: Iterable[FillRecord],
    holdings: Iterable[object],
    sender: MessageSender | None = None,
) -> int:
    holding_map = _holding_map(holdings)
    sent = 0
    for record in records:
        notifier = TradeNotifier(
            current_price_func=lambda code, prices=holding_map: prices.get(
                code.upper(), {}
            ).get("current_price", record.fill_price_usd),
            message_sender=sender,
            money_formatter=fmt_usd,
        )
        _seed_position_for_fill(notifier, record, holding_map)
        if _is_buy(record.side):
            ok = notifier.on_buy_success(
                record.ticker,
                record.ticker_name or record.ticker,
                record.quantity,
                record.fill_price_usd,
                record.order_no or None,
            )
        elif _is_sell(record.side):
            ok = notifier.on_sell_success(
                record.ticker,
                record.ticker_name or record.ticker,
                record.quantity,
                record.fill_price_usd,
                record.order_no or None,
            )
        else:
            ok = False
        sent += int(ok)
    return sent


def send_market_close_report_from_records(
    records: Iterable[FillRecord],
    holdings: Iterable[object],
    sender: MessageSender | None = None,
) -> bool:
    holding_map = _holding_map(holdings)
    notifier = TradeNotifier(
        current_price_func=lambda code: holding_map.get(code.upper(), {}).get(
            "current_price", 0.0
        ),
        message_sender=sender,
        money_formatter=fmt_usd,
    )
    notifier.daily = _daily_from_records(records)
    notifier.positions = {
        code: {
            "name": item["name"],
            "qty": item["qty"],
            "avg_price": item["avg_price"],
        }
        for code, item in holding_map.items()
        if item["qty"] > 0 and item["avg_price"] > 0
    }
    return notifier.send_market_close_report()


def _seed_position_for_fill(
    notifier: TradeNotifier,
    record: FillRecord,
    holding_map: dict[str, dict[str, float | int | str]],
) -> None:
    key = record.ticker.upper()
    holding = holding_map.get(key, {})
    current_qty = int(holding.get("qty", 0))
    current_avg = float(holding.get("avg_price", 0.0))
    if _is_buy(record.side):
        previous_qty = max(0, current_qty - record.quantity)
        previous_avg = _previous_buy_average(current_qty, current_avg, record)
        if previous_qty > 0 and previous_avg > 0:
            notifier.positions[key] = {
                "name": record.ticker_name or record.ticker,
                "qty": previous_qty,
                "avg_price": previous_avg,
            }
        return

    if not _is_sell(record.side):
        return
    previous_qty = current_qty + record.quantity
    avg_price = _sell_entry_price(record, current_avg)
    if previous_qty > 0 and avg_price > 0:
        notifier.positions[key] = {
            "name": record.ticker_name or record.ticker,
            "qty": previous_qty,
            "avg_price": avg_price,
        }


def _previous_buy_average(
    current_qty: int,
    current_avg: float,
    record: FillRecord,
) -> float:
    previous_qty = current_qty - record.quantity
    if previous_qty <= 0:
        return 0.0
    previous_cost = (current_avg * current_qty) - (
        record.fill_price_usd * record.quantity
    )
    return previous_cost / previous_qty if previous_cost > 0 else 0.0


def _sell_entry_price(record: FillRecord, current_avg: float) -> float:
    if record.profit_usd is not None and record.quantity > 0:
        return record.fill_price_usd - (record.profit_usd / record.quantity)
    if record.profit_rate is not None and record.profit_rate > -1:
        return record.fill_price_usd / (1 + record.profit_rate)
    return current_avg


def _daily_from_records(records: Iterable[FillRecord]) -> dict[str, int | float]:
    daily: dict[str, int | float] = {
        "buy_count": 0,
        "sell_count": 0,
        "buy_amount": 0.0,
        "sell_amount": 0.0,
        "realized_pnl": 0.0,
        "realized_cost": 0.0,
    }
    for record in records:
        if _is_buy(record.side):
            daily["buy_count"] = int(daily["buy_count"]) + 1
            daily["buy_amount"] = float(daily["buy_amount"]) + record.fill_amount_usd
        elif _is_sell(record.side):
            daily["sell_count"] = int(daily["sell_count"]) + 1
            daily["sell_amount"] = float(daily["sell_amount"]) + record.fill_amount_usd
            if record.profit_usd is not None:
                daily["realized_pnl"] = float(daily["realized_pnl"]) + record.profit_usd
                daily["realized_cost"] = (
                    float(daily["realized_cost"])
                    + record.fill_amount_usd
                    - record.profit_usd
                )
    return daily


def _holding_map(holdings: Iterable[object]) -> dict[str, dict[str, float | int | str]]:
    result: dict[str, dict[str, float | int | str]] = {}
    for item in holdings:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("ticker")).upper()
        if not code:
            continue
        result[code] = {
            "name": _text(item.get("name")) or code,
            "qty": int(_number(item.get("quantity"))),
            "avg_price": _number(item.get("averagePrice")),
            "current_price": _current_price(item),
        }
    return result


def _current_price(item: dict[str, object]) -> float:
    return (
        _number(item.get("closePrice"))
        or _number(item.get("lastPrice"))
        or _number(item.get("currentPrice"))
        or _number(item.get("price"))
    )


def _date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(_text(value)[:10])


def _number(value: Any) -> float:
    raw = _text(value).replace("$", "").replace(",", "").replace("주", "")
    return float(raw or 0)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _side_key(side: str) -> str:
    if _is_buy(side):
        return "BUY"
    if _is_sell(side):
        return "SELL"
    return side.strip().upper()


def _is_buy(side: str) -> bool:
    normalized = side.strip().upper()
    return "매수" in side or normalized in {"BUY", "B"}


def _is_sell(side: str) -> bool:
    normalized = side.strip().upper()
    return "매도" in side or normalized in {"SELL", "S"}
