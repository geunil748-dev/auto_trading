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
        self.gainers_limit: int | None = None
        self.turnover_limit: int | None = None

    def market_context(self) -> MarketContext:
        return self.context

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.gainers_limit = limit
        return (RankedStock("AAA", 1), RankedStock("BBB", 2), RankedStock("OUT", 3))

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.turnover_limit = limit
        return (RankedStock("BBB", 1), RankedStock("AAA", 2), RankedStock("CCC", 3))

    def candidate_snapshots(self, tickers: set[str]) -> dict[str, CandidateSnapshot]:
        self.snapshot_requests.append(tickers)
        return {
            "AAA": snapshot("AAA", gain_rank=1, turnover_rank=2),
            "BBB": snapshot("BBB", volume_ratio=1.0, gain_rank=2, turnover_rank=1),
        }


class EmptyMarketData:
    def __init__(self) -> None:
        self.snapshot_requests: list[set[str]] = []

    def market_context(self) -> MarketContext:
        return MarketContext(101, 100, 0.01)

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def candidate_snapshots(self, tickers: set[str]) -> dict[str, CandidateSnapshot]:
        self.snapshot_requests.append(tickers)
        return {}


class RelaxableMarketData:
    def __init__(self, price: float = 6.0) -> None:
        self.snapshot_requests: list[set[str]] = []
        self.price = price

    def market_context(self) -> MarketContext:
        return MarketContext(101, 100, 0.01)

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return (RankedStock("AAA", 1),)

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return (RankedStock("AAA", 1),)

    def candidate_snapshots(self, tickers: set[str]) -> dict[str, CandidateSnapshot]:
        self.snapshot_requests.append(tickers)
        return {"AAA": snapshot("AAA", price=self.price)}


class Scoring:
    def __init__(self) -> None:
        self.called = 0

    def score(self, candidate: CandidateSnapshot) -> ScoreRecord:
        self.called += 1
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
    price: float = 12,
    volume_ratio: float = 1.8,
    gain_rank: int = 1,
    turnover_rank: int = 1,
) -> CandidateSnapshot:
    return CandidateSnapshot(
        ticker=ticker,
        price_usd=price,
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
        TradingSettings(min_selected_candidates=2),
    ).run()

    assert run.blocked_reason is None
    assert market_data.gainers_limit == 500
    assert market_data.turnover_limit == 500
    assert market_data.snapshot_requests[0] == {"AAA", "BBB"}
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert [item.score.ticker for item in repository.scores] == ["AAA", "BBB"]
    assert [item.ticker for item in run.selected] == ["AAA", "BBB"]
    messages = [log.message for log in repository.logs]
    assert repository.logs[-1].message == "Screened 2 targets and selected 2."
    assert "CANDIDATE_SNAPSHOT_SAVED: 후보 2건을 DB에 저장했습니다." in messages
    assert "Filter rejects: none." in messages
    assert "[SAVE_TARGETS] candidate_count=2 trade_date=2026-05-22" in messages
    assert "[SAVE_SCORES] score_count=2 trade_date=2026-05-22" in messages
    assert (
        "[PIPELINE] gainers_count=3 volume_count=3 intersection_count=2 "
        "snapshot_success_count=2 snapshot_fail_count=0 risk_pass_count=2 "
        "scoring_pass_count=2 final_selected_count=2"
        in messages
    )
    assert (
        "[FILTER] removed_by_price=0 removed_by_gap=0 removed_by_volume_ratio=0 "
        "removed_by_opening_change=0 removed_by_score=0 final_count=2"
        in messages
    )
    assert any(message.startswith("[PIPELINE_SUMMARY]") for message in messages)


def test_pipeline_passes_custom_ranking_limits_to_market_data() -> None:
    market_data = MarketData(MarketContext(101, 100, 0.01))

    ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        Repository(),
        FixedClock(),
        TradingSettings(
            gainer_ranking_limit=250,
            turnover_ranking_limit=300,
            min_selected_candidates=2,
        ),
    ).run()

    assert market_data.gainers_limit == 250
    assert market_data.turnover_limit == 300


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
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert repository.scores == []
    assert market_data.snapshot_requests[0] == {"AAA", "BBB"}
    assert repository.logs[-2:] == [
        BotLog("WARNING", "pipeline", "Entry blocked: MARKET_BELOW_MA20"),
        BotLog("INFO", "pipeline", "Screened 2 targets and selected 0."),
    ]


def test_pipeline_handles_zero_listed_candidates_without_error() -> None:
    market_data = EmptyMarketData()
    repository = Repository()
    scoring = Scoring()

    run = ScreeningScoringPipeline(
        market_data,
        scoring,
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(),
    ).run()

    assert run.blocked_reason is None
    assert run.targets == ()
    assert run.scores == ()
    assert run.selected == ()
    assert repository.targets == []
    assert repository.scores == []
    assert scoring.called == 0
    assert all(request == set() for request in market_data.snapshot_requests)
    assert repository.logs[-1] == BotLog("INFO", "pipeline", "Screened 0 targets and selected 0.")
    core_logs = [
        log
        for log in repository.logs
        if not log.message.startswith(("[SAVE_", "[PIPELINE]", "[FILTER]"))
        and not log.message.startswith("[PIPELINE_SUMMARY]")
    ]
    assert core_logs[-4:] == [
        BotLog("INFO", "screening", "Filter rejects: none."),
        BotLog("INFO", "screening", "CANDIDATE_SNAPSHOT_SAVED: 후보 0건을 DB에 저장했습니다.", actual_value=0.0),
        BotLog(
            "WARNING",
            "screening",
            "CANDIDATE_SNAPSHOT_EMPTY: 후보 0건으로 수집이 완료되었습니다.",
            reject_reason="CANDIDATE_SNAPSHOT_EMPTY",
            actual_value=0.0,
            threshold_value=3.0,
        ),
        BotLog("INFO", "pipeline", "Screened 0 targets and selected 0."),
    ]


def test_pipeline_keeps_relaxed_candidate_filter_by_default() -> None:
    market_data = RelaxableMarketData()
    repository = Repository()

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=1,
            allow_relaxed_candidate_filter=True,
        ),
    ).run()

    assert [item.candidate.ticker for item in repository.targets] == ["AAA"]
    assert [item.ticker for item in run.selected] == ["AAA"]


def test_pipeline_relaxed_candidate_filter_keeps_min_price_floor() -> None:
    market_data = RelaxableMarketData(price=4.0)
    repository = Repository()
    scoring = Scoring()

    run = ScreeningScoringPipeline(
        market_data,
        scoring,
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=1,
            allow_relaxed_candidate_filter=True,
        ),
    ).run()

    assert run.targets == ()
    assert run.scores == ()
    assert run.selected == ()
    assert scoring.called == 0


def test_pipeline_strict_filter_blocks_shortfall_candidates() -> None:
    market_data = RelaxableMarketData()
    repository = Repository()
    scoring = Scoring()

    run = ScreeningScoringPipeline(
        market_data,
        scoring,
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=1,
            allow_relaxed_candidate_filter=False,
        ),
    ).run()

    assert run.blocked_reason == "STRICT_FILTER_NO_CANDIDATES"
    assert run.targets == ()
    assert run.scores == ()
    assert run.selected == ()
    assert scoring.called == 0
    assert repository.scores == []
    assert repository.logs[-2:] == [
        BotLog(
            "WARNING",
            "screening",
            "STRICT_FILTER_NO_CANDIDATES: 엄격 필터 기준을 만족한 후보가 부족합니다.",
            reject_reason="STRICT_FILTER_NO_CANDIDATES",
            actual_value=0.0,
            threshold_value=1.0,
        ),
        BotLog("INFO", "pipeline", "Screened 0 targets and selected 0."),
    ]
