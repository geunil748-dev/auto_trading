from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import datetime
from typing import Any, Protocol

from trading_bot.models import NewsRecord
from trading_bot.repositories import Connection


class NewsCacheRepository(Protocol):
    def recent_news(self, ticker: str, fetched_after: datetime) -> list[NewsRecord]: ...

    def save_news(self, records: Iterable[NewsRecord]) -> None: ...

    def update_sentiments(self, ticker: str, sentiments: Iterable[tuple[str, int]]) -> None: ...


class SqlServerNewsCacheRepository:
    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def recent_news(self, ticker: str, fetched_after: datetime) -> list[NewsRecord]:
        self._ensure_table()
        rows = self._query(
            """
            SELECT ticker, title, summary, url, published_at, source,
                   sentiment_score, fetched_at
            FROM news_cache
            WHERE ticker = ?
              AND fetched_at >= ?
            ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC
            """,
            (ticker.upper(), fetched_after),
        )
        return [
            NewsRecord(
                ticker=str(row[0]),
                title=str(row[1]),
                summary="" if row[2] is None else str(row[2]),
                url="" if row[3] is None else str(row[3]),
                published_at=row[4],
                source="" if row[5] is None else str(row[5]),
                sentiment_score=None if row[6] is None else int(row[6]),
                fetched_at=row[7],
            )
            for row in rows
            if row[1]
        ]

    def save_news(self, records: Iterable[NewsRecord]) -> None:
        self._ensure_table()
        for item in records:
            if not item.title.strip():
                continue
            self._execute(
                """
                IF EXISTS (
                    SELECT 1 FROM news_cache WHERE ticker = ? AND title = ?
                )
                BEGIN
                    UPDATE news_cache
                    SET summary = ?, url = ?, published_at = ?, source = ?,
                        fetched_at = GETDATE()
                    WHERE ticker = ? AND title = ?
                END
                ELSE
                BEGIN
                    INSERT INTO news_cache
                        (ticker, title, summary, url, published_at, source,
                         sentiment_score, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE())
                END
                """,
                (
                    item.ticker.upper(),
                    item.title,
                    item.summary,
                    item.url,
                    item.published_at,
                    item.source,
                    item.ticker.upper(),
                    item.title,
                    item.ticker.upper(),
                    item.title,
                    item.summary,
                    item.url,
                    item.published_at,
                    item.source,
                    item.sentiment_score,
                ),
            )

    def update_sentiments(self, ticker: str, sentiments: Iterable[tuple[str, int]]) -> None:
        for title, score in sentiments:
            self._execute(
                """
                UPDATE news_cache
                SET sentiment_score = ?
                WHERE ticker = ? AND title = ?
                """,
                (score, ticker.upper(), title),
            )

    def _ensure_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.news_cache', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.news_cache (
                    id INT IDENTITY PRIMARY KEY,
                    ticker VARCHAR(10) NOT NULL,
                    title NVARCHAR(500) NOT NULL,
                    summary NVARCHAR(MAX),
                    url NVARCHAR(1000),
                    published_at DATETIME NULL,
                    source NVARCHAR(100),
                    sentiment_score INT NULL,
                    fetched_at DATETIME DEFAULT GETDATE(),
                    created_at DATETIME DEFAULT GETDATE()
                );
            END
            """,
        )

    def _execute(self, sql: str, row: tuple[Any, ...]) -> None:
        with closing(self.connect()) as connection:
            connection.cursor().execute(sql, row)
            connection.commit()

    def _query(self, sql: str, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            return list(cursor.fetchall())

    def _execute_statement(self, sql: str) -> None:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, ())
            except TypeError:
                cursor.execute(sql)  # type: ignore[call-arg]
            connection.commit()
