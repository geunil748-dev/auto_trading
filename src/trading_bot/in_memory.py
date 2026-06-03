from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from trading_bot.models import BotLog, CandidateEvaluation, DailyScore, DailyTarget, FillRecord, TradeRecord


class InMemoryDailyRepository:
    def __init__(self) -> None:
        self.targets: list[DailyTarget] = []
        self.scores: list[DailyScore] = []
        self.trades: list[TradeRecord] = []
        self.fills: list[FillRecord] = []
        self.logs: list[BotLog] = []
        self.candidate_evaluations: list[CandidateEvaluation] = []

    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None:
        self.targets.extend(targets)

    def save_daily_scores(self, scores: Iterable[DailyScore]) -> None:
        self.scores.extend(scores)

    def save_candidate_evaluations(self, evaluations: Iterable[CandidateEvaluation]) -> None:
        self.candidate_evaluations.extend(evaluations)

    def mark_candidate_evaluation_order_submitted(
        self,
        ticker: str,
        trade_date: date,
        order_id: str | None = None,
    ) -> None:
        for index in range(len(self.candidate_evaluations) - 1, -1, -1):
            item = self.candidate_evaluations[index]
            if item.symbol == ticker and item.trading_date == trade_date and item.buy_allowed:
                self.candidate_evaluations[index] = CandidateEvaluation(
                    **{
                        **item.__dict__,
                        "order_submitted": True,
                        "order_id": order_id,
                        "final_decision": "ORDER_SUBMITTED",
                    }
                )
                return

    def save_trades(self, trades: Iterable[TradeRecord]) -> None:
        self.trades.extend(trades)

    def save_fills(self, fills: Iterable[FillRecord]) -> None:
        self.fills.extend(fills)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)
