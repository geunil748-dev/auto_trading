from datetime import date

from trading_bot.monitor_api import MonitorStateReader
from trading_bot.monitor_state_service import (
    DashboardStateReader,
    accounts_from_cached_state,
    empty_account,
    read_daily_summary_detail_state,
    read_daily_summary_state,
    read_history_state,
)


def test_accounts_from_cached_state_returns_existing_accounts_shape() -> None:
    raw_state = {"accounts": {"mock": {"account": {"cashUsd": "$1.00"}}}}

    assert accounts_from_cached_state(raw_state) is raw_state


def test_accounts_from_cached_state_converts_legacy_flat_state() -> None:
    state = accounts_from_cached_state(
        {
            "account": {"cashUsd": "$10.00"},
            "targets": [["AAA"]],
            "logs": [["09:00", "INFO", "ok"]],
            "trading_stats": {"candidateRate": 80.0},
        }
    )

    assert state["accounts"]["mock"]["label"] == "모의투자"
    assert state["accounts"]["mock"]["account"] == {"cashUsd": "$10.00"}
    assert state["accounts"]["mock"]["targets"] == [["AAA"]]
    assert state["accounts"]["mock"]["logs"] == [["09:00", "INFO", "ok"]]
    assert state["accounts"]["mock"]["trading_stats"] == {"candidateRate": 80.0}
    assert state["accounts"]["real"]["label"] == "실투자"
    assert state["accounts"]["real"]["connected"] is False


def test_empty_account_fields_match_monitor_fallback_shape() -> None:
    assert empty_account() == {
        "cashUsd": "-",
        "equityUsd": "-",
        "investedUsd": "-",
        "cashKrw": "-",
        "equityKrw": "-",
        "openPositions": "-",
        "dailyProfitRate": "-",
        "realizedProfitUsd": "-",
    }


def test_read_history_state_uses_reader_method_when_available() -> None:
    class Reader:
        def read_history(self, trade_date: date) -> dict[str, object]:
            return {"date": trade_date.isoformat(), "targets": [["AAA"]]}

    assert read_history_state(Reader(), date(2026, 6, 5)) == {
        "date": "2026-06-05",
        "targets": [["AAA"]],
    }


def test_read_history_state_falls_back_for_reader_without_history() -> None:
    state = read_history_state(object(), date(2026, 6, 5))

    assert state == {
        "date": "2026-06-05",
        "targets": [],
        "orders": [],
        "fills": [],
        "logs": [],
        "trades": [],
        "entryReasonStats": [],
        "strategyStats": [],
        "exitReasonStats": [],
        "recentTrades": [],
    }


def test_read_daily_summary_state_uses_reader_method_when_available() -> None:
    class Reader:
        def read_daily_summaries(
            self,
            mode: str | None = None,
            limit: int = 30,
        ) -> dict[str, object]:
            return {"mode": mode, "limit": limit, "summaries": [{"tradeDate": "2026-06-05"}]}

    assert read_daily_summary_state(Reader(), mode="mock", limit=5) == {
        "mode": "mock",
        "limit": 5,
        "summaries": [{"tradeDate": "2026-06-05"}],
    }


def test_read_daily_summary_state_falls_back_for_reader_without_method() -> None:
    assert read_daily_summary_state(object()) == {"summaries": []}


def test_read_daily_summary_detail_state_falls_back_for_reader_without_method() -> None:
    assert read_daily_summary_detail_state(object(), date(2026, 6, 5), "mock") == {
        "summary": None
    }


def test_dashboard_state_reader_masks_sql_error_on_fallback(tmp_path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    state.write_text('{"account":{"cashUsd":"$1.00"}}', encoding="utf-8")
    monkeypatch.setenv("MONITOR_BEARER_TOKEN", "secret-token")

    class BrokenSqlReader:
        def read(self) -> dict[str, object]:
            raise RuntimeError("failed with secret-token")

    payload = DashboardStateReader(BrokenSqlReader(), MonitorStateReader(state)).read()

    assert payload["accounts"]["mock"]["account"]["cashUsd"] == "$1.00"
    assert payload["sql"]["connected"] is False
    assert "secret-token" not in payload["sql"]["error"]
    assert "***" in payload["sql"]["error"]
