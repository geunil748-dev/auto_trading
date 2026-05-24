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
    limit: int = 20,
) -> list[CandidateSnapshot]:
    gain_ranks = {item.ticker: item.rank for item in gainers}
    turnover_ranks = {item.ticker: item.rank for item in turnover}
    common_tickers = gain_ranks.keys() & turnover_ranks.keys() & snapshots.keys()

    screened = [
        snapshots[ticker]
        for ticker in common_tickers
        if opening_screen_reason(snapshots[ticker], settings) is None
    ]
    screened.sort(key=lambda item: (item.turnover_rank + item.gain_rank, item.ticker))
    return screened[:limit]


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
