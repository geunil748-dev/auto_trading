from __future__ import annotations

import json
import os
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
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
from trading_bot.manual_sell import submit_manual_mock_sell, submit_manual_mock_sell_all
from trading_bot.manual_screening import ManualScreeningRunner
from trading_bot.monitor_api import MonitorStateReader, authorize_bearer
from trading_bot.real_trading_control import load_real_trading_control, save_manual_enabled
from trading_bot.repositories import SqlServerMonitorRepository
from trading_bot.sql_monitor_state import SqlMonitorStateSource

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
    handler = _handler(reader, monitor_dir, ManualScreeningRunner(state_path))
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
            # 실시간 주문 이력은 targets에도 들어올 수 있으므로,
            # 리스트업 종목 화면은 DB에 저장된 수집 후보를 우선 사용한다.
            mock["targets"] = sql_state.get("targets", [])
            mock["holdings"] = sql_state.get("holdings", [])
            if not mock.get("fills"):
                mock["fills"] = sql_state.get("fills", [])
            mock["trades"] = sql_state.get("trades", [])
            if isinstance(mock.get("account"), dict):
                mock["account"]["realizedProfitUsd"] = (
                    sql_state.get("summary", {}).get("realizedProfitUsd", "$0.00")
                    if isinstance(sql_state.get("summary"), dict)
                    else "$0.00"
                )
            mock["logs"] = list(mock.get("logs", [])) + list(sql_state.get("logs", []))
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


def _handler(reader: Any, monitor_dir: Path, manual_screening: ManualScreeningRunner):
    root = monitor_dir.resolve()

    class MonitorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
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

        def _save_trading_settings(self) -> None:
            if not self._authorize_api():
                return
            body = self._read_json_body()
            try:
                settings_payload = save_runtime_risk_settings(
                    float(body.get("stopLossPercent", 0)),
                    float(body.get("takeProfitPercent", 0)),
                    _optional_float(body.get("minTotalScore")),
                    _optional_float(body.get("minPriceUsd")),
                    _optional_float(body.get("maxPriceUsd")),
                    _optional_float(body.get("minOpeningPriceChangePercent")),
                    _optional_float(body.get("minVolumeRatio")),
                    _optional_float(body.get("maxOpeningGapPercent")),
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
    }


def _query_date(path: str) -> date:
    raw = parse_qs(urlparse(path).query).get("date", [""])[0].strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(float(str(value).replace(",", "").replace("주", "")))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace(",", ""))


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
