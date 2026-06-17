from datetime import date

import trading_bot.notifications as notifications_module
from trading_bot.config import NotificationSettings
from trading_bot.models import FillRecord
from trading_bot.notifications import (
    MARKET_CLOSE_DONE_MESSAGE,
    TradeNotifier,
    resolve_alert_telegram_credentials,
    send_alert_telegram_message,
    send_market_close_done,
    send_telegram_message,
)
from trading_bot.trade_fill_notifications import (
    fill_keys_from_history,
    new_fill_records,
    send_fill_notifications,
    send_market_close_report_from_records,
)


def test_send_market_close_done_skips_without_telegram_settings(monkeypatch) -> None:
    calls: list[str] = []
    for key in (
        "ALERT_TELEGRAM_BOT_TOKEN",
        "ALERT_TELEGRAM_CHAT_ID",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

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


def test_resolve_alert_telegram_credentials_prefers_alert(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "alert-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "alert-chat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")

    credentials = resolve_alert_telegram_credentials()

    assert credentials.token == "alert-token"
    assert credentials.chat_id == "alert-chat"
    assert credentials.source == "ALERT_TELEGRAM"


def test_resolve_alert_telegram_credentials_uses_legacy_when_alert_absent(monkeypatch) -> None:
    monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")

    credentials = resolve_alert_telegram_credentials()

    assert credentials.token == "legacy-token"
    assert credentials.chat_id == "legacy-chat"
    assert credentials.source == "LEGACY_TELEGRAM"


def test_resolve_alert_telegram_credentials_falls_back_for_partial_alert(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "alert-token")
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")

    credentials = resolve_alert_telegram_credentials()

    assert credentials.token == "legacy-token"
    assert credentials.chat_id == "legacy-chat"
    assert credentials.source == "LEGACY_TELEGRAM"
    log_text = "\n".join(item.message for item in caplog.records)
    assert "falling back to legacy credentials" in log_text
    assert "alert_token_present=True" in log_text
    assert "alert_chat_id_present=False" in log_text
    assert "alert-token" not in log_text
    assert "legacy-token" not in log_text
    assert "legacy-chat" not in log_text


def test_send_telegram_message_posts_with_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        ok = True

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    class FakeRequests:
        @staticmethod
        def post(url: str, data: dict[str, object], timeout: int) -> Response:
            calls.append({"url": url, "data": data, "timeout": timeout})
            return Response()

    monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1234")
    monkeypatch.setattr(notifications_module, "requests", FakeRequests)

    assert send_telegram_message("A < B") is True

    assert calls[0]["url"] == "https://api.telegram.org/bottoken/sendMessage"
    assert calls[0]["timeout"] == 10
    data = calls[0]["data"]
    assert data["chat_id"] == "1234"
    assert data["parse_mode"] == "HTML"
    assert data["text"] == "A &lt; B"


def test_send_telegram_message_prefers_alert_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        ok = True

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    class FakeRequests:
        @staticmethod
        def post(url: str, data: dict[str, object], timeout: int) -> Response:
            calls.append({"url": url, "data": data, "timeout": timeout})
            return Response()

    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "alert-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "alert-chat")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")
    monkeypatch.setattr(notifications_module, "requests", FakeRequests)

    assert send_telegram_message("daily report") is True

    assert calls[0]["url"] == "https://api.telegram.org/botalert-token/sendMessage"
    assert calls[0]["data"]["chat_id"] == "alert-chat"


def test_send_market_close_done_falls_back_to_legacy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        ok = True

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    class FakeRequests:
        @staticmethod
        def post(url: str, data: dict[str, object], timeout: int) -> Response:
            calls.append({"url": url, "data": data, "timeout": timeout})
            return Response()

    monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")
    monkeypatch.setattr(notifications_module, "requests", FakeRequests)

    assert send_market_close_done(NotificationSettings()) is True

    assert calls[0]["url"] == "https://api.telegram.org/botlegacy-token/sendMessage"
    assert calls[0]["data"]["chat_id"] == "legacy-chat"


def test_send_market_close_done_falls_back_to_legacy_for_partial_alert_settings(
    monkeypatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        ok = True

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    class FakeRequests:
        @staticmethod
        def post(url: str, data: dict[str, object], timeout: int) -> Response:
            calls.append({"url": url, "data": data, "timeout": timeout})
            return Response()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "legacy-chat")
    monkeypatch.setattr(notifications_module, "requests", FakeRequests)

    settings = NotificationSettings(telegram_bot_token="alert-token", telegram_chat_id="")

    assert send_market_close_done(settings) is True

    assert calls[0]["url"] == "https://api.telegram.org/botlegacy-token/sendMessage"
    assert calls[0]["data"]["chat_id"] == "legacy-chat"


def test_send_alert_telegram_message_logs_missing_credentials_without_secret(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "secret-token")
    monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "legacy-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    assert send_alert_telegram_message("daily report") is False

    log_text = "\n".join(item.message for item in caplog.records)
    assert "token_present=True" in log_text
    assert "chat_id_present=False" in log_text
    assert "source=ALERT_TELEGRAM_PARTIAL" in log_text
    assert "secret-token" not in log_text
    assert "legacy-token" not in log_text


def test_trade_notifier_buy_success_updates_position_and_daily() -> None:
    messages: list[str] = []
    notifier = TradeNotifier(
        current_price_func=lambda code: 72400,
        message_sender=lambda message: messages.append(message) or True,
    )

    sent = notifier.on_buy_success("005930", "삼성전자", 10, 72300, "12345678")

    assert sent is True
    assert notifier.positions["005930"]["qty"] == 10
    assert notifier.positions["005930"]["avg_price"] == 72300
    assert notifier.daily["buy_count"] == 1
    assert notifier.daily["buy_amount"] == 723000
    assert "✅ 매수 성공" in messages[0]
    assert "현재가: 72,400원" in messages[0]
    assert "주문번호: 12345678" in messages[0]


def test_trade_notifier_sell_success_calculates_realized_pnl() -> None:
    messages: list[str] = []
    notifier = TradeNotifier(
        current_price_func=lambda code: 73000,
        message_sender=lambda message: messages.append(message) or True,
    )
    notifier.positions["005930"] = {"name": "삼성전자", "qty": 10, "avg_price": 72300}

    sent = notifier.on_sell_success("005930", "삼성전자", 10, 73100, "12345679")

    assert sent is True
    assert "005930" not in notifier.positions
    assert notifier.daily["sell_count"] == 1
    assert notifier.daily["sell_amount"] == 731000
    assert notifier.daily["realized_pnl"] == 8000
    assert notifier.daily["realized_cost"] == 723000
    assert "✅ 매도 성공" in messages[0]
    assert "실현손익: +8,000원" in messages[0]
    assert "수익률: +1.11%" in messages[0]


def test_trade_notifier_sell_success_without_position_reports_unavailable() -> None:
    messages: list[str] = []
    notifier = TradeNotifier(
        current_price_func=lambda code: 73100,
        message_sender=lambda message: messages.append(message) or True,
    )

    sent = notifier.on_sell_success("005930", "삼성전자", 10, 73100, "12345679")

    assert sent is True
    assert notifier.daily["sell_count"] == 1
    assert notifier.daily["realized_pnl"] == 0
    assert "계산 불가" in messages[0]
    assert "보유정보가 없어" in messages[0]


def test_trade_notifier_market_close_report_summarizes_positions() -> None:
    messages: list[str] = []
    notifier = TradeNotifier(
        current_price_func=lambda code: 73000,
        message_sender=lambda message: messages.append(message) or True,
    )
    notifier.on_buy_success("005930", "삼성전자", 10, 72300, "12345678")

    sent = notifier.send_market_close_report()

    assert sent is True
    report = messages[-1]
    assert "📊 장마감 수익률 요약" in report
    assert "매수 횟수: 1회" in report
    assert "오늘 매수금액: 723,000원" in report
    assert "평가손익: +7,000원" in report
    assert "- 삼성전자(005930) 10주" in report


def test_new_fill_records_excludes_history_rows() -> None:
    record = FillRecord(
        trade_date=date(2026, 6, 4),
        fill_time="22:31:00",
        ticker="AAA",
        ticker_name="Alpha",
        side="BUY",
        quantity=2,
        fill_price_usd=10.5,
        fill_amount_usd=21.0,
        order_no="1001",
    )
    existing = fill_keys_from_history(
        [(date(2026, 6, 4), "22:31:00", "AAA", "Alpha", "BUY", 2, 10.5)]
    )

    assert new_fill_records([record], existing) == []


def test_send_fill_notifications_uses_fill_events_only() -> None:
    messages: list[str] = []
    records = [
        FillRecord(
            trade_date=date(2026, 6, 4),
            fill_time="22:31:00",
            ticker="AAA",
            ticker_name="Alpha",
            side="BUY",
            quantity=2,
            fill_price_usd=10,
            fill_amount_usd=20,
            order_no="1001",
        ),
        FillRecord(
            trade_date=date(2026, 6, 4),
            fill_time="22:41:00",
            ticker="AAA",
            ticker_name="Alpha",
            side="SELL",
            quantity=1,
            fill_price_usd=12,
            fill_amount_usd=12,
            profit_usd=2,
            profit_rate=0.2,
            order_no="1002",
        ),
    ]

    sent = send_fill_notifications(
        records,
        [
            {
                "ticker": "AAA",
                "name": "Alpha",
                "quantity": "1",
                "averagePrice": "$10.00",
                "closePrice": "$12.00",
            }
        ],
        sender=lambda message: messages.append(message) or True,
    )

    assert sent == 2
    assert "✅ 매수 성공" in messages[0]
    assert "보유수량: 2주" in messages[0]
    assert "✅ 매도 성공" in messages[1]
    assert "실현손익: +$2.00" in messages[1]


def test_send_market_close_report_from_records() -> None:
    messages: list[str] = []
    records = [
        FillRecord(
            trade_date=date(2026, 6, 4),
            fill_time="22:31:00",
            ticker="AAA",
            ticker_name="Alpha",
            side="BUY",
            quantity=2,
            fill_price_usd=10,
            fill_amount_usd=20,
        ),
        FillRecord(
            trade_date=date(2026, 6, 4),
            fill_time="22:41:00",
            ticker="AAA",
            ticker_name="Alpha",
            side="SELL",
            quantity=1,
            fill_price_usd=12,
            fill_amount_usd=12,
            profit_usd=2,
            profit_rate=0.2,
        ),
    ]

    sent = send_market_close_report_from_records(
        records,
        [
            {
                "ticker": "AAA",
                "name": "Alpha",
                "quantity": "1",
                "averagePrice": "$10.00",
                "closePrice": "$11.00",
            }
        ],
        sender=lambda message: messages.append(message) or True,
        cumulative_realized_pnl=15.5,
        cumulative_realized_rate=3.2,
    )

    assert sent is True
    assert "매수 횟수: 1회" in messages[0]
    assert "매도 횟수: 1회" in messages[0]
    assert "실현손익: +$2.00" in messages[0]
    assert "평가손익: +$1.00" in messages[0]
    assert "누적실현손익: +$15.50" in messages[0]
    assert "누적수익률: +3.20%" in messages[0]
    assert "총손익:" not in messages[0]
    assert "총수익률:" not in messages[0]
