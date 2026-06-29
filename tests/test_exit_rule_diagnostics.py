from __future__ import annotations

from trading_bot.config import TradingSettings
from trading_bot.exit_rule_diagnostics import build_exit_rule_diagnostics
from trading_bot.models import BotLog, PositionState, SellIntent
from trading_bot.scheduled_tasks import _save_exit_rule_diagnostics


def test_exit_rule_diagnostics_default_off_creates_no_logs() -> None:
    logs = build_exit_rule_diagnostics(
        [PositionState("PURR", 10.0, 1, 9.0, 12.0)],
        TradingSettings(),
    )

    assert logs == []


def test_profit_protection_diagnostic_is_log_only() -> None:
    logs = build_exit_rule_diagnostics(
        [PositionState("PURR", 10.0, 1, 9.0, 12.0)],
        TradingSettings(
            early_exit_diagnostics_enabled=True,
            profit_protection_exit_enabled=True,
            early_negative_exit_enabled=False,
            time_stop_exit_enabled=False,
        ),
    )

    assert len(logs) == 1
    assert isinstance(logs[0], BotLog)
    assert not isinstance(logs[0], SellIntent)
    assert "EXIT_RULE_DIAGNOSTIC ticker=PURR" in logs[0].message
    assert "would_exit=true" in logs[0].message
    assert "actual_exit_not_changed=true" in logs[0].message


def test_time_based_diagnostic_does_not_claim_exit_without_holding_minutes() -> None:
    logs = build_exit_rule_diagnostics(
        [PositionState("CRDO", 10.0, 1, 9.9, 10.0)],
        TradingSettings(
            early_exit_diagnostics_enabled=True,
            profit_protection_exit_enabled=False,
            early_negative_exit_enabled=True,
            time_stop_exit_enabled=True,
            low_profit_60m_exit_enabled=True,
        ),
    )

    assert len(logs) == 3
    assert all("holding_minutes_available=false" in item.message for item in logs)
    assert all("would_exit=false" in item.message for item in logs)
    assert all("actual_exit_not_changed=true" in item.message for item in logs)


def test_save_exit_rule_diagnostics_failure_does_not_raise(monkeypatch) -> None:
    captured: list[tuple[str, str, str]] = []

    class FailingRepository:
        def save_log(self, log: BotLog) -> None:
            raise RuntimeError("boom")

    def fake_safe_scheduler_log(level: str, module: str, message: str, **kwargs) -> None:
        captured.append((level, module, message))

    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.safe_scheduler_log",
        fake_safe_scheduler_log,
    )

    count = _save_exit_rule_diagnostics(
        FailingRepository(),
        [PositionState("PURR", 10.0, 1, 9.0, 12.0)],
        TradingSettings(
            early_exit_diagnostics_enabled=True,
            profit_protection_exit_enabled=True,
        ),
    )

    assert count == 0
    assert captured
    assert captured[0][0] == "WARNING"
    assert "EXIT_RULE_DIAGNOSTICS_FAILED" in captured[0][2]
