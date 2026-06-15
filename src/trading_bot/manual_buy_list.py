from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


MANUAL_BUY_SOURCE = "manual_buy_list"
MANUAL_WATCHLIST_REASON = "MANUAL_WATCHLIST"
DEFAULT_MANUAL_BUY_LIST_PATH = "monitor/manual_buy_list.json"
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?$")


@dataclass(frozen=True)
class ManualBuyTicker:
    ticker: str
    enabled: bool = True
    note: str = ""
    created_at: str = ""
    updated_at: str = ""


class FileManualBuyListSource:
    def __init__(
        self,
        path: str | Path,
        *,
        enabled: bool = True,
        max_tickers: int = 20,
    ) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.max_tickers = max_tickers

    def enabled_tickers(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        items = read_manual_buy_list(self.path)
        tickers = [item.ticker for item in items if item.enabled]
        return tuple(tickers[: max(self.max_tickers, 0)])


def read_manual_buy_list(path: str | Path) -> list[ManualBuyTicker]:
    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("tickers")
    if not isinstance(rows, list):
        return []
    result: list[ManualBuyTicker] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ticker = normalize_ticker(row.get("ticker", ""))
        except ValueError:
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        result.append(
            ManualBuyTicker(
                ticker=ticker,
                enabled=bool(row.get("enabled", True)),
                note=str(row.get("note", "") or ""),
                created_at=str(row.get("created_at", "") or ""),
                updated_at=str(row.get("updated_at", "") or ""),
            )
        )
    return result


def list_manual_buy_tickers(path: str | Path) -> dict[str, Any]:
    items = read_manual_buy_list(path)
    return {
        "ok": True,
        "action": "list",
        "path": str(path),
        "count": len(items),
        "tickers": [asdict(item) for item in items],
    }


def add_manual_buy_ticker(
    path: str | Path,
    ticker: str,
    *,
    note: str = "",
    max_tickers: int = 20,
) -> dict[str, Any]:
    normalized = normalize_ticker(ticker)
    items = read_manual_buy_list(path)
    now = _now()
    for index, item in enumerate(items):
        if item.ticker == normalized:
            items[index] = replace(
                item,
                enabled=True,
                note=note or item.note,
                updated_at=now,
            )
            _write_manual_buy_list(path, items)
            return _result("add", path, normalized, items)
    if len(items) >= max_tickers:
        raise ValueError("MAX_MANUAL_BUY_TICKERS exceeded")
    items.append(
        ManualBuyTicker(
            ticker=normalized,
            enabled=True,
            note=note,
            created_at=now,
            updated_at=now,
        )
    )
    _write_manual_buy_list(path, items)
    return _result("add", path, normalized, items)


def remove_manual_buy_ticker(path: str | Path, ticker: str) -> dict[str, Any]:
    normalized = normalize_ticker(ticker)
    items = [item for item in read_manual_buy_list(path) if item.ticker != normalized]
    _write_manual_buy_list(path, items)
    return _result("remove", path, normalized, items)


def clear_manual_buy_tickers(path: str | Path) -> dict[str, Any]:
    _write_manual_buy_list(path, [])
    return {
        "ok": True,
        "action": "clear",
        "path": str(path),
        "count": 0,
        "tickers": [],
    }


def set_manual_buy_ticker_enabled(
    path: str | Path,
    ticker: str,
    enabled: bool,
) -> dict[str, Any]:
    normalized = normalize_ticker(ticker)
    items = read_manual_buy_list(path)
    now = _now()
    for index, item in enumerate(items):
        if item.ticker == normalized:
            items[index] = replace(item, enabled=enabled, updated_at=now)
            _write_manual_buy_list(path, items)
            return _result("enable" if enabled else "disable", path, normalized, items)
    raise ValueError(f"{normalized} is not in the manual buy list")


def normalize_ticker(value: object) -> str:
    ticker = str(value or "").strip().upper()
    if not TICKER_PATTERN.fullmatch(ticker):
        raise ValueError("invalid ticker")
    return ticker


def _write_manual_buy_list(path: str | Path, items: list[ManualBuyTicker]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tickers": [asdict(item) for item in items]}
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(file_path)


def _result(
    action: str,
    path: str | Path,
    ticker: str,
    items: list[ManualBuyTicker],
) -> dict[str, Any]:
    return {
        "ok": True,
        "action": action,
        "ticker": ticker,
        "path": str(path),
        "count": len(items),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat()
