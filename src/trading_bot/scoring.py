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
    eligible = [record for record in records if record.news_score >= 70]
    eligible.sort(key=lambda item: (-item.total_score, item.ticker))
    return eligible[: settings.max_selected_candidates]


def position_fraction_for_news_score(score: float) -> float:
    if score < 70:
        return 0.0
    if score < 85:
        return 0.05
    if score < 95:
        return 0.10
    return 0.20
