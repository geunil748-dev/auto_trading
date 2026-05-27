from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from trading_bot.adapters.yahoo_news import YahooFinanceNewsSource
from trading_bot.models import NewsRecord, Sentiment
from trading_bot.news_cache import NewsCacheRepository


class HeadlineClassifier(Protocol):
    def classify_many(self, titles: list[str]) -> tuple[Sentiment, ...]: ...


class YahooNewsSentimentSource:
    def __init__(
        self,
        news: YahooFinanceNewsSource,
        classifier: HeadlineClassifier,
        cache: NewsCacheRepository | None = None,
        now: Callable[[], datetime] | None = None,
        cache_ttl_minutes: int = 30,
    ) -> None:
        self.news = news
        self.classifier = classifier
        self.cache = cache
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.cache_ttl_minutes = cache_ttl_minutes

    def sentiments(self, ticker: str) -> tuple[Sentiment, ...]:
        symbol = ticker.upper()
        cached = self._cached_sentiments(symbol)
        if cached:
            return cached

        records = self._fresh_news(symbol)
        if self.cache is not None:
            self.cache.save_news(records)

        sentiments = self.classifier.classify_many([item.title for item in records])
        self._save_sentiments(symbol, records, sentiments)
        return sentiments

    def _cached_sentiments(self, ticker: str) -> tuple[Sentiment, ...]:
        if self.cache is None:
            return ()
        fetched_after = self.now() - timedelta(minutes=self.cache_ttl_minutes)
        records = self.cache.recent_news(ticker, fetched_after)
        if not records:
            return ()

        missing = [item for item in records if item.sentiment_score is None]
        if missing:
            sentiments = self.classifier.classify_many([item.title for item in missing])
            self._save_sentiments(ticker, missing, sentiments)
            score_by_title = {
                item.title: sentiment.value
                for item, sentiment in zip(missing, sentiments, strict=False)
            }
            return tuple(
                Sentiment(
                    item.sentiment_score
                    if item.sentiment_score is not None
                    else score_by_title.get(item.title, Sentiment.NEUTRAL.value)
                )
                for item in records
            )

        return tuple(Sentiment(int(item.sentiment_score)) for item in records)

    def _save_sentiments(
        self,
        ticker: str,
        records,
        sentiments: tuple[Sentiment, ...],
    ) -> None:
        if self.cache is None:
            return
        self.cache.update_sentiments(
            ticker,
            (
                (item.title, sentiment.value)
                for item, sentiment in zip(records, sentiments, strict=False)
            ),
        )

    def _fresh_news(self, ticker: str) -> list[NewsRecord]:
        if hasattr(self.news, "recent_news"):
            return list(self.news.recent_news(ticker))
        return [
            NewsRecord(ticker=ticker, title=title, fetched_at=self.now())
            for title in self.news.recent_titles(ticker)
        ]
