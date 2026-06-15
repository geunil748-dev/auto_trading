from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from time import perf_counter

from trading_bot.config import RANKING_SELECTION_COMPOSITE, TradingSettings
from trading_bot.models import (
    BotLog,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    RankedStock,
    ScoreRecord,
)
from trading_bot.ports import (
    AccountReader,
    DailyRepository,
    ManualBuyListSource,
    ScoringProvider,
    ScreeningMarketData,
    TradingClock,
)
from trading_bot.risk import global_entry_gate
from trading_bot.scoring import select_candidates
from trading_bot.screening import (
    composite_ranking_selection,
    opening_screen_reason,
    ranking_intersection,
    screening_rejection_counts,
    screening_priority_score,
)

CANDIDATE_EVAL_TARGET_REACHED = "target_reached"
CANDIDATE_EVAL_MAX_REACHED = "max_evaluation_candidates_reached"
CANDIDATE_EVAL_TIMEOUT = "timeout_budget_exceeded"
CANDIDATE_EVAL_NO_MORE = "no_more_candidates"
CANDIDATE_SOURCE_AUTO = "auto"
CANDIDATE_SOURCE_BOTH = "both"
CANDIDATE_SOURCE_MANUAL = "manual_buy_list"


CandidateNotificationSender = Callable[
    [date, tuple[DailyTarget, ...], tuple[DailyScore, ...]],
    bool,
]


@dataclass(frozen=True)
class ScoringRun:
    trade_date: date
    blocked_reason: str | None
    targets: tuple[DailyTarget, ...]
    scores: tuple[DailyScore, ...]
    candidate_sources: dict[str, str] = field(default_factory=dict)

    @property
    def selected(self) -> tuple[ScoreRecord, ...]:
        return tuple(item.score for item in self.scores if item.is_selected)

    def candidate_source(self, ticker: str) -> str:
        return self.candidate_sources.get(ticker, CANDIDATE_SOURCE_AUTO)


@dataclass(frozen=True)
class RelaxationProfile:
    level: int
    gainer_limit: int
    turnover_limit: int
    settings: TradingSettings


@dataclass(frozen=True)
class CandidateEvaluationProgress:
    snapshots: dict[str, CandidateSnapshot]
    candidates: list[CandidateSnapshot]
    evaluated_tickers: set[str]
    ranked_evaluation_limit: int
    quote_requested_count: int
    daily_requested_count: int
    stopped_reason: str
    elapsed_ms: int


@dataclass(frozen=True)
class ManualCandidateProgress:
    snapshots: dict[str, CandidateSnapshot]
    candidates: list[CandidateSnapshot]
    evaluated_tickers: set[str]
    quote_requested_count: int
    daily_requested_count: int


class ScreeningScoringPipeline:
    def __init__(
        self,
        market_data: ScreeningMarketData,
        scoring: ScoringProvider,
        accounts: AccountReader,
        repository: DailyRepository,
        clock: TradingClock,
        settings: TradingSettings,
        manual_source: ManualBuyListSource | None = None,
        candidate_notification_sender: CandidateNotificationSender | None = None,
    ) -> None:
        self.market_data = market_data
        self.scoring = scoring
        self.accounts = accounts
        self.repository = repository
        self.clock = clock
        self.settings = settings
        self.manual_source = manual_source
        self.candidate_notification_sender = candidate_notification_sender

    def run(self) -> ScoringRun:
        started_at = perf_counter()
        trade_date = self.clock.today()
        market = self.market_data.market_context()
        account = self.accounts.current_account()
        entry_gate = global_entry_gate(
            market.nasdaq_price_usd,
            market.nasdaq_ma20_usd,
            market.fx_change_rate,
            account,
            self.settings,
        )
        snapshots = {}
        requested_tickers: set[str] = set()
        evaluated_tickers: set[str] = set()
        quote_requested_count = 0
        daily_requested_count = 0
        ranked_evaluation_limit = 0
        candidate_eval_stopped_reason = CANDIDATE_EVAL_NO_MORE
        candidate_eval_elapsed_ms = 0
        candidate_eval_started_at = perf_counter()
        intersection_tickers: set[str] = set()
        gainers: tuple[RankedStock, ...] = ()
        turnover: tuple[RankedStock, ...] = ()
        trade_value: tuple[RankedStock, ...] = ()
        candidates = []
        active_profile = _relaxation_profiles(self.settings)[0]
        for profile in _relaxation_profiles(self.settings):
            if profile.level > 0 and not self.settings.allow_relaxed_candidate_filter:
                break
            active_profile = profile
            gainers = self._fetch_ranked_stocks(
                "상승률",
                lambda: self.market_data.ranked_gainers(profile.gainer_limit),
            )
            turnover = self._fetch_ranked_stocks(
                "거래량",
                lambda: self.market_data.ranked_turnover(profile.turnover_limit),
            )
            trade_value = self._fetch_ranked_stocks(
                "거래대금",
                lambda: self.market_data.ranked_trade_value(profile.turnover_limit),
            )
            gainer_tickers = {item.ticker for item in gainers}
            turnover_tickers = {item.ticker for item in turnover}
            trade_value_tickers = {item.ticker for item in trade_value}
            intersection_tickers = gainer_tickers & turnover_tickers
            requested_tickers = gainer_tickers | turnover_tickers | trade_value_tickers
            ranked_gainers = _with_missing_ranks(gainers, requested_tickers)
            ranked_turnover = _with_missing_ranks(turnover, requested_tickers)
            progress = self._evaluate_ranked_candidates(
                ranked_tickers=_ranked_evaluation_order(
                    gainers,
                    turnover,
                    trade_value,
                    requested_tickers,
                ),
                ranked_gainers=ranked_gainers,
                ranked_turnover=ranked_turnover,
                raw_gainers=gainers,
                raw_turnover=turnover,
                raw_trade_value=trade_value,
                snapshots=snapshots,
                evaluated_tickers=evaluated_tickers,
                settings=profile.settings,
                eval_started_at=candidate_eval_started_at,
            )
            snapshots = progress.snapshots
            candidates = progress.candidates
            evaluated_tickers = progress.evaluated_tickers
            quote_requested_count += progress.quote_requested_count
            daily_requested_count += progress.daily_requested_count
            ranked_evaluation_limit = progress.ranked_evaluation_limit
            candidate_eval_stopped_reason = progress.stopped_reason
            candidate_eval_elapsed_ms = progress.elapsed_ms
            self._log_relaxation_profile(profile, len(candidates))
            if len(candidates) >= self.settings.min_selected_candidates:
                break
        initial_intersection_count = len(intersection_tickers)
        ranking_union_count = len(requested_tickers)
        manual_progress = self._manual_candidate_progress(
            snapshots,
            active_profile.settings,
            evaluated_tickers,
        )
        snapshots = manual_progress.snapshots
        manual_candidates = manual_progress.candidates
        evaluated_tickers = manual_progress.evaluated_tickers
        quote_requested_count += manual_progress.quote_requested_count
        daily_requested_count += manual_progress.daily_requested_count
        candidates, candidate_sources = _merge_candidate_sources(candidates, manual_candidates)
        strict_shortfall = (
            not self.settings.allow_relaxed_candidate_filter
            and len(candidates) < self.settings.min_selected_candidates
            and not manual_candidates
        )
        self._save_screening_diagnostics(
            requested_tickers,
            snapshots,
            active_profile.settings,
            evaluated_tickers,
        )
        targets = tuple(DailyTarget(trade_date, item) for item in candidates)
        self._safe_log(
            BotLog(
                "INFO",
                "screening",
                f"[SAVE_TARGETS] candidate_count={len(targets)} trade_date={trade_date.isoformat()}",
            )
        )
        try:
            self.repository.save_daily_targets(targets)
        except Exception as exc:
            self._safe_log(
                BotLog(
                    "ERROR",
                    "screening",
                    f"CANDIDATE_SNAPSHOT_SAVE_FAILED: 후보 저장에 실패했습니다. ({exc})",
                    actual_value=float(len(targets)),
                )
            )
            raise
        self.repository.save_log(
            BotLog(
                "INFO",
                "screening",
                f"CANDIDATE_SNAPSHOT_SAVED: 후보 {len(targets)}건을 DB에 저장했습니다.",
                actual_value=float(len(targets)),
            )
        )
        if not targets:
            self.repository.save_log(
                BotLog(
                    "WARNING",
                    "screening",
                    "CANDIDATE_SNAPSHOT_EMPTY: 후보 0건으로 수집이 완료되었습니다.",
                    reject_reason="CANDIDATE_SNAPSHOT_EMPTY",
                    actual_value=0.0,
                    threshold_value=float(self.settings.min_selected_candidates),
                )
            )

        if strict_shortfall:
            self._log_pipeline_diagnostics(
                started_at,
                requested_gainer_limit=active_profile.gainer_limit,
                requested_turnover_limit=active_profile.turnover_limit,
                requested_trade_value_limit=active_profile.turnover_limit,
                gainers_count=len(gainers),
                volume_count=len(turnover),
                trade_value_count=len(trade_value),
                intersection_count=initial_intersection_count,
                ranking_union_count=ranking_union_count,
                ranked_evaluation_limit=ranked_evaluation_limit,
                evaluated_candidate_count=len(evaluated_tickers),
                quote_requested_count=quote_requested_count,
                daily_requested_count=daily_requested_count,
                snapshot_success_count=len(snapshots),
                snapshot_fail_count=len(evaluated_tickers - snapshots.keys()),
                risk_pass_count=len(candidates),
                scoring_pass_count=0,
                final_selected_count=0,
                saved_count=len(targets),
                candidate_eval_elapsed_ms=candidate_eval_elapsed_ms,
                candidate_eval_stopped_reason=candidate_eval_stopped_reason,
                snapshots=snapshots,
                scored=(),
                settings=active_profile.settings,
            )
            self.repository.save_log(
                BotLog(
                    "WARNING",
                    "screening",
                    "STRICT_FILTER_NO_CANDIDATES: 엄격 필터 기준을 만족한 후보가 부족합니다.",
                    reject_reason="STRICT_FILTER_NO_CANDIDATES",
                    actual_value=float(len(candidates)),
                    threshold_value=float(self.settings.min_selected_candidates),
                )
            )
            self.repository.save_log(
                BotLog(
                    "INFO",
                    "pipeline",
                    f"Screened {len(targets)} targets and selected 0.",
                )
            )
            self._send_candidate_notification(trade_date, targets, ())
            return ScoringRun(
                trade_date,
                "STRICT_FILTER_NO_CANDIDATES",
                targets,
                (),
                candidate_sources,
            )

        if not entry_gate.allowed:
            self._log_pipeline_diagnostics(
                started_at,
                requested_gainer_limit=active_profile.gainer_limit,
                requested_turnover_limit=active_profile.turnover_limit,
                requested_trade_value_limit=active_profile.turnover_limit,
                gainers_count=len(gainers),
                volume_count=len(turnover),
                trade_value_count=len(trade_value),
                intersection_count=initial_intersection_count,
                ranking_union_count=ranking_union_count,
                ranked_evaluation_limit=ranked_evaluation_limit,
                evaluated_candidate_count=len(evaluated_tickers),
                quote_requested_count=quote_requested_count,
                daily_requested_count=daily_requested_count,
                snapshot_success_count=len(snapshots),
                snapshot_fail_count=len(evaluated_tickers - snapshots.keys()),
                risk_pass_count=len(candidates),
                scoring_pass_count=0,
                final_selected_count=0,
                saved_count=len(targets),
                candidate_eval_elapsed_ms=candidate_eval_elapsed_ms,
                candidate_eval_stopped_reason=candidate_eval_stopped_reason,
                snapshots=snapshots,
                scored=(),
                settings=active_profile.settings,
            )
            self.repository.save_log(
                BotLog("WARNING", "pipeline", f"Entry blocked: {entry_gate.reason}")
            )
            self.repository.save_log(
                BotLog(
                    "INFO",
                    "pipeline",
                    f"Screened {len(targets)} targets and selected 0.",
                )
            )
            return ScoringRun(trade_date, entry_gate.reason, targets, (), candidate_sources)

        scored = [self.scoring.score(item) for item in candidates]
        scoring_settings = active_profile.settings
        scoring_pass_count = sum(
            1 for item in scored if item.total_score >= scoring_settings.min_total_score
        )
        if (
            self.settings.allow_relaxed_candidate_filter
            and scoring_pass_count < self.settings.min_selected_candidates
            and scoring_settings.min_total_score > 35.0
        ):
            scoring_settings = replace(scoring_settings, min_total_score=35.0)
            active_profile = RelaxationProfile(
                max(active_profile.level, 6),
                active_profile.gainer_limit,
                active_profile.turnover_limit,
                scoring_settings,
            )
            scoring_pass_count = sum(
                1 for item in scored if item.total_score >= scoring_settings.min_total_score
            )
            self._log_relaxation_profile(active_profile, len(candidates))
        selected_tickers = _selected_tickers_by_source(scored, scoring_settings, candidate_sources)
        scores = tuple(
            DailyScore(trade_date, item, item.ticker in selected_tickers)
            for item in scored
        )
        self._safe_log(
            BotLog(
                "INFO",
                "screening",
                f"[SAVE_SCORES] score_count={len(scores)} trade_date={trade_date.isoformat()}",
            )
        )
        self.repository.save_daily_scores(scores)
        self._send_candidate_notification(trade_date, targets, scores)
        self._log_pipeline_diagnostics(
            started_at,
            requested_gainer_limit=active_profile.gainer_limit,
            requested_turnover_limit=active_profile.turnover_limit,
            requested_trade_value_limit=active_profile.turnover_limit,
            gainers_count=len(gainers),
            volume_count=len(turnover),
            trade_value_count=len(trade_value),
            intersection_count=initial_intersection_count,
            ranking_union_count=ranking_union_count,
            ranked_evaluation_limit=ranked_evaluation_limit,
            evaluated_candidate_count=len(evaluated_tickers),
            quote_requested_count=quote_requested_count,
            daily_requested_count=daily_requested_count,
            snapshot_success_count=len(snapshots),
            snapshot_fail_count=len(evaluated_tickers - snapshots.keys()),
            risk_pass_count=len(candidates),
            scoring_pass_count=scoring_pass_count,
            final_selected_count=len(selected_tickers),
            saved_count=len(targets),
            candidate_eval_elapsed_ms=candidate_eval_elapsed_ms,
            candidate_eval_stopped_reason=candidate_eval_stopped_reason,
            snapshots=snapshots,
            scored=scored,
            settings=scoring_settings,
        )
        self.repository.save_log(
            BotLog(
                "INFO",
                "pipeline",
                f"Screened {len(targets)} targets and selected {len(selected_tickers)}.",
            )
        )
        return ScoringRun(trade_date, None, targets, scores, candidate_sources)

    def _evaluate_ranked_candidates(
        self,
        *,
        ranked_tickers: tuple[str, ...],
        ranked_gainers: tuple[RankedStock, ...],
        ranked_turnover: tuple[RankedStock, ...],
        raw_gainers: tuple[RankedStock, ...],
        raw_turnover: tuple[RankedStock, ...],
        raw_trade_value: tuple[RankedStock, ...],
        snapshots,
        evaluated_tickers: set[str],
        settings: TradingSettings,
        eval_started_at: float,
    ) -> CandidateEvaluationProgress:
        candidate_snapshots = dict(snapshots)
        evaluated = set(evaluated_tickers)
        quote_requested_count = 0
        daily_requested_count = 0
        ranked_evaluation_limit = min(
            len(ranked_tickers),
            max(self.settings.max_ranked_evaluation_candidates, 0),
        )
        target_filtered_count = max(
            self.settings.target_filtered_candidates,
            self.settings.max_selected_candidates,
        )
        candidate_limit = max(target_filtered_count, self.settings.max_selected_candidates)
        stopped_reason = CANDIDATE_EVAL_NO_MORE

        while True:
            candidates = self._select_ranked_candidates(
                ranked_gainers=ranked_gainers,
                ranked_turnover=ranked_turnover,
                raw_gainers=raw_gainers,
                raw_turnover=raw_turnover,
                raw_trade_value=raw_trade_value,
                snapshots=candidate_snapshots,
                settings=settings,
                limit=candidate_limit,
            )
            if len(candidates) >= target_filtered_count:
                stopped_reason = CANDIDATE_EVAL_TARGET_REACHED
                break
            if _candidate_eval_timed_out(
                eval_started_at,
                self.settings.candidate_eval_timeout_seconds,
            ):
                stopped_reason = CANDIDATE_EVAL_TIMEOUT
                break
            evaluated_ranked_count = _evaluated_ranked_count(
                ranked_tickers,
                evaluated,
                ranked_evaluation_limit,
            )
            if evaluated_ranked_count >= ranked_evaluation_limit:
                stopped_reason = (
                    CANDIDATE_EVAL_MAX_REACHED
                    if ranked_evaluation_limit < len(ranked_tickers)
                    else CANDIDATE_EVAL_NO_MORE
                )
                break
            batch_size = (
                self.settings.initial_ranked_evaluation_limit
                if evaluated_ranked_count == 0
                else self.settings.ranked_evaluation_batch_size
            )
            batch = _next_evaluation_batch(
                ranked_tickers,
                evaluated,
                ranked_evaluation_limit,
                batch_size,
            )
            if not batch:
                stopped_reason = CANDIDATE_EVAL_NO_MORE
                break
            batch_snapshots = self.market_data.candidate_snapshots(batch)
            candidate_snapshots.update(batch_snapshots)
            evaluated.update(batch)
            quote_requested_count += _last_snapshot_request_count(
                self.market_data,
                "last_quote_requested_count",
                len(batch),
            )
            daily_requested_count += _last_snapshot_request_count(
                self.market_data,
                "last_daily_requested_count",
                len(batch),
            )

        return CandidateEvaluationProgress(
            snapshots=candidate_snapshots,
            candidates=candidates,
            evaluated_tickers=evaluated,
            ranked_evaluation_limit=ranked_evaluation_limit,
            quote_requested_count=quote_requested_count,
            daily_requested_count=daily_requested_count,
            stopped_reason=stopped_reason,
            elapsed_ms=int((perf_counter() - eval_started_at) * 1000),
        )

    def _manual_candidate_progress(
        self,
        snapshots,
        settings: TradingSettings,
        evaluated_tickers: set[str],
    ) -> ManualCandidateProgress:
        manual_tickers = self._manual_tickers()
        if not manual_tickers:
            return ManualCandidateProgress(dict(snapshots), [], set(evaluated_tickers), 0, 0)
        candidate_snapshots = dict(snapshots)
        evaluated = set(evaluated_tickers)
        to_fetch = tuple(ticker for ticker in manual_tickers if ticker not in candidate_snapshots)
        quote_requested_count = 0
        daily_requested_count = 0
        if to_fetch:
            fetched = self.market_data.candidate_snapshots(to_fetch)
            candidate_snapshots.update(fetched)
            evaluated.update(to_fetch)
            quote_requested_count = _last_snapshot_request_count(
                self.market_data,
                "last_quote_requested_count",
                len(to_fetch),
            )
            daily_requested_count = _last_snapshot_request_count(
                self.market_data,
                "last_daily_requested_count",
                len(to_fetch),
            )
        candidates = [
            candidate_snapshots[ticker]
            for ticker in manual_tickers
            if ticker in candidate_snapshots
            and opening_screen_reason(candidate_snapshots[ticker], settings) is None
        ]
        candidates.sort(key=lambda item: (-screening_priority_score(item), item.ticker))
        self._safe_log(
            BotLog(
                "INFO",
                "screening",
                "[MANUAL_BUY_LIST] "
                f"enabled_count={len(manual_tickers)} "
                f"passed_filter_count={len(candidates)}",
            )
        )
        return ManualCandidateProgress(
            candidate_snapshots,
            candidates,
            evaluated,
            quote_requested_count,
            daily_requested_count,
        )

    def _manual_tickers(self) -> tuple[str, ...]:
        if not self.settings.manual_buy_list_enabled or self.manual_source is None:
            return ()
        try:
            tickers = tuple(str(ticker).upper() for ticker in self.manual_source.enabled_tickers())
        except Exception as exc:
            self._safe_log(
                BotLog(
                    "WARNING",
                    "screening",
                    f"MANUAL_BUY_LIST_READ_FAILED: {type(exc).__name__}",
                    reject_reason="MANUAL_BUY_LIST_READ_FAILED",
                )
            )
            return ()
        unique: list[str] = []
        seen: set[str] = set()
        for ticker in tickers:
            if ticker and ticker not in seen:
                unique.append(ticker)
                seen.add(ticker)
        return tuple(unique[: max(self.settings.max_manual_buy_tickers, 0)])

    def _select_ranked_candidates(
        self,
        *,
        ranked_gainers: tuple[RankedStock, ...],
        ranked_turnover: tuple[RankedStock, ...],
        raw_gainers: tuple[RankedStock, ...],
        raw_turnover: tuple[RankedStock, ...],
        raw_trade_value: tuple[RankedStock, ...],
        snapshots,
        settings: TradingSettings,
        limit: int,
    ) -> list[CandidateSnapshot]:
        if settings.ranking_selection_mode == RANKING_SELECTION_COMPOSITE:
            return composite_ranking_selection(
                raw_gainers,
                raw_turnover,
                raw_trade_value,
                snapshots,
                settings,
                limit=limit,
            )
        return ranking_intersection(
            ranked_gainers,
            ranked_turnover,
            snapshots,
            settings,
            limit=limit,
        )

    def _save_screening_diagnostics(
        self,
        tickers: set[str],
        snapshots,
        settings: TradingSettings,
        evaluated_tickers: set[str] | None = None,
    ) -> None:
        counts = screening_rejection_counts(snapshots.values(), settings)
        checked_tickers = evaluated_tickers if evaluated_tickers is not None else tickers
        missing = len(checked_tickers - snapshots.keys())
        if missing:
            counts["MISSING_SNAPSHOT"] = missing
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        self.repository.save_log(
            BotLog("INFO", "screening", f"Filter rejects: {summary or 'none'}.")
        )

    def _log_relaxation_profile(
        self,
        profile: RelaxationProfile,
        candidate_count: int,
    ) -> None:
        settings = profile.settings
        self._safe_log(
            BotLog(
                "INFO",
                "screening",
                "[RELAXATION] "
                f"relaxation_level={profile.level} "
                f"min_price={settings.min_price_usd:g} "
                f"max_price={settings.max_price_usd:g} "
                f"gainers_top={profile.gainer_limit} "
                f"volume_top={profile.turnover_limit} "
                f"min_score={settings.min_total_score:g} "
                f"min_opening_change_percent={settings.min_opening_price_change * 100:g} "
                f"min_volume_ratio={settings.min_volume_ratio:g} "
                f"max_gap_percent={settings.max_opening_gap * 100:g} "
                f"candidate_count={candidate_count}",
            )
        )

    def _fetch_ranked_stocks(self, label: str, fetch) -> tuple[RankedStock, ...]:
        try:
            return tuple(fetch())
        except Exception as exc:
            self._safe_log(
                BotLog(
                    "WARNING",
                    "screening",
                    f"RANKING_FETCH_FAILED: {label} 랭킹 조회 실패, 가능한 후보로 계속합니다. ({exc})",
                    reject_reason="RANKING_FETCH_FAILED",
                )
            )
            return ()

    def _log_pipeline_diagnostics(
        self,
        started_at: float,
        *,
        requested_gainer_limit: int,
        requested_turnover_limit: int,
        requested_trade_value_limit: int,
        gainers_count: int,
        volume_count: int,
        trade_value_count: int,
        intersection_count: int,
        ranking_union_count: int,
        ranked_evaluation_limit: int,
        evaluated_candidate_count: int,
        quote_requested_count: int,
        daily_requested_count: int,
        snapshot_success_count: int,
        snapshot_fail_count: int,
        risk_pass_count: int,
        scoring_pass_count: int,
        final_selected_count: int,
        saved_count: int,
        candidate_eval_elapsed_ms: int,
        candidate_eval_stopped_reason: str,
        snapshots,
        scored,
        settings: TradingSettings | None = None,
    ) -> None:
        applied_settings = settings or self.settings
        duration_ms = int((perf_counter() - started_at) * 1000)
        self._safe_log(
            BotLog(
                "INFO",
                "pipeline",
                "[PIPELINE] "
                f"ranking_selection_mode={applied_settings.ranking_selection_mode} "
                f"requested_gainer_limit={requested_gainer_limit} "
                f"received_gainer_count={gainers_count} "
                f"requested_turnover_limit={requested_turnover_limit} "
                f"received_turnover_count={volume_count} "
                f"requested_trade_value_limit={requested_trade_value_limit} "
                f"received_trade_value_count={trade_value_count} "
                f"gainers_count={gainers_count} "
                f"volume_count={volume_count} "
                f"trade_value_count={trade_value_count} "
                f"intersection_count={intersection_count} "
                f"ranking_union_count={ranking_union_count} "
                f"ranked_evaluation_limit={ranked_evaluation_limit} "
                f"evaluated_candidate_count={evaluated_candidate_count} "
                f"quote_requested_count={quote_requested_count} "
                f"daily_requested_count={daily_requested_count} "
                f"snapshot_success_count={snapshot_success_count} "
                f"snapshot_fail_count={snapshot_fail_count} "
                f"risk_pass_count={risk_pass_count} "
                f"filtered_candidate_count={risk_pass_count} "
                f"scoring_pass_count={scoring_pass_count} "
                f"final_selected_count={final_selected_count} "
                f"selected_candidate_count={final_selected_count} "
                f"candidate_eval_elapsed_ms={candidate_eval_elapsed_ms} "
                f"candidate_eval_stopped_reason={candidate_eval_stopped_reason}",
            )
        )
        self._safe_log(
            BotLog(
                "INFO",
                "screening",
                _filter_log_message(
                    snapshots.values(),
                    applied_settings,
                    scored,
                    scoring_pass_count,
                    final_selected_count,
                ),
            )
        )
        self._safe_log(
            BotLog(
                "INFO",
                "pipeline",
                "[PIPELINE_SUMMARY] "
                f"ranking_selection_mode={applied_settings.ranking_selection_mode} "
                f"requested_gainer_limit={requested_gainer_limit} "
                f"received_gainer_count={gainers_count} "
                f"requested_turnover_limit={requested_turnover_limit} "
                f"received_turnover_count={volume_count} "
                f"requested_trade_value_limit={requested_trade_value_limit} "
                f"received_trade_value_count={trade_value_count} "
                f"gainers={gainers_count} "
                f"volume={volume_count} "
                f"trade_value={trade_value_count} "
                f"intersection={intersection_count} "
                f"ranking_union={ranking_union_count} "
                f"ranked_evaluation_limit={ranked_evaluation_limit} "
                f"evaluated_candidate_count={evaluated_candidate_count} "
                f"quote_requested_count={quote_requested_count} "
                f"daily_requested_count={daily_requested_count} "
                f"snapshot_success={snapshot_success_count} "
                f"snapshot_fail={snapshot_fail_count} "
                f"risk_pass={risk_pass_count} "
                f"filtered_candidate_count={risk_pass_count} "
                f"score_pass={scoring_pass_count} "
                f"selected_candidate_count={final_selected_count} "
                f"saved={saved_count} "
                f"candidate_eval_elapsed_ms={candidate_eval_elapsed_ms} "
                f"candidate_eval_stopped_reason={candidate_eval_stopped_reason} "
                f"duration_ms={duration_ms}",
            )
        )

    def _safe_log(self, log: BotLog) -> None:
        try:
            self.repository.save_log(log)
        except Exception:
            pass

    def _send_candidate_notification(
        self,
        trade_date: date,
        targets: tuple[DailyTarget, ...],
        scores: tuple[DailyScore, ...],
    ) -> None:
        if self.candidate_notification_sender is None:
            return
        try:
            sent = self.candidate_notification_sender(trade_date, targets, scores)
        except Exception as exc:
            self._safe_log(
                BotLog(
                    "WARNING",
                    "notification",
                    f"CANDIDATE_LIST_TELEGRAM_FAILED: {type(exc).__name__}",
                    reject_reason="CANDIDATE_LIST_TELEGRAM_FAILED",
                )
            )
            return
        if sent:
            self._safe_log(
                BotLog(
                    "INFO",
                    "notification",
                    "CANDIDATE_LIST_TELEGRAM_SENT: 후보 리스트 텔레그램 발송 완료",
                    reject_reason="CANDIDATE_LIST_TELEGRAM_SENT",
                )
            )
            return
        self._safe_log(
            BotLog(
                "WARNING",
                "notification",
                "CANDIDATE_LIST_TELEGRAM_SKIPPED: 텔레그램 설정이 없거나 발송 실패로 후보 리스트 발송을 건너뜀",
                reject_reason="CANDIDATE_LIST_TELEGRAM_SKIPPED",
            )
        )


def _expanded_tickers(gainers, turnover, rank_limit: int) -> set[str]:
    return {
        item.ticker
        for item in tuple(gainers) + tuple(turnover)
        if item.rank <= rank_limit
    }


def _merge_candidate_sources(
    auto_candidates: list[CandidateSnapshot],
    manual_candidates: list[CandidateSnapshot],
) -> tuple[list[CandidateSnapshot], dict[str, str]]:
    merged = list(auto_candidates)
    sources = {item.ticker: CANDIDATE_SOURCE_AUTO for item in auto_candidates}
    existing = {item.ticker for item in auto_candidates}
    for item in manual_candidates:
        if item.ticker in existing:
            sources[item.ticker] = CANDIDATE_SOURCE_BOTH
            continue
        merged.append(item)
        sources[item.ticker] = CANDIDATE_SOURCE_MANUAL
        existing.add(item.ticker)
    return merged, sources


def _selected_tickers_by_source(
    scored: list[ScoreRecord],
    settings: TradingSettings,
    candidate_sources: dict[str, str],
) -> set[str]:
    auto_scores = [
        item
        for item in scored
        if candidate_sources.get(item.ticker, CANDIDATE_SOURCE_AUTO)
        in {CANDIDATE_SOURCE_AUTO, CANDIDATE_SOURCE_BOTH}
    ]
    manual_scores = [
        item
        for item in scored
        if candidate_sources.get(item.ticker) in {CANDIDATE_SOURCE_MANUAL, CANDIDATE_SOURCE_BOTH}
    ]
    auto_selected = {item.ticker for item in select_candidates(auto_scores, settings)}
    manual_settings = replace(
        settings,
        max_selected_candidates=max(settings.max_manual_selected_candidates, 0),
    )
    manual_selected = {item.ticker for item in select_candidates(manual_scores, manual_settings)}
    return auto_selected | manual_selected


def _with_missing_ranks(rows, tickers: set[str]):
    existing = {item.ticker: item for item in rows}
    fallback_rank = max((item.rank for item in rows), default=0) + 50
    return tuple(existing.get(ticker) or RankedStock(ticker, fallback_rank) for ticker in tickers)


def _ranked_evaluation_order(
    gainers: tuple[RankedStock, ...],
    turnover: tuple[RankedStock, ...],
    trade_value: tuple[RankedStock, ...],
    tickers: set[str],
) -> tuple[str, ...]:
    gain_ranks = {item.ticker: item.rank for item in gainers}
    turnover_ranks = {item.ticker: item.rank for item in turnover}
    trade_value_ranks = {item.ticker: item.rank for item in trade_value}
    gain_fallback = _fallback_rank(gainers)
    turnover_fallback = _fallback_rank(turnover)
    trade_value_fallback = _fallback_rank(trade_value)

    def key(ticker: str) -> tuple[float, int, int, int, int, str]:
        gain_rank = gain_ranks.get(ticker, gain_fallback)
        turnover_rank = turnover_ranks.get(ticker, turnover_fallback)
        trade_value_rank = trade_value_ranks.get(ticker, trade_value_fallback)
        presence_count = sum(
            ticker in ranks for ranks in (gain_ranks, turnover_ranks, trade_value_ranks)
        )
        average_rank = (gain_rank + turnover_rank + trade_value_rank) / 3
        return (
            average_rank,
            -presence_count,
            gain_rank,
            turnover_rank,
            trade_value_rank,
            ticker,
        )

    return tuple(sorted(tickers, key=key))


def _fallback_rank(rows: tuple[RankedStock, ...]) -> int:
    return max((item.rank for item in rows), default=0) + 50


def _evaluated_ranked_count(
    ranked_tickers: tuple[str, ...],
    evaluated_tickers: set[str],
    ranked_evaluation_limit: int,
) -> int:
    return sum(1 for ticker in ranked_tickers[:ranked_evaluation_limit] if ticker in evaluated_tickers)


def _next_evaluation_batch(
    ranked_tickers: tuple[str, ...],
    evaluated_tickers: set[str],
    ranked_evaluation_limit: int,
    batch_size: int,
) -> tuple[str, ...]:
    batch = []
    for ticker in ranked_tickers[:ranked_evaluation_limit]:
        if ticker not in evaluated_tickers:
            batch.append(ticker)
        if len(batch) >= batch_size:
            break
    return tuple(batch)


def _candidate_eval_timed_out(started_at: float, timeout_seconds: float) -> bool:
    return timeout_seconds > 0 and perf_counter() - started_at >= timeout_seconds


def _last_snapshot_request_count(source, attribute: str, default: int) -> int:
    try:
        value = int(getattr(source, attribute, default))
    except (TypeError, ValueError):
        return default
    return max(value, 0)


def _relaxation_profiles(settings: TradingSettings) -> tuple[RelaxationProfile, ...]:
    base = replace(
        settings,
        min_price_usd=max(settings.min_price_usd, 10.0),
        max_opening_gap=min(settings.max_opening_gap, 0.30),
        min_volume_ratio=max(settings.min_volume_ratio, 1.0),
        min_total_score=max(settings.min_total_score, 35.0),
    )
    expanded_price = replace(base, max_price_usd=max(base.max_price_usd, 300.0))
    opening_relaxed = replace(expanded_price, min_opening_price_change=0.0)
    score_relaxed = replace(opening_relaxed, min_total_score=35.0)
    min_price_relaxed = replace(score_relaxed, min_price_usd=5.0)
    return (
        RelaxationProfile(
            0,
            settings.gainer_ranking_limit,
            settings.turnover_ranking_limit,
            base,
        ),
        RelaxationProfile(1, 300, 300, base),
        RelaxationProfile(2, 500, 500, base),
        RelaxationProfile(3, 500, 500, expanded_price),
        RelaxationProfile(4, 1000, 500, expanded_price),
        RelaxationProfile(5, 1000, 500, opening_relaxed),
        RelaxationProfile(6, 1000, 500, score_relaxed),
        RelaxationProfile(7, 1000, 500, min_price_relaxed),
    )


def _filter_log_message(
    snapshots,
    settings: TradingSettings,
    scored,
    scoring_pass_count: int,
    final_count: int,
) -> str:
    rejects = screening_rejection_counts(snapshots, settings)
    scored_count = len(tuple(scored))
    return (
        "[FILTER] "
        f"removed_by_price={rejects.get('PENNY_STOCK', 0) + rejects.get('PRICE_CAP', 0)} "
        f"removed_by_gap={rejects.get('OPENING_GAP', 0)} "
        f"removed_by_volume_ratio={rejects.get('LOW_OPENING_VOLUME', 0)} "
        f"removed_by_opening_change={rejects.get('LOW_OPENING_CHANGE', 0)} "
        f"removed_by_score={max(0, scored_count - scoring_pass_count)} "
        f"final_count={final_count}"
    )
