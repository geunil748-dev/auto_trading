from __future__ import annotations

from collections.abc import Callable, Iterable

from trading_bot.models import CandidateSnapshot, ScoreRecord, Sentiment
from trading_bot.retry import RetryPolicy, YAHOO_RETRY, call_with_retry
from trading_bot.scoring import news_score


class NewsChartScoringProvider:
    def __init__(
        self,
        fetch_news_sentiments: Callable[[str], Iterable[Sentiment]],
        chart_score: Callable[[str], float],
        retry_policy: RetryPolicy = YAHOO_RETRY,
    ) -> None:
        self.fetch_news_sentiments = fetch_news_sentiments
        self.chart_score = chart_score
        self.retry_policy = retry_policy

    def score(self, candidate: CandidateSnapshot) -> ScoreRecord:
        sentiments = call_with_retry(
            lambda: tuple(self.fetch_news_sentiments(candidate.ticker)),
            self.retry_policy,
        )
        return ScoreRecord(
            ticker=candidate.ticker,
            news_score=news_score(sentiments),
            chart_score=self.chart_score(candidate.ticker),
        )
