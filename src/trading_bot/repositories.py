from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import closing
from datetime import date
from typing import Any, Protocol

from trading_bot.config import TradingSettings
from trading_bot.models import (
    BotLog,
    CandidateEvaluation,
    DailyScore,
    DailyTarget,
    DailyTradeSummaryReport,
    EntryProfitSnapshot,
    FillRecord,
    TradeRecord,
)
from trading_bot.strategy_metadata import settings_snapshot, strategy_metadata_from_settings
from trading_bot.trading_date import current_trade_date


class Cursor(Protocol):
    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> Any: ...

    def execute(self, sql: str, row: tuple[Any, ...]) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


# 일별 저장소: 수집/주문/체결/계좌 스냅샷을 거래일 기준으로 기록한다.
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
            _order_snapshot_row(item, trade_date, is_mock)
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
                 order_price, unfilled_quantity, order_no, is_mock, order_status, order_qty,
                 filled_qty, remaining_qty, avg_fill_price, last_fill_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        self._ensure_bot_log_table()
        self._execute(
            """
            INSERT INTO bot_log
                (trade_date, log_level, module, message, symbol, ticker_name,
                 reject_reason, actual_value, threshold_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_trade_date(),
                log.level,
                log.module,
                log.message,
                log.symbol,
                log.name,
                log.reject_reason,
                log.actual_value,
                log.threshold_value,
            ),
        )

    def save_candidate_evaluations(self, evaluations: Iterable[CandidateEvaluation]) -> None:
        rows = [_candidate_evaluation_row(item) for item in evaluations]
        if not rows:
            return
        self._ensure_candidate_evaluations_table()
        self._executemany(
            """
            INSERT INTO candidate_evaluations
                (run_id, evaluation_time, trading_date, source, symbol, symbol_name,
                 current_price, volume, dollar_volume, price_change_percent,
                 opening_gap_percent, price_rank, volume_rank, relaxation_level,
                 min_price, max_price, price_change_top, volume_top,
                 min_selection_score, min_opening_price_change_percent,
                 min_volume_ratio, max_opening_gap_percent, selection_score,
                 soft_score_adjustment, final_score, overheat_condition_mode,
                 breakout_close_condition_mode, volume_increase_condition_mode,
                 vwap_ma20_condition_mode, vwap_ma20_condition_type,
                 pullback_rebreak_condition_mode, overheat_pass, breakout_close_pass,
                 volume_increase_pass, vwap_pass, ma20_pass, vwap_ma20_pass,
                 pullback_rebreak_pass, final_score_pass, buy_allowed,
                 order_submitted, order_id, buy_block_reason, buy_block_reasons,
                 hard_filter_failed_count, soft_condition_failed_count,
                 final_decision, settings_snapshot_json, condition_result_json,
                 raw_candidate_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def mark_candidate_evaluation_order_submitted(
        self,
        ticker: str,
        trade_date: date,
        order_id: str | None = None,
    ) -> None:
        self._ensure_candidate_evaluations_table()
        self._execute(
            """
            UPDATE candidate_evaluations
            SET order_submitted = 1,
                order_id = COALESCE(?, order_id),
                final_decision = 'ORDER_SUBMITTED',
                updated_at = SYSUTCDATETIME()
            WHERE id = (
                SELECT TOP (1) id
                FROM candidate_evaluations
                WHERE symbol = ?
                  AND trading_date = ?
                  AND buy_allowed = 1
                ORDER BY evaluation_time DESC, id DESC
            )
            """,
            (order_id, ticker, trade_date),
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
        strategy_metadata = strategy_metadata_from_settings(settings)
        settings_json = strategy_metadata.settings_snapshot_json
        self._execute(
            """
            IF EXISTS (SELECT 1 FROM daily_run_summary WHERE trade_date = ? AND is_mock = 1)
            BEGIN
                UPDATE daily_run_summary
                SET candidate_selection_mode = ?,
                    settings_json = ?,
                    strategy_version = ?,
                    settings_snapshot_hash = ?,
                    settings_snapshot_json = ?,
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
                     strategy_version, settings_snapshot_hash, settings_snapshot_json,
                     realized_profit_usd, realized_profit_rate, eod_sell_count,
                     cancelled_order_count, buy_fill_count, sell_fill_count, is_mock)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 0), COALESCE(?, 0), ?, ?, 1)
            END
            """,
            (
                trade_date,
                settings.candidate_selection_mode,
                settings_json,
                strategy_metadata.strategy_version,
                strategy_metadata.settings_snapshot_hash,
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
                strategy_metadata.strategy_version,
                strategy_metadata.settings_snapshot_hash,
                settings_json,
                realized_profit_usd,
                realized_profit_rate,
                eod_sell_count,
                cancelled_order_count,
                buy_fill_count,
                sell_fill_count,
            ),
        )

    def save_daily_trade_summary_report(self, report: DailyTradeSummaryReport) -> None:
        self._ensure_daily_trade_summary_report_table()
        self._execute(
            """
            IF EXISTS (
                SELECT 1
                FROM daily_trade_summary_report
                WHERE trade_date = ? AND mode = ?
            )
            BEGIN
                UPDATE daily_trade_summary_report
                SET strategy_version = ?,
                    settings_snapshot_hash = ?,
                    summary_json = ?,
                    summary_text = ?,
                    total_profit_usd = ?,
                    total_profit_rate = ?,
                    trade_count = ?,
                    buy_count = ?,
                    sell_count = ?,
                    win_rate = ?,
                    stop_loss_count = ?,
                    take_profit_count = ?,
                    trailing_stop_count = ?,
                    eod_count = ?,
                    sample_sufficient = ?,
                    updated_at = GETDATE()
                WHERE trade_date = ? AND mode = ?
            END
            ELSE
            BEGIN
                INSERT INTO daily_trade_summary_report
                    (trade_date, mode, strategy_version, settings_snapshot_hash,
                     summary_json, summary_text, total_profit_usd, total_profit_rate,
                     trade_count, buy_count, sell_count, win_rate, stop_loss_count,
                     take_profit_count, trailing_stop_count, eod_count, sample_sufficient)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            END
            """,
            (
                report.trade_date,
                report.mode,
                report.strategy_version,
                report.settings_snapshot_hash,
                report.summary_json,
                report.summary_text,
                report.total_profit_usd,
                report.total_profit_rate,
                report.trade_count,
                report.buy_count,
                report.sell_count,
                report.win_rate,
                report.stop_loss_count,
                report.take_profit_count,
                report.trailing_stop_count,
                report.eod_count,
                report.sample_sufficient,
                report.trade_date,
                report.mode,
                report.trade_date,
                report.mode,
                report.strategy_version,
                report.settings_snapshot_hash,
                report.summary_json,
                report.summary_text,
                report.total_profit_usd,
                report.total_profit_rate,
                report.trade_count,
                report.buy_count,
                report.sell_count,
                report.win_rate,
                report.stop_loss_count,
                report.take_profit_count,
                report.trailing_stop_count,
                report.eod_count,
                report.sample_sufficient,
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
                item.entry_reason,
                item.entry_reason_detail,
                item.is_mock,
                item.order_status,
                item.retry_count,
                item.order_qty if item.order_qty is not None else item.quantity,
                item.filled_qty,
                item.remaining_qty,
                item.avg_fill_price_usd,
                item.last_fill_time,
                item.reject_reason,
                item.actual_value,
                item.threshold_value,
                item.strategy_version,
                item.settings_snapshot_hash,
                item.settings_snapshot_json,
            )
            for item in trade_items
        ]
        self._ensure_trade_history_columns()
        self._executemany(
            """
            INSERT INTO trade_history
                (trade_date, ticker, ticker_name, order_type, order_price, exec_price,
                 entry_price, max_price_after_buy, quantity, usd_krw_rate, profit_usd,
                 profit_krw, profit_rate, exit_reason, entry_reason, entry_reason_detail, is_mock,
                 order_status, retry_count, order_qty, filled_qty, remaining_qty, avg_fill_price,
                 last_fill_time, reject_reason, actual_value, threshold_value,
                 strategy_version, settings_snapshot_hash, settings_snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                item.entry_reason,
                item.entry_reason_detail,
                item.is_mock,
                item.strategy_version,
                item.settings_snapshot_hash,
                item.settings_snapshot_json,
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
                    SET profit_usd = ?,
                        profit_rate = ?,
                        entry_reason = COALESCE(entry_reason, ?),
                        entry_reason_detail = COALESCE(entry_reason_detail, ?),
                        strategy_version = COALESCE(NULLIF(strategy_version, ''), ?),
                        settings_snapshot_hash = COALESCE(settings_snapshot_hash, ?),
                        settings_snapshot_json = COALESCE(settings_snapshot_json, ?)
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
                         fill_price, fill_amount, profit_usd, profit_rate, order_no,
                         entry_reason, entry_reason_detail, is_mock,
                         strategy_version, settings_snapshot_hash, settings_snapshot_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                END
                """,
                (
                    row[0],
                    row[1],
                    row[2],
                    row[4],
                    row[5],
                    row[6],
                    row[13],
                    row[8],
                    row[9],
                    row[11],
                    row[12],
                    row[14],
                    row[15],
                    row[16],
                    row[0],
                    row[1],
                    row[2],
                    row[4],
                    row[5],
                    row[6],
                    row[13],
                    row[0],
                    *row,
                ),
            )

    def history_fills(self, trade_date: date, limit: int = 200) -> list[tuple[Any, ...]]:
        try:
            self._ensure_fill_history_table()
            return self._query(
                """
                SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                       quantity, fill_price, fill_amount, profit_usd, profit_rate,
                       entry_reason, entry_reason_detail, strategy_version
                FROM fill_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            try:
                return self._query(
                    """
                    SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                           quantity, fill_price, fill_amount, profit_usd, profit_rate,
                           entry_reason, entry_reason_detail
                    FROM fill_history
                    WHERE trade_date = ?
                    ORDER BY created_at DESC
                    """,
                    (limit, trade_date),
                )
            except Exception:
                return []

    def save_entry_profit_snapshots(self, snapshots: Iterable[EntryProfitSnapshot]) -> None:
        rows = [
            (
                item.trade_date,
                item.ticker,
                item.ticker_name,
                item.entry_time,
                item.entry_price_usd,
                item.strategy_version,
            )
            for item in snapshots
        ]
        if not rows:
            return
        self._ensure_entry_profit_snapshot_table()
        self._executemany(
            """
            IF NOT EXISTS (
                SELECT 1
                FROM entry_profit_snapshot
                WHERE trade_date = ?
                  AND ticker = ?
                  AND ISNULL(entry_time, '') = ?
            )
            BEGIN
                INSERT INTO entry_profit_snapshot
                    (trade_date, ticker, ticker_name, entry_time, entry_price,
                     strategy_version)
                VALUES (?, ?, ?, ?, ?, ?)
            END
            """,
            [
                (
                    row[0],
                    row[1],
                    row[3],
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                )
                for row in rows
            ],
        )

    def update_entry_profit_snapshots(
        self,
        trade_date: date,
        current_prices: dict[str, float],
        now_text: str,
    ) -> None:
        if not current_prices:
            return
        self._ensure_entry_profit_snapshot_table()
        for ticker, current_price in current_prices.items():
            if current_price <= 0:
                continue
            self._execute(
                """
                UPDATE entry_profit_snapshot
                SET profit_after_5m = CASE
                        WHEN profit_after_5m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 5
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_5m
                    END,
                    profit_after_10m = CASE
                        WHEN profit_after_10m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 10
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_10m
                    END,
                    profit_after_15m = CASE
                        WHEN profit_after_15m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 15
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_15m
                    END,
                    profit_after_20m = CASE
                        WHEN profit_after_20m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 20
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_20m
                    END,
                    profit_after_30m = CASE
                        WHEN profit_after_30m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 30
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_30m
                    END,
                    profit_after_60m = CASE
                        WHEN profit_after_60m IS NULL
                         AND DATEDIFF(MINUTE, dbo._entry_datetime(trade_date, entry_time), dbo._entry_datetime(trade_date, ?)) >= 60
                        THEN (? / NULLIF(entry_price, 0)) - 1
                        ELSE profit_after_60m
                    END,
                    updated_at = GETDATE()
                WHERE trade_date = ?
                  AND ticker = ?
                  AND final_exit_reason IS NULL
                """,
                (
                    now_text,
                    current_price,
                    now_text,
                    current_price,
                    now_text,
                    current_price,
                    now_text,
                    current_price,
                    now_text,
                    current_price,
                    now_text,
                    current_price,
                    trade_date,
                    ticker,
                ),
            )

    def update_entry_profit_snapshot_finals(self, trade_date: date) -> None:
        self._ensure_entry_profit_snapshot_table()
        self._execute(
            """
            UPDATE eps
            SET final_exit_reason = sell.exit_reason,
                final_profit_rate = sell_fill.profit_rate,
                updated_at = GETDATE()
            FROM entry_profit_snapshot eps
            OUTER APPLY (
                SELECT TOP (1) created_at, exit_reason
                FROM trade_history
                WHERE trade_date = eps.trade_date
                  AND ticker = eps.ticker
                  AND order_type = 'SELL'
                  AND exit_reason IS NOT NULL
                  AND created_at >= dbo._entry_datetime(eps.trade_date, eps.entry_time)
                ORDER BY created_at ASC, id ASC
            ) sell
            OUTER APPLY (
                SELECT TOP (1) profit_rate
                FROM fill_history
                WHERE trade_date = eps.trade_date
                  AND ticker = eps.ticker
                  AND profit_rate IS NOT NULL
                  AND (
                      UPPER(side) IN ('SELL', 'S')
                      OR side LIKE N'%매도%'
                  )
                  AND dbo._entry_datetime(trade_date, fill_time) >= dbo._entry_datetime(eps.trade_date, eps.entry_time)
                ORDER BY created_at ASC, id ASC
            ) sell_fill
            WHERE eps.trade_date = ?
              AND eps.final_exit_reason IS NULL
              AND sell.exit_reason IS NOT NULL
            """,
            (trade_date,),
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

    def entry_reasons(self, trade_date: date) -> dict[str, tuple[str, str]]:
        self._ensure_trade_history_columns()
        rows = self._query(
            """
            SELECT ticker, entry_reason, entry_reason_detail
            FROM (
                SELECT ticker, entry_reason, entry_reason_detail,
                       ROW_NUMBER() OVER (
                           PARTITION BY ticker ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM trade_history
                WHERE trade_date = ?
                  AND order_type = 'BUY'
                  AND entry_reason IS NOT NULL
            ) latest
            WHERE rn = 1
            """,
            (trade_date,),
        )
        reasons: dict[str, tuple[str, str]] = {}
        for ticker, reason, detail in rows:
            key = _text(ticker).upper()
            if key and reason:
                reasons[key] = (_text(reason), _text(detail))
        return reasons

    def partial_take_profit_tickers(self, trade_date: date) -> set[str]:
        self._ensure_trade_history_columns()
        rows = self._query(
            """
            SELECT DISTINCT ticker
            FROM trade_history
            WHERE trade_date = ?
              AND order_type = 'SELL'
              AND exit_reason = 'PARTIAL_TAKE_PROFIT'
            """,
            (trade_date,),
        )
        return {_text(ticker).upper() for (ticker,) in rows if _text(ticker)}

    def last_stop_loss_at(self, trade_date: date, ticker: str):
        self._ensure_trade_history_columns()
        rows = self._query(
            """
            SELECT TOP (1) created_at
            FROM trade_history
            WHERE trade_date = ?
              AND ticker = ?
              AND order_type = 'SELL'
              AND exit_reason = 'STOP_LOSS'
            ORDER BY created_at DESC, id DESC
            """,
            (trade_date, _text(ticker).upper()),
        )
        return rows[0][0] if rows else None

    def consecutive_stop_loss_count(self, trade_date: date) -> int:
        self._ensure_trade_history_columns()
        rows = self._query(
            """
            SELECT TOP (50) exit_reason
            FROM trade_history
            WHERE trade_date = ?
              AND order_type = 'SELL'
              AND exit_reason IS NOT NULL
            ORDER BY created_at DESC, id DESC
            """,
            (trade_date,),
        )
        count = 0
        for (reason,) in rows:
            value = _text(reason).upper()
            if value == "STOP_LOSS":
                count += 1
                continue
            if value in {"TAKE_PROFIT", "PARTIAL_TAKE_PROFIT"}:
                break
        return count

    def _ensure_trade_history_columns(self) -> None:
        self._execute_statement(
            """
            IF COL_LENGTH('dbo.trade_history', 'entry_price') IS NULL
                ALTER TABLE dbo.trade_history ADD entry_price DECIMAL(10, 2) NULL

            IF COL_LENGTH('dbo.trade_history', 'ticker_name') IS NULL
                ALTER TABLE dbo.trade_history ADD ticker_name NVARCHAR(100) NULL

            IF COL_LENGTH('dbo.trade_history', 'entry_reason') IS NULL
                ALTER TABLE dbo.trade_history ADD entry_reason VARCHAR(80) NULL

            IF COL_LENGTH('dbo.trade_history', 'entry_reason_detail') IS NULL
                ALTER TABLE dbo.trade_history ADD entry_reason_detail NVARCHAR(500) NULL

            IF COL_LENGTH('dbo.trade_history', 'order_status') IS NULL
                ALTER TABLE dbo.trade_history ADD order_status VARCHAR(40) NULL

            IF COL_LENGTH('dbo.trade_history', 'retry_count') IS NULL
                ALTER TABLE dbo.trade_history ADD retry_count INT NULL

            IF COL_LENGTH('dbo.trade_history', 'order_qty') IS NULL
                ALTER TABLE dbo.trade_history ADD order_qty INT NULL

            IF COL_LENGTH('dbo.trade_history', 'filled_qty') IS NULL
                ALTER TABLE dbo.trade_history ADD filled_qty INT NULL

            IF COL_LENGTH('dbo.trade_history', 'remaining_qty') IS NULL
                ALTER TABLE dbo.trade_history ADD remaining_qty INT NULL

            IF COL_LENGTH('dbo.trade_history', 'avg_fill_price') IS NULL
                ALTER TABLE dbo.trade_history ADD avg_fill_price DECIMAL(10, 2) NULL

            IF COL_LENGTH('dbo.trade_history', 'last_fill_time') IS NULL
                ALTER TABLE dbo.trade_history ADD last_fill_time VARCHAR(20) NULL

            IF COL_LENGTH('dbo.trade_history', 'reject_reason') IS NULL
                ALTER TABLE dbo.trade_history ADD reject_reason VARCHAR(80) NULL

            IF COL_LENGTH('dbo.trade_history', 'actual_value') IS NULL
                ALTER TABLE dbo.trade_history ADD actual_value FLOAT NULL

            IF COL_LENGTH('dbo.trade_history', 'threshold_value') IS NULL
                ALTER TABLE dbo.trade_history ADD threshold_value FLOAT NULL

            IF COL_LENGTH('dbo.trade_history', 'strategy_version') IS NULL
                ALTER TABLE dbo.trade_history ADD strategy_version VARCHAR(60) NULL

            IF COL_LENGTH('dbo.trade_history', 'settings_snapshot_hash') IS NULL
                ALTER TABLE dbo.trade_history ADD settings_snapshot_hash VARCHAR(64) NULL

            IF COL_LENGTH('dbo.trade_history', 'settings_snapshot_json') IS NULL
                ALTER TABLE dbo.trade_history ADD settings_snapshot_json NVARCHAR(MAX) NULL
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
                    entry_reason VARCHAR(80),
                    entry_reason_detail NVARCHAR(500),
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

            IF COL_LENGTH('dbo.fill_history', 'entry_reason') IS NULL
                ALTER TABLE dbo.fill_history ADD entry_reason VARCHAR(80) NULL

            IF COL_LENGTH('dbo.fill_history', 'entry_reason_detail') IS NULL
                ALTER TABLE dbo.fill_history ADD entry_reason_detail NVARCHAR(500) NULL

            IF COL_LENGTH('dbo.fill_history', 'strategy_version') IS NULL
                ALTER TABLE dbo.fill_history ADD strategy_version VARCHAR(60) NULL

            IF COL_LENGTH('dbo.fill_history', 'settings_snapshot_hash') IS NULL
                ALTER TABLE dbo.fill_history ADD settings_snapshot_hash VARCHAR(64) NULL

            IF COL_LENGTH('dbo.fill_history', 'settings_snapshot_json') IS NULL
                ALTER TABLE dbo.fill_history ADD settings_snapshot_json NVARCHAR(MAX) NULL

            EXEC(N'
            UPDATE dbo.fill_history
            SET trade_date = fill_date
            WHERE trade_date IS NULL
            ')
            """,
        )

    def _ensure_entry_profit_snapshot_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.entry_profit_snapshot', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.entry_profit_snapshot (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    ticker VARCHAR(10) NOT NULL,
                    ticker_name NVARCHAR(100),
                    entry_time VARCHAR(8) NOT NULL,
                    entry_price DECIMAL(12, 4) NOT NULL,
                    profit_after_5m DECIMAL(12, 6),
                    profit_after_10m DECIMAL(12, 6),
                    profit_after_15m DECIMAL(12, 6),
                    profit_after_20m DECIMAL(12, 6),
                    profit_after_30m DECIMAL(12, 6),
                    profit_after_60m DECIMAL(12, 6),
                    final_exit_reason VARCHAR(80),
                    final_profit_rate DECIMAL(12, 6),
                    strategy_version VARCHAR(60),
                    created_at DATETIME DEFAULT GETDATE(),
                    updated_at DATETIME DEFAULT GETDATE()
                );
            END

            IF OBJECT_ID(N'dbo._entry_datetime', N'FN') IS NULL
            EXEC(N'
                CREATE FUNCTION dbo._entry_datetime(@trade_date DATE, @time_text VARCHAR(8))
                RETURNS DATETIME
                AS
                BEGIN
                    DECLARE @base DATETIME = CAST(@trade_date AS DATETIME)
                    DECLARE @hour INT = TRY_CONVERT(INT, LEFT(ISNULL(@time_text, ''''), 2))
                    DECLARE @minute INT = TRY_CONVERT(INT, SUBSTRING(ISNULL(@time_text, ''''), 4, 2))
                    DECLARE @second INT = TRY_CONVERT(INT, SUBSTRING(ISNULL(@time_text, ''''), 7, 2))
                    IF @hour IS NULL OR @minute IS NULL OR @second IS NULL
                        RETURN @base
                    IF @hour < 12
                        SET @base = DATEADD(DAY, 1, @base)
                    RETURN DATEADD(SECOND, @second, DATEADD(MINUTE, @minute, DATEADD(HOUR, @hour, @base)))
                END
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
                    order_status VARCHAR(40),
                    order_qty INT,
                    filled_qty INT,
                    remaining_qty INT,
                    avg_fill_price DECIMAL(12, 2),
                    last_fill_time VARCHAR(20),
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.order_snapshot', 'trade_date') IS NULL
                ALTER TABLE dbo.order_snapshot ADD trade_date DATE NULL

            IF COL_LENGTH('dbo.order_snapshot', 'order_status') IS NULL
                ALTER TABLE dbo.order_snapshot ADD order_status VARCHAR(40) NULL

            IF COL_LENGTH('dbo.order_snapshot', 'order_qty') IS NULL
                ALTER TABLE dbo.order_snapshot ADD order_qty INT NULL

            IF COL_LENGTH('dbo.order_snapshot', 'filled_qty') IS NULL
                ALTER TABLE dbo.order_snapshot ADD filled_qty INT NULL

            IF COL_LENGTH('dbo.order_snapshot', 'remaining_qty') IS NULL
                ALTER TABLE dbo.order_snapshot ADD remaining_qty INT NULL

            IF COL_LENGTH('dbo.order_snapshot', 'avg_fill_price') IS NULL
                ALTER TABLE dbo.order_snapshot ADD avg_fill_price DECIMAL(12, 2) NULL

            IF COL_LENGTH('dbo.order_snapshot', 'last_fill_time') IS NULL
                ALTER TABLE dbo.order_snapshot ADD last_fill_time VARCHAR(20) NULL

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
                    symbol VARCHAR(10),
                    ticker_name NVARCHAR(100),
                    reject_reason VARCHAR(80),
                    actual_value FLOAT,
                    threshold_value FLOAT,
                    created_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.bot_log', 'trade_date') IS NULL
                ALTER TABLE dbo.bot_log ADD trade_date DATE NULL

            IF COL_LENGTH('dbo.bot_log', 'symbol') IS NULL
                ALTER TABLE dbo.bot_log ADD symbol VARCHAR(10) NULL

            IF COL_LENGTH('dbo.bot_log', 'ticker_name') IS NULL
                ALTER TABLE dbo.bot_log ADD ticker_name NVARCHAR(100) NULL

            IF COL_LENGTH('dbo.bot_log', 'reject_reason') IS NULL
                ALTER TABLE dbo.bot_log ADD reject_reason VARCHAR(80) NULL

            IF COL_LENGTH('dbo.bot_log', 'actual_value') IS NULL
                ALTER TABLE dbo.bot_log ADD actual_value FLOAT NULL

            IF COL_LENGTH('dbo.bot_log', 'threshold_value') IS NULL
                ALTER TABLE dbo.bot_log ADD threshold_value FLOAT NULL

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
                    strategy_version VARCHAR(60),
                    settings_snapshot_hash VARCHAR(64),
                    settings_snapshot_json NVARCHAR(MAX),
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

            IF COL_LENGTH('dbo.daily_run_summary', 'strategy_version') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD strategy_version VARCHAR(60) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'settings_snapshot_hash') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD settings_snapshot_hash VARCHAR(64) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'settings_snapshot_json') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD settings_snapshot_json NVARCHAR(MAX) NULL

            IF COL_LENGTH('dbo.daily_run_summary', 'is_mock') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD is_mock BIT DEFAULT 1

            IF COL_LENGTH('dbo.daily_run_summary', 'updated_at') IS NULL
                ALTER TABLE dbo.daily_run_summary ADD updated_at DATETIME DEFAULT GETDATE()
            """,
        )

    def _ensure_daily_trade_summary_report_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.daily_trade_summary_report', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.daily_trade_summary_report (
                    id INT IDENTITY PRIMARY KEY,
                    trade_date DATE NOT NULL,
                    mode VARCHAR(10) NOT NULL,
                    strategy_version VARCHAR(60),
                    settings_snapshot_hash VARCHAR(64),
                    summary_json NVARCHAR(MAX),
                    summary_text NVARCHAR(MAX),
                    total_profit_usd DECIMAL(14, 2),
                    total_profit_rate DECIMAL(12, 4),
                    trade_count INT DEFAULT 0,
                    buy_count INT DEFAULT 0,
                    sell_count INT DEFAULT 0,
                    win_rate DECIMAL(8, 4),
                    stop_loss_count INT DEFAULT 0,
                    take_profit_count INT DEFAULT 0,
                    trailing_stop_count INT DEFAULT 0,
                    eod_count INT DEFAULT 0,
                    sample_sufficient BIT DEFAULT 0,
                    created_at DATETIME DEFAULT GETDATE(),
                    updated_at DATETIME DEFAULT GETDATE()
                );
            END

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'strategy_version') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD strategy_version VARCHAR(60) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'settings_snapshot_hash') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD settings_snapshot_hash VARCHAR(64) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'summary_json') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD summary_json NVARCHAR(MAX) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'summary_text') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD summary_text NVARCHAR(MAX) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'total_profit_usd') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD total_profit_usd DECIMAL(14, 2) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'total_profit_rate') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD total_profit_rate DECIMAL(12, 4) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'trade_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD trade_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'buy_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD buy_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'sell_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD sell_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'win_rate') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD win_rate DECIMAL(8, 4) NULL

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'stop_loss_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD stop_loss_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'take_profit_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD take_profit_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'trailing_stop_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD trailing_stop_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'eod_count') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD eod_count INT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'sample_sufficient') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD sample_sufficient BIT DEFAULT 0

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'created_at') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD created_at DATETIME DEFAULT GETDATE()

            IF COL_LENGTH('dbo.daily_trade_summary_report', 'updated_at') IS NULL
                ALTER TABLE dbo.daily_trade_summary_report ADD updated_at DATETIME DEFAULT GETDATE()

            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE name = 'UQ_daily_trade_summary_report_trade_date_mode'
                  AND object_id = OBJECT_ID(N'dbo.daily_trade_summary_report')
            )
                CREATE UNIQUE INDEX UQ_daily_trade_summary_report_trade_date_mode
                ON dbo.daily_trade_summary_report (trade_date, mode)
            """,
        )

    def _ensure_candidate_evaluations_table(self) -> None:
        self._execute_statement(
            """
            IF OBJECT_ID(N'dbo.candidate_evaluations', N'U') IS NULL
            BEGIN
                CREATE TABLE dbo.candidate_evaluations (
                    id BIGINT IDENTITY PRIMARY KEY,
                    run_id NVARCHAR(64) NULL,
                    evaluation_time DATETIME2 NOT NULL,
                    trading_date DATE NULL,
                    source NVARCHAR(64) NULL,
                    symbol NVARCHAR(32) NOT NULL,
                    symbol_name NVARCHAR(128) NULL,
                    current_price DECIMAL(18, 4) NULL,
                    volume BIGINT NULL,
                    dollar_volume DECIMAL(20, 4) NULL,
                    price_change_percent DECIMAL(10, 4) NULL,
                    opening_gap_percent DECIMAL(10, 4) NULL,
                    price_rank INT NULL,
                    volume_rank INT NULL,
                    relaxation_level INT NULL,
                    min_price DECIMAL(18, 4) NULL,
                    max_price DECIMAL(18, 4) NULL,
                    price_change_top INT NULL,
                    volume_top INT NULL,
                    min_selection_score DECIMAL(10, 4) NULL,
                    min_opening_price_change_percent DECIMAL(10, 4) NULL,
                    min_volume_ratio DECIMAL(10, 4) NULL,
                    max_opening_gap_percent DECIMAL(10, 4) NULL,
                    selection_score DECIMAL(10, 4) NULL,
                    soft_score_adjustment DECIMAL(10, 4) NULL,
                    final_score DECIMAL(10, 4) NULL,
                    overheat_condition_mode NVARCHAR(32) NULL,
                    breakout_close_condition_mode NVARCHAR(32) NULL,
                    volume_increase_condition_mode NVARCHAR(32) NULL,
                    vwap_ma20_condition_mode NVARCHAR(32) NULL,
                    vwap_ma20_condition_type NVARCHAR(32) NULL,
                    pullback_rebreak_condition_mode NVARCHAR(32) NULL,
                    overheat_pass BIT NULL,
                    breakout_close_pass BIT NULL,
                    volume_increase_pass BIT NULL,
                    vwap_pass BIT NULL,
                    ma20_pass BIT NULL,
                    vwap_ma20_pass BIT NULL,
                    pullback_rebreak_pass BIT NULL,
                    final_score_pass BIT NULL,
                    buy_allowed BIT NOT NULL DEFAULT 0,
                    order_submitted BIT NOT NULL DEFAULT 0,
                    order_id NVARCHAR(128) NULL,
                    buy_block_reason NVARCHAR(256) NULL,
                    buy_block_reasons NVARCHAR(MAX) NULL,
                    hard_filter_failed_count INT NULL,
                    soft_condition_failed_count INT NULL,
                    final_decision NVARCHAR(64) NULL,
                    settings_snapshot_json NVARCHAR(MAX) NULL,
                    condition_result_json NVARCHAR(MAX) NULL,
                    raw_candidate_json NVARCHAR(MAX) NULL,
                    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                    updated_at DATETIME2 NULL
                );
            END

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_time' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_time ON dbo.candidate_evaluations (evaluation_time)

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_symbol_time' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_symbol_time ON dbo.candidate_evaluations (symbol, evaluation_time)

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_trading_date' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_trading_date ON dbo.candidate_evaluations (trading_date)

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_buy_allowed' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_buy_allowed ON dbo.candidate_evaluations (buy_allowed)

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_order_submitted' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_order_submitted ON dbo.candidate_evaluations (order_submitted)

            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_candidate_evaluations_run_id' AND object_id = OBJECT_ID('dbo.candidate_evaluations'))
                CREATE INDEX IX_candidate_evaluations_run_id ON dbo.candidate_evaluations (run_id)
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


# 모니터 조회 저장소: 화면 API가 사용할 최신값과 날짜별 이력을 조회한다.
class SqlServerMonitorRepository:
    """모니터 화면이 사용할 최신 스냅샷과 날짜별 이력을 DB에서 조회한다."""

    def __init__(self, connect: Callable[[], Connection]) -> None:
        self.connect = connect

    def _ensure_trade_history_columns(self) -> None:
        # 모니터 조회는 스키마를 변경하지 않고, 기존 조회 쿼리의 fallback만 사용한다.
        return None

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

    def candidate_snapshot_status(self) -> tuple[Any, ...]:
        try:
            date_rows = self._query(
                """
                SELECT TOP (30) CONVERT(varchar(10), trade_date, 23) AS trade_date
                FROM (
                    SELECT trade_date FROM daily_target
                    UNION ALL
                    SELECT trade_date FROM listed_target_snapshot
                ) candidate_rows
                GROUP BY CONVERT(varchar(10), trade_date, 23)
                ORDER BY CONVERT(varchar(10), trade_date, 23) DESC
                """,
                (),
            )
            latest_date = str(date_rows[0][0]) if date_rows and date_rows[0][0] else ""
            latest_count = 0
            if latest_date:
                count_rows = self._query(
                    """
                    SELECT COUNT(DISTINCT ticker)
                    FROM (
                        SELECT trade_date, ticker FROM daily_target
                        UNION ALL
                        SELECT trade_date, ticker FROM listed_target_snapshot
                    ) candidate_rows
                    WHERE CONVERT(varchar(10), trade_date, 23) = ?
                    """,
                    (latest_date,),
                )
                latest_count = int(_number(count_rows[0][0])) if count_rows else 0
            status_rows = self._query(
                """
                SELECT TOP (1) log_level, message
                FROM bot_log
                WHERE module = 'screening'
                  AND (
                       message LIKE 'CANDIDATE_SNAPSHOT_%'
                       OR message LIKE N'%후보%DB%저장%'
                       OR message LIKE N'%후보 0건%'
                  )
                ORDER BY created_at DESC, id DESC
                """,
                (),
            )
        except Exception:
            return (0, "", 0, "UNKNOWN", "후보 스냅샷 상태를 조회하지 못했습니다.")
        status = status_rows[0][0] if status_rows else ""
        message = status_rows[0][1] if status_rows else ""
        return (len(date_rows), latest_date, latest_count, status, message)

    def recent_trading_stats(self, limit: int = 30) -> tuple[Any, ...]:
        try:
            rows = self._query(
                """
                SELECT
                    COUNT(1) AS total_trading_days,
                    COALESCE(SUM(candidate_day), 0) AS candidate_days,
                    COALESCE(SUM(scoring_day), 0) AS scoring_days,
                    COALESCE(SUM(strict_filter_day), 0) AS strict_filter_days,
                    COALESCE(SUM(selected_day), 0) AS selected_days
                FROM (
                    SELECT
                        d.trade_date,
                        CASE WHEN EXISTS (
                        SELECT 1 FROM daily_target dt
                        WHERE dt.trade_date = d.trade_date
                        ) THEN 1 ELSE 0 END AS candidate_day,
                        CASE WHEN EXISTS (
                            SELECT 1 FROM scoring sc
                            WHERE sc.trade_date = d.trade_date
                        ) THEN 1 ELSE 0 END AS scoring_day,
                        CASE WHEN EXISTS (
                            SELECT 1 FROM bot_log bl
                            WHERE bl.trade_date = d.trade_date
                              AND bl.message LIKE '%STRICT_FILTER_NO_CANDIDATES%'
                        ) THEN 1 ELSE 0 END AS strict_filter_day,
                        CASE WHEN (
                            EXISTS (
                                SELECT 1 FROM scoring selected_score
                                WHERE selected_score.trade_date = d.trade_date
                                  AND selected_score.is_selected = 1
                            )
                            OR EXISTS (
                                SELECT 1 FROM bot_log selected_log
                                WHERE selected_log.trade_date = d.trade_date
                                  AND selected_log.message LIKE '%final_selected_count=[1-9]%'
                            )
                        ) THEN 1 ELSE 0 END AS selected_day
                    FROM (
                        SELECT TOP (?) trade_date
                        FROM (
                            SELECT trade_date FROM daily_target WHERE trade_date IS NOT NULL
                            UNION
                            SELECT trade_date FROM listed_target_snapshot WHERE trade_date IS NOT NULL
                            UNION
                            SELECT trade_date FROM scoring WHERE trade_date IS NOT NULL
                            UNION
                            SELECT trade_date FROM bot_log WHERE trade_date IS NOT NULL
                            UNION
                            SELECT trade_date FROM daily_run_summary WHERE trade_date IS NOT NULL
                        ) raw_days
                        GROUP BY trade_date
                        ORDER BY trade_date DESC
                    ) d
                ) stats
                """,
                (limit,),
            )
        except Exception:
            return (0, 0, 0, 0, 0)
        return rows[0] if rows else (0, 0, 0, 0, 0)

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
            # 최신 계좌 테이블이 아직 없거나 조회 실패하면 일별 스냅샷으로 fallback 한다.
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

    def latest_recheck_evaluations(
        self,
        trade_date: date | None = None,
    ) -> list[tuple[Any, ...]]:
        target_date = trade_date or current_trade_date()
        try:
            return self._query(
                """
                SELECT symbol, source, evaluation_time, selection_score,
                       soft_score_adjustment, final_score, buy_allowed,
                       order_submitted, buy_block_reason, buy_block_reasons,
                       final_decision, condition_result_json
                FROM (
                    SELECT symbol, source, evaluation_time, selection_score,
                           soft_score_adjustment, final_score, buy_allowed,
                           order_submitted, buy_block_reason, buy_block_reasons,
                           final_decision, condition_result_json, id,
                           ROW_NUMBER() OVER (
                               PARTITION BY symbol
                               ORDER BY evaluation_time DESC, id DESC
                           ) AS rn
                    FROM candidate_evaluations
                    WHERE trading_date = ?
                      AND source IN ('fixed_recheck', 'hybrid_recheck', 'dry_run')
                ) latest
                WHERE rn = 1
                ORDER BY evaluation_time DESC, symbol
                """,
                (target_date,),
            )
        except Exception:
            return []

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
        try:
            return self._query(
                """
                SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                       order_type, order_price, quantity, exit_reason,
                       profit_usd, profit_rate, entry_reason, entry_reason_detail,
                       strategy_version
                FROM trade_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, target_date),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                       order_type, order_price, quantity, exit_reason,
                       profit_usd, profit_rate, entry_reason, entry_reason_detail
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
                       quantity, fill_price, fill_amount, profit_usd, profit_rate,
                       entry_reason, entry_reason_detail, strategy_version
                FROM fill_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, target_date),
            )
        except Exception:
            try:
                return self._query(
                    """
                    SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                           quantity, fill_price, fill_amount, profit_usd, profit_rate,
                           entry_reason, entry_reason_detail
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
            # 최신 후보 스냅샷이 없으면 기존 daily_target 이력 조회로 fallback 한다.
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
        try:
            return self._query(
                """
                SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                       order_type, order_price, quantity, exit_reason,
                       profit_usd, profit_rate, entry_reason, entry_reason_detail,
                       strategy_version
                FROM trade_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return self._query(
                """
                SELECT TOP (?) trade_date, created_at, ticker, ticker_name,
                       order_type, order_price, quantity, exit_reason,
                       profit_usd, profit_rate, entry_reason, entry_reason_detail
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
                       quantity, fill_price, fill_amount, profit_usd, profit_rate,
                       entry_reason, entry_reason_detail, strategy_version
                FROM fill_history
                WHERE trade_date = ?
                ORDER BY created_at DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            try:
                return self._query(
                    """
                    SELECT TOP (?) fill_date, fill_time, ticker, ticker_name, side,
                           quantity, fill_price, fill_amount, profit_usd, profit_rate,
                           entry_reason, entry_reason_detail
                    FROM fill_history
                    WHERE trade_date = ?
                    ORDER BY created_at DESC
                    """,
                    (limit, trade_date),
                )
            except Exception:
                return []

    def latest_entry_profit_snapshots(self, limit: int = 100) -> list[tuple[Any, ...]]:
        return self.history_entry_profit_snapshots(current_trade_date(), limit)

    def history_entry_profit_snapshots(
        self,
        trade_date: date,
        limit: int = 200,
    ) -> list[tuple[Any, ...]]:
        try:
            return self._query(
                """
                SELECT TOP (?) trade_date, ticker, ticker_name, entry_time, entry_price,
                       profit_after_5m, profit_after_10m, profit_after_15m,
                       profit_after_20m, profit_after_30m, profit_after_60m,
                       final_exit_reason, final_profit_rate, strategy_version
                FROM entry_profit_snapshot
                WHERE trade_date = ?
                ORDER BY dbo._entry_datetime(trade_date, entry_time) DESC, id DESC
                """,
                (limit, trade_date),
            )
        except Exception:
            return []

    def entry_reason_performance(self, limit: int = 50) -> list[tuple[Any, ...]]:
        try:
            rows = self._query(
                """
                SELECT entry_reason, profit_usd, profit_rate
                FROM fill_history
                WHERE profit_usd IS NOT NULL
                  AND entry_reason IS NOT NULL
                  AND entry_reason <> ''
                  AND (side LIKE N'%매도%' OR UPPER(side) IN ('SELL', 'S'))
                ORDER BY created_at DESC
                """,
                (),
            )
        except Exception:
            return []
        stats: dict[str, dict[str, float]] = {}
        for reason, profit_usd, profit_rate in rows:
            tokens = [item.strip() for item in str(reason or "").split("+") if item.strip()]
            for token in tokens:
                item = stats.setdefault(
                    token,
                    {"count": 0.0, "profit": 0.0, "rate": 0.0, "wins": 0.0},
                )
                profit = _number(profit_usd)
                item["count"] += 1
                item["profit"] += profit
                item["rate"] += _number(profit_rate)
                if profit > 0:
                    item["wins"] += 1
        ranked = sorted(
            stats.items(),
            key=lambda pair: (pair[1]["profit"], pair[1]["rate"]),
            reverse=True,
        )
        return [
            (
                reason,
                int(item["count"]),
                item["profit"],
                item["rate"] / item["count"] if item["count"] else 0.0,
                item["wins"] / item["count"] if item["count"] else 0.0,
            )
            for reason, item in ranked[:limit]
        ]

    def closed_trade_analysis(self, limit: int = 500) -> list[tuple[Any, ...]]:
        self._ensure_trade_history_columns()
        try:
            return self._query(
                """
                SELECT TOP (?) buy.created_at AS entry_at,
                       sell.created_at AS exit_at,
                       sell.ticker,
                       sell.ticker_name,
                       COALESCE(sell.entry_reason, buy.entry_reason, ''),
                       COALESCE(sell.entry_reason_detail, buy.entry_reason_detail, ''),
                       COALESCE(sell.exit_reason, 'UNKNOWN'),
                       CASE
                           WHEN buy.created_at IS NULL THEN 0
                           ELSE DATEDIFF(MINUTE, buy.created_at, sell.created_at)
                       END,
                       sell.profit_rate,
                       sell.profit_usd,
                       COALESCE(sell.strategy_version, buy.strategy_version, '')
                FROM trade_history sell
                OUTER APPLY (
                    SELECT TOP (1) created_at, entry_reason, entry_reason_detail, strategy_version
                    FROM trade_history buy
                    WHERE buy.ticker = sell.ticker
                      AND buy.created_at <= sell.created_at
                      AND (
                          UPPER(buy.order_type) IN ('BUY', 'B')
                          OR buy.order_type LIKE N'%매수%'
                      )
                    ORDER BY buy.created_at DESC, buy.id DESC
                ) buy
                WHERE sell.profit_usd IS NOT NULL
                  AND (
                      UPPER(sell.order_type) IN ('SELL', 'S')
                      OR sell.order_type LIKE N'%매도%'
                  )
                ORDER BY sell.created_at DESC, sell.id DESC
                """,
                (limit,),
            )
        except Exception:
            return []

    def history_logs(self, trade_date: date) -> list[tuple[Any, ...]]:
        return self._query(
            """
            SELECT created_at, log_level, message
            FROM bot_log
            WHERE trade_date = ?
            ORDER BY created_at DESC
            """,
            (trade_date,),
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

    def daily_trade_summary_reports(
        self,
        mode: str | None = None,
        limit: int = 30,
    ) -> list[tuple[Any, ...]]:
        mode_filter = _text(mode).lower()
        if mode_filter not in {"mock", "real"}:
            mode_filter = ""
        limit_value = max(1, min(int(_number(limit) or 30), 100))
        try:
            return self._query(
                f"""
                SELECT TOP ({limit_value}) trade_date, mode, strategy_version,
                       total_profit_usd, total_profit_rate, trade_count,
                       buy_count, sell_count, win_rate, stop_loss_count,
                       take_profit_count, CAST(NULL AS INT) AS partial_take_profit_count,
                       trailing_stop_count, eod_count, sample_sufficient,
                       summary_json, updated_at
                FROM daily_trade_summary_report
                WHERE (? = '' OR mode = ?)
                ORDER BY trade_date DESC, updated_at DESC, id DESC
                """,
                (mode_filter, mode_filter),
            )
        except Exception:
            return []

    def daily_trade_summary_report_detail(
        self,
        trade_date: date,
        mode: str,
    ) -> tuple[Any, ...] | None:
        mode_filter = _text(mode).lower()
        if mode_filter not in {"mock", "real"}:
            mode_filter = "mock"
        try:
            rows = self._query(
                """
                SELECT TOP (1) trade_date, mode, strategy_version,
                       settings_snapshot_hash, summary_json, summary_text,
                       total_profit_usd, total_profit_rate, trade_count,
                       buy_count, sell_count, win_rate, stop_loss_count,
                       take_profit_count, CAST(NULL AS INT) AS partial_take_profit_count,
                       trailing_stop_count, eod_count, sample_sufficient,
                       created_at, updated_at
                FROM daily_trade_summary_report
                WHERE trade_date = ?
                  AND mode = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (trade_date, mode_filter),
            )
        except Exception:
            return None
        return rows[0] if rows else None

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


def _order_snapshot_row(
    item: dict[str, str],
    trade_date: date,
    is_mock: bool,
) -> tuple[Any, ...]:
    quantity = int(_number(item.get("quantity")))
    unfilled = int(_number(item.get("unfilled")))
    filled = max(0, quantity - unfilled)
    status = "FILLED" if quantity > 0 and unfilled == 0 else "REQUESTED"
    if filled > 0 and unfilled > 0:
        status = "PARTIALLY_FILLED"
    price = _number(item.get("price"))
    time_text = _text(item.get("time"))
    return (
        trade_date,
        trade_date,
        time_text,
        _text(item.get("ticker")),
        _text(item.get("name")),
        _text(item.get("side")),
        quantity,
        price,
        unfilled,
        _text(item.get("orderNo")),
        is_mock,
        status,
        quantity,
        filled,
        unfilled,
        price if filled > 0 else None,
        time_text if filled > 0 else "",
    )


def _candidate_evaluation_row(item: CandidateEvaluation) -> tuple[Any, ...]:
    return (
        item.run_id,
        item.evaluation_time,
        item.trading_date,
        item.source,
        item.symbol,
        item.symbol_name,
        item.current_price,
        item.volume,
        item.dollar_volume,
        item.price_change_percent,
        item.opening_gap_percent,
        item.price_rank,
        item.volume_rank,
        item.relaxation_level,
        item.min_price,
        item.max_price,
        item.price_change_top,
        item.volume_top,
        item.min_selection_score,
        item.min_opening_price_change_percent,
        item.min_volume_ratio,
        item.max_opening_gap_percent,
        item.selection_score,
        item.soft_score_adjustment,
        item.final_score,
        item.overheat_condition_mode,
        item.breakout_close_condition_mode,
        item.volume_increase_condition_mode,
        item.vwap_ma20_condition_mode,
        item.vwap_ma20_condition_type,
        item.pullback_rebreak_condition_mode,
        _bit(item.overheat_pass),
        _bit(item.breakout_close_pass),
        _bit(item.volume_increase_pass),
        _bit(item.vwap_pass),
        _bit(item.ma20_pass),
        _bit(item.vwap_ma20_pass),
        _bit(item.pullback_rebreak_pass),
        _bit(item.final_score_pass),
        _bit(item.buy_allowed),
        _bit(item.order_submitted),
        item.order_id,
        item.buy_block_reason,
        item.buy_block_reasons,
        item.hard_filter_failed_count,
        item.soft_condition_failed_count,
        item.final_decision,
        item.settings_snapshot_json,
        item.condition_result_json,
        item.raw_candidate_json,
    )


def _bit(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


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
    return settings_snapshot(settings)
