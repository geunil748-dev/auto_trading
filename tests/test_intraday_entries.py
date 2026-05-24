from trading_bot.config import TradingSettings
from trading_bot.intraday_entries import limited_intraday_buy_intents
from trading_bot.models import BuyIntent, PositionState


def intent(ticker: str) -> BuyIntent:
    return BuyIntent(ticker, 1, 10, 10, 0.01)


def test_intraday_entries_skip_holdings_and_limit_each_round() -> None:
    intents = limited_intraday_buy_intents(
        [intent("AAA"), intent("BBB"), intent("CCC")],
        positions=[PositionState("AAA", 10, 1, 10.1, 10.1)],
        submitted_tickers=["ccc"],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=0,
        settings=TradingSettings(max_intraday_buy_intents_per_round=1),
    )

    assert [item.ticker for item in intents] == ["BBB"]


def test_intraday_entries_stop_after_daily_round_limit() -> None:
    intents = limited_intraday_buy_intents(
        [intent("AAA")],
        positions=[],
        submitted_tickers=[],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=2,
        settings=TradingSettings(max_intraday_entry_rounds=2),
    )

    assert intents == []


def test_intraday_entries_allow_profitable_pyramiding_once() -> None:
    intents = limited_intraday_buy_intents(
        [intent("AAA")],
        positions=[PositionState("AAA", 10, 1, 10.31, 10.31)],
        submitted_tickers=["AAA"],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=0,
        settings=TradingSettings(),
    )

    assert [item.ticker for item in intents] == ["AAA"]


def test_intraday_entries_block_unfilled_or_repeated_pyramiding() -> None:
    settings = TradingSettings()

    assert limited_intraday_buy_intents(
        [intent("AAA")],
        positions=[PositionState("AAA", 10, 1, 10.31, 10.31)],
        submitted_tickers=[],
        add_on_tickers=[],
        unfilled_tickers=["AAA"],
        completed_rounds=0,
        settings=settings,
    ) == []
    assert limited_intraday_buy_intents(
        [intent("AAA")],
        positions=[PositionState("AAA", 10, 1, 10.31, 10.31)],
        submitted_tickers=[],
        add_on_tickers=["AAA"],
        unfilled_tickers=[],
        completed_rounds=0,
        settings=settings,
    ) == []
