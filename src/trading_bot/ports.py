from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Protocol

from trading_bot.models import (
    AccountState,
    BotLog,
    CandidateEvaluation,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    FillRecord,
    MarketContext,
    RankedStock,
    ScoreRecord,
    TradeRecord,
    TradingEvent,
    BreakoutInput,
)


class ScreeningMarketData(Protocol):
    def market_context(self) -> MarketContext: ...

    def ranked_gainers(self, limit: int | None = None) -> Iterable[RankedStock]: ...

    def ranked_turnover(self, limit: int | None = None) -> Iterable[RankedStock]: ...

    def ranked_trade_value(self, limit: int | None = None) -> Iterable[RankedStock]: ...

    def candidate_snapshots(self, tickers: Iterable[str]) -> Mapping[str, CandidateSnapshot]: ...


class ManualBuyListSource(Protocol):
    def enabled_tickers(self) -> Iterable[str]: ...


class ScreeningContextSource(Protocol):
    def market_context(self) -> MarketContext: ...


class CandidateHistorySource(Protocol):
    def average_daily_volume(self, ticker: str, sessions: int) -> float: ...


class BreakoutSource(Protocol):
    def breakout_input(self, ticker: str) -> BreakoutInput | tuple[float, float, float, float]: ...


class ScoringProvider(Protocol):
    def score(self, candidate: CandidateSnapshot) -> ScoreRecord: ...


class AccountReader(Protocol):
    def current_account(self) -> AccountState: ...


class DailyRepository(Protocol):
    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None: ...

    def save_daily_scores(self, scores: Iterable[DailyScore]) -> None: ...

    def save_candidate_evaluations(self, evaluations: Iterable[CandidateEvaluation]) -> None: ...

    def mark_candidate_evaluation_order_submitted(
        self,
        ticker: str,
        trade_date: date,
        order_id: str | None = None,
    ) -> None: ...

    def mark_candidate_evaluation_order_not_submitted(
        self,
        ticker: str,
        trade_date: date,
        reason: str,
    ) -> None: ...

    def save_log(self, log: BotLog) -> None: ...

    def save_trading_events(self, events: Iterable[TradingEvent]) -> None: ...

    def save_trades(self, trades: Iterable[TradeRecord]) -> None: ...

    def save_fills(self, fills: Iterable[FillRecord]) -> None: ...

    def history_fills(self, trade_date: date, limit: int = 200) -> list[tuple[object, ...]]: ...

    def pending_fill_notifications(self, fills: Iterable[FillRecord]) -> list[FillRecord]: ...

    def mark_fill_notifications_sent(self, fills: Iterable[FillRecord]) -> None: ...

    def last_stop_loss_at(self, trade_date: date, ticker: str): ...

    def consecutive_stop_loss_count(self, trade_date: date) -> int: ...


class TradingClock(Protocol):
    def today(self) -> date: ...
