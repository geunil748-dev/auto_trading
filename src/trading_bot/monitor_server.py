from __future__ import annotations

import json
import os
import time
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from trading_bot.config import (
    load_settings,
    runtime_risk_settings_payload,
    save_runtime_risk_settings,
)
from trading_bot.backtest_service import run_backtest_from_monitor_state
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.manual_sell import submit_manual_mock_sell, submit_manual_mock_sell_all
from trading_bot.manual_screening import ManualScreeningRunner
from trading_bot.monitor_api import MonitorStateReader, authorize_bearer
from trading_bot.real_trading_control import load_real_trading_control, save_manual_enabled
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.sql_monitor_state import SqlMonitorStateSource
from trading_bot.trading_date import current_trade_date

# 선택 의존성: .env 파일이 없어도 배포 환경의 환경변수를 그대로 사용할 수 있다.
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 실행 환경에 따라 선택 의존성을 허용한다.
    load_dotenv = None


def serve_monitor(
    host: str,
    port: int,
    state_path: Path = Path("monitor/state.json"),
    monitor_dir: Path = Path("monitor"),
) -> None:
    reader = _state_reader(state_path)
    handler = _handler(reader, monitor_dir, ManualScreeningRunner(state_path), state_path)
    ThreadingHTTPServer((host, port), handler).serve_forever()


def _state_reader(state_path: Path) -> Any:
    if load_dotenv is not None:
        load_dotenv()
    if mssql_dsn_from_env():
        return _DashboardStateReader(
            SqlMonitorStateSource(SqlServerMonitorRepository(pyodbc_connect_factory())),
            MonitorStateReader(state_path),
        )
    return MonitorStateReader(state_path)


class _DashboardStateReader:
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
        state = _accounts_from_cached_state(cached_state)
        sql_state = self.sql_reader.read()
        mock = state["accounts"]["mock"]
        if isinstance(mock, dict):
            # 화면은 API 응답을 직접 가공하지 않고 DB에 저장된 스냅샷을 우선 표시한다.
            sql_account = sql_state.get("account")
            if isinstance(sql_account, dict) and sql_account.get("cashUsd") != "-":
                mock["account"] = sql_account
            mock["targets"] = sql_state.get("targets", [])
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
        state["trading_stats"] = sql_state.get("trading_stats", {})
        state["sql"] = sql_state
        return state

    def read_history(self, trade_date: date) -> dict[str, object]:
        return self.sql_reader.read_history(trade_date)


def _accounts_from_cached_state(raw_state: dict[str, object]) -> dict[str, object]:
    if isinstance(raw_state.get("accounts"), dict):
        return raw_state
    return {
        "accounts": {
            "mock": {
                "label": "모의투자",
                "connected": True,
                "error": "",
                "account": raw_state.get("account", _empty_account()),
                "targets": raw_state.get("targets", []),
                "holdings": raw_state.get("holdings", []),
                "orders": raw_state.get("orders", []),
                "fills": raw_state.get("fills", []),
                "logs": raw_state.get("logs", []),
                "trades": raw_state.get("trades", []),
                "trading_stats": raw_state.get("trading_stats", {}),
            },
            "real": {
                "label": "실투자",
                "connected": False,
                "error": "실투자 화면은 마지막 연결 상태만 표시합니다.",
                "account": _empty_account(),
                "targets": [],
                "holdings": [],
                "orders": [],
                "fills": [],
                "logs": [],
                "trades": [],
            },
        }
    }


def _empty_account() -> dict[str, str]:
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


def _handler(
    reader: Any,
    monitor_dir: Path,
    manual_screening: ManualScreeningRunner,
    state_path: Path = Path("monitor/state.json"),
):
    root = monitor_dir.resolve()

    class MonitorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/health":
                self._write_health()
                return
            if path == "/api/state":
                self._write_state()
                return
            if path == "/api/history":
                self._write_history()
                return
            if path == "/api/trading-settings":
                self._write_trading_settings()
                return
            if path == "/api/manual-screening":
                self._write_manual_screening_status()
                return
            if path == "/api/backtest":
                self._write_backtest()
                return
            if path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/real-trading-control":
                self._write_real_trading_control()
                return
            if path == "/api/manual-mock-sell":
                self._write_manual_mock_sell()
                return
            if path == "/api/manual-mock-sell-all":
                self._write_manual_mock_sell_all()
                return
            if path == "/api/manual-screening":
                self._start_manual_screening()
                return
            if path == "/api/trading-settings":
                self._save_trading_settings()
                return
            self.send_error(404, "Not found")

        def end_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def guess_type(self, path: str) -> str:
            content_type = super().guess_type(path)
            script_types = {"text/html", "text/css", "text/javascript", "application/javascript"}
            if content_type in script_types:
                return f"{content_type}; charset=utf-8"
            return content_type

        def _write_state(self) -> None:
            if not self._authorize_api():
                return
            state = _read_monitor_state(reader)
            state["runtime"] = _runtime_state(local_bypass=self._allow_local_bypass())
            self._write_json(state)

        def _write_health(self) -> None:
            self._write_json(_health_state(state_path))

        def _write_history(self) -> None:
            if not self._authorize_api():
                return
            self._write_json(_read_history_state(reader, _query_date(self.path)))

        def _write_trading_settings(self) -> None:
            if not self._authorize_api():
                return
            self._write_json({"ok": True, "settings": runtime_risk_settings_payload()})

        def _write_real_trading_control(self) -> None:
            if not self._authorize_api():
                return
            body = self._read_json_body()
            settings = load_settings()
            requested = bool(body.get("enabled", False))
            enabled = requested and settings.real_trading_enabled and not settings.real_emergency_stop
            control = save_manual_enabled(enabled)
            self._write_json(
                {"runtime": _runtime_state(control, local_bypass=self._allow_local_bypass())}
            )

        def _write_manual_mock_sell(self) -> None:
            if not self._authorize_api():
                return
            body = self._read_json_body()
            try:
                result = submit_manual_mock_sell(
                    str(body.get("ticker", "")),
                    _optional_int(body.get("quantity")),
                )
            except Exception as exc:
                self._write_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._write_json(result)

        def _write_manual_mock_sell_all(self) -> None:
            if not self._authorize_api():
                return
            try:
                result = submit_manual_mock_sell_all()
            except Exception as exc:
                self._write_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._write_json(result)

        def _start_manual_screening(self) -> None:
            if not self._authorize_api():
                return
            self._write_json(manual_screening.start())

        def _write_manual_screening_status(self) -> None:
            if not self._authorize_api():
                return
            self._write_json({"ok": True, "status": manual_screening.status()})

        def _write_backtest(self) -> None:
            if not self._authorize_api():
                return
            try:
                trade_date = _query_date(self.path)
                tickers = _query_tickers(self.path)
                state = _read_history_state(reader, trade_date)
                self._write_json(
                    run_backtest_from_monitor_state(
                        state,
                        selected_tickers=tickers,
                    )
                )
            except Exception as exc:
                self._write_json({"ok": False, "error": str(exc)}, status=500)

        def _save_trading_settings(self) -> None:
            if not self._authorize_api():
                return
            body = self._read_json_body()
            current = runtime_risk_settings_payload()
            try:
                settings_payload = save_runtime_risk_settings(
                    _setting_float(body, "stopLossPercent", current),
                    _setting_float(body, "takeProfitPercent", current),
                    min_total_score=_optional_float(body.get("minTotalScore")),
                    min_price_usd=_optional_float(body.get("minPriceUsd")),
                    max_price_usd=_optional_float(body.get("maxPriceUsd")),
                    min_opening_price_change_percent=_optional_float(
                        body.get("minOpeningPriceChangePercent")
                    ),
                    min_volume_ratio=_optional_float(body.get("minVolumeRatio")),
                    max_opening_gap_percent=_optional_float(body.get("maxOpeningGapPercent")),
                    refresh_intraday_candidates=_optional_bool(
                        body.get("refreshIntradayCandidates")
                    ),
                    candidate_selection_mode=_optional_text(body.get("candidateSelectionMode")),
                    partial_take_profit_enabled=_optional_bool(
                        body.get("partialTakeProfitEnabled")
                    ),
                    trailing_stop_activation_percent=_optional_float(
                        body.get("trailingStopActivationPercent")
                    ),
                    max_entry_price_change_percent=_optional_float(
                        body.get("maxEntryPriceChangePercent")
                    ),
                    breakout_hold_minutes=_optional_float(body.get("breakoutHoldMinutes")),
                    require_5m_close_above_breakout=_optional_bool(
                        body.get("require5mCloseAboveBreakout")
                    ),
                    require_5m_volume_increase=_optional_bool(
                        body.get("require5mVolumeIncrease")
                    ),
                    min_5m_volume_increase_percent=_optional_float(
                        body.get("min5mVolumeIncreasePercent")
                    ),
                    require_vwap_or_ma20=_optional_bool(body.get("requireVwapOrMa20")),
                    require_pullback_rebreak=_optional_bool(
                        body.get("requirePullbackRebreak")
                    ),
                    gainer_ranking_limit=_optional_int(body.get("gainerRankingLimit")),
                    turnover_ranking_limit=_optional_int(body.get("turnoverRankingLimit")),
                    overheat_limit_condition_mode=_optional_text(
                        body.get("overheatLimitConditionMode")
                    ),
                    breakout_close_condition_mode=_optional_text(
                        body.get("breakoutCloseConditionMode")
                    ),
                    volume_increase_condition_mode=_optional_text(
                        body.get("volumeIncreaseConditionMode")
                    ),
                    vwap_ma20_condition_mode=_optional_text(
                        body.get("vwapMa20ConditionMode")
                    ),
                    vwap_ma20_condition_type=_optional_text(body.get("vwapMa20ConditionType")),
                    pullback_rebreak_condition_mode=_optional_text(
                        body.get("pullbackRebreakConditionMode")
                    ),
                )
            except Exception as exc:
                self._write_json({"ok": False, "error": str(exc)}, status=400)
                return
            self._write_json({"ok": True, "settings": settings_payload})

        def _authorize_api(self) -> bool:
            token = self.headers.get("Authorization")
            expected = os.getenv("MONITOR_BEARER_TOKEN", "")
            if expected and not self._allow_local_bypass() and not authorize_bearer(token, expected):
                self.send_error(401, "Invalid monitor token")
                return False
            return True

        def _allow_local_bypass(self) -> bool:
            enabled = os.getenv("MONITOR_ALLOW_LOCAL_BYPASS", "true").strip().lower()
            if enabled not in {"1", "true", "yes", "y"}:
                return False
            try:
                return ip_address(self.client_address[0]).is_loopback
            except ValueError:
                return False

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(min(length, 4096))
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}

        def _write_json(self, value: dict[str, object], status: int = 200) -> None:
            payload = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return MonitorHandler


def _health_state(state_path: Path = Path("monitor/state.json")) -> dict[str, object]:
    return {
        "ok": True,
        "database": _database_health(),
        "monitor": {
            "ok": True,
            "pid": os.getpid(),
        },
        "scheduler": _scheduler_health(state_path),
    }


def _database_health() -> dict[str, object]:
    if not mssql_dsn_from_env():
        return {"configured": False, "connected": False}
    try:
        connection = pyodbc_connect_factory()()
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        connection.close()
    except Exception as exc:
        return {"configured": True, "connected": False, "error": str(exc).splitlines()[0]}
    return {"configured": True, "connected": True}


def _scheduler_health(state_path: Path) -> dict[str, object]:
    heartbeat_path = state_path.parent / "scheduler_heartbeat.json"
    heartbeat_age_seconds = _file_age_seconds(heartbeat_path)
    monitor_state_age_seconds = _file_age_seconds(state_path)
    if heartbeat_age_seconds is not None:
        heartbeat_status = "recent" if heartbeat_age_seconds <= 120 else "stale"
        return {
            "status": "running" if heartbeat_status == "recent" else "stale_heartbeat",
            "heartbeat_exists": True,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "heartbeat_status": heartbeat_status,
            "monitor_state_exists": state_path.exists(),
            "monitor_state_age_seconds": monitor_state_age_seconds,
            "monitor_state_status": _age_status(monitor_state_age_seconds, 600),
        }
    if not state_path.exists():
        return {
            "status": "missing_state",
            "heartbeat_exists": False,
            "heartbeat_age_seconds": None,
            "heartbeat_status": "missing",
            "monitor_state_exists": False,
            "monitor_state_age_seconds": None,
            "monitor_state_status": "missing",
        }
    status = _age_status(monitor_state_age_seconds, 600)
    return {
        "status": status,
        "heartbeat_exists": False,
        "heartbeat_age_seconds": None,
        "heartbeat_status": "missing",
        "monitor_state_exists": True,
        "monitor_state_age_seconds": monitor_state_age_seconds,
        "monitor_state_status": status,
    }


def _file_age_seconds(path: Path) -> int | None:
    if not path.exists():
        return None
    return max(int(time.time() - path.stat().st_mtime), 0)


def _age_status(age_seconds: int | None, recent_seconds: int) -> str:
    if age_seconds is None:
        return "missing"
    return "recent" if age_seconds <= recent_seconds else "stale"


def _read_monitor_state(reader: Any) -> dict[str, object]:
    return reader.read()


def _read_history_state(reader: Any, trade_date: date) -> dict[str, object]:
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


def _query_date(path: str) -> date:
    raw = parse_qs(urlparse(path).query).get("date", [""])[0].strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            # 잘못된 날짜 파라미터는 화면을 깨뜨리지 않고 현재 거래일로 fallback 한다.
            pass
    return current_trade_date()


def _query_tickers(path: str) -> list[str] | None:
    raw = parse_qs(urlparse(path).query).get("ticker", [""])[0].strip()
    if not raw or raw.upper() == "ALL":
        return None
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value).replace(",", "").replace("주", "")))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", ""))


def _optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _setting_float(body: dict[str, Any], key: str, current: dict[str, float]) -> float:
    if key in body and body[key] not in (None, ""):
        return _optional_float(body[key]) or 0.0
    return float(current.get(key, 0.0))


def _runtime_state(control: Any | None = None, local_bypass: bool = False) -> dict[str, object]:
    if control is None:
        control = load_real_trading_control(load_settings())
    return {
        "activeMode": "real" if control.orders_unlocked else "mock",
        "modeLabel": control.mode_label,
        "monitorAuth": {
            "localBypass": local_bypass,
            "tokenConfigured": bool(os.getenv("MONITOR_BEARER_TOKEN", "")),
        },
        "realTrading": control.to_dict(),
    }
