from datetime import date
from types import SimpleNamespace

from trading_bot.config import APP_MODE_REAL, APP_MODE_TEST, TradingSettings
from trading_bot.monitor_response import generate_daily_summary_state, runtime_state
from trading_bot.monitor_server import _real_trading_control_enabled
from trading_bot.real_trading_control import load_real_trading_control


def test_generate_daily_summary_state_keeps_response_keys(monkeypatch) -> None:
    def fake_generate_daily_trade_summary(trade_date, mode):
        report = SimpleNamespace(
            trade_date=trade_date,
            mode=mode,
            strategy_version="STRICT_FIXED_NO_PYRAMIDING",
            settings_snapshot_hash="abc123",
            trade_count=4,
            buy_count=2,
            sell_count=2,
            total_profit_usd=12.5,
            total_profit_rate=3.2,
            win_rate=50.0,
        )
        return SimpleNamespace(
            report=report,
            payload={"candidateCount": 5, "selectedCount": 2},
        )

    monkeypatch.setattr(
        "trading_bot.monitor_response.generate_daily_trade_summary",
        fake_generate_daily_trade_summary,
    )

    payload = generate_daily_summary_state({"date": "2026-06-03", "mode": "mock"})

    assert payload == {
        "ok": True,
        "summary": {
            "tradeDate": "2026-06-03",
            "mode": "mock",
            "strategyVersion": "STRICT_FIXED_NO_PYRAMIDING",
            "settingsSnapshotHash": "abc123",
            "tradeCount": 4,
            "buyCount": 2,
            "sellCount": 2,
            "totalProfitUsd": 12.5,
            "totalProfitRate": 3.2,
            "winRate": 50.0,
            "candidateCount": 5,
            "selectedCount": 2,
        },
    }


def test_generate_daily_summary_state_uses_current_trade_date_when_date_missing(
    monkeypatch,
) -> None:
    calls = []

    def fake_generate_daily_trade_summary(trade_date, mode):
        calls.append((trade_date, mode))
        report = SimpleNamespace(
            trade_date=trade_date,
            mode=mode,
            strategy_version="-",
            settings_snapshot_hash="-",
            trade_count=0,
            buy_count=0,
            sell_count=0,
            total_profit_usd=0.0,
            total_profit_rate=0.0,
            win_rate=0.0,
        )
        return SimpleNamespace(report=report, payload={})

    monkeypatch.setattr("trading_bot.monitor_response.current_trade_date", lambda: date(2026, 6, 8))
    monkeypatch.setattr(
        "trading_bot.monitor_response.generate_daily_trade_summary",
        fake_generate_daily_trade_summary,
    )

    payload = generate_daily_summary_state({"mode": "mock"})

    assert calls == [(date(2026, 6, 8), "mock")]
    assert payload["summary"]["tradeDate"] == "2026-06-08"
    assert payload["summary"]["candidateCount"] == 0
    assert payload["summary"]["selectedCount"] == 0


def test_runtime_state_keeps_monitor_auth_shape(monkeypatch) -> None:
    control = SimpleNamespace(
        orders_unlocked=False,
        mode_label="모의투자",
        to_dict=lambda: {"ordersUnlocked": False},
    )
    monkeypatch.setenv("MONITOR_BEARER_TOKEN", "token")

    payload = runtime_state(control, local_bypass=True, bind_host="0.0.0.0")

    assert payload == {
        "activeMode": "mock",
        "modeLabel": "모의투자",
        "monitorAuth": {
            "localBypass": True,
            "tokenConfigured": True,
            "tokenRequired": True,
            "status": "ok",
            "bindHost": "0.0.0.0",
        },
        "realTrading": {"ordersUnlocked": False},
    }


def test_runtime_state_exposes_app_mode_without_unlocking_test_mode(
    tmp_path,
    monkeypatch,
) -> None:
    control_path = tmp_path / "control.json"
    control_path.write_text('{"manualEnabled": true}', encoding="utf-8")
    monkeypatch.delenv("MONITOR_BEARER_TOKEN", raising=False)
    control = load_real_trading_control(
        TradingSettings(
            app_mode=APP_MODE_TEST,
            real_trading_enabled=True,
            real_emergency_stop=False,
        ),
        control_path,
    )

    payload = runtime_state(control)

    assert payload["activeMode"] == "mock"
    assert payload["realTrading"]["appMode"] == "test"
    assert payload["realTrading"]["mockTrading"] is True
    assert payload["realTrading"]["manualEnabled"] is True
    assert payload["realTrading"]["ordersUnlocked"] is False


def test_monitor_unlock_request_requires_real_mode_and_env_switches() -> None:
    assert _real_trading_control_enabled(
        True,
        TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=False,
        ),
    )
    assert not _real_trading_control_enabled(
        True,
        TradingSettings(
            app_mode=APP_MODE_TEST,
            real_trading_enabled=True,
            real_emergency_stop=False,
        ),
    )
    assert not _real_trading_control_enabled(
        True,
        TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=True,
        ),
    )
    assert not _real_trading_control_enabled(
        False,
        TradingSettings(
            app_mode=APP_MODE_REAL,
            real_trading_enabled=True,
            real_emergency_stop=False,
        ),
    )
