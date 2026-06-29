from __future__ import annotations

from datetime import datetime, timedelta

from trading_bot.config import TradingSettings
from trading_bot.exit_planner import plan_position_exits, position_holding_minutes
from trading_bot.models import PositionState


def test_profit_protection_exits_after_two_percent_gain_fades() -> None:
    exits = plan_position_exits(
        [PositionState("AAA", 10.0, 4, 9.96, 10.25)],
        TradingSettings(),
    )

    assert [(item.ticker, item.quantity, item.exit_reason) for item in exits] == [
        ("AAA", 4, "PROFIT_PROTECTION")
    ]


def test_early_negative_exit_after_ten_minutes() -> None:
    now = datetime(2026, 6, 29, 23, 0, 0)
    exits = plan_position_exits(
        [
            PositionState(
                "AAA",
                10.0,
                3,
                9.84,
                10.0,
                entry_time=now - timedelta(minutes=10),
            )
        ],
        TradingSettings(),
        now=now,
    )

    assert [(item.ticker, item.quantity, item.exit_reason) for item in exits] == [
        ("AAA", 3, "EARLY_NEGATIVE_EXIT")
    ]


def test_time_stop_exits_negative_position_after_thirty_minutes() -> None:
    now = datetime(2026, 6, 29, 23, 30, 0)
    exits = plan_position_exits(
        [
            PositionState(
                "AAA",
                10.0,
                2,
                9.99,
                10.1,
                entry_time=(now - timedelta(minutes=30)).isoformat(),
            )
        ],
        TradingSettings(early_negative_exit_enabled=False),
        now=now,
    )

    assert [(item.ticker, item.quantity, item.exit_reason) for item in exits] == [
        ("AAA", 2, "TIME_STOP_EXIT")
    ]


def test_missing_entry_time_keeps_existing_exit_logic() -> None:
    exits = plan_position_exits(
        [PositionState("AAA", 10.0, 2, 9.99, 10.1)],
        TradingSettings(
            early_negative_exit_enabled=True,
            time_stop_exit_enabled=True,
            profit_protection_exit_enabled=False,
        ),
    )

    assert exits == []


def test_eod_and_stop_loss_keep_priority_over_early_exits() -> None:
    now = datetime(2026, 6, 29, 23, 30, 0)
    position = PositionState(
        "AAA",
        10.0,
        2,
        9.6,
        10.3,
        entry_time=now - timedelta(minutes=30),
    )

    regular = plan_position_exits([position], TradingSettings(), now=now)
    eod = plan_position_exits([position], TradingSettings(), end_of_day=True, now=now)

    assert [item.exit_reason for item in regular] == ["STOP_LOSS"]
    assert [item.exit_reason for item in eod] == ["EOD"]


def test_position_holding_minutes_handles_naive_and_iso_entry_time() -> None:
    now = datetime(2026, 6, 29, 23, 30, 0)
    position = PositionState(
        "AAA",
        10.0,
        1,
        10.0,
        10.0,
        entry_time="2026-06-29 23:00:00",
    )

    assert position_holding_minutes(position, now=now) == 30.0
