from __future__ import annotations

from typing import Protocol

from trading_bot.adapters.yahoo_news import YahooFinanceNewsSource
from trading_bot.models import Sentiment


class HeadlineClassifier(Protocol):
    def classify_many(self, titles: list[str]) -> tuple[Sentiment, ...]: ...


class YahooNewsSentimentSource:
    def __init__(
        self,
        news: YahooFinanceNewsSource,
        classifier: HeadlineClassifier,
    ) -> None:
        self.news = news
        self.classifier = classifier

    def sentiments(self, ticker: str) -> tuple[Sentiment, ...]:
        return self.classifier.classify_many(self.news.recent_titles(ticker))
