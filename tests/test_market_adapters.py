import json
import logging
from datetime import UTC, datetime, timedelta

from trading_bot.adapters.chart_history import YahooChartScorer
from trading_bot.adapters.breakout_history import KisBreakoutHistory
from trading_bot.adapters.context import YahooMarketContextSource
from trading_bot.adapters.market_data import KisDailyVolumeHistory, KisScreeningMarketData
from trading_bot.chart_models import PriceBar
from trading_bot.chart_scoring import chart_pattern_score
from trading_bot.models import RankedStock


def test_kis_screening_market_data_maps_quote_and_volume_history(monkeypatch) -> None:
    class Kis:
        def __init__(self) -> None:
            self.gainers_limit: int | None = None
            self.volume_limit: int | None = None
            self.trade_value_limit: int | None = None

        def ranked_gainers(self, limit: int = 100) -> list:
            self.gainers_limit = limit
            return [RankedStock("AAA", 2)]

        def ranked_trade_volume(self, limit: int = 100) -> list:
            self.volume_limit = limit
            return [RankedStock("AAA", 4)]

        def ranked_trade_value(self, limit: int = 100) -> list:
            self.trade_value_limit = limit
            return [RankedStock("AAA", 5)]

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

    monkeypatch.setattr("trading_bot.adapters.market_data._regular_session_elapsed_fraction", lambda: 1.0)
    kis = Kis()
    market = KisScreeningMarketData(kis, Context(), History())
    market.ranked_gainers(220)
    market.ranked_turnover(230)
    market.ranked_trade_value(240)

    snapshot = market.candidate_snapshots(["AAA"])["AAA"]

    assert snapshot.price_usd == 12.3
    assert snapshot.opening_price_change == 0.04
    assert snapshot.opening_volume_ratio == 1.5
    assert (snapshot.gain_rank, snapshot.turnover_rank) == (2, 4)
    assert market.last_quote_requested_count == 1
    assert market.last_daily_requested_count == 1
    assert kis.gainers_limit == 220
    assert kis.volume_limit == 230
    assert kis.trade_value_limit == 240


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
    assert market.last_quote_requested_count == 1
    assert market.last_daily_requested_count == 2


def test_kis_screening_market_data_uses_fallback_rank_for_union_only_ticker() -> None:
    class Kis:
        def quote(self, _: str) -> dict[str, str]:
            return {
                "last": "12.30",
                "open": "11.00",
                "base": "10.00",
                "tvol": "3,000",
            }

    class Context:
        def market_context(self) -> object:
            return object()

    class History:
        def average_daily_volume(self, ticker: str, sessions: int) -> float:
            return 2000

    market = KisScreeningMarketData(Kis(), Context(), History())
    market._gain_ranks = {"AAA": 2}
    market._volume_ranks = {"BBB": 4}

    snapshot = market.candidate_snapshots(["AAA"])["AAA"]

    assert snapshot.gain_rank == 2
    assert snapshot.turnover_rank == 54


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

    errors: list[tuple[str, str]] = []
    market = KisScreeningMarketData(
        Kis(),
        Context(),
        History(),
        on_snapshot_error=lambda ticker, reason: errors.append((ticker, reason)),
    )
    market._gain_ranks = {"NEW": 1}
    market._volume_ranks = {"NEW": 1}

    assert market.candidate_snapshots(["NEW"]) == {}
    assert errors == [("NEW", "daily_prices_insufficient")]
    assert market.last_quote_requested_count == 1
    assert market.last_daily_requested_count == 1


def test_kis_screening_market_data_quote_failure_skips_only_failed_candidate() -> None:
    class Kis:
        def quote(self, ticker: str) -> dict[str, str]:
            if ticker == "BAD":
                raise TimeoutError("slow quote")
            return {
                "last": "12.30",
                "open": "11.00",
                "base": "10.00",
                "tvol": "3,000",
            }

    class Context:
        def market_context(self) -> object:
            return object()

    class History:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def average_daily_volume(self, ticker: str, sessions: int) -> float:
            self.calls.append(ticker)
            return 2000

    history = History()
    errors: list[tuple[str, str]] = []
    market = KisScreeningMarketData(
        Kis(),
        Context(),
        history,
        on_snapshot_error=lambda ticker, reason: errors.append((ticker, reason)),
    )
    market._gain_ranks = {"BAD": 1, "AAA": 2}
    market._volume_ranks = {"BAD": 1, "AAA": 2}

    snapshots = market.candidate_snapshots(["BAD", "AAA"])

    assert list(snapshots) == ["AAA"]
    assert history.calls == ["AAA"]
    assert errors == [("BAD", "quote_timeout")]
    assert market.last_quote_requested_count == 2
    assert market.last_daily_requested_count == 1


def test_kis_daily_volume_history_averages_twenty_daily_rows() -> None:
    class Kis:
        def daily_prices(self, _: str) -> list[dict[str, str]]:
            return [{"tvol": str(value)} for value in range(1, 22)]

    history = KisDailyVolumeHistory(Kis())

    assert history.average_daily_volume("AAA", 20) == 10.5


def test_yahoo_market_context_calculates_nasdaq_ma20_and_fx_change(tmp_path) -> None:
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
    context = YahooMarketContextSource(
        ticker_factory=tickers.__getitem__,
        cache_path=tmp_path / "last_good_market_context.json",
    ).market_context()

    assert context.nasdaq_price_usd == 21
    assert context.nasdaq_ma20_usd == 11.5
    assert round(context.fx_change_rate, 4) == 0.02


def test_yahoo_market_context_fx_ticker_error_falls_back_to_zero(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def history(self, period: str) -> History:
            assert period == "1mo"
            return History(Close=[float(value) for value in range(1, 22)])

    def ticker_factory(symbol: str):
        if symbol == "USDKRW=X":
            raise RuntimeError("fx source unavailable")
        return Ticker()

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=ticker_factory,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.fx_change_rate == 0.0
    assert context.nasdaq_price_usd == 21
    assert "MARKET_CONTEXT_FX_FALLBACK" in caplog.text
    assert "FX 조회 실패로 fx_change_rate=0.0 fallback 적용" in caplog.text
    assert "RuntimeError" in caplog.text


def test_yahoo_market_context_fx_history_error_falls_back_to_zero(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class NasdaqTicker:
        def history(self, period: str) -> History:
            assert period == "1mo"
            return History(Close=[float(value) for value in range(1, 22)])

    class FxTicker:
        def history(self, period: str) -> History:
            assert period == "5d"
            raise RuntimeError("fx history unavailable")

    tickers = {
        "^IXIC": NasdaqTicker(),
        "USDKRW=X": FxTicker(),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.fx_change_rate == 0.0
    assert "MARKET_CONTEXT_FX_FALLBACK" in caplog.text
    assert "reason=FX_HISTORY_FETCH_FAILED" in caplog.text
    assert "RuntimeError" in caplog.text


def test_yahoo_market_context_fx_empty_history_falls_back_to_zero(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes: list[float]) -> None:
            self.closes = closes

        def history(self, period: str) -> History:
            return History(Close=self.closes)

    tickers = {
        "^IXIC": Ticker([float(value) for value in range(1, 22)]),
        "USDKRW=X": Ticker([]),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.fx_change_rate == 0.0
    assert "MARKET_CONTEXT_FX_FALLBACK" in caplog.text
    assert "reason=FX_HISTORY_INSUFFICIENT" in caplog.text


def test_yahoo_market_context_fx_invalid_history_falls_back_to_zero(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, history) -> None:
            self.item_history = history

        def history(self, period: str):
            return self.item_history

    fx_histories = [
        History(AdjClose=[1300.0, 1326.0]),
        History(Close=[float("nan"), 1326.0]),
        History(Close=[1300.0]),
        History(Close=[0.0, 1326.0]),
        History(Close=[1300.0, 0.0]),
    ]

    for index, fx_history in enumerate(fx_histories):
        caplog.clear()
        tickers = {
            "^IXIC": Ticker(History(Close=[float(value) for value in range(1, 22)])),
            "USDKRW=X": Ticker(fx_history),
        }
        with caplog.at_level(logging.WARNING):
            context = YahooMarketContextSource(
                ticker_factory=tickers.__getitem__,
                cache_path=tmp_path / f"last_good_market_context_{index}.json",
            ).market_context()

        assert context.fx_change_rate == 0.0
        assert "MARKET_CONTEXT_FX_FALLBACK" in caplog.text


def test_yahoo_market_context_uses_fallback_period_when_one_month_is_short(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period
            self.periods: list[str] = []

        def history(self, period: str) -> History:
            self.periods.append(period)
            return History(Close=self.closes_by_period[period])

    tickers = {
        "^IXIC": Ticker(
            {
                "1mo": [1.0, 2.0, float("nan")],
                "3mo": [float(value) for value in range(1, 26)],
                "6mo": [float(value) for value in range(1, 31)],
            }
        ),
        "USDKRW=X": Ticker({"5d": [1300.0, 1326.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.nasdaq_price_usd == 25
    assert context.nasdaq_ma20_usd == 15.5
    assert round(context.fx_change_rate, 4) == 0.02
    assert tickers["^IXIC"].periods == ["1mo", "3mo"]
    assert "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK" in caplog.text
    assert "fallback_period=3mo" in caplog.text
    assert "MARKET_CONTEXT_DEGRADED_USED symbol=^IXIC" not in caplog.text


def test_yahoo_market_context_uses_six_month_fallback_when_three_month_is_short(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period
            self.periods: list[str] = []

        def history(self, period: str) -> History:
            self.periods.append(period)
            return History(Close=self.closes_by_period[period])

    tickers = {
        "^IXIC": Ticker(
            {
                "1mo": [1.0, 2.0, float("nan")],
                "3mo": [float(value) for value in range(1, 10)],
                "6mo": [float(value) for value in range(1, 31)],
            }
        ),
        "USDKRW=X": Ticker({"5d": [1300.0, 1326.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.status == "ok"
    assert context.source == "fresh"
    assert context.period == "6mo"
    assert context.nasdaq_price_usd == 30
    assert context.nasdaq_ma20_usd == 20.5
    assert tickers["^IXIC"].periods == ["1mo", "3mo", "6mo"]
    assert "fallback_period=6mo" in caplog.text
    assert "MARKET_CONTEXT_DEGRADED_USED symbol=^IXIC" not in caplog.text


def test_yahoo_market_context_saves_fresh_last_good_cache(caplog, tmp_path) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes: list[float]) -> None:
            self.closes = closes

        def history(self, period: str) -> History:
            return History(Close=self.closes)

    cache_path = tmp_path / "last_good_market_context.json"
    tickers = {
        "^IXIC": Ticker([float(value) for value in range(1, 22)]),
        "USDKRW=X": Ticker([1300.0, 1326.0]),
    }

    with caplog.at_level(logging.INFO):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=cache_path,
        ).market_context()

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert context.source == "fresh"
    assert payload["source"] == "fresh"
    assert payload["last_close"] == 21
    assert payload["ma20"] == 11.5
    assert "LAST_GOOD_MARKET_CONTEXT_SAVED" in caplog.text


def test_yahoo_market_context_uses_last_good_cache_when_primary_history_is_short(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period

        def history(self, period: str) -> History:
            return History(Close=self.closes_by_period.get(period, []))

    cache_path = tmp_path / "last_good_market_context.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "fresh",
                "symbol": "^IXIC",
                "saved_at": datetime.now(UTC).isoformat(),
                "close_count": 63,
                "period": "3mo",
                "ma20": 100.0,
                "last_close": 105.0,
                "fx_change_rate": 0.0,
            }
        ),
        encoding="utf-8",
    )
    tickers = {
        "^IXIC": Ticker({"1mo": [], "3mo": [], "6mo": []}),
        "USDKRW=X": Ticker({"5d": [1300.0, 1300.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=cache_path,
        ).market_context()

    assert context.status == "cached"
    assert context.source == "last_good_cache"
    assert context.nasdaq_price_usd == 105.0
    assert abs(context.nasdaq_ma20_usd - 100.0) < 1e-9
    assert "LAST_GOOD_MARKET_CONTEXT_USED" in caplog.text


def test_yahoo_market_context_uses_qqq_proxy_when_primary_and_cache_fail(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period

        def history(self, period: str) -> History:
            return History(Close=self.closes_by_period.get(period, []))

    tickers = {
        "^IXIC": Ticker({"1mo": [], "3mo": [], "6mo": []}),
        "QQQ": Ticker({"3mo": [float(value) for value in range(1, 22)]}),
        "USDKRW=X": Ticker({"5d": [1300.0, 1300.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "missing_last_good.json",
        ).market_context()

    assert context.status == "ok"
    assert context.source == "proxy"
    assert context.symbol == "QQQ"
    assert context.proxy_for == "^IXIC"
    assert context.confidence == "medium"
    assert "MARKET_CONTEXT_PROXY_USED symbol=QQQ" in caplog.text


def test_yahoo_market_context_uses_ndx_proxy_when_qqq_fails(caplog, tmp_path) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period

        def history(self, period: str) -> History:
            return History(Close=self.closes_by_period.get(period, []))

    tickers = {
        "^IXIC": Ticker({"1mo": [], "3mo": [], "6mo": []}),
        "QQQ": Ticker({"3mo": [], "6mo": []}),
        "^NDX": Ticker({"3mo": [float(value) for value in range(1, 22)]}),
        "USDKRW=X": Ticker({"5d": [1300.0, 1300.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "missing_last_good.json",
        ).market_context()

    assert context.source == "proxy"
    assert context.symbol == "^NDX"
    assert "MARKET_CONTEXT_PROXY_FAILED symbol=QQQ" in caplog.text
    assert "MARKET_CONTEXT_PROXY_USED symbol=^NDX" in caplog.text


def test_yahoo_market_context_skips_stale_last_good_cache_before_proxy(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period

        def history(self, period: str) -> History:
            return History(Close=self.closes_by_period.get(period, []))

    cache_path = tmp_path / "last_good_market_context.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "fresh",
                "symbol": "^IXIC",
                "saved_at": (datetime.now(UTC) - timedelta(hours=72)).isoformat(),
                "close_count": 63,
                "period": "3mo",
                "ma20": 100.0,
                "last_close": 105.0,
            }
        ),
        encoding="utf-8",
    )
    tickers = {
        "^IXIC": Ticker({"1mo": [], "3mo": [], "6mo": []}),
        "QQQ": Ticker({"3mo": [float(value) for value in range(1, 22)]}),
        "USDKRW=X": Ticker({"5d": [1300.0, 1300.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=cache_path,
        ).market_context()

    assert context.source == "proxy"
    assert context.symbol == "QQQ"
    assert "LAST_GOOD_MARKET_CONTEXT_STALE" in caplog.text


def test_yahoo_market_context_uses_neutral_degraded_context_when_history_stays_short(
    caplog,
    tmp_path,
) -> None:
    class History(dict):
        pass

    class Ticker:
        def __init__(self, closes_by_period: dict[str, list[float]]) -> None:
            self.closes_by_period = closes_by_period

        def history(self, period: str) -> History:
            return History(Close=self.closes_by_period.get(period, []))

    tickers = {
        "^IXIC": Ticker(
            {
                "1mo": [],
                "3mo": [10.0, float("nan"), 11.0],
                "6mo": [float(value) for value in range(1, 20)],
            }
        ),
        "USDKRW=X": Ticker({"5d": [1300.0, 1300.0]}),
    }

    with caplog.at_level(logging.WARNING):
        context = YahooMarketContextSource(
            ticker_factory=tickers.__getitem__,
            cache_path=tmp_path / "last_good_market_context.json",
        ).market_context()

    assert context.nasdaq_price_usd == 19
    assert context.nasdaq_ma20_usd == 19
    assert context.fx_change_rate == 0
    assert "NASDAQ_HISTORY_INSUFFICIENT_FALLBACK" in caplog.text
    assert "MARKET_CONTEXT_DEGRADED_USED symbol=^IXIC" in caplog.text
    assert "reason=NASDAQ_HISTORY_INSUFFICIENT" in caplog.text


def test_yahoo_market_context_reads_close_from_multiindex_like_history(tmp_path) -> None:
    class Columns:
        def get_level_values(self, level: int) -> list[str]:
            return ["Ticker"] if level == 0 else ["Close"]

    class MultiIndexHistory:
        columns = Columns()

        def __getitem__(self, _key: str):
            raise KeyError("Close")

        def xs(self, key: str, axis: int, level: int) -> list[float]:
            assert (key, axis, level) == ("Close", 1, 1)
            return [float(value) for value in range(1, 22)]

    class History(dict):
        pass

    class Ticker:
        def __init__(self, history) -> None:
            self.item_history = history

        def history(self, period: str):
            return self.item_history

    tickers = {
        "^IXIC": Ticker(MultiIndexHistory()),
        "USDKRW=X": Ticker(History(Close=[1300.0, 1326.0])),
    }

    context = YahooMarketContextSource(
        ticker_factory=tickers.__getitem__,
        cache_path=tmp_path / "last_good_market_context.json",
    ).market_context()

    assert context.nasdaq_price_usd == 21
    assert context.nasdaq_ma20_usd == 11.5


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

    result = KisBreakoutHistory(Kis()).breakout_input("AAA")

    assert (
        result.last_price_usd,
        result.open_price_usd,
        result.previous_high_usd,
        result.previous_low_usd,
    ) == (12.5, 11, 12, 8)


def test_kis_breakout_history_uses_daily_open_when_quote_has_no_open() -> None:
    class Kis:
        def quote(self, _: str) -> dict[str, str]:
            return {"last": "12.50"}

        def daily_prices(self, _: str) -> list[dict[str, str]]:
            return [
                {"open": "11.00", "high": "13.00", "low": "10.00"},
                {"open": "10.00", "high": "12.00", "low": "8.00"},
            ]

    result = KisBreakoutHistory(Kis()).breakout_input("AAA")

    assert (
        result.last_price_usd,
        result.open_price_usd,
        result.previous_high_usd,
        result.previous_low_usd,
    ) == (12.5, 11, 12, 8)
