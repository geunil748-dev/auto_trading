import json
from dataclasses import replace
from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.models import AccountState, BreakoutInput, BuyIntent, ScoreRecord
from trading_bot.order_execution import BuyIntentExecutor


TRADE_DATE = date(2026, 7, 11)


def strict_settings(**changes: object) -> TradingSettings:
    settings = TradingSettings(
        max_entry_price_change=0.30,
        breakout_hold_minutes=1.0,
        require_5m_close_above_breakout=True,
        breakout_close_condition_mode="HARD_FILTER",
        require_5m_volume_increase=True,
        volume_increase_condition_mode="HARD_FILTER",
        min_5m_volume_increase_percent=5.0,
        require_vwap_or_ma20=True,
        vwap_ma20_condition_mode="HARD_FILTER",
        vwap_ma20_condition_type="OR",
        require_pullback_rebreak=True,
        pullback_rebreak_condition_mode="HARD_FILTER",
    )
    return replace(settings, **changes)


def complete_breakout(**changes: object) -> BreakoutInput:
    breakout = BreakoutInput(
        last_price_usd=12.5,
        open_price_usd=10.0,
        previous_high_usd=12.0,
        previous_low_usd=8.0,
        minutes_above_breakout=2.0,
        recent_5m_close_usd=12.2,
        current_5m_volume=106_000,
        previous_5m_average_volume=100_000,
        vwap_usd=12.0,
        intraday_ma20_usd=12.1,
        pulled_back_after_breakout=True,
    )
    return replace(breakout, **changes)


def account() -> AccountState:
    return AccountState(10_000, 10_000, 0, 0, 0)


def evaluate(
    breakout: BreakoutInput,
    settings: TradingSettings,
) -> tuple[list[BuyIntent], InMemoryDailyRepository, dict[str, object]]:
    repository = InMemoryDailyRepository()
    intents = plan_buy_intents(
        [ScoreRecord("TEST", 95, 90)],
        {"TEST": breakout},
        account(),
        settings,
        repository=repository,
        trade_date=TRADE_DATE,
        source="fixed_recheck",
    )
    details = json.loads(repository.candidate_evaluations[0].condition_result_json or "{}")
    return intents, repository, details


def test_mock_auto_logs_missing_volume_without_false_failure() -> None:
    intents, repository, details = evaluate(
        complete_breakout(
            current_5m_volume=None,
            previous_5m_average_volume=None,
        ),
        strict_settings(),
    )

    assert [intent.ticker for intent in intents] == ["TEST"]
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is True
    assert evaluation.soft_score_adjustment == 0.0
    assert details["volume_increase_state"] == "NO_DATA"
    assert details["volume_increase_pass"] is None
    assert details["missing_data_reasons"] == ["VOLUME_INCREASE_DATA_MISSING"]
    assert "VOLUME_INCREASE_FAILED" not in details["failed_hard_reasons"]
    assert "VOLUME_INCREASE_FAILED" not in details["failed_soft_reasons"]
    assert details["data_quality_status"] == "INCOMPLETE"
    assert details["intraday_missing_data_policy"] == "LOG_ONLY"
    assert details["app_mode"] == "test"
    assert details["mock_trading"] is True
    assert repository.trading_events[0].event_type == "BUY_ALLOWED"
    assert repository.trading_events[0].reason_code == "VOLUME_INCREASE_DATA_MISSING"
    assert repository.trading_events[0].is_blocking is False
    event_details = repository.trading_events[0].details_json
    assert isinstance(event_details, dict)
    assert event_details["missing_data_reasons"] == ["VOLUME_INCREASE_DATA_MISSING"]
    candidate_logs = [log for log in repository.logs if log.module == "candidate_evaluation"]
    assert len(candidate_logs) == 1
    assert candidate_logs[0].reject_reason == "BUY_ALLOWED"
    assert "current_5m_volume" in intents[0].entry_reason_detail


def test_real_forces_block_and_empty_executor_does_not_submit() -> None:
    settings = strict_settings(
        app_mode="real",
        mock_trading=False,
        intraday_missing_data_policy="LOG_ONLY",
    )
    intents, repository, details = evaluate(
        complete_breakout(
            current_5m_volume=None,
            previous_5m_average_volume=None,
        ),
        settings,
    )

    assert intents == []
    evaluation = repository.candidate_evaluations[0]
    assert evaluation.buy_allowed is False
    assert evaluation.buy_block_reason == "VOLUME_INCREASE_DATA_MISSING"
    assert details["intraday_missing_data_policy"] == "BLOCK"
    assert details["volume_increase_state"] == "NO_DATA"
    assert repository.trading_events[0].event_type == "BUY_BLOCKED"
    assert repository.trading_events[0].is_blocking is True

    submitted: list[BuyIntent] = []
    trades = BuyIntentExecutor(
        submit_order=lambda intent: submitted.append(intent) or {"ok": True},
        repository=repository,
        today=lambda: TRADE_DATE,
        settings=settings,
    ).execute(intents)
    assert submitted == []
    assert trades == []


def test_real_uses_required_reason_when_multiple_features_are_missing() -> None:
    intents, repository, details = evaluate(
        BreakoutInput(12.5, 10.0, 12.0, 8.0),
        strict_settings(app_mode="real", mock_trading=False),
    )

    assert intents == []
    assert repository.candidate_evaluations[0].buy_block_reason == (
        "REQUIRED_INTRADAY_DATA_MISSING"
    )
    assert len(details["missing_data_reasons"]) == 5
    assert repository.trading_events[0].reason_code == (
        "REQUIRED_INTRADAY_DATA_MISSING"
    )


def test_present_low_volume_remains_actual_failure() -> None:
    intents, repository, details = evaluate(
        complete_breakout(current_5m_volume=103_000),
        strict_settings(),
    )

    assert intents == []
    assert repository.candidate_evaluations[0].buy_block_reason == "VOLUME_INCREASE_FAILED"
    assert details["volume_increase_state"] == "FAIL"
    assert details["volume_increase_pass"] is False
    assert details["volume_increase_percent"] == 3.0
    assert details["missing_data_reasons"] == []


def test_present_sufficient_volume_is_pass() -> None:
    intents, _, details = evaluate(
        complete_breakout(current_5m_volume=106_000),
        strict_settings(),
    )

    assert [intent.ticker for intent in intents] == ["TEST"]
    assert details["volume_increase_state"] == "PASS"
    assert details["volume_increase_pass"] is True
    assert details["missing_data_reasons"] == []


def test_missing_close_is_logged_in_mock_and_blocked_in_real() -> None:
    mock_intents, _, mock_details = evaluate(
        complete_breakout(recent_5m_close_usd=None),
        strict_settings(),
    )
    real_intents, real_repository, real_details = evaluate(
        complete_breakout(recent_5m_close_usd=None),
        strict_settings(app_mode="real", mock_trading=False),
    )

    assert [intent.ticker for intent in mock_intents] == ["TEST"]
    assert mock_details["breakout_close_state"] == "NO_DATA"
    assert mock_details["missing_data_reasons"] == ["BREAKOUT_CLOSE_DATA_MISSING"]
    assert real_intents == []
    assert real_details["breakout_close_state"] == "NO_DATA"
    assert real_repository.candidate_evaluations[0].buy_block_reason == (
        "BREAKOUT_CLOSE_DATA_MISSING"
    )


def test_missing_hold_and_actual_zero_minutes_are_distinct() -> None:
    missing_intents, _, missing_details = evaluate(
        complete_breakout(minutes_above_breakout=None),
        strict_settings(),
    )
    zero_intents, zero_repository, zero_details = evaluate(
        complete_breakout(minutes_above_breakout=0.0),
        strict_settings(),
    )

    assert [intent.ticker for intent in missing_intents] == ["TEST"]
    assert missing_details["breakout_hold_state"] == "NO_DATA"
    assert missing_details["breakout_hold_pass"] is None
    assert zero_intents == []
    assert zero_details["breakout_hold_state"] == "FAIL"
    assert zero_details["breakout_hold_pass"] is False
    assert zero_repository.candidate_evaluations[0].buy_block_reason == (
        "BREAKOUT_HOLD_FAILED"
    )


def test_missing_pullback_uses_mock_log_only_and_real_block() -> None:
    mock_intents, _, mock_details = evaluate(
        complete_breakout(pulled_back_after_breakout=None),
        strict_settings(),
    )
    real_intents, real_repository, real_details = evaluate(
        complete_breakout(pulled_back_after_breakout=None),
        strict_settings(app_mode="real", mock_trading=False),
    )

    assert [intent.ticker for intent in mock_intents] == ["TEST"]
    assert mock_details["pullback_rebreak_state"] == "NO_DATA"
    assert real_intents == []
    assert real_details["intraday_missing_data_policy"] == "BLOCK"
    assert real_repository.candidate_evaluations[0].buy_block_reason == (
        "PULLBACK_REBREAK_DATA_MISSING"
    )


def test_present_pullback_false_remains_actual_failure() -> None:
    intents, repository, details = evaluate(
        complete_breakout(pulled_back_after_breakout=False),
        strict_settings(),
    )

    assert intents == []
    assert details["pullback_rebreak_state"] == "FAIL"
    assert details["missing_data_reasons"] == []
    assert repository.candidate_evaluations[0].buy_block_reason == (
        "PULLBACK_REBREAK_FAILED"
    )


def test_missing_vwap_ma20_has_standard_and_legacy_no_data_status() -> None:
    mock_intents, _, mock_details = evaluate(
        complete_breakout(vwap_usd=None, intraday_ma20_usd=None),
        strict_settings(),
    )
    real_intents, real_repository, real_details = evaluate(
        complete_breakout(vwap_usd=None, intraday_ma20_usd=None),
        strict_settings(app_mode="real", mock_trading=False),
    )

    assert [intent.ticker for intent in mock_intents] == ["TEST"]
    assert mock_details["vwap_ma20_state"] == "NO_DATA"
    assert mock_details["vwap_ma20_evaluation_status"] == "SKIPPED_NO_DATA"
    assert mock_details["vwap_ma20_pass"] is None
    assert real_intents == []
    assert real_details["vwap_ma20_state"] == "NO_DATA"
    assert real_repository.candidate_evaluations[0].buy_block_reason == (
        "VWAP_MA20_DATA_MISSING"
    )


def test_complete_data_preserves_existing_pass_behavior() -> None:
    intents, repository, details = evaluate(complete_breakout(), strict_settings())

    assert [intent.ticker for intent in intents] == ["TEST"]
    assert repository.candidate_evaluations[0].buy_allowed is True
    assert set(details["condition_states"].values()) == {"PASS"}
    assert details["data_quality_status"] == "COMPLETE"
    assert details["missing_data_reasons"] == []
    assert details["missing_features"] == []


def test_non_triggered_candidate_still_records_data_quality_context() -> None:
    intents, repository, details = evaluate(
        complete_breakout(
            last_price_usd=11.5,
            current_5m_volume=None,
            previous_5m_average_volume=None,
        ),
        strict_settings(),
    )

    assert intents == []
    assert repository.candidate_evaluations[0].buy_block_reason == "BREAKOUT_NOT_TRIGGERED"
    assert details["data_quality_status"] == "INCOMPLETE"
    assert details["missing_data_reasons"] == ["VOLUME_INCREASE_DATA_MISSING"]
    assert details["intraday_missing_data_policy"] == "LOG_ONLY"
