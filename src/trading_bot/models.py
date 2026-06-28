from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any


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
class TradingEvent:
    event_time: datetime
    stage: str
    event_type: str
    severity: str = "INFO"
    trade_date: date | None = None
    mode: str | None = None
    app_mode: str | None = None
    run_id: str | None = None
    correlation_id: str | None = None
    order_id: str | None = None
    order_no: str | None = None
    ticker: str | None = None
    ticker_name: str | None = None
    side: str | None = None
    decision: str | None = None
    reason_code: str | None = None
    reason_label: str | None = None
    is_blocking: bool | None = None
    is_final_decision: bool | None = None
    order_submitted: bool | None = None
    buy_allowed: bool | None = None
    sell_allowed: bool | None = None
    quantity: int | None = None
    price_usd: float | None = None
    order_value_usd: float | None = None
    actual_value: float | None = None
    threshold_value: float | None = None
    profit_rate: float | None = None
    candidate_source: str | None = None
    ranking_selection_mode: str | None = None
    strategy_version: str | None = None
    settings_snapshot_hash: str | None = None
    message: str | None = None
    details_json: str | dict[str, Any] | None = None


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
class CandidateEvaluation:
    run_id: str | None
    evaluation_time: datetime
    trading_date: date | None
    source: str | None
    symbol: str
    symbol_name: str = ""
    current_price: float | None = None
    volume: int | None = None
    dollar_volume: float | None = None
    price_change_percent: float | None = None
    opening_gap_percent: float | None = None
    price_rank: int | None = None
    volume_rank: int | None = None
    relaxation_level: int | None = None
    min_price: float | None = None
    max_price: float | None = None
    price_change_top: int | None = None
    volume_top: int | None = None
    min_selection_score: float | None = None
    min_opening_price_change_percent: float | None = None
    min_volume_ratio: float | None = None
    max_opening_gap_percent: float | None = None
    selection_score: float | None = None
    soft_score_adjustment: float | None = None
    final_score: float | None = None
    overheat_condition_mode: str | None = None
    breakout_close_condition_mode: str | None = None
    volume_increase_condition_mode: str | None = None
    vwap_ma20_condition_mode: str | None = None
    vwap_ma20_condition_type: str | None = None
    pullback_rebreak_condition_mode: str | None = None
    overheat_pass: bool | None = None
    breakout_close_pass: bool | None = None
    volume_increase_pass: bool | None = None
    vwap_pass: bool | None = None
    ma20_pass: bool | None = None
    vwap_ma20_pass: bool | None = None
    pullback_rebreak_pass: bool | None = None
    final_score_pass: bool | None = None
    buy_allowed: bool = False
    order_submitted: bool = False
    order_id: str | None = None
    buy_block_reason: str | None = None
    buy_block_reasons: str | None = None
    hard_filter_failed_count: int | None = None
    soft_condition_failed_count: int | None = None
    final_decision: str | None = None
    settings_snapshot_json: str | None = None
    condition_result_json: str | None = None
    raw_candidate_json: str | None = None


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
class DailyTradeSummaryReport:
    trade_date: date
    mode: str
    strategy_version: str
    settings_snapshot_hash: str
    summary_json: str
    summary_text: str
    total_profit_usd: float
    total_profit_rate: float
    trade_count: int
    buy_count: int
    sell_count: int
    win_rate: float
    stop_loss_count: int
    take_profit_count: int
    trailing_stop_count: int
    eod_count: int
    sample_sufficient: bool


@dataclass(frozen=True)
class EntryProfitSnapshot:
    trade_date: date
    ticker: str
    ticker_name: str
    entry_time: str
    entry_price_usd: float
    strategy_version: str = ""
