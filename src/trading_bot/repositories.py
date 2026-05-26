from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date
from typing import Any, Protocol

from trading_bot.models import BotLog, DailyScore, DailyTarget, FillRecord, TradeRecord


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
                item.entry_price_usd,
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
        self._ensure_trade_history_columns()
        self._executemany(
            """
            INSERT INTO trade_history
                (trade_date, ticker, order_type, order_price, exec_price,
                 entry_price, max_price_after_buy, quantity, usd_krw_rate, profit_usd,
                 profit_krw, profit_rate, exit_reason, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def save_fills(self, fills: Iterable[FillRecord]) -> None:
        rows = [
            (
                item.trade_date,
                item.fill_time,
                item.ticker,
                item.ticker_name,
                item.side,
                item.quantity,
                item.fill_price_usd,
                item.fill_amount_usd,
                item.profit_usd,
                item.profit_rate,
                item.order_no,
                item.is_mock,
            )
            for item in fills
        ]
        if not rows:
            return
        self._ensure_fill_history_table()
        for row in rows:
            self._execute(
                """
                IF EXISTS (
                    SELECT 1
                    FROM fill_history
                    WHERE fill_date = ?
                      AND ISNULL(fill_time, '') = ?
                      AND ticker = ?
                      AND ISNULL(side, '') = ?
                      AND quantity = ?
                      AND fill_price = ?
                      AND is_mock = ?
                )
                BEGIN
                    UPDATE fill_history
                    SET profit_usd = ?, profit_rate = ?
                    WHERE fill_date = ?
                      AND ISNULL(fill_time, '') = ?
                      AND ticker = ?
                      AND ISNULL(side, '') = ?
                      AND quantity = ?
                      AND fill_price = ?
                      AND is_mock = ?
                END
                ELSE
                BEGIN
                    INSERT INTO fill_history
                        (fill_date, fill_time, ticker, ticker_name, side, quantity,
                         fill_price, fill_amount, profit_usd, profit_rate, order_no, is_mock)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                END
                """,
                (
                    row[0],
                    row[1],
                    row[2],
                    row[4],
                    row[5],
                    row[6],
                    row[11],
                    row[8],
                    row[9],
                    row[0],
                    row[1],
                    row[2],
                    row[4],
                    row[5],
                    row[6],
                    row[11],
                    *row,
                ),
            )

    def sell_entry_prices(self, trade_date: date) -> dict[str, float]:
        self._ensure_trade_history_columns()
        rows = self._query(
            """
            SELECT ticker, entry_price
            FROM trade_history
            WHERE trade_date = ?
              AND order_type = 'SELL'
              AND entry_price IS NOT NULL
            ORDER BY created_at DESC
            """,
            (trade_date,),
        )
        prices: dict[str, float] = {}
        for ticker, entry_price in rows:
            key = str(ticker).strip().upper()
            if key and key not in prices:
                prices[key] = _number(entry_price)
        return prices

    def _ensure_trade_history_columns(self) -> None:
        self._execute_statement(
            """
            IF COL_LENGTH('dbo.trade_history', 'entry_price') IS NULL
                ALTER TABLE dbo.trade_history ADD entry_price DECIMAL(10, 2) NULL
            """,
        )

    def _ensure_fill_history_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.fill_history', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.fill_history (
                    id INT IDENTITY PRIMARY KEY,
                    fill_date DATE NOT NULL,
                    fill_time VARCHAR(8),
                    ticker VARCHAR(10) NOT NULL,
                    ticker_name NVARCHAR(100),
                    side NVARCHAR(20),
                    quantity INT,
                    fill_price DECIMAL(10, 2),
                    fill_amount DECIMAL(12, 2),
                    profit_usd DECIMAL(10, 2),
                    profit_rate DECIMAL(8, 4),
                    order_no VARCHAR(30),
                    is_mock BIT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.fill_history', 'profit_usd') IS NULL
                ALTER TABLE dbo.fill_history ADD profit_usd DECIMAL(10, 2) NULL

            IF COL_LENGTH('dbo.fill_history', 'profit_rate') IS NULL
                ALTER TABLE dbo.fill_history ADD profit_rate DECIMAL(8, 4) NULL
            """,
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
            SELECT TOP (?) ticker, order_type, order_price, quantity, exit_reason,
                   profit_usd, profit_rate
            FROM trade_history
            WHERE trade_date = CAST(GETDATE() AS DATE)
            ORDER BY created_at DESC
            """,
            (limit,),
        )

    def today_realized_profit(self) -> float:
        return self._sum_profit(
            """
            SELECT COALESCE(SUM(profit_usd), 0)
            FROM fill_history
            WHERE fill_date = CAST(GETDATE() AS DATE)
              AND (side LIKE N'%매도%' OR UPPER(side) = 'SELL')
            """,
            (),
        )

    def latest_fills(self, limit: int = 20) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                       quantity, fill_price, fill_amount, profit_usd, profit_rate
                FROM fill_history
                ORDER BY created_at DESC
                """,
                (limit,),
            )
        except Exception:
            return []

    def latest_logs(self, limit: int = 20) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) created_at, log_level, message
            FROM bot_log
            WHERE CAST(created_at AS DATE) = CAST(GETDATE() AS DATE)
            ORDER BY created_at DESC
            """,
            (limit,),
        )

    def history_targets(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name, volume_ratio, price_change
                FROM daily_target
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) ticker, volume_ratio, price_change
                FROM daily_target
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )

    def history_scores(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) ticker, news_score, chart_score, total_score, is_selected
            FROM scoring
            WHERE trade_date = ?
            ORDER BY total_score DESC, created_at DESC
            """,
            (limit, trade_date),
        )

    def history_trades(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) ticker, order_type, order_price, quantity, exit_reason,
                   profit_usd, profit_rate
            FROM trade_history
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (limit, trade_date),
        )

    def history_realized_profit(self, trade_date: date) -> float:
        return self._sum_profit(
            """
            SELECT COALESCE(SUM(profit_usd), 0)
            FROM fill_history
            WHERE fill_date = ?
              AND (side LIKE N'%매도%' OR UPPER(side) = 'SELL')
            """,
            (trade_date,),
        )

    def history_fills(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                       quantity, fill_price, fill_amount, profit_usd, profit_rate
                FROM fill_history
                WHERE fill_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return []

    def history_logs(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) created_at, log_level, message
            FROM bot_log
            WHERE CAST(created_at AS DATE) = ?
            ORDER BY created_at DESC
            """,
            (limit, trade_date),
        )

    def _query(self, sql: str, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            return list(cursor.fetchall())

    def _sum_profit(self, sql: str, row: tuple[Any, ...]) -> float:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            rows = list(cursor.fetchall())
        if not rows:
            return 0.0
        value = rows[0][0]
        if value is None:
            return 0.0
        try:
            return float(value)
        except TypeError:
            return float(str(value))


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except TypeError:
        return float(str(value))
