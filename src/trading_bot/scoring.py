from __future__ import annotations

from collections.abc import Iterable

from trading_bot.config import TradingSettings
from trading_bot.models import ScoreRecord, Sentiment


def news_score(sentiments: Iterable[Sentiment]) -> float:
    results = list(sentiments)
    if not results:
        return 0.0
    positives = sum(item is Sentiment.POSITIVE for item in results)
    return positives / len(results) * 100


def select_candidates(
    records: Iterable[ScoreRecord],
    settings: TradingSettings,
) -> list[ScoreRecord]:
    eligible = [record for record in records if record.total_score >= settings.min_total_score]
    eligible.sort(key=lambda item: (-item.total_score, item.ticker))
    return eligible[: settings.max_selected_candidates]


def position_fraction_for_score(score: float, settings: TradingSettings) -> float:
    if score < settings.min_total_score:
        return 0.0
    if score < 70:
        return 0.05
    if score < 85:
        return 0.10
    return 0.20
