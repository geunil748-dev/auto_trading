from datetime import date

from trading_bot.readiness import mock_trading_readiness, next_us_trading_day


def test_next_us_trading_day_skips_memorial_day_2026() -> None:
    assert next_us_trading_day(date(2026, 5, 25)) == date(2026, 5, 26)


def test_mock_trading_readiness_accepts_target_market_date(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("trading_bot.readiness._kis_config_status", lambda: {"configured": True})
    monkeypatch.setattr("trading_bot.readiness._mssql_status", lambda: {"connected": True})

    state = mock_trading_readiness(tmp_path / "missing.json", market_date=date(2026, 5, 25))

    assert not state["ready_for_live_mock_session"]
    assert state["next_us_trading_day"] == "2026-05-26"
