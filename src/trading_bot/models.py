from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Sentiment(Enum):
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1


@dataclass(frozen=True)
class RankedStock:
    ticker: str
    rank: int
    name: str = ""


@dataclass(frozen=True)
class MarketContext:
    nasdaq_price_usd: float
    nasdaq_ma20_usd: float
    fx_change_rate: float


@dataclass(frozen=True)
class CandidateSnapshot:
    ticker: str
    price_usd: float
    open_price_usd: float
    previous_close_usd: float
    opening_price_change: float
    opening_volume_ratio: float
    turnover_rank: int
    gain_rank: int
    name: str = ""

    @property
    def opening_gap(self) -> float:
        if self.previous_close_usd <= 0:
            raise ValueError("previous close must be positive")
        return (self.open_price_usd - self.previous_close_usd) / self.previous_close_usd


@dataclass(frozen=True)
class ScoreRecord:
    ticker: str
    news_score: float
    chart_score: float

    @property
    def total_score(self) -> float:
        return (self.news_score + self.chart_score) / 2


@dataclass(frozen=True)
class DailyTarget:
    trade_date: date
    candidate: CandidateSnapshot


@dataclass(frozen=True)
class DailyScore:
    trade_date: date
    score: ScoreRecord
    is_selected: bool


@dataclass(frozen=True)
class AccountState:
    cash_usd: float
    equity_usd: float
    invested_usd: float
    open_positions: int
    daily_profit_rate: float


@dataclass(frozen=True)
class PositionState:
    ticker: str
    entry_price_usd: float
    quantity: int
    last_price_usd: float
    high_price_usd: float

    @property
    def profit_rate(self) -> float:
        if self.entry_price_usd <= 0:
            raise ValueError("entry price must be positive")
        return (self.last_price_usd - self.entry_price_usd) / self.entry_price_usd


@dataclass(frozen=True)
class BotLog:
    level: str
    module: str
    message: str


@dataclass(frozen=True)
class BuyIntent:
    ticker: str
    quantity: int
    limit_price_usd: float
    order_value_usd: float
    allocation_fraction: float


@dataclass(frozen=True)
class SellIntent:
    ticker: str
    quantity: int
    limit_price_usd: float
    exit_reason: str


@dataclass(frozen=True)
class TradeRecord:
    trade_date: date
    ticker: str
    order_type: str
    order_price_usd: float
    exec_price_usd: float | None
    quantity: int
    usd_krw_rate: float | None = None
    profit_usd: float | None = None
    profit_krw: float | None = None
    profit_rate: float | None = None
    exit_reason: str | None = None
    max_price_after_buy: float | None = None
    is_mock: bool = True
