from trading_bot.monitor_health import (
    _monitor_bind_requires_token,
    _monitor_security_state,
    _safe_error_text,
)


def test_monitor_bind_requires_token_only_for_non_loopback_hosts() -> None:
    assert not _monitor_bind_requires_token("127.0.0.1")
    assert not _monitor_bind_requires_token("localhost")
    assert not _monitor_bind_requires_token("::1")
    assert _monitor_bind_requires_token("0.0.0.0")
    assert _monitor_bind_requires_token("192.168.0.10")


def test_monitor_security_state_requires_token_for_lan_bind(monkeypatch) -> None:
    monkeypatch.delenv("MONITOR_BEARER_TOKEN", raising=False)

    payload = _monitor_security_state("0.0.0.0")

    assert payload["status"] == "fail"
    assert payload["token_required"] is True
    assert payload["token_configured"] is False


def test_monitor_security_state_accepts_configured_lan_token(monkeypatch) -> None:
    monkeypatch.setenv("MONITOR_BEARER_TOKEN", "secret-token")

    payload = _monitor_security_state("0.0.0.0")

    assert payload["status"] == "ok"
    assert payload["token_required"] is True
    assert payload["token_configured"] is True


def test_safe_error_text_masks_sensitive_monitor_and_integration_values(monkeypatch) -> None:
    monkeypatch.setenv("MONITOR_BEARER_TOKEN", "monitor-secret")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "telegram-secret")
    monkeypatch.setenv("KIS_APP_SECRET", "kis-secret")
    monkeypatch.setenv("MSSQL_PASSWORD", "db-secret")

    text = _safe_error_text(
        RuntimeError("monitor-secret telegram-secret kis-secret db-secret")
    )

    assert text == "*** *** *** ***"
