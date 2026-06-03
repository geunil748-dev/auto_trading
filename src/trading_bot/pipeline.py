from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from time import perf_counter

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, DailyScore, DailyTarget, RankedStock, ScoreRecord
from trading_bot.ports import (
    AccountReader,
    DailyRepository,
    ScoringProvider,
    ScreeningMarketData,
    TradingClock,
)
from trading_bot.risk import global_entry_gate
from trading_bot.scoring import select_candidates
from trading_bot.screening import ranking_intersection, screening_rejection_counts


@dataclass(frozen=True)
class ScoringRun:
    trade_date: date
    blocked_reason: str | None
    targets: tuple[DailyTarget, ...]
    scores: tuple[DailyScore, ...]

    @property
    def selected(self) -> tuple[ScoreRecord, ...]:
        return tuple(item.score for item in self.scores if item.is_selected)


@dataclass(frozen=True)
class RelaxationProfile:
    level: int
    gainer_limit: int
    turnover_limit: int
    settings: TradingSettings


class ScreeningScoringPipeline:
    def __init__(
        self,
        market_data: ScreeningMarketData,
        scoring: ScoringProvider,
        accounts: AccountReader,
        repository: DailyRepository,
        clock: TradingClock,
        settings: TradingSettings,
    ) -> None:
        self.market_data = market_data
        self.scoring = scoring
        self.accounts = accounts
        self.repository = repository
        self.clock = clock
        self.settings = settings

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
        gainers: tuple[RankedStock, ...] = ()
        turnover: tuple[RankedStock, ...] = ()
        candidates = []
        active_profile = _relaxation_profiles(self.settings)[0]
        for profile in _relaxation_profiles(self.settings):
            if profile.level > 0 and not self.settings.allow_relaxed_candidate_filter:
                break
            active_profile = profile
            gainers = tuple(self.market_data.ranked_gainers(profile.gainer_limit))
            turnover = tuple(self.market_data.ranked_turnover(profile.turnover_limit))
            requested_tickers = {item.ticker for item in gainers} & {
                item.ticker for item in turnover
            }
            snapshots = {
                **snapshots,
                **self.market_data.candidate_snapshots(
                    requested_tickers - snapshots.keys()
                ),
            }
            candidates = ranking_intersection(
                gainers,
                turnover,
                snapshots,
                profile.settings,
            )
            self._log_relaxation_profile(profile, len(candidates))
            if len(candidates) >= self.settings.min_selected_candidates:
                break
        initial_intersection_count = len(requested_tickers)
        strict_shortfall = (
            not self.settings.allow_relaxed_candidate_filter
            and len(candidates) < self.settings.min_selected_candidates
        )
        self._save_screening_diagnostics(requested_tickers, snapshots, active_profile.settings)
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
                gainers_count=len(gainers),
                volume_count=len(turnover),
                intersection_count=initial_intersection_count,
                snapshot_success_count=len(snapshots),
                snapshot_fail_count=len(requested_tickers - snapshots.keys()),
                risk_pass_count=len(candidates),
                scoring_pass_count=0,
                final_selected_count=0,
                saved_count=len(targets),
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
            return ScoringRun(trade_date, "STRICT_FILTER_NO_CANDIDATES", targets, ())

        if not entry_gate.allowed:
            self._log_pipeline_diagnostics(
                started_at,
                gainers_count=len(gainers),
                volume_count=len(turnover),
                intersection_count=initial_intersection_count,
                snapshot_success_count=len(snapshots),
                snapshot_fail_count=len(requested_tickers - snapshots.keys()),
                risk_pass_count=len(candidates),
                scoring_pass_count=0,
                final_selected_count=0,
                saved_count=len(targets),
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
            return ScoringRun(trade_date, entry_gate.reason, targets, ())

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
        selected_tickers = {
            item.ticker for item in select_candidates(scored, scoring_settings)
        }
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
        self._log_pipeline_diagnostics(
            started_at,
            gainers_count=len(gainers),
            volume_count=len(turnover),
            intersection_count=initial_intersection_count,
            snapshot_success_count=len(snapshots),
            snapshot_fail_count=len(requested_tickers - snapshots.keys()),
            risk_pass_count=len(candidates),
            scoring_pass_count=scoring_pass_count,
            final_selected_count=len(selected_tickers),
            saved_count=len(targets),
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
        return ScoringRun(trade_date, None, targets, scores)

    def _save_screening_diagnostics(
        self,
        tickers: set[str],
        snapshots,
        settings: TradingSettings,
    ) -> None:
        counts = screening_rejection_counts(snapshots.values(), settings)
        missing = len(tickers - snapshots.keys())
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

    def _log_pipeline_diagnostics(
        self,
        started_at: float,
        *,
        gainers_count: int,
        volume_count: int,
        intersection_count: int,
        snapshot_success_count: int,
        snapshot_fail_count: int,
        risk_pass_count: int,
        scoring_pass_count: int,
        final_selected_count: int,
        saved_count: int,
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
                f"gainers_count={gainers_count} "
                f"volume_count={volume_count} "
                f"intersection_count={intersection_count} "
                f"snapshot_success_count={snapshot_success_count} "
                f"snapshot_fail_count={snapshot_fail_count} "
                f"risk_pass_count={risk_pass_count} "
                f"scoring_pass_count={scoring_pass_count} "
                f"final_selected_count={final_selected_count}",
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
                f"gainers={gainers_count} "
                f"volume={volume_count} "
                f"intersection={intersection_count} "
                f"snapshot_success={snapshot_success_count} "
                f"snapshot_fail={snapshot_fail_count} "
                f"risk_pass={risk_pass_count} "
                f"score_pass={scoring_pass_count} "
                f"saved={saved_count} "
                f"duration_ms={duration_ms}",
            )
        )

    def _safe_log(self, log: BotLog) -> None:
        try:
            self.repository.save_log(log)
        except Exception:
            pass


def _expanded_tickers(gainers, turnover, rank_limit: int) -> set[str]:
    return {
        item.ticker
        for item in tuple(gainers) + tuple(turnover)
        if item.rank <= rank_limit
    }


def _with_missing_ranks(rows, tickers: set[str]):
    existing = {item.ticker: item for item in rows}
    fallback_rank = max((item.rank for item in rows), default=0) + 50
    return tuple(existing.get(ticker) or RankedStock(ticker, fallback_rank) for ticker in tickers)


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
