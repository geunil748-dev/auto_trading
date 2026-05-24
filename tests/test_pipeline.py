from datetime import date

from trading_bot.config import TradingSettings
from trading_bot.models import (
    AccountState,
    BotLog,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    MarketContext,
    RankedStock,
    ScoreRecord,
)
from trading_bot.pipeline import ScreeningScoringPipeline


class FixedClock:
    def today(self) -> date:
        return date(2026, 5, 22)


class AccountReader:
    def __init__(self, account: AccountState) -> None:
        self.account = account

    def current_account(self) -> AccountState:
        return self.account


class Repository:
    def __init__(self) -> None:
        self.targets: list[DailyTarget] = []
        self.scores: list[DailyScore] = []
        self.logs: list[BotLog] = []

    def save_daily_targets(self, targets: tuple[DailyTarget, ...]) -> None:
        self.targets.extend(targets)

    def save_daily_scores(self, scores: tuple[DailyScore, ...]) -> None:
        self.scores.extend(scores)

    def save_log(self, log: BotLog) -> None:
        self.logs.append(log)


class MarketData:
    def __init__(self, context: MarketContext) -> None:
        self.context = context
        self.snapshot_requests: list[set[str]] = []

    def market_context(self) -> MarketContext:
        return self.context

    def ranked_gainers(self) -> tuple[RankedStock, ...]:
        return (RankedStock("AAA", 1), RankedStock("BBB", 2), RankedStock("OUT", 3))

    def ranked_turnover(self) -> tuple[RankedStock, ...]:
        return (RankedStock("BBB", 1), RankedStock("AAA", 2), RankedStock("CCC", 3))

    def candidate_snapshots(self, tickers: set[str]) -> dict[str, CandidateSnapshot]:
        self.snapshot_requests.append(tickers)
        return {
            "AAA": snapshot("AAA", gain_rank=1, turnover_rank=2),
            "BBB": snapshot("BBB", volume_ratio=1.0, gain_rank=2, turnover_rank=1),
        }


class Scoring:
    def score(self, candidate: CandidateSnapshot) -> ScoreRecord:
        return ScoreRecord(candidate.ticker, news_score=95, chart_score=80)


def account() -> AccountState:
    return AccountState(
        cash_usd=4000,
        equity_usd=10000,
        invested_usd=3000,
        open_positions=1,
        daily_profit_rate=0,
    )


def snapshot(
    ticker: str,
    volume_ratio: float = 1.8,
    gain_rank: int = 1,
    turnover_rank: int = 1,
) -> CandidateSnapshot:
    return CandidateSnapshot(
        ticker=ticker,
        price_usd=12,
        open_price_usd=11,
        previous_close_usd=10,
        opening_price_change=0.04,
        opening_volume_ratio=volume_ratio,
        gain_rank=gain_rank,
        turnover_rank=turnover_rank,
    )


def test_pipeline_screens_scores_and_persists_selected_candidates() -> None:
    market_data = MarketData(MarketContext(101, 100, 0.01))
    repository = Repository()

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(),
    ).run()

    assert run.blocked_reason is None
    assert market_data.snapshot_requests == [{"AAA", "BBB"}]
    assert [item.candidate.ticker for item in repository.targets] == ["AAA"]
    assert [item.score.ticker for item in repository.scores] == ["AAA"]
    assert [item.ticker for item in run.selected] == ["AAA"]
    assert repository.logs[-1].message == "Screened 1 targets and selected 1."
    assert repository.logs[-2].message == "Filter rejects: LOW_OPENING_VOLUME=1."


def test_pipeline_logs_and_skips_market_calls_when_global_gate_blocks_entry() -> None:
    market_data = MarketData(MarketContext(99, 100, 0.01))
    repository = Repository()

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(),
    ).run()

    assert run.blocked_reason == "MARKET_BELOW_MA20"
    assert repository.targets == []
    assert market_data.snapshot_requests == []
    assert repository.logs == [BotLog("WARNING", "pipeline", "Entry blocked: MARKET_BELOW_MA20")]
