from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from trading_bot.backtest_service import run_backtest_from_monitor_state
from trading_bot.config import (
    load_settings,
    runtime_risk_settings_payload,
    save_runtime_risk_settings,
)
from trading_bot.manual_sell import submit_manual_mock_sell, submit_manual_mock_sell_all
from trading_bot.manual_screening import ManualScreeningRunner
from trading_bot.monitor_health import (
    _health_state,
    _monitor_bind_requires_token,
    _safe_error_text,
)
from trading_bot.monitor_api import authorize_bearer
from trading_bot.monitor_request import (
    _optional_bool,
    _optional_float,
    _optional_int,
    _optional_text,
    _query_date,
    _query_limit,
    _query_mode,
    _query_tickers,
    _setting_float,
    read_json_body,
)
from trading_bot.monitor_response import generate_daily_summary_state, runtime_state
from trading_bot.monitor_routes import (
    GET_BACKTEST,
    GET_DAILY_SUMMARY,
    GET_DAILY_SUMMARY_DETAIL,
    GET_HEALTH,
    GET_HISTORY,
    GET_MANUAL_SCREENING,
    GET_STATE,
    GET_TRADING_SETTINGS,
    INDEX_FILE,
    INDEX_PATH,
    POST_DAILY_SUMMARY_GENERATE,
    POST_MANUAL_MOCK_SELL,
    POST_MANUAL_MOCK_SELL_ALL,
    POST_MANUAL_SCREENING,
    POST_REAL_TRADING_CONTROL,
    POST_TRADING_SETTINGS,
)
from trading_bot.monitor_state_service import (
    build_state_reader,
    read_daily_summary_detail_state,
    read_daily_summary_state,
    read_history_state,
    read_monitor_state,
)
from trading_bot.real_trading_control import save_manual_enabled


def serve_monitor(
    host: str,
    port: int,
    state_path: Path = Path("monitor/state.json"),
    monitor_dir: Path = Path("monitor"),
) -> None:
    reader = build_state_reader(state_path)
    handler = _handler(
        reader,
        monitor_dir,
        ManualScreeningRunner(state_path),
        state_path,
        bind_host=host,
    )
    ThreadingHTTPServer((host, port), handler).serve_forever()


def _handler(
    reader: Any,
    monitor_dir: Path,
    manual_screening: ManualScreeningRunner,
    state_path: Path = Path("monitor/state.json"),
    bind_host: str = "127.0.0.1",
):
    root = monitor_dir.resolve()

    class MonitorHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(root), **kwargs)

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == GET_HEALTH:
                self._write_health()
                return
            if path == GET_STATE:
                self._write_state()
                return
            if path == GET_HISTORY:
                self._write_history()
                return
            if path == GET_DAILY_SUMMARY:
                self._write_daily_summary()
                return
            if path == GET_DAILY_SUMMARY_DETAIL:
                self._write_daily_summary_detail()
                return
            if path == GET_TRADING_SETTINGS:
                self._write_trading_settings()
                return
            if path == GET_MANUAL_SCREENING:
                self._write_manual_screening_status()
                return
            if path == GET_BACKTEST:
                self._write_backtest()
                return
            if path == INDEX_PATH:
                self.path = INDEX_FILE
            super().do_GET()

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == POST_REAL_TRADING_CONTROL:
                self._write_real_trading_control()
                return
            if path == POST_MANUAL_MOCK_SELL:
                self._write_manual_mock_sell()
                return
            if path == POST_MANUAL_MOCK_SELL_ALL:
                self._write_manual_mock_sell_all()
                return
            if path == POST_MANUAL_SCREENING:
                self._start_manual_screening()
                return
            if path == POST_DAILY_SUMMARY_GENERATE:
                self._generate_daily_summary()
                return
            if path == POST_TRADING_SETTINGS:
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
            state = read_monitor_state(reader)
            state["runtime"] = runtime_state(
                local_bypass=self._allow_local_bypass(),
                bind_host=bind_host,
            )
            self._write_json(state)

        def _write_health(self) -> None:
            self._write_json(_health_state(state_path, bind_host=bind_host))

        def _write_history(self) -> None:
            if not self._authorize_api():
                return
            self._write_json(read_history_state(reader, _query_date(self.path)))

        def _write_daily_summary(self) -> None:
            if not self._authorize_api():
                return
            try:
                self._write_json(
                    read_daily_summary_state(
                        reader,
                        mode=_query_mode(self.path),
                        limit=_query_limit(self.path, default=30, maximum=100),
                    )
                )
            except Exception as exc:
                self._write_json(
                    {
                        "ok": False,
                        "error": "일일 요약을 불러오지 못했습니다.",
                        "detail": _safe_error_text(exc),
                    },
                    status=500,
                )

        def _write_daily_summary_detail(self) -> None:
            if not self._authorize_api():
                return
            try:
                self._write_json(
                    read_daily_summary_detail_state(
                        reader,
                        _query_date(self.path),
                        _query_mode(self.path) or "mock",
                    )
                )
            except Exception as exc:
                self._write_json(
                    {
                        "ok": False,
                        "error": "일일 요약을 불러오지 못했습니다.",
                        "detail": _safe_error_text(exc),
                    },
                    status=500,
                )

        def _generate_daily_summary(self) -> None:
            if not self._authorize_api():
                return
            try:
                self._write_json(generate_daily_summary_state(self._read_json_body()))
            except Exception as exc:
                self._write_json(
                    {
                        "ok": False,
                        "error": "일일 요약을 생성/저장하지 못했습니다.",
                        "detail": _safe_error_text(exc),
                    },
                    status=500,
                )

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
                {
                    "runtime": runtime_state(
                        control,
                        local_bypass=self._allow_local_bypass(),
                        bind_host=bind_host,
                    )
                }
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
                self._write_json({"ok": False, "error": _safe_error_text(exc)}, status=400)
                return
            self._write_json(result)

        def _write_manual_mock_sell_all(self) -> None:
            if not self._authorize_api():
                return
            try:
                result = submit_manual_mock_sell_all()
            except Exception as exc:
                self._write_json({"ok": False, "error": _safe_error_text(exc)}, status=400)
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
                state = read_history_state(reader, trade_date)
                self._write_json(
                    run_backtest_from_monitor_state(
                        state,
                        selected_tickers=tickers,
                    )
                )
            except Exception as exc:
                self._write_json({"ok": False, "error": _safe_error_text(exc)}, status=500)

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
                self._write_json({"ok": False, "error": _safe_error_text(exc)}, status=400)
                return
            self._write_json({"ok": True, "settings": settings_payload})

        def _authorize_api(self) -> bool:
            token = self.headers.get("Authorization")
            expected = os.getenv("MONITOR_BEARER_TOKEN", "").strip()
            if not expected and _monitor_bind_requires_token(bind_host):
                self.send_error(403, "Monitor token is required for LAN bindings")
                return False
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
            return read_json_body(self.rfile, self.headers.get("Content-Length"))

        def _write_json(self, value: dict[str, object], status: int = 200) -> None:
            payload = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return MonitorHandler
