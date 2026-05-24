from trading_bot.config import TradingSettings
from trading_bot.list_buy_planner import collect_ranked_buy_intents
from trading_bot.models import AccountState, BuyIntent, RankedStock


def test_ranked_list_collector_uses_price_range_and_small_mock_allocations() -> None:
    quotes = {
        "PENNY": {"last": "1.50"},
        "AAA": {"last": "25.00"},
        "BBB": {"last": "10.00"},
        "CCC": {"last": "20.00"},
    }

    intents = collect_ranked_buy_intents(
        [RankedStock(ticker, rank) for rank, ticker in enumerate(quotes, 1)],
        quotes.__getitem__,
        AccountState(10000, 10000, 0, 0, 0),
        TradingSettings(),
        limit=2,
    )

    assert intents == [
        BuyIntent("AAA", 4, 25, 100, 0.01),
        BuyIntent("BBB", 10, 10, 100, 0.01),
    ]
