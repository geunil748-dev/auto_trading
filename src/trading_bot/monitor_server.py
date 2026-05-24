from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from trading_bot.config import load_settings
from trading_bot.dashboard_state import account_dashboard_state
from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
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
    handler = _handler(reader, monitor_dir)
    ThreadingHTTPServer((host, port), handler).serve_forever()


def _state_reader(state_path: Path) -> Any:
    if load_dotenv is not None:
        load_dotenv()
    if mssql_dsn_from_env():
        return _DashboardStateReader(
            SqlMonitorStateSource(SqlServerMonitorRepository(pyodbc_connect_factory()))
        )
    return MonitorStateReader(state_path)


class _DashboardStateReader:
    def __init__(self, sql_reader: SqlMonitorStateSource) -> None:
        self.sql_reader = sql_reader

    def read(self) -> dict[str, object]:
        state = account_dashboard_state()
        sql_state = self.sql_reader.read()
        mock = state["accounts"]["mock"]
        if isinstance(mock, dict):
            if not mock.get("targets"):
                mock["targets"] = sql_state.get("targets", [])
            mock["trades"] = sql_state.get("trades", [])
            mock["logs"] = list(mock.get("logs", [])) + list(sql_state.get("logs", []))
        state["sql"] = sql_state
        return state


def _handler(reader: Any, monitor_dir: Path):
    root = monitor_dir.resolve()

    class MonitorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/state":
                self._write_state()
                return
            if path == "/":
                self.path = "/index.html"
            super().do_GET()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/api/real-trading-control":
                self._write_real_trading_control()
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
            state = reader.read()
            state["runtime"] = _runtime_state(local_bypass=self._allow_local_bypass())
            self._write_json(state)

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

        def _write_json(self, value: dict[str, object]) -> None:
            payload = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return MonitorHandler


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
