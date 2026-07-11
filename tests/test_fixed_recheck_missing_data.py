import json
from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.in_memory import InMemoryDailyRepository
from trading_bot.models import AccountState, BreakoutInput, ScoreRecord
from trading_bot.runtime import DryRunResult
from trading_bot.scheduler_recheck import recheck_fixed_watchlist


TRADE_DATE = date(2026, 7, 11)


class Scoring:
    trade_date = TRADE_DATE
    selected = (ScoreRecord("FIXED", 95, 90),)


class Accounts:
    def current_account(self) -> AccountState:
        return AccountState(10_000, 10_000, 0, 0, 0)


class Runtime:
    def __init__(self) -> None:
        self.accounts = Accounts()
        self.breakout = self

    def breakout_input(self, ticker: str) -> BreakoutInput:
        assert ticker == "FIXED"
        return BreakoutInput(
            last_price_usd=12.5,
            open_price_usd=10.0,
            previous_high_usd=12.0,
            previous_low_usd=8.0,
            minutes_above_breakout=2.0,
            recent_5m_close_usd=12.2,
            current_5m_volume=None,
            previous_5m_average_volume=None,
            pulled_back_after_breakout=True,
        )


def settings(**changes: object) -> TradingSettings:
    values = {
        "max_entry_price_change": 0.30,
        "breakout_hold_minutes": 1.0,
        "require_5m_close_above_breakout": True,
        "require_5m_volume_increase": True,
        "require_vwap_or_ma20": False,
        "require_pullback_rebreak": True,
    }
    values.update(changes)
    return TradingSettings(**values)


def opening_result() -> DryRunResult:
    account = AccountState(10_000, 10_000, 0, 0, 0)
    return DryRunResult(account, Scoring(), ())


def test_fixed_recheck_keeps_hard_fail_but_logs_no_data_in_mock() -> None:
    repository = InMemoryDailyRepository()
    result = recheck_fixed_watchlist(
        Runtime(),
        opening_result(),
        settings(),
        repository,
    )

    assert [intent.ticker for intent in result.buy_intents] == ["FIXED"]
    details = json.loads(repository.candidate_evaluations[0].condition_result_json or "{}")
    snapshot = json.loads(repository.candidate_evaluations[0].settings_snapshot_json or "{}")
    assert details["volume_increase_state"] == "NO_DATA"
    assert details["failed_hard_reasons"] == []
    assert details["missing_data_reasons"] == ["VOLUME_INCREASE_DATA_MISSING"]
    assert snapshot["intradayMissingDataPolicy"] == "LOG_ONLY"


def test_fixed_recheck_real_missing_data_is_fail_closed() -> None:
    repository = InMemoryDailyRepository()
    result = recheck_fixed_watchlist(
        Runtime(),
        opening_result(),
        settings(
            app_mode="real",
            mock_trading=False,
            intraday_missing_data_policy="LOG_ONLY",
        ),
        repository,
    )

    assert result.buy_intents == ()
    assert repository.candidate_evaluations[0].buy_block_reason == (
        "VOLUME_INCREASE_DATA_MISSING"
    )
