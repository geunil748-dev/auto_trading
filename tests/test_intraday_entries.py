from trading_bot.config import TradingSettings
from trading_bot.intraday_entries import (
    NO_ORDER_ALREADY_SUBMITTED,
    NO_ORDER_INTRADAY_ROUND_LIMIT,
    NO_ORDER_PYRAMIDING_BLOCKED,
    NO_ORDER_ROUND_CAP_REACHED,
    NO_ORDER_UNFILLED_ORDER,
    limited_intraday_buy_intents,
    limited_intraday_buy_intents_with_diagnostics,
)
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
        settings=TradingSettings(enable_pyramiding=True),
    )

    assert [item.ticker for item in intents] == ["AAA"]


def test_intraday_entries_block_pyramiding_when_disabled() -> None:
    intents = limited_intraday_buy_intents(
        [intent("AAA")],
        positions=[PositionState("AAA", 10, 1, 10.31, 10.31)],
        submitted_tickers=["AAA"],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=0,
        settings=TradingSettings(enable_pyramiding=False),
    )

    assert intents == []


def test_intraday_entries_block_unfilled_or_repeated_pyramiding() -> None:
    settings = TradingSettings(enable_pyramiding=True)

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


def test_intraday_entries_explain_order_not_submitted_reasons() -> None:
    accepted, diagnostics = limited_intraday_buy_intents_with_diagnostics(
        [intent("AAA"), intent("BBB"), intent("CCC"), intent("DDD"), intent("EEE")],
        positions=[PositionState("DDD", 10, 1, 10.1, 10.1)],
        submitted_tickers=["BBB"],
        add_on_tickers=[],
        unfilled_tickers=["AAA"],
        completed_rounds=0,
        settings=TradingSettings(max_intraday_buy_intents_per_round=1),
    )

    assert [item.ticker for item in accepted] == ["CCC"]
    assert [(item.ticker, item.reason) for item in diagnostics] == [
        ("AAA", NO_ORDER_UNFILLED_ORDER),
        ("BBB", NO_ORDER_ALREADY_SUBMITTED),
        ("DDD", NO_ORDER_ROUND_CAP_REACHED),
        ("EEE", NO_ORDER_ROUND_CAP_REACHED),
    ]


def test_intraday_entries_explain_round_limit_and_pyramiding() -> None:
    _, round_diagnostics = limited_intraday_buy_intents_with_diagnostics(
        [intent("AAA")],
        positions=[],
        submitted_tickers=[],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=2,
        settings=TradingSettings(max_intraday_entry_rounds=2),
    )
    _, pyramiding_diagnostics = limited_intraday_buy_intents_with_diagnostics(
        [intent("BBB")],
        positions=[PositionState("BBB", 10, 1, 10.1, 10.1)],
        submitted_tickers=[],
        add_on_tickers=[],
        unfilled_tickers=[],
        completed_rounds=0,
        settings=TradingSettings(enable_pyramiding=False),
    )

    assert round_diagnostics[0].reason == NO_ORDER_INTRADAY_ROUND_LIMIT
    assert pyramiding_diagnostics[0].reason == NO_ORDER_PYRAMIDING_BLOCKED
