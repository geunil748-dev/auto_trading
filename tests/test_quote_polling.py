from trading_bot.config import TradingSettings
from trading_bot.models import PositionState, SellIntent
from trading_bot.quote_polling import PollingExitMonitor


def test_polling_exit_monitor_refreshes_highs_and_plans_exits() -> None:
    prices = {"AAA": 12.2, "BBB": 11.5}
    positions = [
        PositionState("AAA", 10, 2, 12, 12),
        PositionState("BBB", 10, 1, 11.5, 12),
    ]

    refreshed, exits = PollingExitMonitor(prices.__getitem__, TradingSettings()).poll(
        positions
    )

    assert refreshed[0].high_price_usd == 12.2
    assert [(item.ticker, item.exit_reason) for item in exits] == [
        ("BBB", "TRAILING_STOP")
    ]


def test_polling_exit_monitor_marks_end_of_day_positions_for_exit() -> None:
    refreshed, exits = PollingExitMonitor(
        price_reader=lambda _: 11.2,
        settings=TradingSettings(),
    ).poll([PositionState("AAA", 10, 2, 11, 12)], end_of_day=True)

    assert refreshed == [PositionState("AAA", 10, 2, 11.2, 12)]
    assert exits == [SellIntent("AAA", 2, 11.2, "EOD")]
