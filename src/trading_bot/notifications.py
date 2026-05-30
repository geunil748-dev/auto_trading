from __future__ import annotations

import subprocess
import os
from typing import Protocol

from trading_bot.config import NotificationSettings

MARKET_CLOSE_DONE_MESSAGE = "[자동매매]\n장마감 처리가 정상 완료되었습니다.\n운용 결과는 모니터에서 확인하세요."


class Sender(Protocol):
    def __call__(self, settings: NotificationSettings, message: str) -> bool: ...


def send_market_close_done(settings: NotificationSettings, sender: Sender | None = None) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    return (sender or send_telegram_notice)(settings, MARKET_CLOSE_DONE_MESSAGE)


def send_telegram_notice(settings: NotificationSettings, message: str) -> bool:
    script = """
$uri = "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/sendMessage"
$body = @{
    chat_id = $env:TELEGRAM_CHAT_ID
    text = $env:TELEGRAM_NOTICE_TEXT
    disable_web_page_preview = "true"
}
$response = Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType "application/x-www-form-urlencoded"
if (-not $response.ok) { exit 1 }
"""
    env = os.environ.copy()
    env.update({
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
        "TELEGRAM_NOTICE_TEXT": message,
    })
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return result.returncode == 0
