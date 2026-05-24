from trading_bot.config import load_notification_settings, load_real_kis_settings, load_settings


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
