from __future__ import annotations

from dataclasses import dataclass
from datetime import date

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
from trading_bot.screening import adaptive_ranking_intersection, screening_rejection_counts


@dataclass(frozen=True)
class ScoringRun:
    trade_date: date
    blocked_reason: str | None
    targets: tuple[DailyTarget, ...]
    scores: tuple[DailyScore, ...]

    @property
    def selected(self) -> tuple[ScoreRecord, ...]:
        return tuple(item.score for item in self.scores if item.is_selected)


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
        gainers = tuple(self.market_data.ranked_gainers())
        turnover = tuple(self.market_data.ranked_turnover())
        requested_tickers = {item.ticker for item in gainers} & {
            item.ticker for item in turnover
        }
        snapshots = self.market_data.candidate_snapshots(requested_tickers)
        candidates = adaptive_ranking_intersection(gainers, turnover, snapshots, self.settings)
        strict_shortfall = (
            not self.settings.allow_relaxed_candidate_filter
            and len(candidates) < self.settings.min_selected_candidates
        )
        if len(candidates) < self.settings.min_selected_candidates and not strict_shortfall:
            for rank_limit in (5, 10, 15):
                expanded_tickers = _expanded_tickers(gainers, turnover, rank_limit)
                snapshots = {
                    **snapshots,
                    **self.market_data.candidate_snapshots(
                        expanded_tickers - snapshots.keys()
                    ),
                }
                expanded_gainers = _with_missing_ranks(gainers, expanded_tickers)
                expanded_turnover = _with_missing_ranks(turnover, expanded_tickers)
                requested_tickers = expanded_tickers
                candidates = adaptive_ranking_intersection(
                    expanded_gainers,
                    expanded_turnover,
                    snapshots,
                    self.settings,
                )
                self.repository.save_log(
                    BotLog(
                        "INFO",
                        "screening",
                        f"후보 수집 범위를 상위 {rank_limit}위까지 확대했습니다. "
                        f"({len(expanded_tickers)}종목)",
                    )
                )
                if len(candidates) >= self.settings.min_selected_candidates:
                    break
        self._save_screening_diagnostics(requested_tickers, snapshots)
        targets = tuple(DailyTarget(trade_date, item) for item in candidates)
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
        selected_tickers = {
            item.ticker for item in select_candidates(scored, self.settings)
        }
        scores = tuple(
            DailyScore(trade_date, item, item.ticker in selected_tickers)
            for item in scored
        )
        self.repository.save_daily_scores(scores)
        self.repository.save_log(
            BotLog(
                "INFO",
                "pipeline",
                f"Screened {len(targets)} targets and selected {len(selected_tickers)}.",
            )
        )
        return ScoringRun(trade_date, None, targets, scores)

    def _save_screening_diagnostics(self, tickers: set[str], snapshots) -> None:
        counts = screening_rejection_counts(snapshots.values(), self.settings)
        missing = len(tickers - snapshots.keys())
        if missing:
            counts["MISSING_SNAPSHOT"] = missing
        summary = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
        self.repository.save_log(
            BotLog("INFO", "screening", f"Filter rejects: {summary or 'none'}.")
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
