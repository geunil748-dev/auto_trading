from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

EXIT_REASON_BUCKETS = (
    "STOP_LOSS",
    "TRAILING_STOP",
    "EOD",
    "PROFIT_PROTECTION",
    "EARLY_NEGATIVE_EXIT",
    "TIME_STOP_EXIT",
    "OTHER",
)
SCORE_BUCKETS = ("below_40", "40_50", "50_60", "60_70", "70_plus", "unknown")
SOURCE_BUCKETS = ("auto", "fixed_recheck", "manual", "other")
UNKNOWN = "unknown"


@dataclass(frozen=True)
class BucketStats:
    sell_count: int = 0
    total_profit_usd: float = 0.0
    win_rate: float = 0.0


def exit_reason_bucket(value: object) -> str:
    text = str(value or "").strip().upper()
    return text if text in EXIT_REASON_BUCKETS and text != "OTHER" else "OTHER"


def score_bucket(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if not text:
        return "unknown"
    if "below" in text or "under" in text or "<40" in text or "0_40" in text:
        return "below_40"
    if "40" in text and "50" in text:
        return "40_50"
    if "50" in text and "60" in text:
        return "50_60"
    if "60" in text and "70" in text:
        return "60_70"
    if "70" in text or "plus" in text or "+" in text:
        return "70_plus"
    return "unknown"


def source_bucket(value: object) -> str:
    text = str(value or "").strip().lower()
    if "fixed_recheck" in text:
        return "fixed_recheck"
    if "manual" in text:
        return "manual"
    if text == "auto" or "opening" in text or "auto" in text:
        return "auto"
    return "other"


def is_sell(value: object) -> bool:
    text = str(value or "").strip()
    upper = text.upper()
    return upper in {"SELL", "S"} or "매도" in text


def is_buy(value: object) -> bool:
    text = str(value or "").strip()
    upper = text.upper()
    return upper in {"BUY", "B"} or "매수" in text


def num(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else 0.0
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    if text.startswith("$"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return 0.0


def fraction(value: object) -> float:
    number = num(str(value).strip().rstrip("%") if value is not None else None)
    if isinstance(value, str) and value.strip().endswith("%"):
        return number / 100.0
    return number / 100.0 if abs(number) > 1.0 else number
