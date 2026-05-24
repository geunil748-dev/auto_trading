from __future__ import annotations

from collections.abc import Iterable

from trading_bot.models import Sentiment


class KeywordHeadlineSentiment:
    positive_words = frozenset(
        {"beat", "beats", "growth", "gain", "surge", "upgrade", "record", "profit"}
    )
    negative_words = frozenset(
        {"cut", "cuts", "loss", "miss", "misses", "downgrade", "probe", "fall"}
    )

    def classify(self, title: str) -> Sentiment:
        words = {word.strip(".,:;!?()[]").lower() for word in title.split()}
        positive = len(words & self.positive_words)
        negative = len(words & self.negative_words)
        if positive > negative:
            return Sentiment.POSITIVE
        if negative > positive:
            return Sentiment.NEGATIVE
        return Sentiment.NEUTRAL

    def classify_many(self, titles: Iterable[str]) -> tuple[Sentiment, ...]:
        return tuple(self.classify(title) for title in titles)
