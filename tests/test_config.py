from trading_bot.config import (
    load_notification_settings,
    load_real_kis_settings,
    load_settings,
    runtime_risk_settings_payload,
    save_runtime_risk_settings,
)


def test_load_real_kis_settings_uses_dedicated_real_env(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_PRODUCT", "01")
    monkeypatch.setenv("KIS_REAL_BASE_URL", "https://real.example")

    settings = load_real_kis_settings()

    assert settings.app_key == "real-key"
    assert settings.app_secret == "real-secret"
    assert settings.account_no == "12345678"
    assert settings.account_product == "01"
    assert settings.base_url == "https://real.example"


def test_load_settings_keeps_real_trading_locked_by_default(monkeypatch) -> None:
    monkeypatch.delenv("REAL_TRADING_ENABLED", raising=False)
    monkeypatch.delenv("REAL_EMERGENCY_STOP", raising=False)

    settings = load_settings()

    assert settings.real_trading_enabled is False
    assert settings.real_emergency_stop is True
    assert settings.real_max_order_krw == 100000
    assert settings.real_max_daily_order_krw == 300000


def test_load_settings_reads_real_trading_safety_limits(monkeypatch) -> None:
    monkeypatch.setenv("REAL_TRADING_ENABLED", "true")
    monkeypatch.setenv("REAL_EMERGENCY_STOP", "false")
    monkeypatch.setenv("REAL_MAX_ORDER_KRW", "50000")
    monkeypatch.setenv("REAL_MAX_DAILY_ORDER_KRW", "150000")

    settings = load_settings()

    assert settings.real_trading_enabled is True
    assert settings.real_emergency_stop is False
    assert settings.real_max_order_krw == 50000
    assert settings.real_max_daily_order_krw == 150000


def test_load_settings_reads_unfilled_reorder_policies(monkeypatch) -> None:
    monkeypatch.setenv("MOCK_UNFILLED_REORDER_MINUTES", "2")
    monkeypatch.setenv("MOCK_UNFILLED_REORDER_LIMIT", "1")
    monkeypatch.setenv("REAL_UNFILLED_REORDER_MINUTES", "1")

    settings = load_settings()

    assert settings.mock_unfilled_reorder_minutes == 2
    assert settings.mock_unfilled_reorder_limit == 1
    assert settings.real_unfilled_reorder_minutes == 1


def test_load_settings_reads_p1_stability_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("STOP_LOSS_COOLDOWN_MINUTES", "45")
    monkeypatch.setenv("MAX_CONSECUTIVE_STOP_LOSS_COUNT", "4")
    monkeypatch.setenv("MAX_BID_ASK_SPREAD_RATE", "1.5")
    monkeypatch.setenv("MAX_EXPECTED_FILL_PRICE_GAP_RATE", "2.5")
    monkeypatch.setenv("MAX_ORDER_RETRY_COUNT", "3")
    monkeypatch.setenv("ORDER_RETRY_DELAY_SECONDS", "5")
    monkeypatch.setenv("PARTIAL_FILL_POLICY", "CANCEL_REMAINING")
    monkeypatch.setenv("UNFILLED_CANCEL_AFTER_SECONDS", "90")

    settings = load_settings()

    assert settings.stop_loss_cooldown_minutes == 45
    assert settings.max_consecutive_stop_loss_count == 4
    assert settings.max_bid_ask_spread_rate == 1.5
    assert settings.max_expected_fill_price_gap_rate == 2.5
    assert settings.max_order_retry_count == 3
    assert settings.order_retry_delay_seconds == 5
    assert settings.partial_fill_policy == "CANCEL_REMAINING"
    assert settings.unfilled_cancel_after_seconds == 90


def test_load_notification_settings_reads_optional_alert_channels(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_DISCORD_WEBHOOK_URL", "https://discord.example")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "1234")

    settings = load_notification_settings()

    assert settings.discord_webhook_url == "https://discord.example"
    assert settings.telegram_bot_token == "telegram-token"
    assert settings.telegram_chat_id == "1234"


def test_runtime_risk_settings_override_env_values(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")
    save_runtime_risk_settings(
        7.5,
        12.0,
        40,
        2,
        120,
        1.5,
        0.8,
        25,
        False,
        "hybrid",
        False,
        4,
        22,
        3,
        True,
        True,
        True,
        True,
    )

    settings = load_settings()

    assert settings.max_position_loss == -0.075
    assert settings.take_profit_rate == 0.12
    assert settings.min_total_score == 40
    assert settings.min_price_usd == 2
    assert settings.max_price_usd == 120
    assert settings.min_opening_price_change == 0.015
    assert settings.min_volume_ratio == 0.8
    assert settings.max_opening_gap == 0.25
    assert settings.partial_take_profit_enabled is False
    assert settings.trailing_stop_activation_rate == 0.04
    assert settings.refresh_intraday_candidates is True
    assert settings.candidate_selection_mode == "hybrid"
    assert runtime_risk_settings_payload(settings)["stopLossPercent"] == 7.5
    assert runtime_risk_settings_payload(settings)["minTotalScore"] == 40
    assert runtime_risk_settings_payload(settings)["minOpeningPriceChangePercent"] == 1.5
    assert runtime_risk_settings_payload(settings)["maxOpeningGapPercent"] == 25
    assert runtime_risk_settings_payload(settings)["refreshIntradayCandidates"] is True
    assert runtime_risk_settings_payload(settings)["candidateSelectionMode"] == "hybrid"
    assert runtime_risk_settings_payload(settings)["partialTakeProfitEnabled"] is False
    assert runtime_risk_settings_payload(settings)["trailingStopActivationPercent"] == 4
    assert runtime_risk_settings_payload(settings)["maxEntryPriceChangePercent"] == 22
    assert runtime_risk_settings_payload(settings)["breakoutHoldMinutes"] == 3
    assert runtime_risk_settings_payload(settings)["require5mCloseAboveBreakout"] is True
    assert runtime_risk_settings_payload(settings)["require5mVolumeIncrease"] is True
    assert runtime_risk_settings_payload(settings)["requireVwapOrMa20"] is True
    assert runtime_risk_settings_payload(settings)["requirePullbackRebreak"] is True
