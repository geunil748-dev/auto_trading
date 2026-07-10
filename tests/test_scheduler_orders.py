from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import BuyIntent
from trading_bot.scheduler_orders import (
    cancel_logs,
    cancel_stale_mock_buy_orders,
    cancel_unfilled_orders_for_scheduler,
    release_cancelled_buy_tickers,
    retry_stale_mock_buy_orders,
    ticker,
    unfilled_cancel_seconds,
    unfilled_order_tickers_from_rows,
)


class Latest:
    def __init__(self) -> None:
        self.retried_buy_tickers: set[str] = set()
        self.cancelled_orders: list[dict[str, object]] = []
        self.buy_tickers: set[str] = set()
        self.add_on_tickers: set[str] = set()
        self.intraday_entry_rounds = 0
        self.result = None
        self.repository = None


class Runtime:
    def __init__(self, result) -> None:
        self.result = result
        self.accounts = self

    def run(self):
        return self.result

    def positions(self):
        return []


class Result:
    buy_intents = (BuyIntent("AAA", 1, 10, 10, 0.01),)


class Executor:
    def __init__(self) -> None:
        self.intents = []

    def execute(self, intents):
        self.intents = intents
        return [object() for _ in intents]


def test_unfilled_cancel_seconds_uses_partial_fill_policy() -> None:
    assert unfilled_cancel_seconds(TradingSettings()) is None
    assert (
        unfilled_cancel_seconds(
            TradingSettings(
                partial_fill_policy="CANCEL_REMAINING",
                unfilled_cancel_after_seconds=90,
            )
        )
        == 90
    )


def test_ticker_normalization_and_unfilled_tickers_from_rows() -> None:
    assert ticker(" aaa ") == "AAA"
    assert unfilled_order_tickers_from_rows(
        [
            {"pdno": " aaa ", "nccs_qty": "1"},
            {"pdno": "BBB", "nccs_qty": "0"},
            {"pdno": "", "nccs_qty": "2"},
        ]
    ) == {"AAA"}


def test_cancel_logs_keep_existing_message_shape() -> None:
    logs = cancel_logs([{"ticker": "AAA"}, {"ticker": "bbb"}], 2)

    assert len(logs) == 1
    assert logs[0][1] == "미체결 취소"
    assert logs[0][2] == "2분 지난 미체결 매수 취소: AAA, BBB"


def test_cancel_stale_mock_buy_orders_submits_requests(monkeypatch) -> None:
    retried: set[str] = set()
    submitted = []
    requests = [{"ticker": "AAA", "order_no": "1"}]

    monkeypatch.setattr("trading_bot.scheduler_orders.mock_order_rows", lambda kis_settings: [{"row": 1}])
    monkeypatch.setattr(
        "trading_bot.scheduler_orders.stale_unfilled_buy_cancel_requests",
        lambda rows, **kwargs: requests,
    )

    class Canceller:
        def __init__(self, kis, kis_settings) -> None:
            self.kis = kis

        def cancel(self, request) -> None:
            submitted.append(request)

    monkeypatch.setattr("trading_bot.scheduler_orders.KisMockOrderCanceller", Canceller)
    monkeypatch.setattr("trading_bot.scheduler_orders.KisOverseasClient", lambda client: "kis")
    monkeypatch.setattr("trading_bot.scheduler_orders.KisJsonClient", lambda settings: "client")

    cancelled = cancel_stale_mock_buy_orders(
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        2,
        retried,
    )

    assert cancelled == requests
    assert submitted == requests
    assert retried == {"AAA"}


def test_cancel_stale_mock_buy_orders_logs_lookup_failure(monkeypatch) -> None:
    logs = []

    monkeypatch.setattr(
        "trading_bot.scheduler_orders.mock_order_rows",
        lambda kis_settings: (_ for _ in ()).throw(RuntimeError("Authorization Bearer secret")),
    )
    monkeypatch.setattr(
        "trading_bot.scheduler_orders.safe_scheduler_log",
        lambda level, module, message, **kwargs: logs.append((level, module, message, kwargs)),
    )

    result = cancel_stale_mock_buy_orders(
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        2,
        set(),
    )

    assert result == []
    assert logs[0][1] == "orders"
    assert logs[0][2] == "STALE_MOCK_BUY_ORDER_LOOKUP_FAILED: RuntimeError"
    assert "secret" not in logs[0][2]


def test_cancel_stale_mock_buy_orders_respects_retry_limit(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("trading_bot.scheduler_orders.mock_order_rows", lambda kis_settings: calls.append("rows"))

    assert cancel_stale_mock_buy_orders(
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        2,
        set(),
        retry_limit=0,
    ) == []
    assert calls == []


def test_release_cancelled_buy_tickers_updates_latest_sets() -> None:
    latest = Latest()
    latest.buy_tickers = {"AAA", "BBB"}
    latest.add_on_tickers = {"AAA", "CCC"}

    release_cancelled_buy_tickers(latest, [{"ticker": " aaa "}])

    assert latest.buy_tickers == {"BBB"}
    assert latest.add_on_tickers == {"CCC"}


def test_cancel_unfilled_orders_for_scheduler_uses_mock_history_and_canceller(monkeypatch) -> None:
    rows = [{"ticker": "AAA"}]
    captured = {}

    class Kis:
        def mock_order_history(self, account_no, account_product, trade_date):
            captured["history"] = (account_no, account_product, trade_date)
            return rows

    class Canceller:
        def __init__(self, kis, kis_settings) -> None:
            captured["canceller"] = kis_settings.account_no

        def cancel(self, request) -> None:
            captured["cancelled"] = request

    def fake_cancel_unfilled_orders(order_rows, cancel):
        captured["rows"] = order_rows
        cancel(order_rows[0])
        return order_rows

    monkeypatch.setattr("trading_bot.scheduler_orders.KisJsonClient", lambda settings: "client")
    monkeypatch.setattr("trading_bot.scheduler_orders.KisOverseasClient", lambda client: Kis())
    monkeypatch.setattr("trading_bot.scheduler_orders.KisMockOrderCanceller", Canceller)
    monkeypatch.setattr("trading_bot.scheduler_orders.cancel_unfilled_orders", fake_cancel_unfilled_orders)
    monkeypatch.setattr(
        "trading_bot.scheduler_orders.current_us_market_date",
        lambda: type("MarketDate", (), {"strftime": lambda self, fmt: "20260608"})(),
    )

    result = cancel_unfilled_orders_for_scheduler(
        KisSettings("key", "secret", "account", "01", "https://kis.example")
    )

    assert result == rows
    assert captured["history"] == ("account", "01", "20260608")
    assert captured["canceller"] == "account"
    assert captured["cancelled"] == rows[0]


def test_retry_stale_mock_buy_orders_returns_state_and_logs(monkeypatch) -> None:
    latest = Latest()
    executor = Executor()
    result = Result()
    cancelled = [{"ticker": "AAA", "order_no": "1"}]

    monkeypatch.setattr("trading_bot.scheduler_orders.cancel_stale_mock_buy_orders", lambda *args: cancelled)
    monkeypatch.setattr("trading_bot.scheduler_orders.unfilled_order_tickers", lambda kis_settings: set())
    monkeypatch.setattr(
        "trading_bot.scheduler_orders.limited_intraday_buy_intents",
        lambda *args: [BuyIntent("AAA", 1, 10, 10, 0.01)],
    )
    monkeypatch.setattr("trading_bot.scheduler_orders.state_from_dry_run", lambda dry_run: {"targets": []})

    retry_state, retry_logs = retry_stale_mock_buy_orders(
        TradingSettings(mock_unfilled_reorder_minutes=2),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        latest,
        build_live_dry_run_func=lambda settings, kis_settings: (Runtime(result), "repository"),
        build_mock_buy_executor_func=lambda kis_settings, repository, settings: executor,
        apply_stop_loss_entry_guards_func=lambda intents, repository, settings: intents,
    )

    assert retry_state == {"targets": []}
    assert retry_logs[0][1] == "미체결 재주문"
    assert "재주문 1건" in retry_logs[0][2]
    assert latest.cancelled_orders == cancelled
    assert latest.intraday_entry_rounds == 0
    assert latest.unfilled_reorder_count == 1
    assert latest.unfilled_reorder_tickers == {"AAA"}
    assert latest.buy_tickers == {"AAA"}
    assert executor.intents[0].entry_reason.endswith("+UNFILLED_REORDER")


def test_retry_stale_mock_buy_orders_returns_empty_when_no_cancelled(monkeypatch) -> None:
    latest = Latest()
    monkeypatch.setattr("trading_bot.scheduler_orders.cancel_stale_mock_buy_orders", lambda *args: [])

    assert retry_stale_mock_buy_orders(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        latest,
        build_live_dry_run_func=lambda settings, kis_settings: (_ for _ in ()).throw(AssertionError),
        build_mock_buy_executor_func=lambda kis_settings, repository, settings: (_ for _ in ()).throw(AssertionError),
        apply_stop_loss_entry_guards_func=lambda intents, repository, settings: intents,
    ) == (None, [])
