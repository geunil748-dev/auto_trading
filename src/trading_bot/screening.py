from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from trading_bot.config import TradingSettings
from trading_bot.models import CandidateSnapshot, RankedStock
from trading_bot.risk import defensive_candidate_gate


def ranking_intersection(
    gainers: Iterable[RankedStock],
    turnover: Iterable[RankedStock],
    snapshots: Mapping[str, CandidateSnapshot],
    settings: TradingSettings,
    limit: int | None = None,
) -> list[CandidateSnapshot]:
    gain_ranks = {item.ticker: item.rank for item in gainers}
    turnover_ranks = {item.ticker: item.rank for item in turnover}
    common_tickers = gain_ranks.keys() & turnover_ranks.keys() & snapshots.keys()

    screened = [
        snapshots[ticker]
        for ticker in common_tickers
        if opening_screen_reason(snapshots[ticker], settings) is None
    ]
    screened.sort(key=lambda item: (-screening_priority_score(item), item.ticker))
    return screened[: limit or settings.max_selected_candidates]


def adaptive_ranking_intersection(
    gainers: Iterable[RankedStock],
    turnover: Iterable[RankedStock],
    snapshots: Mapping[str, CandidateSnapshot],
    settings: TradingSettings,
    limit: int | None = None,
) -> list[CandidateSnapshot]:
    if not settings.allow_relaxed_candidate_filter:
        if settings.relax_opening_change_only:
            return opening_change_relaxed_intersection(
                gainers,
                turnover,
                snapshots,
                settings,
                limit,
            )
        return ranking_intersection(gainers, turnover, snapshots, settings, limit)

    max_count = limit or settings.max_selected_candidates
    min_count = min(settings.min_selected_candidates, max_count)
    gain_ranks = {item.ticker: item.rank for item in gainers}
    turnover_ranks = {item.ticker: item.rank for item in turnover}
    common_tickers = gain_ranks.keys() & turnover_ranks.keys() & snapshots.keys()
    candidates = [snapshots[ticker] for ticker in common_tickers]

    candidates = _first_passing_stage(
        candidates,
        _price_stages(settings),
        lambda item, stage: stage[0] <= item.price_usd <= stage[1],
        min_count,
    )
    candidates = _first_passing_stage(
        candidates,
        _opening_change_stages(settings),
        lambda item, stage: item.opening_price_change >= stage,
        min_count,
    )
    candidates = _first_passing_stage(
        candidates,
        _volume_stages(settings),
        lambda item, stage: item.opening_volume_ratio >= stage,
        min_count,
    )
    candidates = _first_passing_stage(
        candidates,
        _gap_stages(settings),
        lambda item, stage: item.opening_gap < stage,
        min_count,
    )
    candidates.sort(key=lambda item: (-screening_priority_score(item), item.ticker))
    return candidates[:max_count]


def opening_change_relaxed_intersection(
    gainers: Iterable[RankedStock],
    turnover: Iterable[RankedStock],
    snapshots: Mapping[str, CandidateSnapshot],
    settings: TradingSettings,
    limit: int | None = None,
) -> list[CandidateSnapshot]:
    gain_ranks = {item.ticker: item.rank for item in gainers}
    turnover_ranks = {item.ticker: item.rank for item in turnover}
    common_tickers = gain_ranks.keys() & turnover_ranks.keys() & snapshots.keys()
    opening_change_floor = _relaxed_opening_change_threshold(settings)
    screened = [
        snapshots[ticker]
        for ticker in common_tickers
        if _passes_opening_change_only_relax(
            snapshots[ticker],
            settings,
            opening_change_floor,
        )
    ]
    screened.sort(key=lambda item: (-screening_priority_score(item), item.ticker))
    return screened[: limit or settings.max_selected_candidates]


def screening_priority_score(candidate: CandidateSnapshot) -> float:
    return (
        _rank_score(candidate)
        + _volume_bonus(candidate.opening_volume_ratio)
        + _opening_change_adjustment(candidate.opening_price_change)
        + _gap_adjustment(candidate.opening_gap)
    )


def screening_rejection_counts(
    snapshots: Iterable[CandidateSnapshot],
    settings: TradingSettings,
) -> dict[str, int]:
    reasons = Counter(
        reason
        for item in snapshots
        if (reason := opening_screen_reason(item, settings)) is not None
    )
    return dict(reasons)


def opening_screen_reason(
    candidate: CandidateSnapshot,
    settings: TradingSettings,
) -> str | None:
    if candidate.opening_volume_ratio < settings.min_volume_ratio:
        return "LOW_OPENING_VOLUME"
    if candidate.opening_price_change < settings.min_opening_price_change:
        return "LOW_OPENING_CHANGE"
    return defensive_candidate_gate(candidate, settings).reason


def _rank_score(candidate: CandidateSnapshot) -> float:
    average_rank = (candidate.turnover_rank + candidate.gain_rank) / 2
    return max(0.0, 100.0 - average_rank)


def _volume_bonus(volume_ratio: float) -> float:
    if volume_ratio >= 3.0:
        return 15.0
    if volume_ratio >= 2.0:
        return 10.0
    return 5.0


def _opening_change_adjustment(price_change: float) -> float:
    if price_change < 0.08:
        return 10.0
    if price_change < 0.15:
        return 5.0
    if price_change < 0.25:
        return -5.0
    return -10.0


def _gap_adjustment(opening_gap: float) -> float:
    if opening_gap < 0.05:
        return 5.0
    if opening_gap < 0.10:
        return 2.0
    return -5.0


def _first_passing_stage(
    candidates: list[CandidateSnapshot],
    stages: Iterable[object],
    predicate,
    min_count: int,
) -> list[CandidateSnapshot]:
    best: list[CandidateSnapshot] = []
    for stage in stages:
        current = [item for item in candidates if predicate(item, stage)]
        if len(current) >= min_count:
            return current
        if len(current) > len(best):
            best = current
    return best


def _price_stages(settings: TradingSettings) -> tuple[tuple[float, float], ...]:
    return (
        (settings.min_price_usd, settings.max_price_usd),
        (3.0, 80.0),
        (1.0, 100.0),
        (0.5, 150.0),
    )


def _opening_change_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.min_opening_price_change,
        0.02,
        0.01,
        0.0,
        -0.05,
    )


def _volume_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.min_volume_ratio,
        1.2,
        1.0,
        0.7,
        0.5,
        0.0,
    )


def _gap_stages(settings: TradingSettings) -> tuple[float, ...]:
    return (
        settings.max_opening_gap,
        0.25,
        0.30,
        0.40,
        1.00,
    )


def _passes_opening_change_only_relax(
    candidate: CandidateSnapshot,
    settings: TradingSettings,
    opening_change_floor: float,
) -> bool:
    return (
        candidate.opening_volume_ratio >= settings.min_volume_ratio
        and candidate.opening_price_change >= opening_change_floor
        and defensive_candidate_gate(candidate, settings).reason is None
    )


def _relaxed_opening_change_threshold(settings: TradingSettings) -> float:
    if settings.min_opening_price_change <= 0:
        return settings.min_opening_price_change
    return max(0.0001, settings.min_opening_price_change - 0.01)
