from trading_bot.config import TradingSettings
from trading_bot.execution import trailing_stop_triggered, update_high
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.exit_planner import plan_position_exits
from trading_bot.models import (
    AccountState,
    CandidateSnapshot,
    PositionState,
    RankedStock,
    ScoreRecord,
    Sentiment,
)
from trading_bot.risk import (
    defensive_candidate_gate,
    global_entry_gate,
    hard_stop_triggered,
    position_entry_gate,
)
from trading_bot.scoring import (
    news_score,
    position_fraction_for_news_score,
    select_candidates,
)
from trading_bot.screening import ranking_intersection
from trading_bot.strategy import breakout_triggered, volatility_breakout_price


SETTINGS = TradingSettings()


def candidate(
    ticker: str,
    price: float = 12.0,
    open_price: float = 11.0,
    previous_close: float = 10.0,
    change: float = 0.04,
    volume_ratio: float = 1.8,
    turnover_rank: int = 1,
    gain_rank: int = 1,
) -> CandidateSnapshot:
    return CandidateSnapshot(
        ticker=ticker,
        price_usd=price,
        open_price_usd=open_price,
        previous_close_usd=previous_close,
        opening_price_change=change,
        opening_volume_ratio=volume_ratio,
        turnover_rank=turnover_rank,
        gain_rank=gain_rank,
    )


def account(**changes: float) -> AccountState:
    values = {
        "cash_usd": 3000.0,
        "equity_usd": 10000.0,
        "invested_usd": 6000.0,
        "open_positions": 2,
        "daily_profit_rate": 0.0,
    }
    values.update(changes)
    return AccountState(**values)


def test_global_gate_uses_market_priority_before_fx() -> None:
    blocked = global_entry_gate(99, 100, 0.03, account(), SETTINGS)

    assert not blocked.allowed
    assert blocked.reason == "MARKET_BELOW_MA20"


def test_defensive_gate_blocks_gap_and_price_outliers() -> None:
    assert defensive_candidate_gate(candidate("LOW", price=4.99), SETTINGS).reason == "PENNY_STOCK"
    assert defensive_candidate_gate(candidate("GAP", open_price=12.1), SETTINGS).reason == "OPENING_GAP"
    assert defensive_candidate_gate(candidate("OK"), SETTINGS).allowed


def test_screening_keeps_rank_intersection_with_opening_filters() -> None:
    snapshots = {
        "AAA": candidate("AAA", turnover_rank=2, gain_rank=3),
        "BBB": candidate("BBB", volume_ratio=1.0, turnover_rank=1, gain_rank=2),
        "CCC": candidate("CCC", turnover_rank=3, gain_rank=1),
    }

    selected = ranking_intersection(
        [RankedStock("AAA", 3), RankedStock("BBB", 2), RankedStock("CCC", 1)],
        [RankedStock("AAA", 2), RankedStock("BBB", 1)],
        snapshots,
        SETTINGS,
    )

    assert [item.ticker for item in selected] == ["AAA"]


def test_scoring_uses_positive_news_ratio_and_score_sizing() -> None:
    score = news_score([Sentiment.POSITIVE, Sentiment.NEUTRAL, Sentiment.POSITIVE])

    assert round(score, 2) == 66.67
    assert position_fraction_for_news_score(84.9) == 0.05
    assert position_fraction_for_news_score(95) == 0.20


def test_candidate_selection_requires_buyable_news_score() -> None:
    selected = select_candidates(
        [
            ScoreRecord("LOW", 60, 99),
            ScoreRecord("MID", 75, 70),
            ScoreRecord("TOP", 95, 85),
        ],
        SETTINGS,
    )

    assert [item.ticker for item in selected] == ["TOP", "MID"]


def test_breakout_threshold_and_trailing_stop() -> None:
    assert volatility_breakout_price(10, 12, 8) == 12
    assert breakout_triggered(12, 10, 12, 8)

    position = PositionState("AAA", 10, 10, 12, 12)
    pulled_back = update_high(position, 11.63)

    assert trailing_stop_triggered(pulled_back, SETTINGS)


def test_exposure_and_loss_stops() -> None:
    oversized = position_entry_gate(account(), 2500, SETTINGS)
    losing = PositionState("AAA", 10, 10, 9.49, 11)

    assert oversized.reason == "POSITION_EXPOSURE_LIMIT"
    assert hard_stop_triggered(losing, SETTINGS)


def test_entry_planner_requires_breakout_and_reserves_exposure() -> None:
    intents = plan_buy_intents(
        [
            ScoreRecord("TOP", 95, 90),
            ScoreRecord("NOPE", 95, 90),
            ScoreRecord("NEXT", 85, 80),
        ],
        {
            "TOP": (10, 9, 10, 8),
            "NOPE": (9, 9, 10, 8),
            "NEXT": (20, 19, 20, 18),
        },
        account(cash_usd=5000, invested_usd=5000),
        SETTINGS,
    )

    assert [(item.ticker, item.quantity) for item in intents] == [("TOP", 200), ("NEXT", 50)]
    assert [item.order_value_usd for item in intents] == [2000, 1000]


def test_exit_planner_prioritizes_eod_hard_stop_and_trailing_stop() -> None:
    positions = [
        PositionState("LOSS", 10, 2, 9.4, 11),
        PositionState("TRAIL", 10, 3, 11.6, 12),
        PositionState("HOLD", 10, 1, 11.9, 12),
    ]

    regular = plan_position_exits(positions, SETTINGS)
    eod = plan_position_exits(positions, SETTINGS, end_of_day=True)

    assert [(item.ticker, item.exit_reason) for item in regular] == [
        ("LOSS", "STOP_LOSS"),
        ("TRAIL", "TRAILING_STOP"),
    ]
    assert [item.exit_reason for item in eod] == ["EOD", "EOD", "EOD"]
