from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import closing
from typing import Any, Protocol

from trading_bot.models import BotLog, DailyScore, DailyTarget, TradeRecord


class Cursor(Protocol):
    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> Any: ...

    def execute(self, sql: str, row: tuple[Any, ...]) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


class SqlServerDailyRepository:
    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None:
        rows = [
            (
                item.trade_date,
                item.candidate.ticker,
                item.candidate.name,
                item.candidate.opening_volume_ratio * 100,
                item.candidate.opening_price_change * 100,
            )
            for item in targets
        ]
        self._executemany_with_daily_target_name(
            """
            INSERT INTO daily_target
                (trade_date, ticker, ticker_name, volume_ratio, price_change)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )

    def save_daily_scores(self, scores: Iterable[DailyScore]) -> None:
        rows = [
            (
                item.trade_date,
                item.score.ticker,
                item.score.news_score,
                item.score.chart_score,
                item.score.total_score,
                item.is_selected,
            )
            for item in scores
        ]
        self._executemany(
            """
            INSERT INTO scoring
                (trade_date, ticker, news_score, chart_score, total_score, is_selected)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def save_log(self, log: BotLog) -> None:
        self._execute(
            """
            INSERT INTO bot_log (log_level, module, message)
            VALUES (?, ?, ?)
            """,
            (log.level, log.module, log.message),
        )

    def save_trades(self, trades: Iterable[TradeRecord]) -> None:
        rows = [
            (
                item.trade_date,
                item.ticker,
                item.order_type,
                item.order_price_usd,
                item.exec_price_usd,
                item.max_price_after_buy,
                item.quantity,
                item.usd_krw_rate,
                item.profit_usd,
                item.profit_krw,
                item.profit_rate,
                item.exit_reason,
                item.is_mock,
            )
            for item in trades
        ]
        self._executemany(
            """
            INSERT INTO trade_history
                (trade_date, ticker, order_type, order_price, exec_price,
                 max_price_after_buy, quantity, usd_krw_rate, profit_usd,
                 profit_krw, profit_rate, exit_reason, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        if not rows:
            return
        with closing(self.connect()) as connection:
            connection.cursor().executemany(sql, rows)
            connection.commit()

    def _executemany_with_daily_target_name(
        self,
        sql: str,
        rows: list[tuple[Any, ...]],
    ) -> None:
        if not rows:
            return
        try:
            self._executemany(sql, rows)
        except Exception:
            self._execute_statement(
                """
                IF COL_LENGTH('dbo.daily_target', 'ticker_name') IS NULL
                    ALTER TABLE dbo.daily_target ADD ticker_name NVARCHAR(100) NULL
                """,
            )
            self._executemany(sql, rows)

    def _execute(self, sql: str, row: tuple[Any, ...]) -> None:
        with closing(self.connect()) as connection:
            connection.cursor().execute(sql, row)
            connection.commit()

    def _execute_statement(self, sql: str) -> None:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql, ())
            except TypeError:
                cursor.execute(sql)  # type: ignore[call-arg]
            connection.commit()


class SqlServerMonitorRepository:
    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def latest_targets(self, limit: int = 20) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name, volume_ratio, price_change
                FROM daily_target
                WHERE trade_date = CAST(GETDATE() AS DATE)
                ORDER BY created_at DESC
                """,
                (limit,),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) ticker, volume_ratio, price_change
                FROM daily_target
                WHERE trade_date = CAST(GETDATE() AS DATE)
                ORDER BY created_at DESC
                """,
                (limit,),
            )

    def latest_scores(self, limit: int = 20) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) ticker, news_score, chart_score, total_score, is_selected
            FROM scoring
            WHERE trade_date = CAST(GETDATE() AS DATE)
            ORDER BY total_score DESC, created_at DESC
            """,
            (limit,),
        )

    def latest_trades(self, limit: int = 20) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) ticker, order_type, order_price, quantity, exit_reason
            FROM trade_history
            ORDER BY created_at DESC
            """,
            (limit,),
        )

    def latest_logs(self, limit: int = 20) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) created_at, log_level, message
            FROM bot_log
            ORDER BY created_at DESC
            """,
            (limit,),
        )

    def _query(self, sql: str, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            return list(cursor.fetchall())
