from datetime import date

from trading_bot.config import NotificationSettings, TradingSettings
from trading_bot.scheduler_market_close import (
    save_daily_run_summary,
    save_daily_trade_summary_report,
    send_market_close_notice,
    send_market_close_report,
)


def test_save_daily_run_summary_calls_repositories(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class MonitorRepository:
        def history_fill_counts(self, trade_date):
            captured["fill_counts_date"] = trade_date
            return 2, 3

        def history_realized_profit(self, trade_date):
            captured["profit_date"] = trade_date
            return 12.5

        def history_realized_profit_rate(self, trade_date):
            captured["profit_rate_date"] = trade_date
            return 4.2

    class DailyRepository:
        def save_daily_run_summary(
            self,
            trade_date,
            settings,
            realized_profit,
            realized_profit_rate,
            eod_sell_count,
            cancelled_order_count,
            buy_count,
            sell_count,
        ):
            captured["summary"] = (
                trade_date,
                settings,
                realized_profit,
                realized_profit_rate,
                eod_sell_count,
                cancelled_order_count,
                buy_count,
                sell_count,
            )

    settings = TradingSettings()
    monkeypatch.setattr("trading_bot.scheduler_market_close.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.current_trade_date",
        lambda: date(2026, 6, 5),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerMonitorRepository",
        lambda connect: MonitorRepository(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerDailyRepository",
        lambda connect: DailyRepository(),
    )

    save_daily_run_summary(settings, 1, 2)

    assert captured["fill_counts_date"] == date(2026, 6, 5)
    assert captured["profit_date"] == date(2026, 6, 5)
    assert captured["profit_rate_date"] == date(2026, 6, 5)
    assert captured["summary"] == (date(2026, 6, 5), settings, 12.5, 4.2, 1, 2, 2, 3)


def test_save_daily_run_summary_failure_logs_warning(monkeypatch) -> None:
    logs = []

    def fail_monitor_repository(connect):
        raise RuntimeError("MSSQL_PASSWORD=secret")

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerMonitorRepository",
        fail_monitor_repository,
    )
    monkeypatch.setattr("trading_bot.scheduler_market_close.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    save_daily_run_summary(TradingSettings(), None, None)

    assert logs[0][2] == "DAILY_RUN_SUMMARY_SAVE_FAILED: RuntimeError"
    assert logs[0][3]["reject_reason"] == "DAILY_RUN_SUMMARY_SAVE_FAILED"
    assert "secret" not in logs[0][2]


def test_save_daily_trade_summary_report_failure_logs_warning(monkeypatch) -> None:
    logs = []
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.generate_daily_trade_summary",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("DB_PASSWORD=secret")),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    save_daily_trade_summary_report()

    assert logs == [
        (
            "WARNING",
            "summary",
            "SUMMARY_REPORT_SAVE_FAILED: RuntimeError",
            {"reject_reason": "SUMMARY_REPORT_SAVE_FAILED"},
        )
    ]


def test_send_market_close_notice_failure_logs_warning(monkeypatch) -> None:
    logs = []

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.load_notification_settings",
        lambda: NotificationSettings(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_market_close_done",
        lambda settings: (_ for _ in ()).throw(RuntimeError("telegram token secret")),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    send_market_close_notice()

    assert logs[0][2] == "MARKET_CLOSE_NOTICE_FAILED: RuntimeError"
    assert logs[0][3]["reject_reason"] == "MARKET_CLOSE_NOTICE_FAILED"
    assert "secret" not in logs[0][2]


def test_send_market_close_report_uses_records_and_safe_holdings(monkeypatch) -> None:
    captured: dict[str, object] = {}
    settings = NotificationSettings(telegram_bot_token="token", telegram_chat_id="chat")

    class Repository:
        def sell_entry_prices(self, trade_date):
            captured["trade_date"] = trade_date
            return {}

        def entry_reasons(self, trade_date):
            return {}

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerDailyRepository",
        lambda connect: Repository(),
    )
    monkeypatch.setattr("trading_bot.scheduler_market_close.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.current_trade_date",
        lambda: date(2026, 6, 5),
    )
    monkeypatch.setattr("trading_bot.scheduler_market_close.load_settings", lambda: TradingSettings())
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.load_notification_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.fill_records_from_monitor_rows",
        lambda fills, entry_prices, entry_reasons, settings: ["record"],
    )

    def fake_send_report(records, holdings, sender):
        captured["records"] = records
        captured["holdings"] = holdings
        return sender("market close report")

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_market_close_report_from_records",
        fake_send_report,
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_alert_telegram_message",
        lambda message, notification_settings: captured.update(
            {
                "message": message,
                "notification_settings": notification_settings,
            }
        )
        or True,
    )

    send_market_close_report({"fills": [{"ticker": "AAA"}], "holdings": "bad"})

    assert captured["trade_date"] == date(2026, 6, 5)
    assert captured["records"] == ["record"]
    assert captured["holdings"] == []
    assert captured["message"] == "market close report"
    assert captured["notification_settings"] is settings


def test_send_market_close_report_returns_when_fills_not_list(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_market_close_report_from_records",
        lambda *args, **kwargs: called.append(True),
    )

    send_market_close_report({"fills": "bad", "holdings": []})

    assert called == []


def test_send_market_close_report_failure_logs_warning(monkeypatch) -> None:
    logs = []

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.load_notification_settings",
        lambda: NotificationSettings(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerDailyRepository",
        lambda connect: (_ for _ in ()).throw(RuntimeError("MSSQL_PASSWORD=secret")),
    )
    monkeypatch.setattr("trading_bot.scheduler_market_close.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    send_market_close_report({"fills": [{"ticker": "AAA"}], "holdings": []})

    assert logs[0][2] == "MARKET_CLOSE_REPORT_FAILED: RuntimeError"
    assert logs[0][3]["reject_reason"] == "MARKET_CLOSE_REPORT_FAILED"
    assert "secret" not in logs[0][2]
