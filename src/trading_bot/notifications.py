from __future__ import annotations

import os
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


class Sender(Protocol):
    def __call__(self, settings: NotificationSettings, message: str) -> bool: ...


def send_telegram_message(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return _post_telegram_message(token, chat_id, message)


def send_market_close_done(settings: NotificationSettings, sender: Sender | None = None) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    return (sender or send_telegram_notice)(settings, MARKET_CLOSE_DONE_MESSAGE)


def send_telegram_notice(settings: NotificationSettings, message: str) -> bool:
    return _post_telegram_message(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        message,
    )


def _post_telegram_message(token: str, chat_id: str, message: str) -> bool:
    if not token or not chat_id or requests is None:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": escape(message, quote=False),
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=TELEGRAM_TIMEOUT_SECONDS,
        )
        if not response.ok:
            return False
        payload = response.json()
    except Exception:
        return False
    return isinstance(payload, dict) and bool(payload.get("ok"))


__all__ = [
    "MARKET_CLOSE_DONE_MESSAGE",
    "TradeNotifier",
    "fmt_pct",
    "fmt_usd",
    "fmt_won",
    "get_current_price",
    "is_market_day",
    "now_kst",
    "send_market_close_done",
    "send_telegram_message",
    "send_telegram_notice",
    "start_market_close_report_scheduler",
]
