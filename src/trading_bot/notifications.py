from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from html import escape
from typing import Protocol

from trading_bot.config import NotificationSettings
from trading_bot.trade_notifier import TradeNotifier, get_current_price
from trading_bot.trade_notifier_messages import fmt_pct, fmt_usd, fmt_won, now_kst
from trading_bot.trade_notifier_schedule import (
    is_market_day,
    start_market_close_report_scheduler,
)

try:
    import requests
except ImportError:  # pragma: no cover - dependency absence is handled at runtime.
    requests = None


MARKET_CLOSE_DONE_MESSAGE = "[자동매매]\n장마감 처리가 정상 완료되었습니다.\n운용 결과는 모니터에서 확인하세요."
TELEGRAM_TIMEOUT_SECONDS = 10
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramCredentials:
    token: str
    chat_id: str
    source: str

    @property
    def complete(self) -> bool:
        return bool(self.token and self.chat_id)


class Sender(Protocol):
    def __call__(self, settings: NotificationSettings, message: str) -> bool: ...


def send_telegram_message(message: str) -> bool:
    return send_alert_telegram_message(message)


def send_alert_telegram_message(
    message: str,
    settings: NotificationSettings | None = None,
) -> bool:
    return _post_telegram_message(resolve_alert_telegram_credentials(settings), message)


def send_market_close_done(
    settings: NotificationSettings,
    sender: Sender | None = None,
) -> bool:
    credentials = resolve_alert_telegram_credentials(settings)
    if not credentials.complete:
        _log_missing_credentials(credentials)
        return False
    return (sender or send_telegram_notice)(settings, MARKET_CLOSE_DONE_MESSAGE)


def send_telegram_notice(settings: NotificationSettings, message: str) -> bool:
    return _post_telegram_message(resolve_alert_telegram_credentials(settings), message)


def resolve_alert_telegram_credentials(
    settings: NotificationSettings | None = None,
) -> TelegramCredentials:
    alert_token = (
        settings.telegram_bot_token
        if settings is not None
        else os.getenv("ALERT_TELEGRAM_BOT_TOKEN", "")
    ).strip()
    alert_chat_id = (
        settings.telegram_chat_id
        if settings is not None
        else os.getenv("ALERT_TELEGRAM_CHAT_ID", "")
    ).strip()
    legacy_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    legacy_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    alert_complete = bool(alert_token and alert_chat_id)
    legacy_complete = bool(legacy_token and legacy_chat_id)

    if alert_complete:
        return TelegramCredentials(alert_token, alert_chat_id, "ALERT_TELEGRAM")

    if legacy_complete:
        if alert_token or alert_chat_id:
            logger.warning(
                "telegram alert config partial; falling back to legacy credentials "
                "alert_token_present=%s alert_chat_id_present=%s",
                bool(alert_token),
                bool(alert_chat_id),
            )
        return TelegramCredentials(legacy_token, legacy_chat_id, "LEGACY_TELEGRAM")

    if alert_token or alert_chat_id:
        return TelegramCredentials(alert_token, alert_chat_id, "ALERT_TELEGRAM_PARTIAL")

    if legacy_token or legacy_chat_id:
        return TelegramCredentials(legacy_token, legacy_chat_id, "LEGACY_TELEGRAM_PARTIAL")

    return TelegramCredentials("", "", "MISSING")


def _post_telegram_message(credentials: TelegramCredentials, message: str) -> bool:
    if not credentials.complete:
        _log_missing_credentials(credentials)
        return False
    if requests is None:
        logger.warning(
            "telegram alert send skipped: requests_unavailable source=%s",
            credentials.source,
        )
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{credentials.token}/sendMessage",
            data={
                "chat_id": credentials.chat_id,
                "text": escape(message, quote=False),
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        if not response.ok:
            logger.warning(
                "telegram alert send failed: status_code=%s source=%s",
                getattr(response, "status_code", "unknown"),
                credentials.source,
            )
            return False
        payload = response.json()
    except Exception as exc:
        logger.warning(
            "telegram alert send failed: exception=%s source=%s",
            type(exc).__name__,
            credentials.source,
        )
        return False
    ok = isinstance(payload, dict) and bool(payload.get("ok"))
    if not ok:
        logger.warning(
            "telegram alert send failed: response_ok=false source=%s",
            credentials.source,
        )
    return ok


def _log_missing_credentials(credentials: TelegramCredentials) -> None:
    logger.warning(
        "telegram alert send skipped: missing credentials "
        "token_present=%s chat_id_present=%s source=%s",
        bool(credentials.token),
        bool(credentials.chat_id),
        credentials.source,
    )


__all__ = [
    "MARKET_CLOSE_DONE_MESSAGE",
    "TradeNotifier",
    "fmt_pct",
    "fmt_usd",
    "fmt_won",
    "get_current_price",
    "is_market_day",
    "now_kst",
    "resolve_alert_telegram_credentials",
    "send_alert_telegram_message",
    "send_market_close_done",
    "send_telegram_message",
    "send_telegram_notice",
    "start_market_close_report_scheduler",
]
