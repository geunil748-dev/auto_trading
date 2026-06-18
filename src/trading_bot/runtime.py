from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import TradingSettings
from trading_bot.entry_planner import plan_buy_intents
from trading_bot.models import AccountState, BuyIntent
from trading_bot.pipeline import ScoringRun, ScreeningScoringPipeline
from trading_bot.ports import AccountReader, BreakoutSource


@dataclass(frozen=True)
class DryRunResult:
    account: AccountState
    scoring: ScoringRun
    buy_intents: tuple[BuyIntent, ...]


class DryRunRuntime:
    def __init__(
        self,
        pipeline: ScreeningScoringPipeline,
        accounts: AccountReader,
        breakout: BreakoutSource,
        settings: TradingSettings,
    ) -> None:
        self.pipeline = pipeline
        self.accounts = accounts
        self.breakout = breakout
        self.settings = settings

    def run(self) -> DryRunResult:
        account = self.accounts.current_account()
        scoring = self.pipeline.run()
        if scoring.blocked_reason:
            return DryRunResult(account, scoring, ())
        breakout_inputs = {
            item.ticker: self.breakout.breakout_input(item.ticker)
            for item in scoring.selected
        }
        intents = plan_buy_intents(
            scoring.selected,
            breakout_inputs,
            account,
            self.settings,
            repository=getattr(self.pipeline, "repository", None),
            trade_date=scoring.trade_date,
            source="dry_run",
            source_by_ticker={
                item.ticker: scoring.candidate_source(item.ticker)
                for item in scoring.selected
            },
            entry_reason_tags=(
                (scoring.bypass_reason,) if scoring.bypass_reason else ()
            ),
        )
        return DryRunResult(account, scoring, tuple(intents))
