from __future__ import annotations

import os
from pathlib import Path

from trading_bot.config import TradingSettings, load_notification_settings, load_settings
from trading_bot.daily_trade_summary import generate_daily_trade_summary
from trading_bot.database import pyodbc_connect_factory
from trading_bot.fill_persistence import fill_records_from_monitor_rows
from trading_bot.notifications import (
    send_alert_telegram_message,
    send_market_close_done,
)
from trading_bot.performance_digest import (
    DEFAULT_DATA_DIGEST_MAX_CHARS,
    build_strategy_review_digest,
    save_strategy_review_digest,
)
from trading_bot.repositories import SqlServerDailyRepository, SqlServerMonitorRepository
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.slack_digest_notifier import send_slack_digest_message
from trading_bot.trade_fill_notifications import send_market_close_report_from_records
from trading_bot.trading_date import current_trade_date

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STRATEGY_REVIEW_EXPORT_DIR = PROJECT_ROOT / "exports" / "strategy_reviews"
DEFAULT_STRATEGY_REVIEW_DATE_FROM = "2026-05-20"


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


def save_strategy_review_export() -> Path | None:
    try:
        trade_date = current_trade_date()
        date_from = os.getenv("STRATEGY_REVIEW_DATE_FROM", DEFAULT_STRATEGY_REVIEW_DATE_FROM)
        export_dir = Path(
            os.getenv("STRATEGY_REVIEW_EXPORT_DIR", "").strip()
            or DEFAULT_STRATEGY_REVIEW_EXPORT_DIR
        )
        output = export_dir / f"strategy_review_{trade_date:%Y%m%d}.xlsx"
        path, results, failures = export_strategy_review_workbook_with_results(
            date_from=date_from,
            date_to=trade_date,
            output=output,
            include_real=False,
        )
        safe_scheduler_log(
            "INFO",
            "summary",
            f"STRATEGY_REVIEW_EXPORT_SAVED: path={path}",
            reject_reason="STRATEGY_REVIEW_EXPORT_SAVED",
        )
        save_auto_trading_data_digest(
            strategy_review_path=path,
            sheet_results=results,
            failures=failures,
            report_date=trade_date,
            date_from=date_from,
            date_to=trade_date,
        )
        return path
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "summary",
            f"STRATEGY_REVIEW_EXPORT_FAILED: {safe_exception_summary(exc)}",
            reject_reason="STRATEGY_REVIEW_EXPORT_FAILED",
        )
        return None


def save_auto_trading_data_digest(
    *,
    strategy_review_path: Path,
    sheet_results: list[object],
    failures: list[tuple[str, str]],
    report_date,
    date_from,
    date_to,
) -> Path | None:
    if not _env_flag("AUTO_TRADING_DATA_DIGEST_ENABLED"):
        safe_scheduler_log(
            "INFO",
            "summary",
            "AUTO_TRADING_DATA_DIGEST_SKIPPED: disabled",
            reject_reason="AUTO_TRADING_DATA_DIGEST_SKIPPED",
        )
        return None
    try:
        digest = build_strategy_review_digest(
            sheet_results,
            report_date=report_date,
            date_from=date_from,
            date_to=date_to,
            source_xlsx=strategy_review_path,
            failures=failures,
            max_chars=_env_int(
                "AUTO_TRADING_DATA_DIGEST_MAX_CHARS",
                DEFAULT_DATA_DIGEST_MAX_CHARS,
            ),
        )
        digest_path = save_strategy_review_digest(digest, strategy_review_path)
        safe_scheduler_log(
            "INFO",
            "summary",
            f"AUTO_TRADING_DATA_DIGEST_SAVED: path={digest_path}",
            reject_reason="AUTO_TRADING_DATA_DIGEST_SAVED",
        )
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "summary",
            f"AUTO_TRADING_DATA_DIGEST_FAILED: {safe_exception_summary(exc)}",
            reject_reason="AUTO_TRADING_DATA_DIGEST_FAILED",
        )
        return None

    _send_auto_trading_data_digest_to_slack(digest)
    return digest_path


def _send_auto_trading_data_digest_to_slack(digest: str) -> None:
    if not _env_flag("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED"):
        return
    webhook_url = os.getenv("AUTO_TRADING_DATA_DIGEST_SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        safe_scheduler_log(
            "INFO",
            "summary",
            "AUTO_TRADING_DATA_DIGEST_SLACK_SKIPPED: missing_webhook",
            reject_reason="AUTO_TRADING_DATA_DIGEST_SLACK_SKIPPED",
        )
        return
    try:
        send_slack_digest_message(webhook_url, digest)
        safe_scheduler_log(
            "INFO",
            "summary",
            "AUTO_TRADING_DATA_DIGEST_SLACK_SENT",
            reject_reason="AUTO_TRADING_DATA_DIGEST_SLACK_SENT",
        )
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "summary",
            f"AUTO_TRADING_DATA_DIGEST_SLACK_FAILED: {safe_exception_summary(exc)}",
            reject_reason="AUTO_TRADING_DATA_DIGEST_SLACK_FAILED",
        )


def export_strategy_review_workbook(
    date_from,
    date_to=None,
    output=None,
    include_real: bool = False,
):
    from tools.export_strategy_review import export_strategy_review_workbook as export

    return export(
        date_from=date_from,
        date_to=date_to,
        output=output,
        include_real=include_real,
    )


def export_strategy_review_workbook_with_results(
    date_from,
    date_to=None,
    output=None,
    include_real: bool = False,
):
    from tools.export_strategy_review import export_strategy_review_workbook_with_results as export

    return export(
        date_from=date_from,
        date_to=date_to,
        output=output,
        include_real=include_real,
    )


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def send_market_close_report(state: dict[str, object]) -> None:
    fills = state.get("fills", [])
    holdings = state.get("holdings", [])
    if not isinstance(fills, list):
        return
    try:
        notification_settings = load_notification_settings()
        connect = pyodbc_connect_factory()
        repository = SqlServerDailyRepository(connect)
        monitor_repository = SqlServerMonitorRepository(connect)
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
            cumulative_realized_pnl=_cumulative_realized_profit(monitor_repository),
            cumulative_realized_rate=_cumulative_realized_profit_rate(monitor_repository),
        )
    except Exception as exc:
        safe_scheduler_log(
            "WARNING",
            "notification",
            f"MARKET_CLOSE_REPORT_FAILED: {safe_exception_summary(exc)}",
            reject_reason="MARKET_CLOSE_REPORT_FAILED",
        )
        return


def _cumulative_realized_profit(monitor_repository: object) -> float:
    method = getattr(monitor_repository, "cumulative_realized_profit", None)
    if callable(method):
        return float(method())
    return float(monitor_repository.today_realized_profit())


def _cumulative_realized_profit_rate(monitor_repository: object) -> float:
    method = getattr(monitor_repository, "cumulative_realized_profit_rate", None)
    if callable(method):
        return float(method())
    return float(monitor_repository.today_realized_profit_rate())
