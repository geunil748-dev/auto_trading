from __future__ import annotations

from datetime import date
from typing import Any

from trading_bot.repositories import SqlServerMonitorRepository


class SqlMonitorStateSource:
    def __init__(self, repository: SqlServerMonitorRepository) -> None:
        self.repository = repository

    def read(self) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.latest_scores()}
        return {
            "targets": [
                _target(row, scores.get(row[0]))
                for row in self.repository.latest_targets()
            ],
            "positions": [],
            "holdings": [],
            "orders": [],
            "fills": [_fill(row) for row in self.repository.latest_fills()],
            "gates": [
                ["저장소", "MSSQL"],
                ["점수 기록", str(len(scores))],
            ],
            "logs": [_log(row) for row in self.repository.latest_logs()],
            "trades": [_trade(row) for row in self.repository.latest_trades()],
            "chart": {"closes": [], "movingAverage": []},
        }

    def read_history(self, trade_date: date) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.history_scores(trade_date)}
        return {
            "date": trade_date.isoformat(),
            "targets": [
                _target(row, scores.get(row[0]))
                for row in self.repository.history_targets(trade_date)
            ],
            "orders": [],
            "fills": [_fill(row) for row in self.repository.history_fills(trade_date)],
            "logs": [_log(row) for row in self.repository.history_logs(trade_date)],
            "trades": [_trade(row) for row in self.repository.history_trades(trade_date)],
        }


def _target(row: tuple[Any, ...], score: tuple[Any, ...] | None) -> list[str]:
    if len(row) >= 4:
        ticker, ticker_name, volume_ratio, price_change = row[:4]
    else:
        ticker, volume_ratio, price_change = row
        ticker_name = "-"
    score_value = "-" if score is None else str(round(_number(score[3])))
    state = "점수대기" if score is None else ("선정" if score[4] else "제외")
    return [
        str(ticker),
        str(ticker_name or "-"),
        "-",
        f"{_number(volume_ratio):.0f}%",
        f"{_number(price_change):+.1f}%",
        score_value,
        state,
    ]


def _log(row: tuple[Any, ...]) -> list[str]:
    created_at, level, message = row
    timestamp = created_at.strftime("%H:%M:%S") if hasattr(created_at, "strftime") else str(created_at)
    return [timestamp, str(level), str(message)]


def _trade(row: tuple[Any, ...]) -> dict[str, str]:
    ticker, order_type, order_price, quantity, exit_reason = row
    return {
        "ticker": str(ticker),
        "type": str(order_type),
        "price": f"${_number(order_price):.2f}",
        "quantity": str(quantity),
        "exitReason": "" if exit_reason is None else str(exit_reason),
    }


def _fill(row: tuple[Any, ...]) -> dict[str, str]:
    fill_date, fill_time, ticker, ticker_name, side, quantity, fill_price, fill_amount = row
    date_text = _date_text(fill_date)
    time_text = "" if fill_time is None else str(fill_time)
    return {
        "date": date_text,
        "time": time_text,
        "filledAt": f"{date_text} {time_text}".strip(),
        "ticker": str(ticker),
        "name": str(ticker_name or ""),
        "side": str(side or ""),
        "quantity": str(quantity),
        "price": f"${_number(fill_price):,.2f}",
        "total": f"${_number(fill_amount):,.2f}",
    }


def _date_text(value: Any) -> str:
    if all(hasattr(value, field) for field in ("Year", "Month", "Day")):
        return f"{value.Year:04d}-{value.Month:02d}-{value.Day:02d}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except TypeError:
        return float(str(value))
