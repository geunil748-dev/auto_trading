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
    save_runtime_risk_settings(7.5, 12.0, 40, 2, 120, 1.5, 0.8, 25, False, "hybrid")

    settings = load_settings()

    assert settings.max_position_loss == -0.075
    assert settings.take_profit_rate == 0.12
    assert settings.min_total_score == 40
    assert settings.min_price_usd == 2
    assert settings.max_price_usd == 120
    assert settings.min_opening_price_change == 0.015
    assert settings.min_volume_ratio == 0.8
    assert settings.max_opening_gap == 0.25
    assert settings.refresh_intraday_candidates is True
    assert settings.candidate_selection_mode == "hybrid"
    assert runtime_risk_settings_payload(settings)["stopLossPercent"] == 7.5
    assert runtime_risk_settings_payload(settings)["minTotalScore"] == 40
    assert runtime_risk_settings_payload(settings)["minOpeningPriceChangePercent"] == 1.5
    assert runtime_risk_settings_payload(settings)["maxOpeningGapPercent"] == 25
    assert runtime_risk_settings_payload(settings)["refreshIntradayCandidates"] is True
    assert runtime_risk_settings_payload(settings)["candidateSelectionMode"] == "hybrid"
