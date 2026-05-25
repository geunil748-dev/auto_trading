from __future__ import annotations

from datetime import datetime

from trading_bot.config import TradingSettings
from trading_bot.models import PositionState


def log_row(module: str, message: str) -> list[str]:
    return [datetime.now().strftime("%H:%M:%S"), module, message]


def watch_message(
    positions: list[PositionState],
    exits: list[object],
    executable: list[object],
    pending_exits: set[str],
) -> str:
    exit_tickers = ", ".join(_ticker(item.ticker) for item in executable) or "없음"
    pending = ", ".join(sorted(pending_exits)) or "없음"
    return (
        f"보유 {len(positions)}종목 감시, 매도조건 {len(exits)}건, "
        f"신규 매도 {len(executable)}건({exit_tickers}), 미체결 매도 추적 {pending}"
    )


def recheck_message(
    candidates: tuple[object, ...],
    accepted: list[object],
    positions: list[PositionState],
    unfilled: set[str],
    completed_rounds: int,
    settings: TradingSettings,
) -> str:
    accepted_tickers = ", ".join(_ticker(item.ticker) for item in accepted) or "없음"
    held = ", ".join(sorted(_ticker(item.ticker) for item in positions)) or "없음"
    blocked = ", ".join(sorted(unfilled)) or "없음"
    return (
        f"후보 {len(candidates)}건 중 추가매수 {len(accepted)}건({accepted_tickers}); "
        f"보유 {held}; 미체결 차단 {blocked}; "
        f"라운드 {completed_rounds}/{settings.max_intraday_entry_rounds}"
    )


def _ticker(value: str) -> str:
    return value.strip().upper()
