from trading_bot.adapters.chart_history import YahooChartScorer
from trading_bot.adapters.breakout_history import KisBreakoutHistory
from trading_bot.adapters.context import YahooMarketContextSource
from trading_bot.adapters.market_data import KisDailyVolumeHistory, KisScreeningMarketData
from trading_bot.chart_models import PriceBar
from trading_bot.chart_scoring import chart_pattern_score
from trading_bot.models import RankedStock


def test_kis_screening_market_data_maps_quote_and_volume_history() -> None:
    class Kis:
        def ranked_gainers(self) -> list:
            return [RankedStock("AAA", 2)]

        def ranked_trade_volume(self) -> list:
            return [RankedStock("AAA", 4)]

        def quote(self, _: str) -> dict[str, str]:
            return {
                "last": "12.30",
                "open": "11.00",
                "base": "10.00",
                "tvol": "3,000",
                "rate": "4.00",
            }

    class Context:
        def market_context(self) -> object:
            return object()

    class History:
        def average_daily_volume(self, ticker: str, sessions: int) -> float:
            assert (ticker, sessions) == ("AAA", 20)
            return 2000

    market = KisScreeningMarketData(Kis(), Context(), History())
    market.ranked_gainers()
    market.ranked_turnover()

    snapshot = market.candidate_snapshots(["AAA"])["AAA"]

    assert snapshot.price_usd == 12.3
    assert snapshot.opening_price_change == 0.04
    assert snapshot.opening_volume_ratio == 1.5
    assert (snapshot.gain_rank, snapshot.turnover_rank) == (2, 4)


def test_kis_screening_market_data_reads_open_from_daily_price_when_quote_omits_it() -> None:
    class Kis:
        def quote(self, _: str) -> dict[str, str]:
            return {"last": "12.30", "base": "10.00", "tvol": "3,000", "rate": "4.00"}

        def daily_prices(self, _: str) -> list[dict[str, str]]:
            return [{"open": "11.00"}]

    class Context:
        def market_context(self) -> object:
            return object()

    class History:
        def average_daily_volume(self, ticker: str, sessions: int) -> float:
            return 2000

    market = KisScreeningMarketData(Kis(), Context(), History())
    market._gain_ranks = {"AAA": 2}
    market._volume_ranks = {"AAA": 4}

    assert market.candidate_snapshots(["AAA"])["AAA"].open_price_usd == 11


def test_kis_screening_market_data_skips_candidates_without_history() -> None:
    class Kis:
        def quote(self, ticker: str) -> dict[str, str]:
            return {"last": "12.30", "open": "11.00", "base": "10.00", "tvol": "3,000"}

    class Context:
        def market_context(self) -> object:
            return object()

    class History:
        def average_daily_volume(self, ticker: str, sessions: int) -> float:
            raise ValueError(f"{ticker} has fewer than {sessions} volume rows")

    market = KisScreeningMarketData(Kis(), Context(), History())
    market._gain_ranks = {"NEW": 1}
    market._volume_ranks = {"NEW": 1}

    assert market.candidate_snapshots(["NEW"]) == {}


def test_kis_daily_volume_history_averages_twenty_daily_rows() -> None:
    class Kis:
        def daily_prices(self, _: str) -> list[dict[str, str]]:
            return [{"tvol": str(value)} for value in range(1, 22)]

    history = KisDailyVolumeHistory(Kis())

    assert history.average_daily_volume("AAA", 20) == 10.5


def test_yahoo_market_context_calculates_nasdaq_ma20_and_fx_change() -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes: list[float]) -> None:
            self.closes = closes

        def history(self, period: str) -> History:
            assert period in {"1mo", "5d"}
            return History(Close=self.closes)

    tickers = {
        "^IXIC": Ticker([float(value) for value in range(1, 22)]),
        "USDKRW=X": Ticker([1300.0, 1326.0]),
    }
    context = YahooMarketContextSource(ticker_factory=tickers.__getitem__).market_context()

    assert context.nasdaq_price_usd == 21
    assert context.nasdaq_ma20_usd == 11.5
    assert round(context.fx_change_rate, 4) == 0.02


def test_chart_pattern_score_stays_in_range_for_uptrend() -> None:
    bars = [
        PriceBar(close=10 + value * 0.2, high=10.2 + value * 0.2, low=9.8 + value * 0.2)
        for value in range(45)
    ]

    assert 0 <= chart_pattern_score(bars) <= 100


def test_yahoo_chart_scorer_reads_ohlc_history() -> None:
    class History(dict):
        pass

    class Ticker:
        def history(self, period: str, interval: str) -> History:
            assert (period, interval) == ("3mo", "1d")
            closes = [10 + value * 0.1 for value in range(45)]
            return History(
                Close=closes,
                High=[value + 0.2 for value in closes],
                Low=[value - 0.2 for value in closes],
            )

    scorer = YahooChartScorer(ticker_factory=lambda _: Ticker())

    assert 0 <= scorer.score("AAA") <= 100


def test_kis_breakout_history_combines_quote_and_previous_daily_range() -> None:
    class Kis:
        def quote(self, ticker: str) -> dict[str, str]:
            assert ticker == "AAA"
            return {"last": "12.50", "open": "11.00"}

        def daily_prices(self, ticker: str) -> list[dict[str, str]]:
            assert ticker == "AAA"
            return [{"high": "12.00", "low": "8.00"}]

    assert KisBreakoutHistory(Kis()).breakout_input("AAA") == (12.5, 11, 12, 8)


def test_kis_breakout_history_uses_daily_open_when_quote_has_no_open() -> None:
    class Kis:
        def quote(self, _: str) -> dict[str, str]:
            return {"last": "12.50"}

        def daily_prices(self, _: str) -> list[dict[str, str]]:
            return [
                {"open": "11.00", "high": "13.00", "low": "10.00"},
                {"open": "10.00", "high": "12.00", "low": "8.00"},
            ]

    assert KisBreakoutHistory(Kis()).breakout_input("AAA") == (12.5, 11, 12, 8)
