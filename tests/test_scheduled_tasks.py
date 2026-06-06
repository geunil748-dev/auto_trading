from datetime import date, datetime, timedelta

from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import AccountState, BuyIntent, FillRecord, PositionState, ScoreRecord, SellIntent
from trading_bot.scheduled_tasks import (
    _apply_stop_loss_entry_guards,
    _entry_profit_snapshots_from_fills,
    _holding_prices,
    _persist_live_snapshot,
    live_mock_tasks,
)


class Accounts:
    def positions(self) -> list[str]:
        return ["holding"]


class Monitor:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool]] = []

    def poll(self, positions: list[str], end_of_day: bool = False):
        self.calls.append((positions, end_of_day))
        return positions, [SellIntent("AAA", 2, 10.5, "EOD")]


class Executor:
    def __init__(self) -> None:
        self.intents: list[SellIntent] = []

    def execute(self, intents: list[SellIntent]) -> list[object]:
        self.intents = intents
        return [object()]


class IntradayAccounts:
    def positions(self) -> list[PositionState]:
        return [PositionState("AAA", 10, 2, 9.7, 10.0)]


class IntradayMonitor:
    def __init__(self) -> None:
        self.highs: list[float] = []

    def poll(
        self,
        positions: list[PositionState],
        end_of_day: bool = False,
        partial_take_profit_tickers=None,
    ):
        self.highs.append(positions[0].high_price_usd)
        refreshed = [PositionState("AAA", 10, 2, 9.6, 10.5)]
        return refreshed, [SellIntent("AAA", 2, 9.6, "STOP_LOSS")]


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[list[SellIntent]] = []

    def execute(self, intents: list[SellIntent]) -> list[object]:
        self.calls.append(intents)
        return [object() for _ in intents]


class RiskRepository:
    def __init__(
        self,
        last_stop_loss_at=None,
        consecutive_stop_loss_count: int = 0,
    ) -> None:
        self.last_value = last_stop_loss_at
        self.count = consecutive_stop_loss_count
        self.logs = []

    def last_stop_loss_at(self, trade_date, ticker):
        return self.last_value

    def consecutive_stop_loss_count(self, trade_date):
        return self.count

    def save_log(self, log):
        self.logs.append(log)


class SnapshotRepository:
    def __init__(self) -> None:
        self.fills: list[FillRecord] = []
        self.entry_snapshots = []
        self.updated_prices: dict[str, float] = {}
        self.final_updates: list[date] = []

    def save_account_snapshot(self, account, trade_date):
        self.account = (account, trade_date)

    def save_order_snapshot(self, orders, trade_date):
        self.orders = (orders, trade_date)

    def save_holdings(self, holdings, trade_date):
        self.holdings = (holdings, trade_date)

    def sell_entry_prices(self, trade_date):
        return {}

    def entry_reasons(self, trade_date):
        return {"AAA": ("OPENING_BREAKOUT", "breakout detail")}

    def history_fills(self, trade_date, limit=200):
        return []

    def save_fills(self, fills):
        self.fills.extend(fills)

    def save_entry_profit_snapshots(self, snapshots):
        self.entry_snapshots.extend(snapshots)

    def update_entry_profit_snapshots(self, trade_date, current_prices, now_text):
        self.updated_prices.update(current_prices)

    def update_entry_profit_snapshot_finals(self, trade_date):
        self.final_updates.append(trade_date)


class RecheckAccounts:
    def current_account(self) -> AccountState:
        return AccountState(100000, 100000, 0, 0, 0)

    def positions(self) -> list[PositionState]:
        return []


class RecheckScoring:
    selected = (ScoreRecord("AAA", 90, 90), ScoreRecord("BBB", 80, 80))


class RecheckResult:
    scoring = RecheckScoring()
    buy_intents = (
        BuyIntent("AAA", 1, 10, 10, 0.01),
        BuyIntent("BBB", 1, 10, 10, 0.01),
    )


class HybridScoring:
    def __init__(self, selected: tuple[ScoreRecord, ...]) -> None:
        self.selected = selected


class HybridResult:
    def __init__(self, selected: tuple[ScoreRecord, ...]) -> None:
        self.scoring = HybridScoring(selected)
        self.buy_intents = tuple(
            BuyIntent(item.ticker, 1, 10, 10, 0.01)
            for item in selected
        )


class RecheckRuntime:
    def __init__(self) -> None:
        self.accounts = RecheckAccounts()
        self.breakout = self

    def run(self) -> RecheckResult:
        return RecheckResult()

    def breakout_input(self, ticker: str):
        return (10, 9, 9.5, 8)


def test_close_session_submits_end_of_day_mock_sells(monkeypatch, tmp_path) -> None:
    monitor = Monitor()
    executor = Executor()
    notice_calls = []
    report_calls = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_exit_poll",
        lambda settings, kis_settings: (Accounts(), monitor, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_sell_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings: {"orders": [], "fills": [], "holdings": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._cancel_unfilled_orders",
        lambda kis_settings: [{"ticker": "OLD", "order_no": "1", "quantity": 1}],
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.write_daily_report",
        lambda report_dir, trade_day, state, cancelled_orders, eod_sell_count: tmp_path
        / "report.json",
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._send_market_close_notice",
        lambda: notice_calls.append("sent"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._send_market_close_report",
        lambda state: report_calls.append(state),
    )

    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
        regular_session=lambda: True,
    )

    assert "장마감 모의 매도 주문 1건 제출" in tasks.close_session()
    assert monitor.calls == [(["holding"], True)]
    assert executor.intents == [SellIntent("AAA", 2, 10.5, "EOD")]
    assert notice_calls == ["sent"]
    assert report_calls == [{"orders": [], "fills": [], "holdings": []}]


def test_close_session_skips_after_regular_session(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._cancel_unfilled_orders",
        lambda kis_settings: calls.append("cancel") or [],
    )

    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
        regular_session=lambda: False,
    )

    assert tasks.close_session() == "미국 정규장 시간이 아니라 장마감 처리를 건너뜁니다."
    assert calls == []


def test_cancel_unfilled_submits_cancellations_and_refreshes_monitor(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._cancel_unfilled_orders",
        lambda kis_settings: [{"ticker": "AAA", "order_no": "111", "quantity": 2}],
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings: calls.append("refresh") or {},
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
    )

    assert tasks.cancel_unfilled() == "미체결 모의 주문 1건 취소."
    assert calls == ["refresh"]


def test_stop_loss_cooldown_blocks_same_symbol_entry() -> None:
    repository = RiskRepository(last_stop_loss_at=datetime.now() - timedelta(minutes=5))

    intents = _apply_stop_loss_entry_guards(
        [BuyIntent("AAA", 1, 10, 10, 0.01)],
        repository,
        TradingSettings(stop_loss_cooldown_minutes=30),
    )

    assert intents == []
    assert repository.logs[0].reject_reason == "STOP_LOSS_COOLDOWN"


def test_entry_profit_snapshots_are_created_from_buy_fills() -> None:
    snapshots = _entry_profit_snapshots_from_fills(
        [
            FillRecord(
                trade_date=date(2026, 5, 29),
                ticker="AAA",
                ticker_name="Alpha",
                side="BUY",
                quantity=3,
                fill_price_usd=10.5,
                fill_amount_usd=31.5,
                fill_time="22:35:00",
                strategy_version="STRICT_FIXED",
            ),
            FillRecord(
                trade_date=date(2026, 5, 29),
                ticker="AAA",
                side="SELL",
                quantity=3,
                fill_price_usd=11.0,
                fill_amount_usd=33.0,
                fill_time="22:45:00",
            ),
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].ticker == "AAA"
    assert snapshots[0].entry_time == "22:35:00"
    assert snapshots[0].entry_price_usd == 10.5
    assert snapshots[0].strategy_version == "STRICT_FIXED"


def test_holding_prices_parse_current_price_fields() -> None:
    prices = _holding_prices(
        [
            {"ticker": " aaa ", "closePrice": "$12.34"},
            {"ticker": "BBB", "lastPrice": "9.87"},
            {"ticker": "", "closePrice": "$1.00"},
        ]
    )

    assert prices == {"AAA": 12.34, "BBB": 9.87}


def test_persist_live_snapshot_saves_fill_history_and_entry_snapshot(monkeypatch) -> None:
    repository = SnapshotRepository()
    notifications = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.SqlServerDailyRepository",
        lambda connect: repository,
    )
    monkeypatch.setattr("trading_bot.scheduled_tasks.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr("trading_bot.scheduled_tasks.current_trade_date", lambda: date(2026, 6, 5))
    monkeypatch.setattr("trading_bot.scheduled_tasks.load_settings", lambda: TradingSettings())
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._send_fill_notifications",
        lambda records, holdings: notifications.append((records, holdings)),
    )

    error = _persist_live_snapshot(
        {
            "account": {"cashUsd": "$100.00"},
            "orders": [],
            "holdings": [{"ticker": "AAA", "closePrice": "$11.00"}],
            "fills": [
                {
                    "date": "2026-06-05",
                    "time": "22:35:00",
                    "ticker": "AAA",
                    "name": "Alpha",
                    "side": "BUY",
                    "quantity": "3",
                    "price": "$10.50",
                    "total": "$31.50",
                    "orderNo": "123",
                }
            ],
        }
    )

    assert error == ""
    assert len(repository.fills) == 1
    assert repository.fills[0].ticker == "AAA"
    assert repository.fills[0].entry_reason == "OPENING_BREAKOUT"
    assert len(repository.entry_snapshots) == 1
    assert repository.entry_snapshots[0].ticker == "AAA"
    assert repository.updated_prices == {"AAA": 11.0}
    assert repository.final_updates == [date(2026, 6, 5)]
    assert notifications


def test_consecutive_stop_loss_limit_blocks_all_new_entries() -> None:
    repository = RiskRepository(consecutive_stop_loss_count=3)

    intents = _apply_stop_loss_entry_guards(
        [BuyIntent("AAA", 1, 10, 10, 0.01)],
        repository,
        TradingSettings(max_consecutive_stop_loss_count=3),
    )

    assert intents == []
    assert repository.logs[0].reject_reason == "CONSECUTIVE_STOP_LOSS_LIMIT"


def test_market_closed_skips_scheduled_trading_and_writes_monitor_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        state_path,
        trading_day=lambda: False,
    )

    assert tasks.dry_run() == "미국 휴장일이라 후보 점검을 건너뜁니다."
    assert "\ubbf8\uad6d \uac70\ub798\uc77c" in state_path.read_text(encoding="utf-8")


def test_intraday_watch_submits_one_exit_and_remembers_pending_sells(
    monkeypatch,
    tmp_path,
) -> None:
    monitor = IntradayMonitor()
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_exit_poll",
        lambda settings, kis_settings: (IntradayAccounts(), monitor, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_sell_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, **kwargs: None,
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert tasks.intraday_watch() == "1분 감시 완료: 모의 매도 주문 1건 제출."
    assert tasks.intraday_watch() == "1분 감시 완료: 모의 매도 주문 0건 제출."
    assert monitor.highs == [10.0, 10.5]
    assert executor.calls == [[SellIntent("AAA", 2, 9.6, "STOP_LOSS")], []]


def test_intraday_watch_skips_when_trading_guard_reports_degraded(
    monkeypatch,
    tmp_path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_exit_poll",
        lambda settings, kis_settings: calls.append("exit_poll"),
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
        trading_guard=lambda: "SKIP trading cycle: monitor degraded reason=db_connected=false",
    )

    assert tasks.intraday_watch() == "SKIP trading cycle: monitor degraded reason=db_connected=false"
    assert calls == []


def test_intraday_recheck_screens_and_limits_additional_buys(monkeypatch, tmp_path) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (RecheckRuntime(), "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: set(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["BBB"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    monkeypatch.setattr(
        "trading_bot.entry_planner.position_fraction_for_score",
        lambda score, settings: 0.01,
    )
    tasks = live_mock_tasks(
        TradingSettings(max_intraday_entry_rounds=1),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert "모의 매수 주문 1건 제출" in tasks.intraday_recheck()
    assert "모의 매수 주문 0건 제출" in tasks.intraday_recheck()
    assert executor.calls == [
        [
            BuyIntent(
                "AAA",
                1,
                10,
                10,
                0.01,
                "OPENING_BREAKOUT+INTRADAY_RECHECK+OPENING_FIXED",
                "15분 재평가 후보; 장초반 고정 후보 재평가",
            )
        ],
        [],
    ]


def test_intraday_recheck_can_reuse_fixed_watchlist(monkeypatch, tmp_path) -> None:
    runtime = RecheckRuntime()
    run_count = 0
    executor = RecordingExecutor()

    def run_once():
        nonlocal run_count
        run_count += 1
        return RecheckResult()

    runtime.run = run_once
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (runtime, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: set(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["AAA"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.plan_buy_intents",
        lambda selected, breakout_inputs, account, settings: [
            BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected
        ],
    )
    tasks = live_mock_tasks(
        TradingSettings(refresh_intraday_candidates=False, max_intraday_entry_rounds=2),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
        regular_session=lambda: True,
    )

    tasks.dry_run()
    tasks.intraday_recheck()
    tasks.intraday_recheck()

    assert run_count == 1


def test_fixed_watchlist_waits_for_next_opening_collection(monkeypatch, tmp_path) -> None:
    runtime = RecheckRuntime()
    run_count = 0
    current_settings = TradingSettings(
        refresh_intraday_candidates=True,
        candidate_selection_mode="refresh",
    )

    def run_once():
        nonlocal run_count
        run_count += 1
        return RecheckResult()

    runtime.run = run_once
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (runtime, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository, settings=None: RecordingExecutor(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: set(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["AAA"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    tasks = live_mock_tasks(
        lambda: current_settings,
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
        regular_session=lambda: True,
    )

    tasks.dry_run()
    current_settings = TradingSettings(refresh_intraday_candidates=False)
    tasks.intraday_recheck()

    assert run_count == 2


def test_intraday_recheck_hybrid_merges_opening_and_refresh_candidates(monkeypatch, tmp_path) -> None:
    runtime = RecheckRuntime()
    results = [
        HybridResult((
            ScoreRecord("OPEN1", 95, 95),
            ScoreRecord("OPEN2", 94, 94),
            ScoreRecord("OPEN3", 93, 93),
            ScoreRecord("OPEN4", 92, 92),
            ScoreRecord("OPEN5", 91, 91),
            ScoreRecord("OPEN6", 90, 90),
        )),
        HybridResult((
            ScoreRecord("NEW1", 99, 99),
            ScoreRecord("NEW2", 98, 98),
            ScoreRecord("OPEN2", 97, 97),
            ScoreRecord("NEW3", 70, 70),
        )),
    ]

    def run_once():
        return results.pop(0)

    runtime.run = run_once
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (runtime, "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: set(),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.plan_buy_intents",
        lambda selected, breakout_inputs, account, settings: [
            BuyIntent(item.ticker, 1, 10, 10, 0.01) for item in selected
        ],
    )
    tasks = live_mock_tasks(
        TradingSettings(
            candidate_selection_mode="hybrid",
            max_intraday_entry_rounds=2,
            max_intraday_buy_intents_per_round=8,
            max_position_exposure=1.0,
            max_account_exposure=1.0,
        ),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        trading_day=lambda: True,
        regular_session=lambda: True,
    )

    tasks.dry_run()
    tasks.intraday_recheck()

    tickers = [intent.ticker for intent in executor.calls[0]]
    assert tickers == ["NEW1", "NEW2", "OPEN2", "OPEN1", "OPEN3", "OPEN4", "OPEN5"]


def test_intraday_recheck_blocks_add_on_when_order_is_unfilled(
    monkeypatch,
    tmp_path,
) -> None:
    executor = RecordingExecutor()
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_live_dry_run",
        lambda settings, kis_settings: (RecheckRuntime(), "repository"),
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.build_mock_buy_executor",
        lambda kis_settings, repository, settings=None: executor,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks.state_from_dry_run",
        lambda result: {"targets": [["AAA"]], "gates": [], "logs": []},
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._write_live_state",
        lambda monitor_state, kis_settings, screening_state=None, **kwargs: None,
    )
    monkeypatch.setattr(
        "trading_bot.scheduled_tasks._unfilled_order_tickers",
        lambda kis_settings: {"AAA", "BBB"},
    )
    tasks = live_mock_tasks(
        TradingSettings(),
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        tmp_path / "state.json",
        regular_session=lambda: True,
    )

    assert "모의 매수 주문 0건 제출" in tasks.intraday_recheck()
    assert executor.calls == [[]]
