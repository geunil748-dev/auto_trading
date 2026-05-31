from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class Sentiment(Enum):
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1


@dataclass(frozen=True)
class NewsRecord:
    ticker: str
    title: str
    summary: str = ""
    url: str = ""
    published_at: datetime | None = None
    source: str = ""
    sentiment_score: int | None = None
    fetched_at: datetime | None = None


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
    opening_volume: float = 0.0
    average_volume_20d: float = 0.0

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
        # 뉴스는 느리거나 없을 수 있으므로 보조 점수로만 반영하고, 차트 판단을 중심으로 둔다.
        return self.chart_score * 0.9 + self.news_score * 0.1


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
class BreakoutInput:
    last_price_usd: float
    open_price_usd: float
    previous_high_usd: float
    previous_low_usd: float
    minutes_above_breakout: float = 0.0
    recent_5m_close_usd: float | None = None
    current_5m_volume: float | None = None
    previous_5m_average_volume: float | None = None
    vwap_usd: float | None = None
    intraday_ma20_usd: float | None = None
    pulled_back_after_breakout: bool | None = None


@dataclass(frozen=True)
class BotLog:
    level: str
    module: str
    message: str
    symbol: str = ""
    name: str = ""
    reject_reason: str = ""
    actual_value: float | None = None
    threshold_value: float | None = None


@dataclass(frozen=True)
class BuyIntent:
    ticker: str
    quantity: int
    limit_price_usd: float
    order_value_usd: float
    allocation_fraction: float
    entry_reason: str = "OPENING_BREAKOUT"
    entry_reason_detail: str = ""


@dataclass(frozen=True)
class SellIntent:
    ticker: str
    quantity: int
    limit_price_usd: float
    exit_reason: str
    entry_price_usd: float | None = None


@dataclass(frozen=True)
class TradeRecord:
    trade_date: date
    ticker: str
    order_type: str
    order_price_usd: float
    exec_price_usd: float | None
    quantity: int
    entry_price_usd: float | None = None
    usd_krw_rate: float | None = None
    profit_usd: float | None = None
    profit_krw: float | None = None
    profit_rate: float | None = None
    exit_reason: str | None = None
    entry_reason: str | None = None
    entry_reason_detail: str | None = None
    max_price_after_buy: float | None = None
    is_mock: bool = True
    ticker_name: str = ""
    order_status: str = "REQUESTED"
    retry_count: int = 0
    order_qty: int | None = None
    filled_qty: int | None = None
    remaining_qty: int | None = None
    avg_fill_price_usd: float | None = None
    last_fill_time: str = ""
    reject_reason: str | None = None
    actual_value: float | None = None
    threshold_value: float | None = None
    strategy_version: str = ""
    settings_snapshot_hash: str = ""
    settings_snapshot_json: str = ""


@dataclass(frozen=True)
class FillRecord:
    trade_date: date
    ticker: str
    side: str
    quantity: int
    fill_price_usd: float
    fill_amount_usd: float
    fill_time: str = ""
    ticker_name: str = ""
    order_no: str = ""
    profit_usd: float | None = None
    profit_rate: float | None = None
    entry_reason: str | None = None
    entry_reason_detail: str | None = None
    is_mock: bool = True
    strategy_version: str = ""
    settings_snapshot_hash: str = ""
    settings_snapshot_json: str = ""


@dataclass(frozen=True)
class EntryProfitSnapshot:
    trade_date: date
    ticker: str
    ticker_name: str
    entry_time: str
    entry_price_usd: float
    strategy_version: str = ""
