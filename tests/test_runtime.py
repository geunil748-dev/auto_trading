from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import (
    AccountState,
    BreakoutInput,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    ScoreRecord,
)
from trading_bot.monitor_state import state_from_dry_run
from trading_bot.pipeline import ScoringRun
from trading_bot.runtime import DryRunRuntime


class Pipeline:
    def run(self) -> ScoringRun:
        target = DailyTarget(
            date(2026, 5, 22),
            CandidateSnapshot("AAA", 12, 11, 10, 0.04, 1.8, 1, 2, "Alpha"),
        )
        score = ScoreRecord("AAA", 95, 85)
        return ScoringRun(
            date(2026, 5, 22),
            None,
            (target,),
            (DailyScore(date(2026, 5, 22), score, True),),
        )


class BlockedPipeline(Pipeline):
    def run(self) -> ScoringRun:
        target = DailyTarget(
            date(2026, 5, 22),
            CandidateSnapshot("AAA", 12, 11, 10, 0.04, 1.8, 1, 2, "Alpha"),
        )
        score = ScoreRecord("AAA", 95, 85)
        return ScoringRun(
            date(2026, 5, 22),
            "MARKET_BELOW_MA20",
            (target,),
            (DailyScore(date(2026, 5, 22), score, True),),
        )


class BypassPipeline(Pipeline):
    def run(self) -> ScoringRun:
        target = DailyTarget(
            date(2026, 5, 22),
            CandidateSnapshot("AAA", 12, 11, 10, 0.04, 1.8, 1, 2, "Alpha"),
        )
        score = ScoreRecord("AAA", 95, 85)
        return ScoringRun(
            date(2026, 5, 22),
            None,
            (target,),
            (DailyScore(date(2026, 5, 22), score, True),),
            bypass_reason="MARKET_BELOW_MA20_BYPASSED",
        )


class Accounts:
    def current_account(self) -> AccountState:
        return AccountState(5000, 10000, 3000, 1, 0)


class Breakout:
    def breakout_input(self, ticker: str) -> BreakoutInput:
        assert ticker == "AAA"
        return BreakoutInput(
            last_price_usd=13,
            open_price_usd=11,
            previous_high_usd=12,
            previous_low_usd=8,
            current_5m_volume=106_000,
            previous_5m_average_volume=100_000,
        )


class FailingBreakout:
    def breakout_input(self, ticker: str) -> BreakoutInput:
        raise AssertionError(f"breakout should not be called for blocked scoring: {ticker}")


def test_dry_run_runtime_plans_buy_intents_and_monitor_state() -> None:
    settings = TradingSettings(max_entry_price_change=0.30)
    result = DryRunRuntime(Pipeline(), Accounts(), Breakout(), settings).run()
    state = state_from_dry_run(result)

    assert [(item.ticker, item.quantity) for item in result.buy_intents] == [("AAA", 153)]
    assert state["targets"][0][:7] == ["AAA", "Alpha", "$12.00", "-", "180%", "+10.0%", "86"]
    assert state["targets"][0][6]
    assert state["gates"][-1][1] == "1"


def test_dry_run_runtime_skips_buy_intents_when_scoring_is_blocked() -> None:
    settings = TradingSettings(max_entry_price_change=0.30)
    result = DryRunRuntime(BlockedPipeline(), Accounts(), FailingBreakout(), settings).run()

    assert result.scoring.blocked_reason == "MARKET_BELOW_MA20"
    assert [item.ticker for item in result.scoring.selected] == ["AAA"]
    assert result.buy_intents == ()


def test_dry_run_runtime_tags_buy_intents_when_market_bypass_is_used() -> None:
    settings = TradingSettings(max_entry_price_change=0.30)
    result = DryRunRuntime(BypassPipeline(), Accounts(), Breakout(), settings).run()

    assert result.scoring.bypass_reason == "MARKET_BELOW_MA20_BYPASSED"
    assert [(item.ticker, item.quantity) for item in result.buy_intents] == [("AAA", 153)]
    assert "MARKET_BELOW_MA20_BYPASSED" in result.buy_intents[0].entry_reason
    assert "MARKET_BELOW_MA20_BYPASSED" in result.buy_intents[0].entry_reason_detail
