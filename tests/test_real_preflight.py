import json

from trading_bot.config import APP_MODE_REAL, APP_MODE_TEST, KisSettings, TradingSettings
from trading_bot.real_preflight import (
    MOCK_MONITOR_STATE_PATH,
    REAL_MONITOR_STATE_PATH,
    real_preflight,
    safe_error_text,
)


def _db_ok() -> dict[str, object]:
    return {"configured": True, "connected": True, "error": ""}


def test_real_preflight_reports_app_mode_test_as_blocking(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key-secret")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret-value")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")

    payload = real_preflight(
        settings=TradingSettings(
            app_mode=APP_MODE_TEST,
            real_trading_enabled=True,
            real_emergency_stop=False,
            real_order_execution_enabled=True,
        ),
        db_health_func=_db_ok,
    )

    assert payload["appMode"] == "test"
    assert payload["ordersUnlocked"] is False
    assert "APP_MODE_NOT_REAL" in payload["blockingReasons"]
    assert "12345678" not in json.dumps(payload, ensure_ascii=False)
    assert "real-secret-value" not in json.dumps(payload, ensure_ascii=False)


def test_real_preflight_reports_real_blocking_reasons(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")

    payload = real_preflight(
        settings=TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=False,
            real_emergency_stop=True,
            real_order_execution_enabled=False,
        ),
        db_health_func=_db_ok,
    )

    assert "REAL_TRADING_DISABLED" in payload["blockingReasons"]
    assert "REAL_EMERGENCY_STOP" in payload["blockingReasons"]
    assert "MANUAL_UNLOCK_DISABLED" in payload["blockingReasons"]
    assert "REAL_ORDER_EXECUTION_DISABLED" in payload["blockingReasons"]


def test_real_preflight_sensitive_error_is_sanitized(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")

    class BrokenReader:
        def current_account(self):
            raise RuntimeError("failed appsecret=real-secret account=12345678 token=abc")

    payload = real_preflight(
        check_account=True,
        settings=TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=False,
            real_order_execution_enabled=False,
        ),
        account_reader_factory=lambda settings: BrokenReader(),
        db_health_func=_db_ok,
    )

    text = json.dumps(payload, ensure_ascii=False)
    assert "real-secret" not in text
    assert "12345678" not in text
    assert "abc" not in payload["realAccountReadOnly"]["error"]


def test_real_preflight_account_check_is_read_only(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")
    calls = []

    class Reader:
        def current_account(self):
            calls.append("current_account")
            return object()

        def submit(self):
            raise AssertionError("order path must not be called")

    payload = real_preflight(
        check_account=True,
        settings=TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=False,
            real_order_execution_enabled=False,
        ),
        account_reader_factory=lambda settings: Reader(),
        db_health_func=_db_ok,
    )

    assert payload["realAccountReadOnly"]["available"] is True
    assert calls == ["current_account"]


def test_real_preflight_state_isolation_defaults_are_separate() -> None:
    payload = real_preflight(
        settings=TradingSettings(app_mode=APP_MODE_REAL),
        db_health_func=_db_ok,
    )

    assert payload["realStatePath"] == str(REAL_MONITOR_STATE_PATH)
    assert payload["mockStatePath"] == str(MOCK_MONITOR_STATE_PATH)
    assert payload["stateIsolation"]["ok"] is True


def test_safe_error_text_redacts_env_values_and_sensitive_pairs(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "12345678")

    text = safe_error_text(RuntimeError("account_no=12345678 access_token=secret-token"))

    assert "12345678" not in text
    assert "secret-token" not in text


def test_real_preflight_token_environment_uses_real_base_url(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_BASE_URL", "https://openapi.koreainvestment.com:9443")

    payload = real_preflight(
        settings=TradingSettings(app_mode=APP_MODE_REAL),
        db_health_func=_db_ok,
    )

    assert payload["kisTokenEnvironment"] == "real"


def test_real_preflight_accepts_fake_real_kis_settings_without_leaking_raw_values(monkeypatch) -> None:
    monkeypatch.setenv("KIS_REAL_APP_KEY", "fake-real-key")
    monkeypatch.setenv("KIS_REAL_APP_SECRET", "fake-real-secret")
    monkeypatch.setenv("KIS_REAL_ACCOUNT_NO", "99999999")

    payload = real_preflight(
        settings=TradingSettings(app_mode=APP_MODE_REAL),
        db_health_func=_db_ok,
    )

    assert payload["kisRealConfig"]["configured"] is True
    assert payload["kisRealConfig"]["appKey"] is True
    assert payload["kisRealConfig"]["appSecret"] is True
    assert payload["kisRealConfig"]["accountNo"] is True
    assert "fake-real-key" not in json.dumps(payload, ensure_ascii=False)
    assert "99999999" not in json.dumps(payload, ensure_ascii=False)
