import json
from dataclasses import replace
from datetime import date

import pytest

from trading_bot.config import TradingSettings
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.models import AccountState, BreakoutInput, ScoreRecord


def settings(**changes: object) -> TradingSettings:
    base = TradingSettings(
        max_entry_price_change=0.30,
        breakout_hold_minutes=0,
        require_5m_close_above_breakout=False,
        require_5m_volume_increase=False,
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="HARD_FILTER",
        require_pullback_rebreak=False,
    )
    return replace(base, **changes)


def evaluate(
    breakout: BreakoutInput,
    current_settings: TradingSettings,
) -> tuple[list, InMemoryDailyRepository, dict[str, object]]:
    repository = InMemoryDailyRepository()
    intents = plan_buy_intents(
        [ScoreRecord("STATE", 95, 90)],
        {"STATE": breakout},
        AccountState(10_000, 10_000, 0, 0, 0),
        current_settings,
        repository=repository,
        trade_date=date(2026, 7, 11),
    )
    details = json.loads(repository.candidate_evaluations[0].condition_result_json or "{}")
    return intents, repository, details


def breakout(
    *,
    vwap_usd: float | None = None,
    intraday_ma20_usd: float | None = None,
) -> BreakoutInput:
    return BreakoutInput(
        12.5,
        10.0,
        12.0,
        8.0,
        vwap_usd=vwap_usd,
        intraday_ma20_usd=intraday_ma20_usd,
    )


@pytest.mark.parametrize(
    ("condition_type", "vwap", "ma20", "state", "allowed", "reason"),
    (
        ("OR", 12.0, None, "PASS", True, None),
        ("OR", 13.0, None, "NO_DATA", True, "VWAP_MA20_DATA_MISSING"),
        ("AND", 13.0, None, "FAIL", False, "VWAP_MA20_FAILED"),
        ("AND", 12.0, None, "NO_DATA", True, "VWAP_MA20_DATA_MISSING"),
    ),
)
def test_vwap_ma20_partial_data_uses_three_state_truth_table(
    condition_type: str,
    vwap: float | None,
    ma20: float | None,
    state: str,
    allowed: bool,
    reason: str | None,
) -> None:
    intents, repository, details = evaluate(
        breakout(vwap_usd=vwap, intraday_ma20_usd=ma20),
        settings(vwap_ma20_condition_type=condition_type),
    )

    assert bool(intents) is allowed
    assert details["vwap_ma20_state"] == state
    assert repository.candidate_evaluations[0].vwap_ma20_pass == (
        True if state == "PASS" else False if state == "FAIL" else None
    )
    if reason and state == "NO_DATA":
        assert details["missing_data_reasons"] == [reason]
    elif reason:
        assert repository.candidate_evaluations[0].buy_block_reason == reason
    else:
        assert details["missing_data_reasons"] == []


def test_disabled_vwap_state_is_separate_from_raw_feature_completeness() -> None:
    intents, _, details = evaluate(
        breakout(),
        settings(require_vwap_or_ma20=False),
    )

    assert intents
    assert details["vwap_ma20_state"] == "DISABLED"
    assert details["vwap_ma20_evaluation_status"] == "DISABLED"
    assert details["required_data_quality_status"] == "COMPLETE"
    assert details["data_quality_status"] == "INCOMPLETE"
    assert {"vwap_usd", "intraday_ma20_usd"}.issubset(details["missing_features"])


def test_legacy_breakout_close_pass_remains_close_and_hold_combined() -> None:
    current = settings(
        breakout_hold_minutes=1.0,
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_vwap_or_ma20=False,
    )
    value = replace(
        breakout(),
        minutes_above_breakout=0.0,
        recent_5m_close_usd=12.2,
    )
    intents, repository, details = evaluate(value, current)

    assert intents == []
    assert repository.candidate_evaluations[0].breakout_close_pass is False
    assert details["breakout_close_only_pass"] is True
    assert details["breakout_confirmation_pass"] is False
    assert repository.candidate_evaluations[0].buy_block_reason == "BREAKOUT_HOLD_FAILED"


def test_disabled_hold_does_not_make_close_result_no_data() -> None:
    current = settings(
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_vwap_or_ma20=False,
    )
    value = replace(breakout(), recent_5m_close_usd=12.2)
    intents, repository, details = evaluate(value, current)

    assert intents
    assert details["breakout_hold_state"] == "DISABLED"
    assert details["breakout_close_only_pass"] is True
    assert details["breakout_confirmation_pass"] is True
    assert repository.candidate_evaluations[0].breakout_close_pass is True


def test_actual_failure_precedes_missing_data_in_block_reasons() -> None:
    current = settings(
        app_mode="real",
        mock_trading=False,
        breakout_hold_minutes=1.0,
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_5m_volume_increase=True,
        volume_increase_condition_mode="HARD_FILTER",
        require_vwap_or_ma20=False,
        require_pullback_rebreak=True,
        pullback_rebreak_condition_mode="HARD_FILTER",
    )
    value = replace(
        breakout(),
        minutes_above_breakout=2.0,
        recent_5m_close_usd=11.5,
    )
    intents, repository, details = evaluate(value, current)

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_block_reason == "BREAKOUT_CLOSE_FAILED"
    assert json.loads(evaluation.buy_block_reasons or "[]") == [
        "BREAKOUT_CLOSE_FAILED",
        "REQUIRED_INTRADAY_DATA_MISSING",
    ]
    assert len(details["missing_data_reasons"]) == 2
