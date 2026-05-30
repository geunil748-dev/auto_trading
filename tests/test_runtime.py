from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import (
    AccountState,
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


class Accounts:
    def current_account(self) -> AccountState:
        return AccountState(5000, 10000, 3000, 1, 0)


class Breakout:
    def breakout_input(self, ticker: str) -> tuple[float, float, float, float]:
        assert ticker == "AAA"
        return (13, 11, 12, 8)


def test_dry_run_runtime_plans_buy_intents_and_monitor_state() -> None:
    result = DryRunRuntime(Pipeline(), Accounts(), Breakout(), TradingSettings()).run()
    state = state_from_dry_run(result)

    assert [(item.ticker, item.quantity) for item in result.buy_intents] == [("AAA", 153)]
    assert state["targets"][0][:7] == ["AAA", "Alpha", "$12.00", "-", "180%", "+10.0%", "86"]
    assert state["targets"][0][6]
    assert state["gates"][-1][1] == "1"
