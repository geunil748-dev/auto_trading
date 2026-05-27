from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from trading_bot.composition import build_live_dry_run
from trading_bot.config import load_kis_settings, load_settings
from trading_bot.monitor_state import state_from_dry_run


class ManualScreeningRunner:
    def __init__(
        self,
        monitor_state: Path,
        run_screening: Callable[[], dict[str, object]] | None = None,
    ) -> None:
        self.monitor_state = monitor_state
        self.run_screening = run_screening or self._run_live_screening
        self._lock = threading.Lock()
        self._running = False
        self._last_status: dict[str, object] = {
            "running": False,
            "message": "수동 리스트업 대기 중입니다.",
        }

    def start(self) -> dict[str, object]:
        with self._lock:
            if self._running:
                return {
                    "ok": True,
                    "started": False,
                    "status": self._last_status,
                    "message": "이미 수동 리스트업을 진행 중입니다.",
                }
            self._running = True
            self._last_status = {
                "running": True,
                "startedAt": datetime.now().isoformat(timespec="seconds"),
                "message": "수동 리스트업을 시작했습니다.",
            }
        threading.Thread(target=self._run_background, daemon=True).start()
        return {
            "ok": True,
            "started": True,
            "status": self._last_status,
            "message": "수동 리스트업을 백그라운드에서 시작했습니다.",
        }

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._last_status)

    def _run_background(self) -> None:
        try:
            result = self.run_screening()
            status = {
                "running": False,
                "finishedAt": datetime.now().isoformat(timespec="seconds"),
                **result,
            }
        except Exception as exc:
            status = {
                "running": False,
                "finishedAt": datetime.now().isoformat(timespec="seconds"),
                "ok": False,
                "message": f"수동 리스트업 실패: {exc}",
            }
        with self._lock:
            self._running = False
            self._last_status = status

    def _run_live_screening(self) -> dict[str, object]:
        runtime, _repository = build_live_dry_run(load_settings(), load_kis_settings())
        result = runtime.run()
        state = state_from_dry_run(result)
        self.monitor_state.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "message": (
                f"수동 리스트업 완료: 후보 {len(result.scoring.targets)}개, "
                f"선정 {len(result.scoring.selected)}개"
            ),
            "targets": len(result.scoring.targets),
            "selected": len(result.scoring.selected),
        }
