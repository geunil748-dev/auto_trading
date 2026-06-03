from datetime import date, datetime, timedelta, timezone

import pytest

from trading_bot.adapters.kis_overseas import KisOverseasClient
from trading_bot.adapters.kis_orders import (
    KisMockBuySubmitter,
    KisMockOrderCanceller,
    KisMockSellSubmitter,
)
from trading_bot.adapters.news_sentiment import YahooNewsSentimentSource
from trading_bot.adapters.scoring import NewsChartScoringProvider
from trading_bot.adapters.yahoo_news import YahooFinanceNewsSource
from trading_bot.config import KisSettings, TradingSettings, save_runtime_risk_settings
from trading_bot.models import (
    BotLog,
    CandidateEvaluation,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    FillRecord,
    NewsRecord,
    ScoreRecord,
    Sentiment,
    TradeRecord,
    BuyIntent,
    SellIntent,
)
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.retry import RetryPolicy, call_with_retry
from trading_bot.runtime_settings_store import RuntimeSettingsStore
from trading_bot.sentiment import KeywordHeadlineSentiment


class Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]] | tuple[object, ...]]] = []

    def executemany(self, sql: str, rows: list[tuple[object, ...]]) -> None:
        self.calls.append((sql, rows))

    def execute(self, sql: str, row: tuple[object, ...]) -> None:
        self.calls.append((sql, row))

    def fetchall(self) -> list[tuple[object, ...]]:
        return [("AAA", 180, 4.2)]


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self.db_cursor = cursor
        self.commits = 0
        self.closed = False

    def cursor(self) -> Cursor:
        return self.db_cursor

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def candidate() -> CandidateSnapshot:
    return CandidateSnapshot("AAA", 12, 11, 10, 0.04, 1.8, 1, 2)


def test_retry_policy_delays_before_request_and_between_failures() -> None:
    sleeps: list[float] = []
    calls = 0

    def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("retry")
        return "ok"

    result = call_with_retry(
        flaky,
        RetryPolicy(attempts=2, retry_delay_seconds=3, request_delay_seconds=0.5),
        retryable=(TimeoutError,),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == [0.5, 3]


def test_scoring_adapter_retries_news_before_combining_chart_score() -> None:
    calls = 0

    def sentiments(_: str) -> tuple[Sentiment, ...]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary")
        return (Sentiment.POSITIVE, Sentiment.NEUTRAL)

    scorer = NewsChartScoringProvider(
        sentiments,
        chart_score=lambda _: 72,
        retry_policy=RetryPolicy(attempts=2, retry_delay_seconds=0),
    )

    assert scorer.score(candidate()) == ScoreRecord("AAA", 50, 72)


def test_news_sentiment_uses_cached_scores_before_fetching_yahoo() -> None:
    class Cache:
        def recent_news(self, ticker, fetched_after):
            assert ticker == "AAA"
            assert fetched_after <= datetime(2026, 5, 27, 1, 0, tzinfo=timezone.utc)
            return [NewsRecord("AAA", "AAA shares surge", sentiment_score=1)]

        def save_news(self, records):
            raise AssertionError("fresh news should not be fetched when cache is warm")

        def update_sentiments(self, ticker, sentiments):
            raise AssertionError("cached scored news should not be reclassified")

    class News:
        def recent_news(self, ticker):
            raise AssertionError("Yahoo news should not be called when cache is warm")

    source = YahooNewsSentimentSource(
        News(),
        KeywordHeadlineSentiment(),
        cache=Cache(),
        now=lambda: datetime(2026, 5, 27, 1, 30, tzinfo=timezone.utc),
        cache_ttl_minutes=30,
    )

    assert source.sentiments("AAA") == (Sentiment.POSITIVE,)


def test_news_sentiment_saves_and_scores_fresh_news_when_cache_is_empty() -> None:
    class Cache:
        def __init__(self) -> None:
            self.saved = []
            self.updated = []

        def recent_news(self, ticker, fetched_after):
            return []

        def save_news(self, records):
            self.saved.extend(records)

        def update_sentiments(self, ticker, sentiments):
            self.updated.extend((ticker, title, score) for title, score in sentiments)

    class News:
        def recent_news(self, ticker):
            return [NewsRecord(ticker, "AAA beats estimates")]

    cache = Cache()
    source = YahooNewsSentimentSource(News(), KeywordHeadlineSentiment(), cache=cache)

    assert source.sentiments("AAA") == (Sentiment.POSITIVE,)
    assert [item.title for item in cache.saved] == ["AAA beats estimates"]
    assert cache.updated == [("AAA", "AAA beats estimates", 1)]


def test_sql_repository_writes_daily_rows_and_logs() -> None:
    cursors: list[Cursor] = []
    connections: list[Connection] = []

    def connect() -> Connection:
        cursor = Cursor()
        connection = Connection(cursor)
        cursors.append(cursor)
        connections.append(connection)
        return connection

    repository = SqlServerDailyRepository(connect)
    repository.save_daily_targets([DailyTarget(date(2026, 5, 22), candidate())])
    repository.save_daily_scores(
        [DailyScore(date(2026, 5, 22), ScoreRecord("AAA", 95, 80), True)]
    )
    repository.save_log(BotLog("INFO", "test", "stored"))
    repository.save_trades(
        [
            TradeRecord(
                date(2026, 5, 22),
                "AAA",
                "BUY",
                12,
                None,
                2,
                ticker_name="Alpha",
            )
        ]
    )

    assert cursors[0].calls[0][1] == [
        (date(2026, 5, 22), "AAA", "", 0.0, 0.0, 180.0, 4.0)
    ]
    assert "CREATE TABLE dbo.listed_target_snapshot" in cursors[1].calls[0][0]
    assert cursors[2].calls[0][1] == [
        (date(2026, 5, 22), "AAA", "", 12, 0.0, 0.0, 180.0, 4.0)
    ]
    assert cursors[3].calls[0][1] == [(date(2026, 5, 22), "AAA", 95, 80, 81.5, True)]
    assert cursors[5].calls[0][1][1:4] == ("INFO", "test", "stored")
    assert cursors[9].calls[0][1] == [
        (
            date(2026, 5, 22),
            "AAA",
            "Alpha",
            "BUY",
            12,
            None,
            None,
            None,
            2,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            True,
            "REQUESTED",
            0,
            2,
            None,
            None,
            None,
            "",
            None,
            None,
            None,
            "",
            "",
            "",
        )
    ]
    assert all(connection.closed for connection in connections)
    assert sum(connection.commits for connection in connections) == 9


def test_sql_repository_writes_daily_run_summary() -> None:
    cursor = Cursor()
    connection = Connection(cursor)
    repository = SqlServerDailyRepository(lambda: connection)

    repository.save_daily_run_summary(
        date(2026, 5, 22),
        TradingSettings(candidate_selection_mode="hybrid", min_total_score=40),
        12.5,
        3.4,
        2,
        1,
        4,
        3,
    )

    assert "daily_run_summary" in cursor.calls[0][0]
    assert "IF EXISTS" in cursor.calls[1][0]
    assert cursor.calls[1][1][1] == "hybrid"
    assert '"minTotalScore": 40' in cursor.calls[1][1][2]
    assert cursor.calls[1][1][3] == "LEGACY_RELAXED"
    assert len(cursor.calls[1][1][4]) == 64
    assert '"strategyVersion": "LEGACY_RELAXED"' in cursor.calls[1][1][5]
    assert cursor.calls[1][1][6:12] == (12.5, 3.4, 2, 1, 4, 3)


def test_sql_repository_writes_candidate_evaluation_and_update() -> None:
    cursors: list[Cursor] = []

    def connect() -> Connection:
        cursor = Cursor()
        cursors.append(cursor)
        return Connection(cursor)

    repository = SqlServerDailyRepository(connect)
    repository.save_candidate_evaluations(
        [
            CandidateEvaluation(
                run_id="run-1",
                evaluation_time=datetime(2026, 5, 22, 13, 30, tzinfo=timezone.utc),
                trading_date=date(2026, 5, 22),
                source="dry_run",
                symbol="AAA",
                current_price=12.5,
                selection_score=42.0,
                soft_score_adjustment=-5.0,
                final_score=37.0,
                overheat_condition_mode="HARD_FILTER",
                breakout_close_condition_mode="SOFT_SCORE",
                volume_increase_condition_mode="SOFT_SCORE",
                vwap_ma20_condition_mode="HARD_FILTER",
                vwap_ma20_condition_type="OR",
                pullback_rebreak_condition_mode="SOFT_SCORE",
                breakout_close_pass=False,
                final_score_pass=True,
                buy_allowed=False,
                buy_block_reason="VWAP_MA20_FAILED",
                buy_block_reasons='["VWAP_MA20_FAILED"]',
                hard_filter_failed_count=1,
                soft_condition_failed_count=1,
                final_decision="VWAP_MA20_FAILED",
            )
        ]
    )
    repository.mark_candidate_evaluation_order_submitted("AAA", date(2026, 5, 22), "1001")

    assert "CREATE TABLE dbo.candidate_evaluations" in cursors[0].calls[0][0]
    assert "IX_candidate_evaluations_time" in cursors[0].calls[0][0]
    assert "INSERT INTO candidate_evaluations" in cursors[1].calls[0][0]
    row = cursors[1].calls[0][1][0]
    assert row[0] == "run-1"
    assert row[4] == "AAA"
    assert row[23:25] == (-5.0, 37.0)
    assert row[39:44] == (0, 0, None, "VWAP_MA20_FAILED", '["VWAP_MA20_FAILED"]')
    assert "UPDATE candidate_evaluations" in cursors[3].calls[0][0]
    assert cursors[3].calls[0][1] == ("1001", "AAA", date(2026, 5, 22))


def test_sql_monitor_run_summaries_ignore_history_date() -> None:
    cursor = Cursor()
    repository = SqlServerMonitorRepository(lambda: Connection(cursor))

    repository.history_run_summaries(date(2026, 5, 22))

    sql, params = cursor.calls[-1]
    assert "daily_run_summary" in sql
    assert "WHERE is_mock = 1" in sql
    assert "trade_date = ?" not in sql
    assert params == (20,)


def test_sql_repository_writes_holding_snapshot() -> None:
    cursors: list[Cursor] = []

    def connect() -> Connection:
        cursor = Cursor()
        cursors.append(cursor)
        return Connection(cursor)

    repository = SqlServerDailyRepository(connect)
    repository.save_holdings(
        [
            {
                "ticker": "AAA",
                "name": "Alpha",
                "quantity": "2",
                "averagePrice": "$10.50",
                "openPrice": "$11.10",
                "closePrice": "$11.60",
                "totalPrice": "$23.20",
            }
        ],
        date(2026, 5, 22),
    )

    assert "CREATE TABLE dbo.holding_snapshot" in cursors[0].calls[0][0]
    assert "DELETE FROM holding_snapshot" in cursors[1].calls[0][0]
    assert cursors[2].calls[0][1] == [
        (
            date(2026, 5, 22),
            date(2026, 5, 22),
            "AAA",
            "Alpha",
            2,
            10.5,
            11.1,
            11.6,
            23.2,
            True,
        )
    ]


def test_sql_repository_writes_account_and_order_snapshots() -> None:
    cursors: list[Cursor] = []

    def connect() -> Connection:
        cursor = Cursor()
        cursors.append(cursor)
        return Connection(cursor)

    repository = SqlServerDailyRepository(connect)
    repository.save_account_snapshot(
        {
            "cashUsd": "$1,000.00",
            "equityUsd": "$1,250.00",
            "investedUsd": "$250.00",
            "openPositions": "1",
            "dailyProfitRate": "1.25%",
            "realizedProfitUsd": "+$15.50",
            "cashKrw": "100,000원",
            "equityKrw": "125,000원",
        },
        date(2026, 5, 22),
    )
    repository.save_order_snapshot(
        [
            {
                "time": "22:40:10",
                "ticker": "AAA",
                "name": "Alpha",
                "side": "매수",
                "quantity": "2",
                "price": "$12.50",
                "unfilled": "0",
                "orderNo": "1001",
            }
        ],
        date(2026, 5, 22),
    )

    assert "CREATE TABLE dbo.account_snapshot" in cursors[0].calls[0][0]
    assert "CREATE TABLE dbo.account_current" in cursors[1].calls[0][0]
    assert "IF EXISTS" in cursors[2].calls[0][0]
    current_params = cursors[2].calls[0][1]
    assert current_params[0] == "mock"
    assert current_params[6:8] == (100000.0, 125000.0)
    assert current_params[18:20] == (100000.0, 125000.0)
    assert cursors[3].calls[0][1] == (
        date(2026, 5, 22),
        date(2026, 5, 22),
        1000.0,
        1250.0,
        250.0,
        1,
        1.25,
        15.5,
        True,
    )
    assert "CREATE TABLE dbo.order_snapshot" in cursors[4].calls[0][0]
    assert "DELETE FROM order_snapshot" in cursors[5].calls[0][0]
    assert cursors[6].calls[0][1] == [
        (
            date(2026, 5, 22),
            date(2026, 5, 22),
            "22:40:10",
            "AAA",
            "Alpha",
            "매수",
            2,
            12.5,
            0,
            "1001",
            True,
            "FILLED",
            2,
            2,
            0,
            12.5,
            "22:40:10",
        )
    ]


def test_runtime_settings_store_saves_and_reads_settings() -> None:
    class SettingsCursor(Cursor):
        def fetchall(self) -> list[tuple[object, ...]]:
            return [("take_profit_rate", 0.1), ("min_total_score", 40.0)]

    cursor = SettingsCursor()
    connection = Connection(cursor)
    store = RuntimeSettingsStore(lambda: connection)

    store.save({"take_profit_rate": 0.1, "min_total_score": 40})
    values = store.read({"take_profit_rate", "min_total_score"})

    assert "CREATE TABLE dbo.runtime_setting" in cursor.calls[0][0]
    assert "IF EXISTS" in cursor.calls[1][0]
    assert cursor.calls[1][1] == (
        "take_profit_rate",
        0.1,
        "take_profit_rate",
        "take_profit_rate",
        0.1,
    )
    assert "FROM runtime_setting" in cursor.calls[-1][0]
    assert values == {"take_profit_rate": 0.1, "min_total_score": 40.0}


def test_save_runtime_settings_accepts_hybrid_candidate_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "MSSQL_DSN",
        "MSSQL_HOST",
        "MSSQL_DATABASE",
        "MSSQL_USERNAME",
        "MSSQL_PASSWORD",
    ):
        monkeypatch.setenv(name, "")

    payload = save_runtime_risk_settings(
        5,
        10,
        refresh_intraday_candidates=True,
        candidate_selection_mode="hybrid",
    )

    assert payload["candidateSelectionMode"] == "hybrid"
    assert payload["refreshIntradayCandidates"] is True


def test_sql_monitor_repository_reads_rows() -> None:
    cursor = Cursor()
    connection = Connection(cursor)
    rows = SqlServerMonitorRepository(lambda: connection).latest_targets(5)

    assert rows == [("AAA", 180, 4.2)]
    assert cursor.calls[0][1][0] == 5
    assert connection.closed


def test_sql_monitor_repository_falls_back_to_daily_targets_when_snapshot_is_empty() -> None:
    class SequenceCursor(Cursor):
        def __init__(self) -> None:
            super().__init__()
            self.results = [
                [],
                [(0,)],
                [("AAA", "Alpha", 180, 4.2)],
            ]

        def fetchall(self) -> list[tuple[object, ...]]:
            return self.results.pop(0)

    cursor = SequenceCursor()
    connection = Connection(cursor)
    rows = SqlServerMonitorRepository(lambda: connection).latest_targets(5)

    assert rows == [("AAA", "Alpha", 180, 4.2)]
    assert "FROM listed_target_snapshot" in cursor.calls[0][0]
    assert "FROM daily_target" in cursor.calls[2][0]


def test_sql_monitor_repository_sums_all_realized_profit() -> None:
    class ProfitCursor(Cursor):
        def fetchall(self) -> list[tuple[object, ...]]:
            return [(12.5,)]

    cursor = ProfitCursor()
    connection = Connection(cursor)

    profit = SqlServerMonitorRepository(lambda: connection).today_realized_profit()

    assert profit == 12.5
    assert "FROM fill_history" in cursor.calls[0][0]
    assert "fill_date = ?" not in cursor.calls[0][0]
    assert cursor.calls[0][1] == ()


def test_sql_monitor_repository_calculates_all_realized_profit_rate() -> None:
    class ProfitRateCursor(Cursor):
        def fetchall(self) -> list[tuple[object, ...]]:
            return [(12.5, 250.0)]

    cursor = ProfitRateCursor()
    connection = Connection(cursor)

    rate = SqlServerMonitorRepository(lambda: connection).today_realized_profit_rate()

    assert rate == 5.0
    assert "SUM(fill_amount - profit_usd)" in cursor.calls[0][0]
    assert cursor.calls[0][1] == ()


def test_sql_monitor_repository_uses_us_market_date_for_latest_trades(monkeypatch) -> None:
    cursor = Cursor()
    connection = Connection(cursor)
    monkeypatch.setattr(
        "trading_bot.repositories.current_trade_date",
        lambda: date(2026, 5, 27),
    )

    SqlServerMonitorRepository(lambda: connection).latest_trades(10)

    assert "trade_date = ?" in cursor.calls[0][0]
    assert cursor.calls[0][1] == (10, date(2026, 5, 27))


def test_sql_repository_writes_fill_rows_without_duplicates() -> None:
    cursors: list[Cursor] = []

    def connect() -> Connection:
        cursor = Cursor()
        cursors.append(cursor)
        return Connection(cursor)

    repository = SqlServerDailyRepository(connect)
    repository.save_fills(
        [
            FillRecord(
                date(2026, 5, 22),
                "AAA",
                "매수",
                2,
                12.5,
                25.0,
                "22:41:10",
                "Alpha",
                "1001",
            )
        ]
    )

    assert "CREATE TABLE dbo.fill_history" in cursors[0].calls[0][0]
    assert "IF EXISTS" in cursors[1].calls[0][0]
    assert cursors[1].calls[0][1] == (
        date(2026, 5, 22),
        "22:41:10",
        "AAA",
        "매수",
        2,
        12.5,
        True,
        None,
        None,
        None,
        None,
        "",
        "",
        "",
        date(2026, 5, 22),
        "22:41:10",
        "AAA",
        "매수",
        2,
        12.5,
        True,
        date(2026, 5, 22),
        date(2026, 5, 22),
        "22:41:10",
        "AAA",
        "Alpha",
        "매수",
        2,
        12.5,
        25.0,
        None,
        None,
        "1001",
        None,
        None,
        True,
        "",
        "",
        "",
    )


def test_kis_overseas_client_uses_official_ranking_and_quote_shapes() -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    class Http:
        def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, object]:
            calls.append((path, tr_id, params))
            if path.endswith("price-fluct"):
                return {"output2": [{"symb": "AAA"}, {"symb": "BBB"}]}
            if path.endswith("trade-vol"):
                return {"output2": [{"rsym": "CCC"}]}
            if path.endswith("trade-pbmn"):
                return {"output2": [{"symb": "DDD"}]}
            if path.endswith("inquire-ccnl"):
                return {"output": [{"pdno": "AAA"}]}
            return {"output": {"last": "12.30"}}

    client = KisOverseasClient(Http(), "NAS")

    assert [item.ticker for item in client.ranked_gainers(1)] == ["AAA"]
    assert [item.ticker for item in client.ranked_trade_volume()] == ["CCC"]
    assert [item.ticker for item in client.ranked_trade_value()] == ["DDD"]
    assert client.quote("AAA") == {"last": "12.30"}
    assert client.daily_prices("AAA") == []
    assert client.mock_order_history("12345678", "01", "20260522") == [{"pdno": "AAA"}]
    assert calls[0][2]["GUBN"] == "1"
    assert calls[1][2]["NDAY"] == "0"
    assert calls[2][1] == "HHDFS76320010"
    assert calls[2][2]["NDAY"] == "0"
    assert calls[3][2]["SYMB"] == "AAA"
    assert calls[4][2]["GUBN"] == "0"
    assert calls[5][2]["ORD_STRT_DT"] == "20260522"


def test_kis_overseas_client_uses_mock_balance_and_limit_order_shapes() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Http:
        def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, object]:
            calls.append((path, tr_id, params))
            return {"output1": [], "output2": {}}

        def post(self, path: str, tr_id: str, body: dict[str, object]) -> dict[str, object]:
            calls.append((path, tr_id, body))
            return {"output": {"ODNO": "1"}}

    client = KisOverseasClient(Http(), "NAS")
    client.balance("12345678", "01")
    result = client.limit_order("12345678", "01", "AAA", 2, 10.5, "buy")
    sell_result = client.limit_order("12345678", "01", "AAA", 2, 10.1, "sell")
    cancel = client.cancel_order("12345678", "01", "AAA", "999", 1)
    client.buyable_amount("12345678", "01", "QQQ")

    assert calls[0][1] == "VTTS3012R"
    assert calls[0][2]["OVRS_EXCG_CD"] == "NASD"
    assert calls[1][1] == "VTTT1002U"
    assert calls[1][2]["OVRS_ORD_UNPR"] == "10.50"
    assert calls[1][2]["ORD_UNPR"] == "10.50"
    assert calls[1][2]["ORD_GRNT_DVSN_CD"] == "0"
    assert result == {"output": {"ODNO": "1"}}
    assert calls[2][1] == "VTTT1001U"
    assert calls[2][2]["OVRS_ORD_UNPR"] == "10.10"
    assert calls[2][2]["ORD_UNPR"] == "10.10"
    assert calls[2][2]["SLL_TYPE"] == "00"
    assert calls[2][2]["ORD_GRNT_DVSN_CD"] == "0"
    assert sell_result == {"output": {"ODNO": "1"}}
    assert calls[3][1] == "VTTT1004U"
    assert calls[3][2]["ORGN_ODNO"] == "999"
    assert calls[3][2]["RVSE_CNCL_DVSN_CD"] == "02"
    assert calls[3][2]["OVRS_ORD_UNPR"] == "0"
    assert cancel == {"output": {"ODNO": "1"}}
    assert calls[4][1] == "VTTS3007R"
    assert calls[4][2]["ITEM_CD"] == "QQQ"


def test_kis_overseas_client_normalizes_order_ticker_and_exchange() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    class Http:
        def post(self, path: str, tr_id: str, body: dict[str, object]) -> dict[str, object]:
            calls.append((path, tr_id, body))
            return {"output": {"ODNO": "1"}}

        def get(self, path: str, tr_id: str, params: dict[str, str]) -> dict[str, object]:
            calls.append((path, tr_id, params))
            return {"output": {}}

    client = KisOverseasClient(Http(), "NAS")
    client.limit_order("12345678", "01", " aapl ", 3, 185.5, "sell", " nasd ")
    client.cancel_order("12345678", "01", " tsla ", "999", 1, " nyse ")
    client.buyable_amount("12345678", "01", " qqq ", 10.0, " nasd ")

    assert calls[0][2]["PDNO"] == "AAPL"
    assert calls[0][2]["OVRS_EXCG_CD"] == "NASD"
    assert calls[0][2]["ORD_QTY"] == "3"
    assert calls[0][2]["ORD_UNPR"] == "185.50"
    assert calls[1][2]["PDNO"] == "TSLA"
    assert calls[1][2]["OVRS_EXCG_CD"] == "NYSE"
    assert calls[1][2]["ORD_QTY"] == "1"
    assert calls[2][2]["ITEM_CD"] == "QQQ"
    assert calls[2][2]["OVRS_EXCG_CD"] == "NASD"


def test_yahoo_news_source_caps_recent_titles() -> None:
    now = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)
    recent = int((now - timedelta(hours=1)).timestamp())
    stale = int((now - timedelta(hours=30)).timestamp())

    class Ticker:
        news = [
            {"title": "Fresh title", "providerPublishTime": recent},
            {"title": "Old title", "providerPublishTime": stale},
            {"content": {"title": "Nested title"}, "providerPublishTime": recent},
        ]

    source = YahooFinanceNewsSource(ticker_factory=lambda _: Ticker(), now=lambda: now)

    assert source.recent_titles("AAA") == ["Fresh title", "Nested title"]




def test_yahoo_news_sentiment_source_uses_replaceable_classifier() -> None:
    class News:
        def recent_titles(self, ticker: str) -> list[str]:
            assert ticker == "AAA"
            return ["Revenue growth beats outlook", "Regulator probe widens"]

    sentiments = YahooNewsSentimentSource(
        News(),
        KeywordHeadlineSentiment(),
    ).sentiments("AAA")

    assert sentiments == (Sentiment.POSITIVE, Sentiment.NEGATIVE)


def test_kis_mock_buy_submitter_uses_settings_for_limit_order() -> None:
    calls: list[tuple[object, ...]] = []

    class Kis:
        def limit_order(self, *args: object, **kwargs: object) -> dict[str, object]:
            calls.append(args + (kwargs,))
            return {"ok": True}

        def cancel_order(self, *args: object, **kwargs: object) -> dict[str, object]:
            calls.append(args + (kwargs,))
            return {"ok": True}

    result = KisMockBuySubmitter(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).submit(BuyIntent("AAA", 2, 10.5, 21, 0.05))

    assert result == {"ok": True}
    assert calls[0][:6] == ("12345678", "01", "AAA", 2, 10.5, "buy")

    sell_result = KisMockSellSubmitter(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).submit(SellIntent("AAA", 2, 10.1, "TRAILING_STOP"))

    assert sell_result == {"ok": True}
    assert calls[1][:6] == ("12345678", "01", "AAA", 2, 10.1, "sell")

    cancel_result = KisMockOrderCanceller(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    ).cancel({"ticker": "AAA", "order_no": "999", "quantity": 1})

    assert cancel_result == {"ok": True}
    assert calls[2][:5] == ("12345678", "01", "AAA", "999", 1)


def test_kis_mock_submitter_raises_on_business_error_response() -> None:
    class Kis:
        def limit_order(self, *args: object, **kwargs: object) -> dict[str, object]:
            return {"rt_cd": "1", "msg1": "모의투자에서는 해당업무가 제공되지 않습니다."}

    submitter = KisMockSellSubmitter(
        Kis(),
        KisSettings("app", "secret", "12345678", "01", "https://kis.test"),
    )

    with pytest.raises(RuntimeError, match="모의투자에서는 해당업무"):
        submitter.submit(SellIntent("AAA", 2, 10.1, "EOD"))
