from __future__ import annotations

import json
from datetime import date
from typing import Any, BinaryIO
from urllib.parse import parse_qs, urlparse

from trading_bot.trading_date import current_trade_date


def read_json_body(
    rfile: BinaryIO,
    content_length: str | None,
    max_bytes: int = 4096,
) -> dict[str, Any]:
    length = int(content_length or "0")
    if length <= 0:
        return {}
    raw = rfile.read(min(length, max_bytes))
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _query_date(path: str) -> date:
    raw = parse_qs(urlparse(path).query).get("date", [""])[0].strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return current_trade_date()


def _query_mode(path: str) -> str | None:
    raw = parse_qs(urlparse(path).query).get("mode", [""])[0].strip().lower()
    return raw if raw in {"mock", "real"} else None


def _query_limit(path: str, default: int = 30, maximum: int = 100) -> int:
    raw = parse_qs(urlparse(path).query).get("limit", [""])[0].strip()
    if not raw:
        return default
    try:
        value = int(float(raw))
    except ValueError:
        return default
    return max(1, min(value, maximum))


def _query_tickers(path: str) -> list[str] | None:
    raw = parse_qs(urlparse(path).query).get("ticker", [""])[0].strip()
    if not raw or raw.upper() == "ALL":
        return None
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "").replace("\uc8fc", "")
    return int(float(text))


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
