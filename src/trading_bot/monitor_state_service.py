from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.monitor_api import MonitorStateReader
from trading_bot.monitor_health import _safe_error_text
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.sql_monitor_state import SqlMonitorStateSource

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - runtime environment may omit optional dotenv.
    load_dotenv = None


def build_state_reader(state_path: Path) -> Any:
    if load_dotenv is not None:
        load_dotenv()
    if mssql_dsn_from_env():
        return DashboardStateReader(
            SqlMonitorStateSource(SqlServerMonitorRepository(pyodbc_connect_factory())),
            MonitorStateReader(state_path),
        )
    return MonitorStateReader(state_path)


class DashboardStateReader:
    def __init__(
        self,
        sql_reader: SqlMonitorStateSource,
        state_reader: MonitorStateReader,
    ) -> None:
        self.sql_reader = sql_reader
        self.state_reader = state_reader

    def read(self) -> dict[str, object]:
        try:
            cached_state = self.state_reader.read()
        except Exception:
            cached_state = {}
        state = accounts_from_cached_state(cached_state)
        try:
            sql_state = self.sql_reader.read()
        except Exception as exc:
            state["sql"] = {
                "connected": False,
                "error": _safe_error_text(exc),
            }
            return state
        mock = state["accounts"]["mock"]
        if isinstance(mock, dict):
            sql_account = sql_state.get("account")
            if isinstance(sql_account, dict) and sql_account.get("cashUsd") != "-":
                mock["account"] = sql_account
            mock["targets"] = sql_state.get("targets", [])
            mock["targetRunnerProfiles"] = sql_state.get("targetRunnerProfiles", {})
            mock["holdings"] = sql_state.get("holdings", [])
            mock["orders"] = sql_state.get("orders", [])
            mock["fills"] = sql_state.get("fills", [])
            mock["trades"] = sql_state.get("trades", [])
            mock["strategyStats"] = sql_state.get("strategyStats", [])
            mock["exitReasonStats"] = sql_state.get("exitReasonStats", [])
            mock["recentTrades"] = sql_state.get("recentTrades", [])
            mock["entryProfitSnapshots"] = sql_state.get("entryProfitSnapshots", [])
            mock["entryProfitSnapshotStats"] = sql_state.get("entryProfitSnapshotStats", {})
            mock["trading_stats"] = sql_state.get("trading_stats", {})
            if isinstance(mock.get("account"), dict):
                mock["account"]["realizedProfitUsd"] = (
                    sql_state.get("summary", {}).get("realizedProfitUsd", "$0.00")
                    if isinstance(sql_state.get("summary"), dict)
                    else "$0.00"
                )
            mock["logs"] = list(mock.get("logs", [])) + list(sql_state.get("logs", []))
        real = state["accounts"].get("real") if isinstance(state.get("accounts"), dict) else None
        sql_real_account = sql_state.get("realAccount")
        if isinstance(real, dict) and isinstance(sql_real_account, dict):
            if sql_real_account.get("cashUsd") != "-" or sql_real_account.get("cashKrw") != "-":
                real["account"] = sql_real_account
                real["connected"] = True
                real["error"] = ""
        state["date"] = sql_state.get("date")
        state["globalEntryGate"] = sql_state.get("globalEntryGate")
        state["trading_stats"] = sql_state.get("trading_stats", {})
        state["sql"] = sql_state
        return state

    def read_history(self, trade_date: date) -> dict[str, object]:
        return self.sql_reader.read_history(trade_date)

    def read_daily_summaries(
        self,
        mode: str | None = None,
        limit: int = 30,
    ) -> dict[str, object]:
        return self.sql_reader.read_daily_summaries(mode=mode, limit=limit)

    def read_daily_summary_detail(self, trade_date: date, mode: str) -> dict[str, object]:
        return self.sql_reader.read_daily_summary_detail(trade_date, mode)


def accounts_from_cached_state(raw_state: dict[str, object]) -> dict[str, object]:
    if isinstance(raw_state.get("accounts"), dict):
        return raw_state
    return {
        "accounts": {
            "mock": {
                "label": "\ubaa8\uc758\ud22c\uc790",
                "connected": True,
                "error": "",
                "account": raw_state.get("account", empty_account()),
                "targets": raw_state.get("targets", []),
                "targetRunnerProfiles": raw_state.get("targetRunnerProfiles", {}),
                "holdings": raw_state.get("holdings", []),
                "orders": raw_state.get("orders", []),
                "fills": raw_state.get("fills", []),
                "logs": raw_state.get("logs", []),
                "trades": raw_state.get("trades", []),
                "trading_stats": raw_state.get("trading_stats", {}),
            },
            "real": {
                "label": "\uc2e4\ud22c\uc790",
                "connected": False,
                "error": "\uc2e4\ud22c\uc790 \ud654\uba74\uc740 \ub9c8\uc9c0\ub9c9 \uc5f0\uacb0 \uc0c1\ud0dc\ub9cc \ud45c\uc2dc\ud569\ub2c8\ub2e4.",
                "account": empty_account(),
                "targets": [],
                "targetRunnerProfiles": {},
                "holdings": [],
                "orders": [],
                "fills": [],
                "logs": [],
                "trades": [],
            },
        }
    }


def empty_account() -> dict[str, str]:
    return {
        "cashUsd": "-",
        "equityUsd": "-",
        "investedUsd": "-",
        "cashKrw": "-",
        "equityKrw": "-",
        "openPositions": "-",
        "dailyProfitRate": "-",
        "realizedProfitUsd": "-",
    }


def read_monitor_state(reader: Any) -> dict[str, object]:
    return reader.read()


def read_history_state(reader: Any, trade_date: date) -> dict[str, object]:
    if hasattr(reader, "read_history"):
        return reader.read_history(trade_date)
    return {
        "date": trade_date.isoformat(),
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


def read_daily_summary_state(
    reader: Any,
    mode: str | None = None,
    limit: int = 30,
) -> dict[str, object]:
    if hasattr(reader, "read_daily_summaries"):
        return reader.read_daily_summaries(mode=mode, limit=limit)
    return {"summaries": []}


def read_daily_summary_detail_state(
    reader: Any,
    trade_date: date,
    mode: str,
) -> dict[str, object]:
    if hasattr(reader, "read_daily_summary_detail"):
        return reader.read_daily_summary_detail(trade_date, mode)
    return {"summary": None}
