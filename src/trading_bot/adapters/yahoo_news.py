from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from trading_bot.models import NewsRecord


class YahooFinanceNewsSource:
    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.ticker_factory = ticker_factory or _yfinance_ticker
        self.now = now or (lambda: datetime.now(timezone.utc))

    def recent_titles(self, ticker: str, hours: int = 24, limit: int = 5) -> list[str]:
        return [item.title for item in self.recent_news(ticker, hours, limit)]

    def recent_news(self, ticker: str, hours: int = 24, limit: int = 5) -> list[NewsRecord]:
        cutoff = self.now() - timedelta(hours=hours)
        records: list[NewsRecord] = []
        for item in self._news_items(ticker):
            published_at = _published_at(item)
            title = _title(item)
            if published_at is not None and published_at < cutoff:
                continue
            if title:
                records.append(
                    NewsRecord(
                        ticker=ticker.upper(),
                        title=title,
                        summary=_summary(item),
                        url=_url(item),
                        published_at=published_at,
                        source=_source(item),
                        fetched_at=self.now(),
                    )
                )
            if len(records) == limit:
                break
        return records

    def _news_items(self, ticker: str) -> Iterable[dict[str, Any]]:
        news = getattr(self.ticker_factory(ticker), "news", [])
        return (item for item in news if isinstance(item, dict))


def _published_at(item: dict[str, Any]) -> datetime | None:
    timestamp = item.get("providerPublishTime") or item.get("pubDate")
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(timestamp, str):
        normalized = timestamp.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return None


def _title(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, dict):
        return str(content.get("title", "")).strip()
    return str(item.get("title", "")).strip()


def _summary(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, dict):
        return str(content.get("summary", "") or content.get("description", "")).strip()
    return str(item.get("summary", "") or item.get("description", "")).strip()


def _url(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, dict):
        canonical = content.get("canonicalUrl")
        if isinstance(canonical, dict):
            return str(canonical.get("url", "")).strip()
        click = content.get("clickThroughUrl")
        if isinstance(click, dict):
            return str(click.get("url", "")).strip()
        if content.get("url"):
            return str(content.get("url", "")).strip()
    link = item.get("link") or item.get("url")
    return str(link or "").strip()


def _source(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, dict):
        provider = content.get("provider")
        if isinstance(provider, dict):
            return str(provider.get("displayName", "") or provider.get("name", "")).strip()
        if content.get("publisher"):
            return str(content.get("publisher", "")).strip()
    return str(item.get("publisher", "") or item.get("source", "")).strip()


def _yfinance_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)
