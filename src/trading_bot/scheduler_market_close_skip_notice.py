from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from trading_bot.market_calendar import (
    NEW_YORK,
    current_us_market_date,
    is_us_trading_day,
    us_market_holiday_name,
)
from trading_bot.performance_digest_skip_packet import format_auto_trading_data_packet_skipped
from trading_bot.scheduler_logging import safe_exception_summary, safe_scheduler_log
from trading_bot.slack_digest_notifier import send_slack_digest_message

KOREA = ZoneInfo("Asia/Seoul")
MARKET_CLOSE_SLACK_CHECK_DELAY_MINUTES = 10


def build_auto_trading_data_packet_skipped_notice(
    report_date: date | None = None,
) -> str:
    target_date = report_date or current_us_market_date()
    next_trading_date = _next_us_trading_day(target_date)
    next_close = _next_market_close(next_trading_date)
    return format_auto_trading_data_packet_skipped(
        report_date=target_date,
        market_status="CLOSED",
        skip_reason=_market_skip_reason(target_date),
        holiday_name=us_market_holiday_name(target_date),
        next_expected_trading_date=next_trading_date,
        next_expected_market_close=next_close,
        check_slack_after_kst=next_close.astimezone(KOREA)
        + timedelta(minutes=MARKET_CLOSE_SLACK_CHECK_DELAY_MINUTES),
    )


def send_auto_trading_data_packet_skipped_notice(
    report_date: date | None = None,
) -> str:
    target_date = report_date or current_us_market_date()
    notice = build_auto_trading_data_packet_skipped_notice(target_date)
    dry_run = _env_flag("AUTO_TRADING_DATA_DIGEST_SLACK_DRY_RUN") or _env_flag("DRY_RUN")
    sent = False
    attempted = False
    status = "disabled"

    if not _env_flag("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED"):
        status = "disabled"
    elif dry_run:
        status = "dry_run"
    else:
        webhook_url = os.getenv("AUTO_TRADING_DATA_DIGEST_SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            status = "missing_webhook"
        else:
            attempted = True
            try:
                send_slack_digest_message(webhook_url, notice)
                sent = True
                status = "sent"
            except Exception as exc:
                status = "failed"
                safe_scheduler_log(
                    "WARNING",
                    "summary",
                    f"AUTO_TRADING_DATA_PACKET_SKIPPED_SLACK_FAILED: {safe_exception_summary(exc)}",
                    reject_reason="AUTO_TRADING_DATA_PACKET_SKIPPED_SLACK_FAILED",
                )

    _log_skipped_notice_result(
        target_date=target_date,
        attempted=attempted,
        sent=sent,
        dry_run=dry_run,
        status=status,
    )
    return notice


def _log_skipped_notice_result(
    *,
    target_date: date,
    attempted: bool,
    sent: bool,
    dry_run: bool,
    status: str,
) -> None:
    next_close = _next_market_close(_next_us_trading_day(target_date))
    safe_scheduler_log(
        "INFO",
        "summary",
        (
            "AUTO_TRADING_DATA_PACKET_SKIPPED: close_session holiday skip detected "
            f"report_date={target_date:%Y-%m-%d} "
            f"holiday_reason={_market_skip_reason(target_date)} "
            f"holiday_name={us_market_holiday_name(target_date) or 'local_calendar_reason'} "
            f"slack_skip_notice_attempted={str(attempted).lower()} "
            f"slack_skip_notice_sent={str(sent).lower()} "
            f"dry_run={str(dry_run).lower()} "
            f"slack_status={status} "
            f"next_expected_trading_close={next_close.isoformat()}"
        ),
        reject_reason="AUTO_TRADING_DATA_PACKET_SKIPPED",
    )


def _market_skip_reason(target_date: date) -> str:
    if us_market_holiday_name(target_date):
        return "US_MARKET_HOLIDAY"
    if target_date.weekday() >= 5:
        return "US_MARKET_WEEKEND"
    return "US_MARKET_CLOSED_NON_TRADING_DAY"


def _next_us_trading_day(start: date) -> date:
    candidate = start + timedelta(days=1)
    while not is_us_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def _next_market_close(trading_day: date) -> datetime:
    return datetime.combine(trading_day, time(15, 58, tzinfo=NEW_YORK))


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
