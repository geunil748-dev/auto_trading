import json
from datetime import date

from trading_bot.config import KisSettings, TradingSettings
from trading_bot.models import FillRecord
from trading_bot.scheduler_state import (
    entry_profit_snapshots_from_fills,
    float_text,
    holding_prices,
    is_buy_side,
    persist_live_snapshot,
    write_closed_state,
    write_live_state,
    write_state_file,
)


class SnapshotRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fills: list[FillRecord] = []
        self.entry_snapshots = []
        self.updated_prices: dict[str, float] = {}
        self.final_updates: list[date] = []

    def save_account_snapshot(self, account, trade_date):
        self.calls.append("account")

    def save_order_snapshot(self, orders, trade_date):
        self.calls.append("orders")

    def save_holdings(self, holdings, trade_date):
        self.calls.append("holdings")

    def sell_entry_prices(self, trade_date):
        self.calls.append("entry_prices")
        return {}

    def entry_reasons(self, trade_date):
        self.calls.append("entry_reasons")
        return {"AAA": ("OPENING_BREAKOUT", "breakout detail")}

    def history_fills(self, trade_date, limit=200):
        self.calls.append("history_fills")
        return []

    def save_fills(self, fills):
        self.calls.append("fills")
        self.fills.extend(fills)

    def save_entry_profit_snapshots(self, snapshots):
        self.calls.append("entry_snapshots")
        self.entry_snapshots.extend(snapshots)

    def update_entry_profit_snapshots(self, trade_date, current_prices, now_text):
        self.calls.append("update_snapshots")
        self.updated_prices.update(current_prices)

    def update_entry_profit_snapshot_finals(self, trade_date):
        self.calls.append("finals")
        self.final_updates.append(trade_date)


def test_write_state_file_adds_last_updated_and_replaces_tmp(tmp_path) -> None:
    state_path = tmp_path / "state.json"

    write_state_file(state_path, {"logs": []})

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["logs"] == []
    assert "last_updated" in payload
    assert not state_path.with_name("state.json.tmp").exists()


def test_write_closed_state_keeps_closed_market_shape(tmp_path) -> None:
    state_path = tmp_path / "state.json"

    write_closed_state(state_path)

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["targets"] == []
    assert payload["holdings"] == []
    assert payload["orders"] == []
    assert payload["fills"] == []
    assert payload["trades"] == []
    assert payload["chart"] == {"closes": [], "movingAverage": []}
    assert payload["gates"] == [["미국 거래일", "휴장"]]
    assert payload["logs"][0][0] == "스케줄"


def test_entry_profit_snapshots_from_fills_keeps_buy_fills_only() -> None:
    snapshots = entry_profit_snapshots_from_fills(
        [
            FillRecord(
                trade_date=date(2026, 6, 5),
                ticker="AAA",
                ticker_name="Alpha",
                side="매수",
                quantity=2,
                fill_price_usd=10.5,
                fill_amount_usd=21.0,
                fill_time="22:35:00",
                strategy_version="STRICT_FIXED",
            ),
            FillRecord(
                trade_date=date(2026, 6, 5),
                ticker="BBB",
                side="SELL",
                quantity=1,
                fill_price_usd=9.0,
                fill_amount_usd=9.0,
                fill_time="22:40:00",
            ),
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].ticker == "AAA"
    assert snapshots[0].entry_price_usd == 10.5
    assert snapshots[0].strategy_version == "STRICT_FIXED"


def test_holding_prices_keep_price_field_priority() -> None:
    assert holding_prices(
        [
            {"ticker": " aaa ", "closePrice": "$12.34", "lastPrice": "1.00"},
            {"ticker": "BBB", "lastPrice": "9.87", "currentPrice": "1.00"},
            {"ticker": "CCC", "currentPrice": "8.76", "price": "1.00"},
            {"ticker": "DDD", "price": "7.65"},
            {"ticker": "EEE", "price": "0"},
        ]
    ) == {"AAA": 12.34, "BBB": 9.87, "CCC": 8.76, "DDD": 7.65}


def test_float_text_and_is_buy_side_keep_existing_parsing() -> None:
    assert float_text("$1,234.50") == 1234.5
    assert float_text("") == 0.0
    assert float_text("bad") == 0.0
    assert is_buy_side("매수")
    assert is_buy_side("BUY")
    assert is_buy_side("b")
    assert not is_buy_side("SELL")


def test_persist_live_snapshot_keeps_save_order_and_fill_callback(monkeypatch) -> None:
    repository = SnapshotRepository()
    notifications = []
    summaries = []
    records = [
        FillRecord(
            trade_date=date(2026, 6, 5),
            ticker="AAA",
            side="BUY",
            quantity=3,
            fill_price_usd=10.5,
            fill_amount_usd=31.5,
            fill_time="22:35:00",
            profit_usd=1.25,
        )
    ]

    monkeypatch.setattr("trading_bot.scheduler_state.SqlServerDailyRepository", lambda connect: repository)
    monkeypatch.setattr("trading_bot.scheduler_state.pyodbc_connect_factory", lambda: object)
    monkeypatch.setattr("trading_bot.scheduler_state.current_trade_date", lambda: date(2026, 6, 5))
    monkeypatch.setattr("trading_bot.scheduler_state.load_settings", lambda: TradingSettings())
    monkeypatch.setattr("trading_bot.scheduler_state.fill_records_from_monitor_rows", lambda *args, **kwargs: records)
    monkeypatch.setattr("trading_bot.scheduler_state.new_fill_records", lambda records, keys: records)
    monkeypatch.setattr("trading_bot.scheduler_state.save_daily_run_summary", lambda *args: summaries.append(args))

    error = persist_live_snapshot(
        {
            "account": {"cashUsd": "$100.00"},
            "orders": [{"ticker": "AAA"}],
            "holdings": [{"ticker": "AAA", "closePrice": "$11.00"}],
            "fills": [{"ticker": "AAA"}],
        },
        send_fill_notifications_func=lambda records, holdings: notifications.append((records, holdings)),
    )

    assert error == ""
    assert repository.calls == [
        "account",
        "orders",
        "holdings",
        "entry_prices",
        "entry_reasons",
        "history_fills",
        "fills",
        "entry_snapshots",
        "update_snapshots",
        "finals",
    ]
    assert repository.fills == records
    assert len(repository.entry_snapshots) == 1
    assert repository.updated_prices == {"AAA": 11.0}
    assert repository.final_updates == [date(2026, 6, 5)]
    assert summaries
    assert notifications == [(records, [{"ticker": "AAA", "closePrice": "$11.00"}])]


def test_persist_live_snapshot_returns_blank_for_value_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "trading_bot.scheduler_state.SqlServerDailyRepository",
        lambda connect: (_ for _ in ()).throw(ValueError("bad")),
    )
    monkeypatch.setattr("trading_bot.scheduler_state.pyodbc_connect_factory", lambda: object)

    assert persist_live_snapshot({"fills": []}) == ""


def test_persist_live_snapshot_masks_general_exception(monkeypatch) -> None:
    def fail_repository(connect):
        raise RuntimeError("MSSQL_PASSWORD=secret")

    monkeypatch.setattr("trading_bot.scheduler_state.SqlServerDailyRepository", fail_repository)
    monkeypatch.setattr("trading_bot.scheduler_state.pyodbc_connect_factory", lambda: object)

    error = persist_live_snapshot({"account": {}, "orders": [], "holdings": [], "fills": []})

    assert error == "모니터 DB 저장 실패: RuntimeError"
    assert "secret" not in error
    assert "MSSQL_PASSWORD" not in error


def test_write_live_state_merges_screening_logs_and_persist_error(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        "trading_bot.scheduler_state.live_kis_monitor_state",
        lambda kis, accounts, kis_settings: {
            "targets": [["live"]],
            "gates": [["live_gate"]],
            "logs": [["live_log"]],
        },
    )
    monkeypatch.setattr("trading_bot.scheduler_state.persist_live_snapshot", lambda live_state, **kwargs: "DB_FAIL")

    state = write_live_state(
        state_path,
        KisSettings("key", "secret", "account", "01", "https://kis.example"),
        screening_state={"targets": [["screen"]], "gates": [["screen_gate"]], "logs": [["screen_log"]]},
        extra_logs=[["extra_log"]],
    )

    assert state["targets"] == [["screen"]]
    assert state["gates"] == [["screen_gate"], ["live_gate"]]
    assert state["logs"][0][1:] == ["DB", "DB_FAIL"]
    assert state["logs"][1:] == [["extra_log"], ["screen_log"], ["live_log"]]
    assert json.loads(state_path.read_text(encoding="utf-8"))["logs"][0][1:] == ["DB", "DB_FAIL"]
