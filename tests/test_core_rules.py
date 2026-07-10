import json
from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.execution import trailing_stop_triggered, update_high
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.exit_planner import plan_position_exits
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.models import (
    AccountState,
    BreakoutInput,
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
    position_fraction_for_score,
    select_candidates,
)
from trading_bot.screening import (
    adaptive_ranking_intersection,
    composite_ranking_selection,
    ranking_intersection,
    screening_priority_score,
)
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
        "invested_usd": 1000.0,
        "open_positions": 2,
        "daily_profit_rate": 0.0,
    }
    values.update(changes)
    return AccountState(**values)


def entry_test_settings(**overrides: object) -> TradingSettings:
    values = {
        "max_entry_price_change": 0.30,
    }
    values.update(overrides)
    return TradingSettings(**values)


def test_global_gate_uses_market_priority_before_fx() -> None:
    blocked = global_entry_gate(99, 100, 0.03, account(), SETTINGS)

    assert not blocked.allowed
    assert blocked.reason == "MARKET_BELOW_MA20"


def test_global_gate_can_bypass_market_ma20_only_in_test_mock_mode() -> None:
    settings = TradingSettings(allow_market_below_ma20_bypass=True)

    decision = global_entry_gate(99, 100, 0.0, account(), settings)

    assert decision.allowed
    assert decision.reason is None
    assert decision.bypass_reason == "MARKET_BELOW_MA20_BYPASSED"


def test_global_gate_does_not_bypass_market_ma20_in_real_mode() -> None:
    settings = TradingSettings(
        app_mode="real",
        mock_trading=False,
        allow_market_below_ma20_bypass=True,
    )

    decision = global_entry_gate(99, 100, 0.0, account(), settings)

    assert not decision.allowed
    assert decision.reason == "MARKET_BELOW_MA20"
    assert decision.bypass_reason is None


def test_global_gate_market_bypass_keeps_other_global_blocks() -> None:
    settings = TradingSettings(allow_market_below_ma20_bypass=True)

    decision = global_entry_gate(99, 100, 0.03, account(), settings)

    assert not decision.allowed
    assert decision.reason == "FX_VOLATILITY"
    assert decision.bypass_reason is None


def test_defensive_gate_blocks_gap_and_price_outliers() -> None:
    assert defensive_candidate_gate(candidate("LOW", price=4.99), SETTINGS).reason == "PENNY_STOCK"
    assert defensive_candidate_gate(candidate("GAP", open_price=13.1), SETTINGS).reason == "OPENING_GAP"
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
        TradingSettings(min_volume_ratio=1.5),
    )

    assert [item.ticker for item in selected] == ["AAA"]


def test_composite_ranking_selection_uses_trade_value_and_presence() -> None:
    snapshots = {
        "AAA": candidate("AAA", turnover_rank=5, gain_rank=5),
        "BBB": candidate("BBB", turnover_rank=1, gain_rank=1),
        "CCC": candidate("CCC", turnover_rank=80, gain_rank=80),
    }

    selected = composite_ranking_selection(
        [RankedStock("BBB", 1), RankedStock("AAA", 5)],
        [RankedStock("BBB", 1), RankedStock("AAA", 5)],
        [RankedStock("CCC", 1), RankedStock("AAA", 5)],
        snapshots,
        SETTINGS,
        limit=3,
    )

    assert [item.ticker for item in selected] == ["AAA", "BBB", "CCC"]


def test_composite_ranking_selection_prioritizes_two_rankings_over_one() -> None:
    snapshots = {
        "ONE": candidate("ONE", turnover_rank=80, gain_rank=1),
        "TWO": candidate("TWO", turnover_rank=30, gain_rank=30),
    }

    selected = composite_ranking_selection(
        [RankedStock("ONE", 1), RankedStock("TWO", 30)],
        [RankedStock("TWO", 30)],
        [],
        snapshots,
        SETTINGS,
        limit=2,
    )

    assert [item.ticker for item in selected] == ["TWO", "ONE"]


def test_composite_ranking_selection_keeps_opening_filters_strict() -> None:
    snapshots = {
        "BAD": candidate("BAD", price=4.0, turnover_rank=1, gain_rank=1),
        "OK": candidate("OK", turnover_rank=10, gain_rank=10),
    }

    selected = composite_ranking_selection(
        [RankedStock("BAD", 1), RankedStock("OK", 10)],
        [RankedStock("BAD", 1), RankedStock("OK", 10)],
        [RankedStock("BAD", 1), RankedStock("OK", 10)],
        snapshots,
        SETTINGS,
        limit=2,
    )

    assert [item.ticker for item in selected] == ["OK"]


def test_composite_ranking_selection_limits_and_tie_breaks_by_ticker() -> None:
    snapshots = {
        "BBB": candidate("BBB", turnover_rank=1, gain_rank=1),
        "AAA": candidate("AAA", turnover_rank=1, gain_rank=1),
    }

    selected = composite_ranking_selection(
        [RankedStock("BBB", 1), RankedStock("AAA", 1)],
        [RankedStock("BBB", 1), RankedStock("AAA", 1)],
        [RankedStock("BBB", 1), RankedStock("AAA", 1)],
        snapshots,
        SETTINGS,
        limit=1,
    )

    assert [item.ticker for item in selected] == ["AAA"]


def test_screening_prioritizes_bonus_score_and_limits_list() -> None:
    snapshots = {
        "STEADY": candidate(
            "STEADY",
            change=0.06,
            volume_ratio=3.5,
            turnover_rank=8,
            gain_rank=8,
        ),
        "CHASE": candidate(
            "CHASE",
            open_price=13.0,
            change=0.28,
            volume_ratio=3.5,
            turnover_rank=1,
            gain_rank=1,
        ),
        "MID": candidate(
            "MID",
            change=0.11,
            volume_ratio=2.2,
            turnover_rank=5,
            gain_rank=6,
        ),
    }

    selected = ranking_intersection(
        [RankedStock("CHASE", 1), RankedStock("MID", 5), RankedStock("STEADY", 8)],
        [RankedStock("CHASE", 1), RankedStock("MID", 6), RankedStock("STEADY", 8)],
        snapshots,
        TradingSettings(max_selected_candidates=2),
    )

    assert [item.ticker for item in selected] == ["STEADY", "MID"]
    assert screening_priority_score(snapshots["STEADY"]) > screening_priority_score(
        snapshots["CHASE"]
    )


def test_adaptive_screening_relaxes_filters_until_enough_candidates() -> None:
    snapshots = {
        "LOW": candidate("LOW", price=4.0, change=0.04, volume_ratio=1.8),
        "CHANGE": candidate("CHANGE", change=0.02, volume_ratio=1.8),
        "VOLUME": candidate("VOLUME", change=0.04, volume_ratio=1.0),
        "GAP": candidate("GAP", open_price=12.6, change=0.04, volume_ratio=1.8),
    }

    selected = adaptive_ranking_intersection(
        [
            RankedStock("LOW", 1),
            RankedStock("CHANGE", 2),
            RankedStock("VOLUME", 3),
            RankedStock("GAP", 4),
        ],
        [
            RankedStock("LOW", 1),
            RankedStock("CHANGE", 2),
            RankedStock("VOLUME", 3),
            RankedStock("GAP", 4),
        ],
        snapshots,
        SETTINGS,
    )

    assert len(selected) == 3
    assert {item.ticker for item in selected} == {"CHANGE", "VOLUME", "GAP"}


def test_opening_change_only_relax_keeps_other_filters_strict() -> None:
    snapshots = {
        "OPENING": candidate("OPENING", change=0.02, volume_ratio=1.8),
        "PRICE": candidate("PRICE", price=4.0, change=0.02, volume_ratio=1.8),
        "VOLUME": candidate("VOLUME", change=0.02, volume_ratio=1.0),
        "GAP": candidate("GAP", open_price=12.6, change=0.02, volume_ratio=1.8),
    }

    selected = adaptive_ranking_intersection(
        [
            RankedStock("OPENING", 1),
            RankedStock("PRICE", 2),
            RankedStock("VOLUME", 3),
            RankedStock("GAP", 4),
        ],
        [
            RankedStock("OPENING", 1),
            RankedStock("PRICE", 2),
            RankedStock("VOLUME", 3),
            RankedStock("GAP", 4),
        ],
        snapshots,
        TradingSettings(
            allow_relaxed_candidate_filter=False,
            relax_opening_change_only=True,
            min_selected_candidates=1,
            min_volume_ratio=1.5,
            max_opening_gap=0.20,
        ),
    )

    assert [item.ticker for item in selected] == ["OPENING"]


def test_scoring_uses_positive_news_ratio_and_score_sizing() -> None:
    score = news_score([Sentiment.POSITIVE, Sentiment.NEUTRAL, Sentiment.POSITIVE])
    settings = TradingSettings(min_total_score=40)

    assert round(score, 2) == 66.67
    assert position_fraction_for_score(39.9, settings) == 0.0
    assert position_fraction_for_score(40, settings) == 0.05
    assert position_fraction_for_score(84.9, settings) == 0.10


def test_candidate_selection_requires_minimum_total_score() -> None:
    selected = select_candidates(
        [
            ScoreRecord("LOW", 20, 40),
            ScoreRecord("MID", 40, 50),
            ScoreRecord("TOP", 95, 85),
        ],
        TradingSettings(min_total_score=40),
    )

    assert [item.ticker for item in selected] == ["TOP", "MID"]


def test_breakout_threshold_and_trailing_stop() -> None:
    assert volatility_breakout_price(10, 12, 8) == 12
    assert breakout_triggered(12, 10, 12, 8)

    position = PositionState("AAA", 10, 10, 12, 12)
    pulled_back = update_high(position, 11.63)
    early_pullback = PositionState("EARLY", 10, 10, 9.9, 10.19)

    assert trailing_stop_triggered(pulled_back, SETTINGS)
    assert not trailing_stop_triggered(early_pullback, SETTINGS)


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
            "TOP": (10.4, 9.5, 10, 9),
            "NOPE": (9, 9, 10, 8),
            "NEXT": (20, 19, 20, 18),
        },
        account(cash_usd=5000, invested_usd=1000),
        SETTINGS,
    )

    assert [(item.ticker, item.quantity) for item in intents] == [("TOP", 96), ("NEXT", 50)]
    assert [item.order_value_usd for item in intents] == [998.4000000000001, 1000]


def test_entry_planner_blocks_overheated_intraday_entry() -> None:
    intents = plan_buy_intents(
        [ScoreRecord("HOT", 95, 90)],
        {
            "HOT": BreakoutInput(
                last_price_usd=13,
                open_price_usd=10,
                previous_high_usd=11,
                previous_low_usd=9,
            ),
        },
        account(),
        TradingSettings(max_entry_price_change=0.25),
    )

    assert intents == []


def test_entry_planner_can_require_extra_intraday_confirmation() -> None:
    settings = entry_test_settings(
        breakout_hold_minutes=2,
        require_5m_close_above_breakout=True,
        require_5m_volume_increase=True,
        require_vwap_or_ma20=True,
        require_pullback_rebreak=True,
    )
    confirmed = BreakoutInput(
        last_price_usd=12.5,
        open_price_usd=10,
        previous_high_usd=12,
        previous_low_usd=8,
        minutes_above_breakout=3,
        recent_5m_close_usd=12.2,
        current_5m_volume=1200,
        previous_5m_average_volume=800,
        vwap_usd=12.0,
        pulled_back_after_breakout=True,
    )

    intents = plan_buy_intents(
        [ScoreRecord("OK", 95, 90)],
        {"OK": confirmed},
        account(),
        settings,
    )

    assert [item.ticker for item in intents] == ["OK"]


def test_entry_planner_soft_score_condition_does_not_block_entry() -> None:
    settings = entry_test_settings(
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="SOFT_SCORE",
        require_5m_volume_increase=False,
    )

    intents = plan_buy_intents(
        [ScoreRecord("SOFT", 95, 90)],
        {
            "SOFT": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                recent_5m_close_usd=11.5,
            ),
        },
        account(),
        settings,
    )

    assert [item.ticker for item in intents] == ["SOFT"]
    assert "soft BREAKOUT_CLOSE_FAILED" in intents[0].entry_reason_detail


def test_entry_planner_hard_filter_condition_blocks_entry() -> None:
    settings = entry_test_settings(
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_5m_volume_increase=False,
    )

    intents = plan_buy_intents(
        [ScoreRecord("HARD", 95, 90)],
        {
            "HARD": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                recent_5m_close_usd=11.5,
            ),
        },
        account(),
        settings,
    )

    assert intents == []


def test_entry_planner_saves_unbought_hard_filter_evaluation() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_5m_volume_increase=False,
    )

    intents = plan_buy_intents(
        [ScoreRecord("HARD", 95, 90)],
        {
            "HARD": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                recent_5m_close_usd=11.5,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.symbol == "HARD"
    assert evaluation.buy_allowed is False
    assert evaluation.buy_block_reason == "BREAKOUT_CLOSE_FAILED"
    assert json.loads(evaluation.buy_block_reasons) == ["BREAKOUT_CLOSE_FAILED"]
    assert evaluation.hard_filter_failed_count == 1
    assert evaluation.soft_condition_failed_count == 0
    assert repository.trading_events[0].event_type == "BUY_BLOCKED"
    assert repository.trading_events[0].reason_code == "BREAKOUT_CLOSE_FAILED"


def test_entry_planner_saves_bought_and_soft_score_evaluation() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="SOFT_SCORE",
        require_5m_volume_increase=False,
    )

    intents = plan_buy_intents(
        [ScoreRecord("SOFT", 95, 90)],
        {
            "SOFT": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                recent_5m_close_usd=11.5,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["SOFT"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.buy_block_reason == "BUY_ALLOWED"
    assert evaluation.soft_score_adjustment == -5.0
    assert evaluation.hard_filter_failed_count == 0
    assert evaluation.soft_condition_failed_count == 1
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["failed_soft_reasons"] == ["BREAKOUT_CLOSE_FAILED"]
    assert repository.logs[0].message == (
        "후보평가 저장: 종목=SOFT 최종점수=85.5 매수허용=예 주문제출=아니오 "
        "매수판정=매수 허용 하드필터탈락=0 소프트조건탈락=1 VWAP/MA20상태=비활성화"
    )
    assert repository.logs[0].reject_reason == "BUY_ALLOWED"
    assert repository.trading_events[0].event_type == "BUY_ALLOWED"


def test_entry_planner_marks_manual_watchlist_source_and_reason() -> None:
    repository = InMemoryDailyRepository()

    intents = plan_buy_intents(
        [ScoreRecord("MAN", 95, 90)],
        {
            "MAN": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
            ),
        },
        account(),
        entry_test_settings(require_5m_volume_increase=False),
        repository=repository,
        trade_date=date(2026, 5, 22),
        source="intraday_recheck",
        source_by_ticker={"MAN": "manual_buy_list"},
    )

    assert [item.ticker for item in intents] == ["MAN"]
    assert intents[0].entry_reason.startswith("MANUAL_WATCHLIST+OPENING_BREAKOUT")
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.source == "manual_buy_list"
    assert evaluation.buy_block_reason == "BUY_ALLOWED"


def test_entry_planner_records_market_bypass_tag_in_intent_and_evaluation() -> None:
    repository = InMemoryDailyRepository()

    intents = plan_buy_intents(
        [ScoreRecord("BYP", 95, 90)],
        {
            "BYP": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
            ),
        },
        account(),
        entry_test_settings(require_5m_volume_increase=False),
        repository=repository,
        trade_date=date(2026, 5, 22),
        entry_reason_tags=("MARKET_BELOW_MA20_BYPASSED",),
    )

    assert [item.ticker for item in intents] == ["BYP"]
    assert "MARKET_BELOW_MA20_BYPASSED" in intents[0].entry_reason
    assert "MARKET_BELOW_MA20_BYPASSED" in intents[0].entry_reason_detail
    condition_json = json.loads(repository.candidate_evaluations[0].condition_result_json)
    raw_json = json.loads(repository.candidate_evaluations[0].raw_candidate_json)
    assert condition_json["market_below_ma20_bypassed"] is True
    assert condition_json["analysis_group"] == "market_bypass_trades"
    assert raw_json["market_bypass_reason"] == "MARKET_BELOW_MA20_BYPASSED"


def test_entry_planner_requires_configured_5m_volume_increase_percent() -> None:
    settings = entry_test_settings(
        require_5m_volume_increase=True,
        volume_increase_condition_mode="HARD_FILTER",
        min_5m_volume_increase_percent=5.0,
    )

    def intents_for(symbol: str, current_volume: float):
        return plan_buy_intents(
            [ScoreRecord(symbol, 95, 90)],
            {
                symbol: BreakoutInput(
                    last_price_usd=12.5,
                    open_price_usd=10,
                    previous_high_usd=12,
                    previous_low_usd=8,
                    current_5m_volume=current_volume,
                    previous_5m_average_volume=100_000,
                ),
            },
            account(),
            settings,
        )

    assert intents_for("TINY", 100_001) == []
    assert intents_for("THREE", 103_000) == []
    assert [item.ticker for item in intents_for("SIX", 106_000)] == ["SIX"]


def test_entry_planner_records_insufficient_5m_volume_data_without_zero_division() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_volume_increase=True,
        volume_increase_condition_mode="SOFT_SCORE",
        min_5m_volume_increase_percent=5.0,
    )

    intents = plan_buy_intents(
        [ScoreRecord("ZERO", 95, 90)],
        {
            "ZERO": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                current_5m_volume=10_000,
                previous_5m_average_volume=0,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["ZERO"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.soft_score_adjustment == -5.0
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["recent_5m_volume"] == 10_000
    assert condition_json["previous_5m_volume"] == 0
    assert condition_json["volume_increase_percent"] is None
    assert condition_json["min5mVolumeIncreasePercent"] == 5.0
    assert condition_json["volume_increase_pass"] is False
    assert condition_json["volume_increase_insufficient"] is True


def test_entry_planner_separates_missing_volume_from_actual_failure() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_volume_increase=True,
        volume_increase_condition_mode="HARD_FILTER",
        volume_data_missing_condition_mode="HARD_FILTER",
    )

    plan_buy_intents(
        [ScoreRecord("MISSING", 95, 90)],
        {"MISSING": BreakoutInput(12.5, 10, 12, 8, current_5m_volume=None,
                                  previous_5m_average_volume=100_000)},
        account(), settings, repository=repository, trade_date=date(2026, 7, 10),
    )

    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_block_reason == "VOLUME_INCREASE_DATA_MISSING"
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["volume_data_available"] is False
    assert condition_json["volume_data_missing_reason"] == "CURRENT_5M_VOLUME_MISSING"


def test_real_mode_always_hard_blocks_missing_volume_data() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        app_mode="real",
        require_5m_volume_increase=True,
        volume_data_missing_condition_mode="LOG_ONLY",
    )

    intents = plan_buy_intents(
        [ScoreRecord("REAL", 95, 90)],
        {"REAL": BreakoutInput(12.5, 10, 12, 8)},
        account(), settings, repository=repository, trade_date=date(2026, 7, 10),
    )

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_block_reason == "VOLUME_INCREASE_DATA_MISSING"
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["configured_volume_data_missing_condition_mode"] == "LOG_ONLY"
    assert condition_json["effective_volume_data_missing_condition_mode"] == "HARD_FILTER"


def test_entry_planner_hard_filter_blocks_failed_5m_volume_increase() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_volume_increase=True,
        volume_increase_condition_mode="HARD_FILTER",
        min_5m_volume_increase_percent=5.0,
    )

    intents = plan_buy_intents(
        [ScoreRecord("VOLHARD", 95, 90)],
        {
            "VOLHARD": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                current_5m_volume=103_000,
                previous_5m_average_volume=100_000,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is False
    assert evaluation.buy_block_reason == "VOLUME_INCREASE_FAILED"
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["volume_increase_percent"] == 3.0
    assert condition_json["volume_increase_pass"] is False


def test_entry_planner_records_vwap_ma20_or_pass_with_vwap_only_data() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="HARD_FILTER",
        vwap_ma20_condition_type="OR",
    )

    intents = plan_buy_intents(
        [ScoreRecord("VWAP", 95, 90)],
        {
            "VWAP": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                vwap_usd=12.0,
                intraday_ma20_usd=13.0,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["VWAP"]
    condition_json = json.loads(repository.candidate_evaluations[0].condition_result_json)
    assert condition_json["vwap_ma20_evaluation_status"] == "PASS"
    assert condition_json["vwap_pass"] is True
    assert condition_json["ma20_pass"] is False
    assert condition_json["vwap_ma20_pass"] is True
    assert condition_json["vwap_ma20_compare_operator"] == ">="


def test_entry_planner_records_vwap_ma20_or_fail_with_data() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="HARD_FILTER",
        vwap_ma20_condition_type="OR",
    )

    intents = plan_buy_intents(
        [ScoreRecord("VMFAIL", 95, 90)],
        {
            "VMFAIL": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                vwap_usd=13.0,
                intraday_ma20_usd=13.5,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is False
    assert evaluation.buy_block_reason == "VWAP_MA20_FAILED"
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["vwap_ma20_evaluation_status"] == "FAIL"
    assert condition_json["vwap_ma20_pass"] is False


def test_entry_planner_records_vwap_ma20_skipped_no_data_without_blocking() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="HARD_FILTER",
        vwap_ma20_condition_type="OR",
    )

    intents = plan_buy_intents(
        [ScoreRecord("NODATA", 95, 90)],
        {
            "NODATA": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["NODATA"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.vwap_ma20_pass is None
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["vwap_ma20_evaluation_status"] == "SKIPPED_NO_DATA"
    assert condition_json["vwap_ma20_pass"] is None
    assert condition_json["vwap_data_available"] is False
    assert condition_json["intraday_ma20_data_available"] is False
    assert condition_json["ma20_insufficient"] is True


def test_entry_planner_vwap_ma20_soft_score_failure_only_adjusts_score() -> None:
    repository = InMemoryDailyRepository()
    settings = entry_test_settings(
        require_5m_volume_increase=False,
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="SOFT_SCORE",
        vwap_ma20_condition_type="AND",
    )

    intents = plan_buy_intents(
        [ScoreRecord("VMSOFT", 95, 90)],
        {
            "VMSOFT": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                vwap_usd=12.0,
                intraday_ma20_usd=13.0,
            ),
        },
        account(),
        settings,
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["VMSOFT"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.soft_score_adjustment == -5.0
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["vwap_ma20_evaluation_status"] == "FAIL"
    assert condition_json["vwap_ma20_pass"] is False


def test_entry_planner_vwap_ma20_only_modes_and_disabled_status() -> None:
    base = {
        "ONLY": BreakoutInput(
            last_price_usd=12.5,
            open_price_usd=10,
            previous_high_usd=12,
            previous_low_usd=8,
            vwap_usd=12.0,
            intraday_ma20_usd=13.0,
        )
    }

    vwap_repository = InMemoryDailyRepository()
    ma20_repository = InMemoryDailyRepository()
    off_repository = InMemoryDailyRepository()

    assert plan_buy_intents(
        [ScoreRecord("ONLY", 95, 90)],
        base,
        account(),
        entry_test_settings(require_vwap_or_ma20=True, vwap_ma20_condition_type="VWAP_ONLY"),
        repository=vwap_repository,
        trade_date=date(2026, 5, 22),
    )
    assert plan_buy_intents(
        [ScoreRecord("ONLY", 95, 90)],
        base,
        account(),
        entry_test_settings(
            require_vwap_or_ma20=True,
            vwap_ma20_condition_type="MA20_ONLY",
            vwap_ma20_condition_mode="SOFT_SCORE",
        ),
        repository=ma20_repository,
        trade_date=date(2026, 5, 22),
    )
    assert plan_buy_intents(
        [ScoreRecord("ONLY", 95, 90)],
        base,
        account(),
        entry_test_settings(require_vwap_or_ma20=False),
        repository=off_repository,
        trade_date=date(2026, 5, 22),
    )

    assert json.loads(vwap_repository.candidate_evaluations[0].condition_result_json)[
        "vwap_ma20_evaluation_status"
    ] == "PASS"
    assert json.loads(ma20_repository.candidate_evaluations[0].condition_result_json)[
        "vwap_ma20_evaluation_status"
    ] == "FAIL"
    assert json.loads(off_repository.candidate_evaluations[0].condition_result_json)[
        "vwap_ma20_evaluation_status"
    ] == "DISABLED"


def test_entry_planner_default_vwap_ma20_off_does_not_block_or_adjust_score() -> None:
    repository = InMemoryDailyRepository()

    intents = plan_buy_intents(
        [ScoreRecord("OFFDEFAULT", 95, 90)],
        {
            "OFFDEFAULT": BreakoutInput(
                last_price_usd=12.5,
                open_price_usd=10,
                previous_high_usd=12,
                previous_low_usd=8,
                vwap_usd=20.0,
                intraday_ma20_usd=21.0,
            ),
        },
        account(),
        entry_test_settings(require_5m_volume_increase=False),
        repository=repository,
        trade_date=date(2026, 5, 22),
    )

    assert [item.ticker for item in intents] == ["OFFDEFAULT"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.soft_score_adjustment == 0.0
    assert evaluation.buy_block_reason == "BUY_ALLOWED"
    condition_json = json.loads(evaluation.condition_result_json)
    assert condition_json["vwap_ma20_evaluation_status"] == "DISABLED"
    assert "VWAP_MA20_FAILED" not in condition_json["failed_hard_reasons"]
    assert "VWAP_MA20_FAILED" not in condition_json["failed_soft_reasons"]


def test_entry_planner_ignores_unavailable_intraday_confirmation_data() -> None:
    settings = entry_test_settings(
        breakout_hold_minutes=2,
        require_5m_close_above_breakout=True,
        require_5m_volume_increase=True,
        require_vwap_or_ma20=True,
        require_pullback_rebreak=True,
    )

    intents = plan_buy_intents(
        [ScoreRecord("LEGACY", 95, 90)],
        {"LEGACY": (12.5, 10, 12, 8)},
        account(),
        settings,
    )

    assert [item.ticker for item in intents] == ["LEGACY"]


def test_exit_planner_prioritizes_eod_hard_stop_partial_profit_and_trailing_stop() -> None:
    positions = [
        PositionState("LOSS", 10, 2, 9.4, 11),
        PositionState("PROFIT", 10, 2, 11.0, 11.0),
        PositionState("TRAIL", 10, 3, 10.27, 10.6),
        PositionState("HOLD", 10, 1, 10.3, 10.3),
    ]

    regular = plan_position_exits(positions, SETTINGS)
    eod = plan_position_exits(positions, SETTINGS, end_of_day=True)

    assert [(item.ticker, item.exit_reason) for item in regular] == [
        ("LOSS", "STOP_LOSS"),
        ("PROFIT", "PARTIAL_TAKE_PROFIT"),
        ("TRAIL", "TRAILING_STOP"),
    ]
    assert regular[1].quantity == 1
    assert regular[0].entry_price_usd == 10
    assert [item.exit_reason for item in eod] == ["EOD", "EOD", "EOD", "EOD"]


def test_exit_planner_does_not_repeat_partial_take_profit() -> None:
    exits = plan_position_exits(
        [PositionState("PROFIT", 10, 2, 11.0, 11.0)],
        SETTINGS,
        partial_take_profit_tickers={"PROFIT"},
    )

    assert exits == []


def test_exit_planner_uses_full_take_profit_when_partial_profit_is_disabled() -> None:
    exits = plan_position_exits(
        [PositionState("PROFIT", 10, 2, 11.0, 11.0)],
        TradingSettings(partial_take_profit_enabled=False),
    )

    assert [(item.ticker, item.exit_reason, item.quantity) for item in exits] == [
        ("PROFIT", "TAKE_PROFIT", 2)
    ]
