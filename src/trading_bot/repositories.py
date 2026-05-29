from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date
from typing import Any, Protocol

from trading_bot.config import TradingSettings
from trading_bot.models import BotLog, DailyScore, DailyTarget, FillRecord, TradeRecord
from trading_bot.trading_date import current_trade_date


class Cursor(Protocol):
    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> Any: ...

    def execute(self, sql: str, row: tuple[Any, ...]) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


class SqlServerDailyRepository:
    """자동매매 실행 결과를 거래일 기준으로 MSSQL에 저장하는 저장소."""

    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def save_daily_targets(self, targets: Iterable[DailyTarget]) -> None:
        target_items = list(targets)
        rows = [
            (
                item.trade_date,
                item.candidate.ticker,
                item.candidate.name,
                item.candidate.opening_volume,
                item.candidate.average_volume_20d,
                item.candidate.opening_volume_ratio * 100,
                item.candidate.opening_price_change * 100,
            )
            for item in target_items
        ]
        self._executemany_with_daily_target_name(
            """
            INSERT INTO daily_target
                (trade_date, ticker, ticker_name, opening_volume, average_volume_20d,
                 volume_ratio, price_change)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        self.save_listed_targets(target_items)

    def save_listed_targets(self, targets: Iterable[DailyTarget]) -> None:
        rows = [
            (
                item.trade_date,
                item.candidate.ticker,
                item.candidate.name,
                item.candidate.price_usd,
                item.candidate.opening_volume,
                item.candidate.average_volume_20d,
                item.candidate.opening_volume_ratio * 100,
                item.candidate.opening_price_change * 100,
            )
            for item in targets
        ]
        if not rows:
            return
        self._ensure_listed_target_snapshot_table()
        self._executemany(
            """
            INSERT INTO listed_target_snapshot
                (trade_date, ticker, ticker_name, price_usd, opening_volume,
                 average_volume_20d, volume_ratio, price_change)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def save_holdings(
        self,
        holdings: Iterable[dict[str, str]],
        trade_date: date,
        is_mock: bool = True,
    ) -> None:
        rows = [
            (
                trade_date,
                _text(item.get("ticker")),
                _text(item.get("name")),
                int(_number(item.get("quantity"))),
                _number(item.get("averagePrice")),
                _number(item.get("openPrice")),
                _number(item.get("closePrice")),
                _number(item.get("totalPrice")),
                is_mock,
            )
            for item in holdings
            if _text(item.get("ticker")) and _number(item.get("quantity")) > 0
        ]
        self._ensure_holding_snapshot_table()
        self._execute(
            """
            DELETE FROM holding_snapshot
            WHERE trade_date = ? AND is_mock = ?
            """,
            (trade_date, is_mock),
        )
        self._executemany(
            """
            INSERT INTO holding_snapshot
                (trade_date, snapshot_date, ticker, ticker_name, quantity, average_price,
                 open_price, close_price, total_price, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(row[0], *row) for row in rows],
        )

    def save_account_snapshot(
        self,
        account: dict[str, str],
        trade_date: date,
        is_mock: bool = True,
    ) -> None:
        self._ensure_account_snapshot_table()
        self.save_account_current(account, is_mock, trade_date)
        self._execute(
            """
            INSERT INTO account_snapshot
                (trade_date, snapshot_date, cash_usd, equity_usd, invested_usd,
                 open_positions, daily_profit_rate, realized_profit_usd, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_date,
                trade_date,
                _number(account.get("cashUsd")),
                _number(account.get("equityUsd")),
                _number(account.get("investedUsd")),
                int(_number(account.get("openPositions"))),
                _number(account.get("dailyProfitRate")),
                _number(account.get("realizedProfitUsd")),
                is_mock,
            ),
        )

    def save_account_current(
        self,
        account: dict[str, str],
        is_mock: bool = True,
        trade_date: date | None = None,
    ) -> None:
        # 대시보드 상단 계좌 요약은 계좌 유형별 한 행만 유지하며 최신값으로 갱신한다.
        target_date = trade_date or current_trade_date()
        account_type = _account_type(is_mock)
        account_label = "모의투자계좌" if is_mock else "실투자계좌"
        self._ensure_account_current_table()
        self._execute(
            """
            IF EXISTS (
                SELECT 1 FROM account_current WHERE account_type = ?
            )
            BEGIN
                UPDATE account_current
                SET account_label = ?,
                    trade_date = ?,
                    cash_usd = ?,
                    equity_usd = ?,
                    invested_usd = ?,
                    cash_krw = ?,
                    equity_krw = ?,
                    open_positions = ?,
                    daily_profit_rate = ?,
                    realized_profit_usd = ?,
                    updated_at = GETDATE()
                WHERE account_type = ?
            END
            ELSE
            BEGIN
                INSERT INTO account_current
                    (account_type, account_label, trade_date, cash_usd, equity_usd,
                     invested_usd, cash_krw, equity_krw, open_positions,
                     daily_profit_rate, realized_profit_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            END
            """,
            (
                account_type,
                account_label,
                target_date,
                _number(account.get("cashUsd")),
                _number(account.get("equityUsd")),
                _number(account.get("investedUsd")),
                _number(account.get("cashKrw")),
                _number(account.get("equityKrw")),
                int(_number(account.get("openPositions"))),
                _number(account.get("dailyProfitRate")),
                _number(account.get("realizedProfitUsd")),
                account_type,
                account_type,
                account_label,
                target_date,
                _number(account.get("cashUsd")),
                _number(account.get("equityUsd")),
                _number(account.get("investedUsd")),
                _number(account.get("cashKrw")),
                _number(account.get("equityKrw")),
                int(_number(account.get("openPositions"))),
                _number(account.get("dailyProfitRate")),
                _number(account.get("realizedProfitUsd")),
            ),
        )

    def save_order_snapshot(
        self,
        orders: Iterable[dict[str, str]],
        trade_date: date,
        is_mock: bool = True,
    ) -> None:
        rows = [
            (
                trade_date,
                _text(item.get("time")),
                _text(item.get("ticker")),
                _text(item.get("name")),
                _text(item.get("side")),
                int(_number(item.get("quantity"))),
                _number(item.get("price")),
                int(_number(item.get("unfilled"))),
                _text(item.get("orderNo")),
                is_mock,
            )
            for item in orders
            if _text(item.get("ticker"))
        ]
        self._ensure_order_snapshot_table()
        self._execute(
            """
            DELETE FROM order_snapshot
            WHERE trade_date = ? AND is_mock = ?
            """,
            (trade_date, is_mock),
        )
        self._executemany(
            """
            INSERT INTO order_snapshot
                (trade_date, order_date, order_time, ticker, ticker_name, side, quantity,
                 order_price, unfilled_quantity, order_no, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(row[0], *row) for row in rows],
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
        self._ensure_bot_log_table()
        self._execute(
            """
            INSERT INTO bot_log (trade_date, log_level, module, message)
            VALUES (?, ?, ?, ?)
            """,
            (current_trade_date(), log.level, log.module, log.message),
        )

    def save_daily_run_summary(
        self,
        trade_date: date,
        settings: TradingSettings,
        realized_profit_usd: float,
        realized_profit_rate: float,
        eod_sell_count: int | None,
        cancelled_order_count: int | None,
        buy_fill_count: int,
        sell_fill_count: int,
    ) -> None:
        self._ensure_daily_run_summary_table()
        settings_json = json.dumps(_settings_snapshot(settings), ensure_ascii=False, sort_keys=True)
        self._execute(
            """
            IF EXISTS (SELECT 1 FROM daily_run_summary WHERE trade_date = ? AND is_mock = 1)
            BEGIN
                UPDATE daily_run_summary
                SET candidate_selection_mode = ?,
                    settings_json = ?,
                    realized_profit_usd = ?,
                    realized_profit_rate = ?,
                    eod_sell_count = COALESCE(?, eod_sell_count),
                    cancelled_order_count = COALESCE(?, cancelled_order_count),
                    buy_fill_count = ?,
                    sell_fill_count = ?,
                    updated_at = GETDATE()
                WHERE trade_date = ? AND is_mock = 1
            END
            ELSE
            BEGIN
                INSERT INTO daily_run_summary
                    (trade_date, candidate_selection_mode, settings_json,
                     realized_profit_usd, realized_profit_rate, eod_sell_count,
                     cancelled_order_count, buy_fill_count, sell_fill_count, is_mock)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, 0), ?, ?, 1)
            END
            """,
            (
                trade_date,
                settings.candidate_selection_mode,
                settings_json,
                realized_profit_usd,
                realized_profit_rate,
                eod_sell_count,
                cancelled_order_count,
                buy_fill_count,
                sell_fill_count,
                trade_date,
                trade_date,
                settings.candidate_selection_mode,
                settings_json,
                realized_profit_usd,
                realized_profit_rate,
                eod_sell_count,
                cancelled_order_count,
                buy_fill_count,
                sell_fill_count,
            ),
        )

    def save_trades(self, trades: Iterable[TradeRecord]) -> None:
        trade_items = list(trades)
        ticker_names = self._trade_ticker_names(item.ticker for item in trade_items)
        rows = [
            (
                item.trade_date,
                item.ticker,
                _text(item.ticker_name) or ticker_names.get(item.ticker.strip().upper(), ""),
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
            for item in trade_items
        ]
        self._ensure_trade_history_columns()
        self._executemany(
            """
            INSERT INTO trade_history
                (trade_date, ticker, ticker_name, order_type, order_price, exec_price,
                 entry_price, max_price_after_buy, quantity, usd_krw_rate, profit_usd,
                 profit_krw, profit_rate, exit_reason, is_mock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    WHERE trade_date = ?
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
                    WHERE trade_date = ?
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
                        (trade_date, fill_date, fill_time, ticker, ticker_name, side, quantity,
                         fill_price, fill_amount, profit_usd, profit_rate, order_no, is_mock)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    row[0],
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

            IF COL_LENGTH('dbo.trade_history', 'ticker_name') IS NULL
                ALTER TABLE dbo.trade_history ADD ticker_name NVARCHAR(100) NULL
            """,
        )
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.fill_history', N'U') IS NOT NULL
               AND OBJECT_ID(N'dbo.listed_target_snapshot', N'U') IS NOT NULL
               AND OBJECT_ID(N'dbo.daily_target', N'U') IS NOT NULL
            BEGIN
                UPDATE th
                SET ticker_name = COALESCE(fh.ticker_name, lts.ticker_name, dt.ticker_name)
                FROM dbo.trade_history th
                OUTER APPLY (
                    SELECT TOP (1) ticker_name
                    FROM dbo.fill_history
                    WHERE ticker = th.ticker
                      AND ticker_name IS NOT NULL
                      AND ticker_name <> ''
                    ORDER BY fill_date DESC, created_at DESC
                ) fh
                OUTER APPLY (
                    SELECT TOP (1) ticker_name
                    FROM dbo.listed_target_snapshot
                    WHERE ticker = th.ticker
                      AND ticker_name IS NOT NULL
                      AND ticker_name <> ''
                    ORDER BY trade_date DESC, created_at DESC
                ) lts
                OUTER APPLY (
                    SELECT TOP (1) ticker_name
                    FROM dbo.daily_target
                    WHERE ticker = th.ticker
                      AND ticker_name IS NOT NULL
                      AND ticker_name <> ''
                    ORDER BY trade_date DESC, created_at DESC
                ) dt
                WHERE (th.ticker_name IS NULL OR th.ticker_name = '')
                  AND COALESCE(fh.ticker_name, lts.ticker_name, dt.ticker_name) IS NOT NULL
            END
            """,
        )

    def _trade_ticker_names(self, tickers: Iterable[str]) -> dict[str, str]:
        symbols = sorted({_text(ticker).upper() for ticker in tickers if _text(ticker)})
        if not symbols:
            return {}
        placeholders = ", ".join("?" for _ in symbols)
        try:
            rows = self._query(
                f"""
                SELECT ticker, ticker_name
                FROM (
                    SELECT ticker, ticker_name, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC
                           ) AS rn
                    FROM (
                        SELECT ticker, ticker_name, created_at
                        FROM fill_history
                        WHERE ticker IN ({placeholders})
                          AND ticker_name IS NOT NULL
                          AND ticker_name <> ''
                        UNION ALL
                        SELECT ticker, ticker_name, created_at
                        FROM listed_target_snapshot
                        WHERE ticker IN ({placeholders})
                          AND ticker_name IS NOT NULL
                          AND ticker_name <> ''
                        UNION ALL
                        SELECT ticker, ticker_name, created_at
                        FROM daily_target
                        WHERE ticker IN ({placeholders})
                          AND ticker_name IS NOT NULL
                          AND ticker_name <> ''
                    ) names
                ) ranked
                WHERE rn = 1
                """,
                tuple(symbols * 3),
            )
        except Exception:
            return {}
        names: dict[str, str] = {}
        for row in rows:
            if len(row) < 2 or not isinstance(row[1], str):
                continue
            ticker = _text(row[0]).upper()
            name = _text(row[1])
            if ticker and name:
                names[ticker] = name
        return names

    def _ensure_fill_history_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.fill_history', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.fill_history (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
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

            IF COL_LENGTH('dbo.fill_history', 'trade_date') IS NULL
                ALTER TABLE dbo.fill_history ADD trade_date DATE NULL

            EXEC(N'
            UPDATE dbo.fill_history
            SET trade_date = fill_date
            WHERE trade_date IS NULL
            ')
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
            self._ensure_daily_target_schema()
            self._executemany(sql, rows)

    def _ensure_daily_target_schema(self) -> None:
        self._execute_statement(
            """
            IF COL_LENGTH('dbo.daily_target', 'ticker_name') IS NULL
                ALTER TABLE dbo.daily_target ADD ticker_name NVARCHAR(100) NULL

            IF COL_LENGTH('dbo.daily_target', 'opening_volume') IS NULL
                ALTER TABLE dbo.daily_target ADD opening_volume BIGINT NULL

            IF COL_LENGTH('dbo.daily_target', 'average_volume_20d') IS NULL
                ALTER TABLE dbo.daily_target ADD average_volume_20d BIGINT NULL

            ALTER TABLE dbo.daily_target ALTER COLUMN volume_ratio DECIMAL(12, 2) NULL
            ALTER TABLE dbo.daily_target ALTER COLUMN price_change DECIMAL(12, 2) NULL
            """,
        )

    def _ensure_listed_target_snapshot_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.listed_target_snapshot', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.listed_target_snapshot (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    ticker_name NVARCHAR(100),
                    price_usd DECIMAL(12, 2),
                    opening_volume BIGINT,
                    average_volume_20d BIGINT,
                    volume_ratio DECIMAL(12, 2),
                    price_change DECIMAL(12, 2),
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.listed_target_snapshot', 'opening_volume') IS NULL
                ALTER TABLE dbo.listed_target_snapshot ADD opening_volume BIGINT NULL

            IF COL_LENGTH('dbo.listed_target_snapshot', 'average_volume_20d') IS NULL
                ALTER TABLE dbo.listed_target_snapshot ADD average_volume_20d BIGINT NULL
            """,
        )

    def _ensure_holding_snapshot_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.holding_snapshot', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.holding_snapshot (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    snapshot_date DATE NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    ticker_name NVARCHAR(100),
                    quantity INT,
                    average_price DECIMAL(12, 2),
                    open_price DECIMAL(12, 2),
                    close_price DECIMAL(12, 2),
                    total_price DECIMAL(14, 2),
                    is_mock BIT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.holding_snapshot', 'trade_date') IS NULL
                ALTER TABLE dbo.holding_snapshot ADD trade_date DATE NULL

            EXEC(N'
            UPDATE dbo.holding_snapshot
            SET trade_date = snapshot_date
            WHERE trade_date IS NULL
            ')
            """,
        )

    def _ensure_account_snapshot_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.account_snapshot', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.account_snapshot (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    snapshot_date DATE NOT NULL,
                    cash_usd DECIMAL(14, 2),
                    equity_usd DECIMAL(14, 2),
                    invested_usd DECIMAL(14, 2),
                    open_positions INT,
                    daily_profit_rate DECIMAL(8, 4),
                    realized_profit_usd DECIMAL(14, 2),
                    is_mock BIT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.account_snapshot', 'trade_date') IS NULL
                ALTER TABLE dbo.account_snapshot ADD trade_date DATE NULL

            EXEC(N'
            UPDATE dbo.account_snapshot
            SET trade_date = snapshot_date
            WHERE trade_date IS NULL
            ')
            """,
        )

    def _ensure_account_current_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.account_current', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.account_current (
                    account_type VARCHAR(10) NOT NULL PRIMARY KEY,
                    account_label NVARCHAR(30) NOT NULL,
                    trade_date DATE,
                    cash_usd DECIMAL(14, 2),
                    equity_usd DECIMAL(14, 2),
                    invested_usd DECIMAL(14, 2),
                    cash_krw DECIMAL(18, 2),
                    equity_krw DECIMAL(18, 2),
                    open_positions INT,
                    daily_profit_rate DECIMAL(8, 4),
                    realized_profit_usd DECIMAL(14, 2),
                    updated_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.account_current', 'trade_date') IS NULL
                ALTER TABLE dbo.account_current ADD trade_date DATE NULL
            """,
        )

    def _ensure_order_snapshot_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.order_snapshot', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.order_snapshot (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    order_date DATE NOT NULL,
                    order_time VARCHAR(8),
                    ticker VARCHAR(10) NOT NULL,
                    ticker_name NVARCHAR(100),
                    side NVARCHAR(20),
                    quantity INT,
                    order_price DECIMAL(12, 2),
                    unfilled_quantity INT,
                    order_no VARCHAR(30),
                    is_mock BIT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.order_snapshot', 'trade_date') IS NULL
                ALTER TABLE dbo.order_snapshot ADD trade_date DATE NULL

            EXEC(N'
            UPDATE dbo.order_snapshot
            SET trade_date = order_date
            WHERE trade_date IS NULL
            ')
            """,
        )

    def _ensure_bot_log_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.bot_log', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.bot_log (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE,
                    log_level VARCHAR(10),
                    module VARCHAR(50),
                    message NVARCHAR(500),
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.bot_log', 'trade_date') IS NULL
                ALTER TABLE dbo.bot_log ADD trade_date DATE NULL

            EXEC(N'
            UPDATE dbo.bot_log
            SET trade_date = CAST(created_at AS DATE)
            WHERE trade_date IS NULL
            ')
            """,
        )

    def _ensure_daily_run_summary_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.daily_run_summary', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.daily_run_summary (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    candidate_selection_mode VARCHAR(20) NOT NULL,
                    settings_json NVARCHAR(MAX),
                    realized_profit_usd DECIMAL(14, 2),
                    realized_profit_rate DECIMAL(8, 4),
                    eod_sell_count INT DEFAULT 0,
                    cancelled_order_count INT DEFAULT 0,
                    buy_fill_count INT DEFAULT 0,
                    sell_fill_count INT DEFAULT 0,
                    is_mock BIT DEFAULT 1,
                    created_at DATETIME DEFAULT GETDATE(),
                    updated_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.daily_run_summary', 'candidate_selection_mode') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD candidate_selection_mode VARCHAR(20) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'settings_json') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD settings_json NVARCHAR(MAX) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'realized_profit_usd') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD realized_profit_usd DECIMAL(14, 2) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'realized_profit_rate') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD realized_profit_rate DECIMAL(8, 4) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'eod_sell_count') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD eod_sell_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_run_summary', 'cancelled_order_count') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD cancelled_order_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_run_summary', 'buy_fill_count') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD buy_fill_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_run_summary', 'sell_fill_count') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD sell_fill_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_run_summary', 'is_mock') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD is_mock BIT DEFAULT 1

            IF COL_LENGTH('dbo.daily_run_summary', 'updated_at') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD updated_at DATETIME DEFAULT GETDATE()
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


class SqlServerMonitorRepository:
    """모니터 화면이 사용할 최신 스냅샷과 날짜별 이력을 DB에서 조회한다."""

    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def latest_targets(self, limit: int = 20) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        try:
            rows = self._query(
                """
                SELECT TOP (?) ticker, ticker_name, price_usd, opening_volume,
                       volume_ratio, price_change
                FROM (
                    SELECT ticker, ticker_name, price_usd, opening_volume,
                           volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM listed_target_snapshot
                    WHERE trade_date = ?
                      AND created_at >= DATEADD(
                          second,
                          -5,
                          (
                              SELECT MAX(created_at)
                              FROM listed_target_snapshot
                              WHERE trade_date = ?
                          )
                      )
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, target_date, target_date),
            )
        except Exception:
            try:
                rows = self._query(
                    """
                    SELECT TOP (?) ticker, ticker_name,
                           CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                           opening_volume, volume_ratio, price_change
                    FROM (
                        SELECT ticker, ticker_name, opening_volume,
                               volume_ratio, price_change, created_at,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ticker ORDER BY created_at DESC, id DESC
                               ) AS rn
                        FROM daily_target
                        WHERE trade_date = ?
                          AND created_at >= DATEADD(
                              second,
                              -5,
                              (
                                  SELECT MAX(created_at)
                                  FROM daily_target
                                  WHERE trade_date = ?
                              )
                          )
                    ) latest
                    WHERE rn = 1
                    ORDER BY created_at DESC
                    """,
                    (limit, target_date, target_date),
                )
            except Exception:
                rows = self._query(
                    """
                    SELECT TOP (?) ticker,
                           CAST(NULL AS NVARCHAR(100)) AS ticker_name,
                           CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                           opening_volume, volume_ratio, price_change
                    FROM (
                        SELECT ticker, opening_volume, volume_ratio, price_change, created_at,
                               ROW_NUMBER() OVER (
                                   PARTITION BY ticker ORDER BY created_at DESC, id DESC
                               ) AS rn
                        FROM daily_target
                        WHERE trade_date = ?
                          AND created_at >= DATEADD(
                              second,
                              -5,
                              (
                                  SELECT MAX(created_at)
                                  FROM daily_target
                                  WHERE trade_date = ?
                              )
                          )
                    ) latest
                    WHERE rn = 1
                    ORDER BY created_at DESC
                    """,
                    (limit, target_date, target_date),
                )
        if self._latest_screening_saved_no_targets():
            return []
        if rows:
            return rows
        return self._latest_daily_targets(limit)

    def _latest_daily_targets(self, limit: int) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name,
                       CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                       opening_volume, volume_ratio, price_change
                FROM (
                    SELECT ticker, ticker_name, opening_volume,
                           volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM daily_target
                    WHERE trade_date = ?
                      AND created_at >= DATEADD(
                          second,
                          -5,
                          (
                              SELECT MAX(created_at)
                              FROM daily_target
                              WHERE trade_date = ?
                          )
                      )
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, target_date, target_date),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) ticker,
                       CAST(NULL AS NVARCHAR(100)) AS ticker_name,
                       CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                       opening_volume, volume_ratio, price_change
                FROM (
                    SELECT ticker, opening_volume, volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM daily_target
                    WHERE trade_date = ?
                      AND created_at >= DATEADD(
                          second,
                          -5,
                          (
                              SELECT MAX(created_at)
                              FROM daily_target
                              WHERE trade_date = ?
                          )
                      )
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, target_date, target_date),
            )

    def latest_holdings(self, limit: int = 50) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name, quantity, average_price,
                       open_price, close_price, total_price
                FROM (
                    SELECT ticker, ticker_name, quantity, average_price,
                           open_price, close_price, total_price, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM holding_snapshot
                    WHERE trade_date = ?
                      AND is_mock = 1
                      AND created_at >= DATEADD(
                          second,
                          -5,
                          (
                              SELECT MAX(created_at)
                              FROM holding_snapshot
                              WHERE trade_date = ?
                                AND is_mock = 1
                          )
                      )
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, target_date, target_date),
            )
        except Exception:
            return []

    def latest_account(self, is_mock: bool = True) -> tuple[Any, ...] | None:
        account_type = _account_type(is_mock)
        target_date = current_trade_date()
        try:
            rows = self._query(
                """
                SELECT TOP (1) cash_usd, equity_usd, invested_usd, open_positions,
                       daily_profit_rate, realized_profit_usd, cash_krw, equity_krw
                FROM account_current
                WHERE account_type = ?
                ORDER BY updated_at DESC
                """,
                (account_type,),
            )
            if rows:
                return rows[0]
        except Exception:
            pass
        try:
            rows = self._query(
                """
                SELECT TOP (1) cash_usd, equity_usd, invested_usd, open_positions,
                       daily_profit_rate, realized_profit_usd
                FROM account_snapshot
                WHERE trade_date = ?
                  AND is_mock = ?
                ORDER BY created_at DESC, id DESC
                """,
                (target_date, is_mock),
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def latest_orders(self, limit: int = 50) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        try:
            return self._query(
                """
                SELECT TOP (?) order_date, order_time, ticker, ticker_name, side,
                       quantity, order_price, unfilled_quantity, order_no
                FROM order_snapshot
                WHERE trade_date = ?
                  AND is_mock = 1
                ORDER BY created_at DESC, id DESC
                """,
                (limit, target_date),
            )
        except Exception:
            return []

    def latest_scores(self, limit: int = 20) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        rows = self._query(
            """
            SELECT TOP (?) ticker, news_score, chart_score, total_score, is_selected
            FROM (
                SELECT ticker, news_score, chart_score, total_score, is_selected, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM scoring
                WHERE trade_date = ?
                  AND created_at >= DATEADD(
                      second,
                      -5,
                      (
                          SELECT MAX(created_at)
                          FROM scoring
                          WHERE trade_date = ?
                      )
                  )
            ) latest
            WHERE rn = 1
            ORDER BY total_score DESC, created_at DESC
            """,
            (limit, target_date, target_date),
        )
        if self._latest_screening_saved_no_targets():
            return []
        return rows

    def _latest_screening_saved_no_targets(self) -> bool:
        target_date = current_trade_date()
        try:
            rows = self._query(
                """
                SELECT CASE WHEN EXISTS (
                    SELECT 1
                    FROM bot_log
                    WHERE trade_date = ?
                      AND module = 'pipeline'
                      AND message LIKE 'Screened 0 targets%'
                      AND created_at >= COALESCE(
                          (
                              SELECT MAX(created_at)
                              FROM daily_target
                              WHERE trade_date = ?
                          ),
                          CONVERT(datetime, '19000101', 112)
                      )
                ) THEN 1 ELSE 0 END
                """,
                (target_date, target_date),
            )
        except Exception:
            return False
        try:
            return bool(rows and _number(rows[0][0]))
        except (TypeError, ValueError):
            return False

    def latest_trades(self, limit: int = 20) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        return self._query(
            """
            SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                   order_type, order_price, quantity, exit_reason,
                   profit_usd, profit_rate
            FROM trade_history
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (limit, target_date),
        )

    def today_realized_profit(self) -> float:
        return self._sum_profit(
            """
            SELECT COALESCE(SUM(profit_usd), 0)
            FROM fill_history
            WHERE side LIKE N'%매도%'
               OR UPPER(side) IN ('SELL', 'S')
            """,
            (),
        )

    def today_realized_profit_rate(self) -> float:
        # 전체 매도 체결 기준 수익률: 실현손익 / 매수원금.
        return self._profit_rate_percent(
            """
            SELECT COALESCE(SUM(profit_usd), 0),
                   COALESCE(SUM(fill_amount - profit_usd), 0)
            FROM fill_history
            WHERE profit_usd IS NOT NULL
              AND (side LIKE N'%매도%' OR UPPER(side) IN ('SELL', 'S'))
            """,
            (),
        )

    def latest_fills(self, limit: int = 20) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        try:
            return self._query(
                """
                SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                       quantity, fill_price, fill_amount, profit_usd, profit_rate
                FROM fill_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, target_date),
            )
        except Exception:
            return []

    def latest_logs(self, limit: int = 20) -> list[tuple[Any, ...]]:
        target_date = current_trade_date()
        return self._query(
            """
            SELECT TOP (?) created_at, log_level, message
            FROM bot_log
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (limit, target_date),
        )

    def history_targets(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            rows = self._query(
                """
                SELECT TOP (?) ticker, ticker_name, price_usd, opening_volume,
                       volume_ratio, price_change
                FROM (
                    SELECT ticker, ticker_name, price_usd, opening_volume,
                           volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM listed_target_snapshot
                    WHERE trade_date = ?
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
            if rows:
                return rows
        except Exception:
            pass
        return self._history_daily_targets(trade_date, limit)

    def _history_daily_targets(
        self,
        trade_date: date,
        limit: int,
    ) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name,
                       CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                       opening_volume, volume_ratio, price_change
                FROM (
                    SELECT ticker, ticker_name, opening_volume,
                           volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM daily_target
                    WHERE trade_date = ?
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) ticker,
                       CAST(NULL AS NVARCHAR(100)) AS ticker_name,
                       CAST(NULL AS DECIMAL(12, 2)) AS price_usd,
                       opening_volume, volume_ratio, price_change
                FROM (
                    SELECT ticker, opening_volume, volume_ratio, price_change, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM daily_target
                    WHERE trade_date = ?
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )

    def history_holdings(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) ticker, ticker_name, quantity, average_price,
                       open_price, close_price, total_price
                FROM (
                    SELECT ticker, ticker_name, quantity, average_price,
                           open_price, close_price, total_price, created_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY ticker ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM holding_snapshot
                    WHERE trade_date = ?
                      AND is_mock = 1
                ) latest
                WHERE rn = 1
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return []

    def history_account(self, trade_date: date, is_mock: bool = True) -> tuple[Any, ...] | None:
        try:
            rows = self._query(
                """
                SELECT TOP (1) cash_usd, equity_usd, invested_usd, open_positions,
                       daily_profit_rate, realized_profit_usd
                FROM account_snapshot
                WHERE trade_date = ?
                  AND is_mock = ?
                ORDER BY created_at DESC, id DESC
                """,
                (trade_date, is_mock),
            )
        except Exception:
            return None
        return rows[0] if rows else None

    def history_orders(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) order_date, order_time, ticker, ticker_name, side,
                       quantity, order_price, unfilled_quantity, order_no
                FROM order_snapshot
                WHERE trade_date = ?
                  AND is_mock = 1
                ORDER BY created_at DESC, id DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return []

    def history_scores(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) ticker, news_score, chart_score, total_score, is_selected
            FROM (
                SELECT ticker, news_score, chart_score, total_score, is_selected, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM scoring
                WHERE trade_date = ?
            ) latest
            WHERE rn = 1
            ORDER BY total_score DESC, created_at DESC
            """,
            (limit, trade_date),
        )

    def history_trades(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                   order_type, order_price, quantity, exit_reason,
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
            WHERE trade_date = ?
              AND (side LIKE N'%매도%' OR UPPER(side) = 'SELL')
            """,
            (trade_date,),
        )

    def history_realized_profit_rate(self, trade_date: date) -> float:
        return self._profit_rate_percent(
            """
            SELECT COALESCE(SUM(profit_usd), 0),
                   COALESCE(SUM(fill_amount - profit_usd), 0)
            FROM fill_history
            WHERE trade_date = ?
              AND profit_usd IS NOT NULL
              AND (side LIKE N'%매도%' OR UPPER(side) IN ('SELL', 'S'))
            """,
            (trade_date,),
        )

    def history_fill_counts(self, trade_date: date) -> tuple[int, int]:
        try:
            rows = self._query(
                """
                SELECT
                    SUM(CASE
                        WHEN side LIKE N'%매수%' OR UPPER(side) IN ('BUY', 'B') THEN 1
                        ELSE 0
                    END),
                    SUM(CASE
                        WHEN side LIKE N'%매도%' OR UPPER(side) IN ('SELL', 'S') THEN 1
                        ELSE 0
                    END)
                FROM fill_history
                WHERE trade_date = ?
                """,
                (trade_date,),
            )
        except Exception:
            return (0, 0)
        if not rows:
            return (0, 0)
        return (int(_number(rows[0][0])), int(_number(rows[0][1])))

    def history_fills(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                       quantity, fill_price, fill_amount, profit_usd, profit_rate
                FROM fill_history
                WHERE trade_date = ?
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
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (limit, trade_date),
        )

    def history_run_summaries(self, trade_date: date, limit: int = 20) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) trade_date, candidate_selection_mode, settings_json,
                       realized_profit_usd, realized_profit_rate, eod_sell_count,
                       cancelled_order_count, buy_fill_count, sell_fill_count,
                       updated_at
                FROM daily_run_summary
                WHERE is_mock = 1
                ORDER BY trade_date DESC, updated_at DESC, id DESC
                """,
                (limit,),
            )
        except Exception:
            return []

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

    def _profit_rate_percent(self, sql: str, row: tuple[Any, ...]) -> float:
        with closing(self.connect()) as connection:
            cursor = connection.cursor()
            cursor.execute(sql, row)
            rows = list(cursor.fetchall())
        if not rows:
            return 0.0
        profit = _number(rows[0][0])
        cost_basis = _number(rows[0][1]) if len(rows[0]) > 1 else 0.0
        if cost_basis <= 0:
            return 0.0
        return profit / cost_basis * 100


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(
            str(value)
            .replace("$", "")
            .replace(",", "")
            .replace("%", "")
            .replace("원", "")
            .replace("+", "")
            .strip()
        )
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _account_type(is_mock: bool) -> str:
    return "mock" if is_mock else "real"


def _settings_snapshot(settings: TradingSettings) -> dict[str, object]:
    return {
        "candidateSelectionMode": settings.candidate_selection_mode,
        "stopLossPercent": abs(settings.max_position_loss * 100),
        "takeProfitPercent": settings.take_profit_rate * 100,
        "minTotalScore": settings.min_total_score,
        "minPriceUsd": settings.min_price_usd,
        "maxPriceUsd": settings.max_price_usd,
        "minOpeningPriceChangePercent": settings.min_opening_price_change * 100,
        "minVolumeRatio": settings.min_volume_ratio,
        "maxOpeningGapPercent": settings.max_opening_gap * 100,
        "openingFixedCandidateLimit": settings.opening_fixed_candidate_limit,
        "intradayRefreshCandidateLimit": settings.intraday_refresh_candidate_limit,
        "hybridCandidateLimit": settings.hybrid_candidate_limit,
    }
