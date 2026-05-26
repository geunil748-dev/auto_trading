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
from trading_bot.config import KisSettings
from trading_bot.models import (
    BotLog,
    CandidateSnapshot,
    DailyScore,
    DailyTarget,
    FillRecord,
    ScoreRecord,
    Sentiment,
    TradeRecord,
    BuyIntent,
    SellIntent,
)
from trading_bot.repositories import SqlServerDailyRepository
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.retry import RetryPolicy, call_with_retry
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
        [TradeRecord(date(2026, 5, 22), "AAA", "BUY", 12, None, 2)]
    )

    assert cursors[0].calls[0][1] == [(date(2026, 5, 22), "AAA", "", 180.0, 4.0)]
    assert cursors[1].calls[0][1] == [(date(2026, 5, 22), "AAA", 95, 80, 87.5, True)]
    assert cursors[2].calls[0][1] == ("INFO", "test", "stored")
    assert cursors[4].calls[0][1] == [
        (
            date(2026, 5, 22),
            "AAA",
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
            True,
        )
    ]
    assert all(connection.commits == 1 and connection.closed for connection in connections)


def test_sql_monitor_repository_reads_rows() -> None:
    cursor = Cursor()
    connection = Connection(cursor)
    rows = SqlServerMonitorRepository(lambda: connection).latest_targets(5)

    assert rows == [("AAA", 180, 4.2)]
    assert cursor.calls[0][1] == (5,)
    assert connection.closed


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
        date(2026, 5, 22),
        "22:41:10",
        "AAA",
        "매수",
        2,
        12.5,
        True,
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
        True,
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
            if path.endswith("inquire-ccnl"):
                return {"output": [{"pdno": "AAA"}]}
            return {"output": {"last": "12.30"}}

    client = KisOverseasClient(Http(), "NAS")

    assert [item.ticker for item in client.ranked_gainers(1)] == ["AAA"]
    assert [item.ticker for item in client.ranked_trade_volume()] == ["CCC"]
    assert client.quote("AAA") == {"last": "12.30"}
    assert client.daily_prices("AAA") == []
    assert client.mock_order_history("12345678", "01", "20260522") == [{"pdno": "AAA"}]
    assert calls[0][2]["GUBN"] == "1"
    assert calls[1][2]["NDAY"] == "0"
    assert calls[2][2]["SYMB"] == "AAA"
    assert calls[3][2]["GUBN"] == "0"
    assert calls[4][2]["ORD_STRT_DT"] == "20260522"


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
