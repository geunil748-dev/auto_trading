from __future__ import annotations

from collections.abc import Iterable

from trading_bot.models import BotLog, DailyScore, DailyTarget, TradeRecord


class InMemoryDailyRepository:
    def __init__(self) -> None:
        self.targets: list[DailyTarget] = []
        self.scores: list[DailyScore] = []
        self.trades: list[TradeRecord] = []
        self.logs: list[BotLog] = []

    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None:
        self.targets.extend(targets)

    def save_daily_scores(self, scores: Iterable[DailyScore]) -> None:
        self.scores.extend(scores)

    def save_trades(self, trades: Iterable[TradeRecord]) -> None:
        self.trades.extend(trades)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)
