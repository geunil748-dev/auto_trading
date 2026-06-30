from datetime import date

from trading_bot.config import NotificationSettings, TradingSettings
from trading_bot.scheduler_market_close import (
    save_auto_trading_data_digest,
    save_daily_run_summary,
    save_daily_trade_summary_report,
    save_strategy_review_export,
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


def test_save_strategy_review_export_uses_daily_filename(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    logs = []
    expected_output = tmp_path / "strategy_review_20260629.xlsx"

    monkeypatch.setenv("STRATEGY_REVIEW_EXPORT_DIR", str(tmp_path))
    monkeypatch.delenv("STRATEGY_REVIEW_DATE_FROM", raising=False)
    monkeypatch.delenv("AUTO_TRADING_DATA_DIGEST_ENABLED", raising=False)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.current_trade_date",
        lambda: date(2026, 6, 29),
    )

    def fake_export_strategy_review_workbook_with_results(**kwargs):
        captured.update(kwargs)
        return kwargs["output"], [], []

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.export_strategy_review_workbook_with_results",
        fake_export_strategy_review_workbook_with_results,
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    assert save_strategy_review_export() == expected_output
    assert captured == {
        "date_from": "2026-05-20",
        "date_to": date(2026, 6, 29),
        "output": expected_output,
        "include_real": False,
    }
    assert logs[0][0] == "INFO"
    assert logs[0][1] == "summary"
    assert logs[0][3]["reject_reason"] == "STRATEGY_REVIEW_EXPORT_SAVED"


def test_save_strategy_review_export_uses_env_date_from(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("STRATEGY_REVIEW_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("STRATEGY_REVIEW_DATE_FROM", "2026-06-01")
    monkeypatch.delenv("AUTO_TRADING_DATA_DIGEST_ENABLED", raising=False)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.current_trade_date",
        lambda: date(2026, 6, 29),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.export_strategy_review_workbook_with_results",
        lambda **kwargs: (captured.update(kwargs) or (kwargs["output"], [], [])),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda *args, **kwargs: None,
    )

    save_strategy_review_export()

    assert captured["date_from"] == "2026-06-01"
    assert captured["date_to"] == date(2026, 6, 29)
    assert captured["output"] == tmp_path / "strategy_review_20260629.xlsx"


def test_save_auto_trading_data_digest_skips_when_disabled(monkeypatch, tmp_path) -> None:
    logs = []
    monkeypatch.delenv("AUTO_TRADING_DATA_DIGEST_ENABLED", raising=False)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    result = save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert result is None
    assert logs == [
        (
            "INFO",
            "summary",
            "AUTO_TRADING_DATA_DIGEST_SKIPPED: disabled",
            {"reject_reason": "AUTO_TRADING_DATA_DIGEST_SKIPPED"},
        )
    ]


def test_save_auto_trading_data_digest_saves_text_without_slack(monkeypatch, tmp_path) -> None:
    logs = []
    slack_calls = []
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_ENABLED", "true")
    monkeypatch.delenv("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED", raising=False)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.build_strategy_review_digest",
        lambda *args, **kwargs: "[AUTO_TRADING_DATA_DIGEST]\nbody",
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_slack_digest_message",
        lambda *args, **kwargs: slack_calls.append(args),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    digest_path = save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert digest_path == tmp_path / "strategy_digest_20260629.txt"
    assert digest_path.read_text(encoding="utf-8").startswith("[AUTO_TRADING_DATA_DIGEST]")
    assert slack_calls == []
    assert logs[0][3]["reject_reason"] == "AUTO_TRADING_DATA_DIGEST_SAVED"


def test_save_auto_trading_data_digest_slack_missing_webhook(monkeypatch, tmp_path) -> None:
    logs = []
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED", "true")
    monkeypatch.delenv("AUTO_TRADING_DATA_DIGEST_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.build_strategy_review_digest",
        lambda *args, **kwargs: "[AUTO_TRADING_DATA_DIGEST]\nbody",
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert [log[3]["reject_reason"] for log in logs] == [
        "AUTO_TRADING_DATA_DIGEST_SAVED",
        "AUTO_TRADING_DATA_DIGEST_SLACK_SKIPPED",
    ]


def test_save_auto_trading_data_digest_slack_sends_plain_text(monkeypatch, tmp_path) -> None:
    logs = []
    sent = []
    digest_text = "[AUTO_TRADING_DATA_DIGEST]\nbody"
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_SLACK_WEBHOOK_URL", "https://hooks.slack.test/example")
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.build_strategy_review_digest",
        lambda *args, **kwargs: digest_text,
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_slack_digest_message",
        lambda webhook_url, text: sent.append((webhook_url, text)) or True,
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert sent == [("https://hooks.slack.test/example", digest_text)]
    assert [log[3]["reject_reason"] for log in logs] == [
        "AUTO_TRADING_DATA_DIGEST_SAVED",
        "AUTO_TRADING_DATA_DIGEST_SLACK_SENT",
    ]
    assert all("secret" not in log[2] for log in logs)


def test_save_auto_trading_data_digest_continues_when_slack_fails(monkeypatch, tmp_path) -> None:
    logs = []
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_SLACK_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_SLACK_WEBHOOK_URL", "https://hooks.slack.test/example")
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.build_strategy_review_digest",
        lambda *args, **kwargs: "[AUTO_TRADING_DATA_DIGEST]\nbody",
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.send_slack_digest_message",
        lambda webhook_url, text: (_ for _ in ()).throw(RuntimeError("webhook hidden")),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    digest_path = save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert digest_path == tmp_path / "strategy_digest_20260629.txt"
    assert logs[-1][0] == "WARNING"
    assert logs[-1][2] == "AUTO_TRADING_DATA_DIGEST_SLACK_FAILED: RuntimeError"
    assert "hidden" not in logs[-1][2]


def test_save_auto_trading_data_digest_continues_when_digest_fails(monkeypatch, tmp_path) -> None:
    logs = []
    monkeypatch.setenv("AUTO_TRADING_DATA_DIGEST_ENABLED", "true")
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.build_strategy_review_digest",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("DB_PASSWORD=secret")),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    result = save_auto_trading_data_digest(
        strategy_review_path=tmp_path / "strategy_review_20260629.xlsx",
        sheet_results=[],
        failures=[],
        report_date=date(2026, 6, 29),
        date_from="2026-05-20",
        date_to=date(2026, 6, 29),
    )

    assert result is None
    assert logs == [
        (
            "WARNING",
            "summary",
            "AUTO_TRADING_DATA_DIGEST_FAILED: RuntimeError",
            {"reject_reason": "AUTO_TRADING_DATA_DIGEST_FAILED"},
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

    class MonitorRepository:
        def cumulative_realized_profit(self):
            return 123.45

        def cumulative_realized_profit_rate(self):
            return 6.7

    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerDailyRepository",
        lambda connect: Repository(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_market_close.SqlServerMonitorRepository",
        lambda connect: MonitorRepository(),
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

    def fake_send_report(
        records,
        holdings,
        sender,
        *,
        cumulative_realized_pnl,
        cumulative_realized_rate,
    ):
        captured["records"] = records
        captured["holdings"] = holdings
        captured["cumulative_realized_pnl"] = cumulative_realized_pnl
        captured["cumulative_realized_rate"] = cumulative_realized_rate
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
    assert captured["cumulative_realized_pnl"] == 123.45
    assert captured["cumulative_realized_rate"] == 6.7
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
