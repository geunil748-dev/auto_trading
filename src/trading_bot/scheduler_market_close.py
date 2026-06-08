from __future__ import annotations

from trading_bot.config import TradingSettings, load_notification_settings, load_settings
from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.database import pyodbc_connect_factory
from trading_bot.fill_persistence import fill_records_from_monitor_rows
from trading_bot.notifications import (
    send_alert_telegram_message,
    send_market_close_done,
)
from trading_bot.repositories import SqlServerDailyRepository, SqlServerMonitorRepository
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.trade_fill_notifications import send_market_close_report_from_records
from trading_bot.trading_date import current_trade_date


def save_daily_run_summary(
    settings: TradingSettings,
    eod_sell_count: int | None,
    cancelled_order_count: int | None,
) -> None:
    try:
        connect = pyodbc_connect_factory()
        monitor_repository = SqlServerMonitorRepository(connect)
        daily_repository = SqlServerDailyRepository(connect)
        trade_date = current_trade_date()
        buy_count, sell_count = monitor_repository.history_fill_counts(trade_date)
        daily_repository.save_daily_run_summary(
            trade_date,
            settings,
            monitor_repository.history_realized_profit(trade_date),
            monitor_repository.history_realized_profit_rate(trade_date),
            eod_sell_count,
            cancelled_order_count,
            buy_count,
            sell_count,
        )
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "summary",
            f"DAILY_RUN_SUMMARY_SAVE_FAILED: {safe_exception_summary(exc)}",
            reject_reason="DAILY_RUN_SUMMARY_SAVE_FAILED",
        )
        return


def save_daily_trade_summary_report() -> None:
    try:
        generate_daily_trade_summary(trade_date=current_trade_date(), mode="mock")
    except Exception as exc:
        log_daily_trade_summary_failure(exc)


def log_daily_trade_summary_failure(exc: Exception) -> None:
    safe_scheduler_log(
        "WARNING",
        "summary",
        f"SUMMARY_REPORT_SAVE_FAILED: {safe_exception_summary(exc)}",
        reject_reason="SUMMARY_REPORT_SAVE_FAILED",
    )


def send_market_close_notice() -> None:
    try:
        send_market_close_done(load_notification_settings())
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "notification",
            f"MARKET_CLOSE_NOTICE_FAILED: {safe_exception_summary(exc)}",
            reject_reason="MARKET_CLOSE_NOTICE_FAILED",
        )
        return


def send_market_close_report(state: dict[str, object]) -> None:
    fills = state.get("fills", [])
    holdings = state.get("holdings", [])
    if not isinstance(fills, list):
        return
    try:
        notification_settings = load_notification_settings()
        repository = SqlServerDailyRepository(pyodbc_connect_factory())
        trade_date = current_trade_date()
        records = fill_records_from_monitor_rows(
            fills,
            repository.sell_entry_prices(trade_date),
            repository.entry_reasons(trade_date),
            settings=load_settings(),
        )
        send_market_close_report_from_records(
            records,
            holdings if isinstance(holdings, list) else [],
            sender=lambda message: send_alert_telegram_message(
                message,
                notification_settings,
            ),
        )
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "notification",
            f"MARKET_CLOSE_REPORT_FAILED: {safe_exception_summary(exc)}",
            reject_reason="MARKET_CLOSE_REPORT_FAILED",
        )
        return
