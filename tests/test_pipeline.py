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
        self.snapshot_requests: list[tuple[str, ...]] = []
        self.gainers_limit: int | None = None
        self.turnover_limit: int | None = None
        self.trade_value_limit: int | None = None

    def market_context(self) -> MarketContext:
        return self.context

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.gainers_limit = limit
        return (RankedStock("AAA", 1), RankedStock("BBB", 2), RankedStock("OUT", 3))

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.turnover_limit = limit
        return (RankedStock("BBB", 1), RankedStock("AAA", 2), RankedStock("CCC", 3))

    def ranked_trade_value(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.trade_value_limit = limit
        return (RankedStock("DDD", 1), RankedStock("BBB", 2))

    def candidate_snapshots(self, tickers) -> dict[str, CandidateSnapshot]:
        batch = tuple(tickers)
        self.snapshot_requests.append(batch)
        return {
            "AAA": snapshot("AAA", gain_rank=1, turnover_rank=2),
            "BBB": snapshot("BBB", volume_ratio=1.0, gain_rank=2, turnover_rank=1),
        }


class LargeUnionMarketData:
    def __init__(
        self,
        *,
        passing_batches: set[int] | None = None,
        failing_tickers: set[str] | None = None,
    ) -> None:
        self.snapshot_requests: list[tuple[str, ...]] = []
        self.passing_batches = passing_batches or set()
        self.failing_tickers = failing_tickers or set()

    def market_context(self) -> MarketContext:
        return MarketContext(101, 100, 0.01)

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return tuple(RankedStock(f"G{index:03}", index + 1) for index in range(100))

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return tuple(RankedStock(f"V{index:03}", index + 1) for index in range(100))

    def ranked_trade_value(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        unique = [RankedStock(f"P{index:03}", index + 1) for index in range(54)]
        overlapping = [RankedStock(f"G{index:03}", index + 55) for index in range(46)]
        return tuple(unique + overlapping)

    def candidate_snapshots(self, tickers) -> dict[str, CandidateSnapshot]:
        batch = tuple(tickers)
        batch_index = len(self.snapshot_requests)
        self.snapshot_requests.append(batch)
        price = 12 if batch_index in self.passing_batches else 4
        return {
            ticker: snapshot(ticker, price=price)
            for ticker in batch
            if ticker not in self.failing_tickers
        }


class EmptyMarketData:
    def __init__(self) -> None:
        self.snapshot_requests: list[tuple[str, ...]] = []

    def market_context(self) -> MarketContext:
        return MarketContext(101, 100, 0.01)

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def ranked_trade_value(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def candidate_snapshots(self, tickers) -> dict[str, CandidateSnapshot]:
        batch = tuple(tickers)
        self.snapshot_requests.append(batch)
        return {}


class RelaxableMarketData:
    def __init__(self, price: float = 6.0) -> None:
        self.snapshot_requests: list[tuple[str, ...]] = []
        self.price = price

    def market_context(self) -> MarketContext:
        return MarketContext(101, 100, 0.01)

    def ranked_gainers(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return (RankedStock("AAA", 1),)

    def ranked_turnover(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return (RankedStock("AAA", 1),)

    def ranked_trade_value(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        return ()

    def candidate_snapshots(self, tickers) -> dict[str, CandidateSnapshot]:
        batch = tuple(tickers)
        self.snapshot_requests.append(batch)
        return {"AAA": snapshot("AAA", price=self.price)}


class RankingFailureMarketData(MarketData):
    def ranked_trade_value(self, limit: int | None = None) -> tuple[RankedStock, ...]:
        self.trade_value_limit = limit
        raise RuntimeError("trade value ranking unavailable")


class SnapshotCountMarketData(LargeUnionMarketData):
    def __init__(self) -> None:
        super().__init__(passing_batches={0})
        self.last_quote_requested_count = 0
        self.last_daily_requested_count = 0

    def candidate_snapshots(self, tickers) -> dict[str, CandidateSnapshot]:
        batch = tuple(tickers)
        self.snapshot_requests.append(batch)
        quote_failed = {batch[0], batch[1]}
        daily_failed = {batch[2]}
        self.last_quote_requested_count = len(batch)
        self.last_daily_requested_count = len(batch) - len(quote_failed)
        return {
            ticker: snapshot(ticker)
            for ticker in batch
            if ticker not in quote_failed | daily_failed
        }


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


def run_pipeline(
    market_data,
    settings: TradingSettings | None = None,
) -> tuple:
    repository = Repository()
    scoring = Scoring()
    run = ScreeningScoringPipeline(
        market_data,
        scoring,
        AccountReader(account()),
        repository,
        FixedClock(),
        settings or TradingSettings(),
    ).run()
    return run, repository, scoring


def pipeline_log(repository: Repository) -> str:
    return next(log.message for log in repository.logs if log.message.startswith("[PIPELINE]"))


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
    assert market_data.gainers_limit == 100
    assert market_data.turnover_limit == 100
    assert market_data.trade_value_limit == 100
    assert market_data.snapshot_requests[0] == ("BBB", "AAA", "DDD", "OUT", "CCC")
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert [item.score.ticker for item in repository.scores] == ["AAA", "BBB"]
    assert [item.ticker for item in run.selected] == ["AAA", "BBB"]
    messages = [log.message for log in repository.logs]
    assert repository.logs[-1].message == "Screened 2 targets and selected 2."
    assert "CANDIDATE_SNAPSHOT_SAVED: 후보 2건을 DB에 저장했습니다." in messages
    assert "Filter rejects: MISSING_SNAPSHOT=3." in messages
    assert "[SAVE_TARGETS] candidate_count=2 trade_date=2026-05-22" in messages
    assert "[SAVE_SCORES] score_count=2 trade_date=2026-05-22" in messages
    pipeline_message = next(message for message in messages if message.startswith("[PIPELINE]"))
    assert "requested_gainer_limit=100 received_gainer_count=3" in pipeline_message
    assert "requested_turnover_limit=100 received_turnover_count=3" in pipeline_message
    assert "requested_trade_value_limit=100 received_trade_value_count=2" in pipeline_message
    assert "gainers_count=3 volume_count=3 trade_value_count=2 intersection_count=2" in pipeline_message
    assert "ranking_union_count=5 ranked_evaluation_limit=5" in pipeline_message
    assert "evaluated_candidate_count=5 quote_requested_count=5 daily_requested_count=5" in pipeline_message
    assert "snapshot_success_count=2 snapshot_fail_count=3" in pipeline_message
    assert "risk_pass_count=2 filtered_candidate_count=2" in pipeline_message
    assert "scoring_pass_count=2 final_selected_count=2 selected_candidate_count=2" in pipeline_message
    assert "candidate_eval_stopped_reason=no_more_candidates" in pipeline_message
    assert (
        "[FILTER] removed_by_price=0 removed_by_gap=0 removed_by_volume_ratio=0 "
        "removed_by_opening_change=0 removed_by_score=0 final_count=2"
        in messages
    )
    assert any(message.startswith("[PIPELINE_SUMMARY]") for message in messages)


def test_pipeline_sends_candidate_notification_after_scores_are_saved() -> None:
    market_data = MarketData(MarketContext(101, 100, 0.01))
    repository = Repository()
    notifications = []

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(min_selected_candidates=2),
        candidate_notification_sender=lambda trade_date, targets, scores: notifications.append(
            (trade_date, targets, scores)
        )
        or True,
    ).run()

    assert run.blocked_reason is None
    assert len(notifications) == 1
    trade_date, targets, scores = notifications[0]
    assert trade_date == date(2026, 5, 22)
    assert [item.candidate.ticker for item in targets] == ["AAA", "BBB"]
    assert [item.score.ticker for item in scores] == ["AAA", "BBB"]
    assert any(
        log.message == "CANDIDATE_LIST_TELEGRAM_SENT: 후보 리스트 텔레그램 발송 완료"
        and log.reject_reason == "CANDIDATE_LIST_TELEGRAM_SENT"
        for log in repository.logs
    )


def test_pipeline_keeps_running_when_candidate_notification_fails() -> None:
    market_data = MarketData(MarketContext(101, 100, 0.01))
    repository = Repository()

    def fail_notification(*_args) -> bool:
        raise RuntimeError("telegram token secret")

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(min_selected_candidates=2),
        candidate_notification_sender=fail_notification,
    ).run()

    assert run.blocked_reason is None
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    failure_log = next(
        log for log in repository.logs if log.reject_reason == "CANDIDATE_LIST_TELEGRAM_FAILED"
    )
    assert failure_log.message == "CANDIDATE_LIST_TELEGRAM_FAILED: RuntimeError"
    assert "secret" not in failure_log.message


def test_pipeline_sends_entry_gate_block_notification_when_blocked() -> None:
    market_data = MarketData(MarketContext(99, 100, 0.01))
    repository = Repository()
    notifications = []

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            app_mode="real",
            mock_trading=False,
            real_trading_enabled=True,
        ),
        entry_gate_blocked_notification_sender=lambda trade_date, reason: notifications.append(
            (trade_date, reason)
        )
        or True,
    ).run()

    assert run.blocked_reason == "MARKET_BELOW_MA20"
    assert notifications == [(date(2026, 5, 22), "MARKET_BELOW_MA20")]
    assert any(
        log.message == "ENTRY_GATE_TELEGRAM_SENT: 진입 게이트 차단 알림 발송 완료"
        and log.reject_reason == "ENTRY_GATE_TELEGRAM_SENT"
        for log in repository.logs
    )


def test_pipeline_hides_entry_gate_notification_exception_message() -> None:
    market_data = MarketData(MarketContext(99, 100, 0.01))
    repository = Repository()

    def fail_notification(*_args) -> bool:
        raise RuntimeError("telegram token secret")

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            app_mode="real",
            mock_trading=False,
            real_trading_enabled=True,
        ),
        entry_gate_blocked_notification_sender=fail_notification,
    ).run()

    assert run.blocked_reason == "MARKET_BELOW_MA20"
    failure_log = next(
        log for log in repository.logs if log.reject_reason == "ENTRY_GATE_TELEGRAM_FAILED"
    )
    assert failure_log.message == "ENTRY_GATE_TELEGRAM_FAILED: RuntimeError"
    assert "secret" not in failure_log.message


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
    assert market_data.trade_value_limit == 300


def test_pipeline_logs_and_skips_market_calls_when_global_gate_blocks_entry() -> None:
    market_data = MarketData(MarketContext(99, 100, 0.01))
    repository = Repository()

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(
            app_mode="real",
            mock_trading=False,
            real_trading_enabled=True,
        ),
    ).run()

    assert run.blocked_reason == "MARKET_BELOW_MA20"
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert repository.scores == []
    assert market_data.snapshot_requests[0] == ("BBB", "AAA", "DDD", "OUT", "CCC")
    assert repository.logs[-2:] == [
        BotLog(
            "WARNING",
            "pipeline",
            "Entry blocked: MARKET_BELOW_MA20",
            reject_reason="MARKET_BELOW_MA20",
        ),
        BotLog("INFO", "pipeline", "Screened 2 targets and selected 0."),
    ]


def test_pipeline_bypasses_market_below_ma20_for_mock_trading() -> None:
    market_data = MarketData(MarketContext(99, 100, 0.01))
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
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert [item.score.ticker for item in repository.scores] == ["AAA", "BBB"]
    assert scoring.called == 2
    assert BotLog(
        "INFO",
        "pipeline",
        "Entry bypassed: MARKET_BELOW_MA20 for mock trading",
        reject_reason="MARKET_BELOW_MA20",
    ) in repository.logs


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
    assert all(request == () for request in market_data.snapshot_requests)
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


def test_pipeline_sends_no_candidate_notification_before_strict_shortfall_return() -> None:
    market_data = EmptyMarketData()
    repository = Repository()
    notifications = []

    run = ScreeningScoringPipeline(
        market_data,
        Scoring(),
        AccountReader(account()),
        repository,
        FixedClock(),
        TradingSettings(allow_relaxed_candidate_filter=False),
        candidate_notification_sender=lambda trade_date, targets, scores: notifications.append(
            (trade_date, targets, scores)
        )
        or True,
    ).run()

    assert run.blocked_reason == "STRICT_FILTER_NO_CANDIDATES"
    assert len(notifications) == 1
    trade_date, targets, scores = notifications[0]
    assert trade_date == date(2026, 5, 22)
    assert targets == ()
    assert scores == ()
    assert any(
        log.message == "CANDIDATE_LIST_TELEGRAM_SENT: 후보 리스트 텔레그램 발송 완료"
        and log.reject_reason == "CANDIDATE_LIST_TELEGRAM_SENT"
        for log in repository.logs
    )


def test_ranked_union_limits_initial_expensive_evaluation_to_configured_size() -> None:
    market_data = LargeUnionMarketData(passing_batches={0})

    run, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=5,
            initial_ranked_evaluation_limit=50,
            target_filtered_candidates=15,
        ),
    )

    assert sum(len(request) for request in market_data.snapshot_requests) == 50
    assert len(market_data.snapshot_requests) == 1
    assert len(repository.targets) == 15
    assert len(run.selected) == 5
    message = pipeline_log(repository)
    assert "ranking_union_count=254" in message
    assert "ranked_evaluation_limit=125" in message
    assert "evaluated_candidate_count=50" in message
    assert "candidate_eval_stopped_reason=target_reached" in message


def test_ranked_union_keeps_rank_fallback_order_for_expensive_evaluation() -> None:
    market_data = MarketData(MarketContext(101, 100, 0.01))

    run_pipeline(
        market_data,
        TradingSettings(min_selected_candidates=2),
    )

    assert market_data.snapshot_requests[0] == ("BBB", "AAA", "DDD", "OUT", "CCC")


def test_ranked_union_continues_when_one_ranking_api_fails() -> None:
    market_data = RankingFailureMarketData(MarketContext(101, 100, 0.01))

    run, repository, _ = run_pipeline(
        market_data,
        TradingSettings(min_selected_candidates=2),
    )

    assert run.blocked_reason is None
    assert [item.candidate.ticker for item in repository.targets] == ["AAA", "BBB"]
    assert market_data.trade_value_limit == 100
    assert any(
        log.reject_reason == "RANKING_FETCH_FAILED" and "거래대금 랭킹 조회 실패" in log.message
        for log in repository.logs
    )


def test_ranked_union_stops_before_next_batch_when_target_is_reached() -> None:
    market_data = LargeUnionMarketData(passing_batches={0, 1})

    _, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            initial_ranked_evaluation_limit=50,
            ranked_evaluation_batch_size=25,
            target_filtered_candidates=15,
        ),
    )

    assert [len(request) for request in market_data.snapshot_requests] == [50]
    assert "candidate_eval_stopped_reason=target_reached" in pipeline_log(repository)


def test_ranked_union_fetches_additional_batch_when_filtered_candidates_are_short() -> None:
    market_data = LargeUnionMarketData(passing_batches={1})

    run, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=5,
            initial_ranked_evaluation_limit=50,
            ranked_evaluation_batch_size=25,
            target_filtered_candidates=15,
        ),
    )

    assert [len(request) for request in market_data.snapshot_requests] == [50, 25]
    assert len(run.selected) == 5
    message = pipeline_log(repository)
    assert "evaluated_candidate_count=75" in message
    assert "candidate_eval_stopped_reason=target_reached" in message


def test_ranked_union_never_exceeds_max_ranked_evaluation_candidates() -> None:
    market_data = LargeUnionMarketData()

    run, repository, scoring = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            initial_ranked_evaluation_limit=50,
            ranked_evaluation_batch_size=25,
            max_ranked_evaluation_candidates=125,
            target_filtered_candidates=15,
        ),
    )

    assert [len(request) for request in market_data.snapshot_requests] == [50, 25, 25, 25]
    assert sum(len(request) for request in market_data.snapshot_requests) == 125
    assert run.selected == ()
    assert scoring.called == 0
    message = pipeline_log(repository)
    assert "evaluated_candidate_count=125" in message
    assert "candidate_eval_stopped_reason=max_evaluation_candidates_reached" in message


def test_ranked_union_timeout_budget_uses_current_filtered_candidates(monkeypatch) -> None:
    values = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 2.0])

    def fake_perf_counter() -> float:
        return next(values, 2.0)

    monkeypatch.setattr("trading_bot.pipeline.perf_counter", fake_perf_counter)
    market_data = LargeUnionMarketData(passing_batches={0, 1})

    run, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=5,
            initial_ranked_evaluation_limit=50,
            ranked_evaluation_batch_size=25,
            target_filtered_candidates=100,
            candidate_eval_timeout_seconds=1,
        ),
    )

    assert [len(request) for request in market_data.snapshot_requests] == [50]
    assert len(repository.targets) == 50
    assert len(run.selected) == 5
    message = pipeline_log(repository)
    assert "filtered_candidate_count=50" in message
    assert "candidate_eval_stopped_reason=timeout_budget_exceeded" in message


def test_ranked_union_partial_snapshot_failures_drop_only_failed_tickers() -> None:
    market_data = LargeUnionMarketData(
        passing_batches={0},
        failing_tickers={"G000", "G001", "G002"},
    )

    run, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=5,
            initial_ranked_evaluation_limit=50,
            target_filtered_candidates=15,
        ),
    )

    assert len(market_data.snapshot_requests) == 1
    assert len(repository.targets) == 15
    assert len(run.selected) == 5
    message = pipeline_log(repository)
    assert "evaluated_candidate_count=50" in message
    assert "snapshot_fail_count=3" in message


def test_ranked_union_uses_market_data_snapshot_request_counts() -> None:
    market_data = SnapshotCountMarketData()

    _, repository, _ = run_pipeline(
        market_data,
        TradingSettings(
            min_selected_candidates=1,
            max_selected_candidates=5,
            initial_ranked_evaluation_limit=50,
            target_filtered_candidates=15,
        ),
    )

    message = pipeline_log(repository)
    assert "evaluated_candidate_count=50" in message
    assert "quote_requested_count=50" in message
    assert "daily_requested_count=48" in message
    assert "snapshot_fail_count=3" in message


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
