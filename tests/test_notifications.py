from trading_bot.config import NotificationSettings
from trading_bot.notifications import (
    MARKET_CLOSE_DONE_MESSAGE,
    send_market_close_done,
)


def test_send_market_close_done_skips_without_telegram_settings() -> None:
    calls: list[str] = []

    sent = send_market_close_done(
        NotificationSettings(),
        lambda settings, message: calls.append(message) or True,
    )

    assert sent is False
    assert calls == []


def test_send_market_close_done_sends_notice_only() -> None:
    calls: list[str] = []

    sent = send_market_close_done(
        NotificationSettings(telegram_bot_token="token", telegram_chat_id="123"),
        lambda settings, message: calls.append(message) or True,
    )

    assert sent is True
    assert calls == [MARKET_CLOSE_DONE_MESSAGE]
    assert "$" not in calls[0]
    assert "%" not in calls[0]
    assert "체결" not in calls[0]
