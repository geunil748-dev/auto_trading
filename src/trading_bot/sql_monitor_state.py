from __future__ import annotations

from typing import Any

from trading_bot.repositories import SqlServerMonitorRepository


class SqlMonitorStateSource:
    def __init__(self, repository: SqlServerMonitorRepository) -> None:
        self.repository = repository

    def read(self) -> dict[str, object]:
        scores = {row[0]: row for row in self.repository.latest_scores()}
        return {
            "targets": [_target(row, scores.get(row[0])) for row in self.repository.latest_targets()],
            "positions": [],
            "holdings": [],
            "orders": [],
            "fills": [],
            "gates": [
                ["저장소", "MSSQL"],
                ["점수 기록", str(len(scores))],
            ],
            "logs": [_log(row) for row in self.repository.latest_logs()],
            "trades": [_trade(row) for row in self.repository.latest_trades()],
            "chart": {"closes": [], "movingAverage": []},
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


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except TypeError:
        return float(str(value))
