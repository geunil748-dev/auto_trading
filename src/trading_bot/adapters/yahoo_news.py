from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from typing import Any


class YahooFinanceNewsSource:
    def __init__(
        self,
        ticker_factory: Callable[[str], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.ticker_factory = ticker_factory or _yfinance_ticker
        self.now = now or (lambda: datetime.now(timezone.utc))

    def recent_titles(self, ticker: str, hours: int = 24, limit: int = 5) -> list[str]:
        cutoff = self.now() - timedelta(hours=hours)
        titles: list[str] = []
        for item in self._news_items(ticker):
            published_at = _published_at(item)
            title = _title(item)
            if published_at is not None and published_at < cutoff:
                continue
            if title:
                titles.append(title)
            if len(titles) == limit:
                break
        return titles

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


def _yfinance_ticker(ticker: str) -> Any:
    import yfinance as yf

    return yf.Ticker(ticker)
