from __future__ import annotations

import json
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

SINGLE_ROW = "SINGLE_ROW"
EXACT_DUPLICATE_COLLAPSED = "EXACT_DUPLICATE_COLLAPSED"
LEGACY_CUMULATIVE_LATEST = "LEGACY_CUMULATIVE_LATEST"
DELTA_ROWS_SUMMED = "DELTA_ROWS_SUMMED"
NO_ORDER_NO_FALLBACK = "NO_ORDER_NO_FALLBACK"
AMBIGUOUS_EXCLUDED = "AMBIGUOUS_EXCLUDED"
AMBIGUOUS_WARNING = "AMBIGUOUS_FILLS_EXCLUDED"
MONEY_TOLERANCE = Decimal("0.01")
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_TIME_RE = re.compile(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?")


def normalize_side(value: Any) -> str:
    text = text_value(value)
    upper = text.upper()
    if upper in {"BUY", "B"} or text == "매수":
        return "BUY"
    if upper in {"SELL", "S"} or text == "매도":
        return "SELL"
    return "UNKNOWN"


def normalized_side_sql(column_expression: str) -> str:
    expression = column_expression.strip()
    if not expression:
        raise ValueError("column_expression must not be empty")
    cleaned = f"LTRIM(RTRIM(COALESCE(CONVERT(NVARCHAR(40), {expression}), N'')))"
    return (
        "CASE "
        f"WHEN UPPER({cleaned}) IN ('BUY', 'B') OR {cleaned} = N'매수' THEN 'BUY' "
        f"WHEN UPPER({cleaned}) IN ('SELL', 'S') OR {cleaned} = N'매도' THEN 'SELL' "
        "ELSE 'UNKNOWN' END"
    )


def prepare_fill(source: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(source)
    return {
        "raw": row,
        "source_id": text_value(row.get("id")),
        "trade_date": date_text(row.get("trade_date", row.get("fill_date"))),
        "is_mock": mode_is_mock(row),
        "ticker": ticker_text(row.get("ticker", row.get("symbol"))),
        "ticker_name": text_value(row.get("ticker_name", row.get("name"))),
        "raw_side": text_value(row.get("side")),
        "side": normalize_side(row.get("side")),
        "order_no": text_value(row.get("order_no", row.get("orderNo"))),
        "fill_time": text_value(row.get("fill_time", row.get("time"))),
        "quantity": integer_value(row.get("quantity")),
        "fill_price": decimal_value(row.get("fill_price", row.get("price"))),
        "fill_amount": decimal_value(row.get("fill_amount", row.get("total"))),
        "profit_usd": decimal_value(row.get("profit_usd")),
        "profit_rate": decimal_value(row.get("profit_rate")),
        "entry_reason": text_value(row.get("entry_reason")),
        "entry_reason_detail": text_value(row.get("entry_reason_detail")),
        "created_at": date_time_text(row.get("created_at")),
    }


def prepare_trade(source: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(source)
    last_fill_time = text_value(row.get("last_fill_time", row.get("fill_time")))
    return {
        "raw": row,
        "source_id": text_value(row.get("id")),
        "trade_date": date_text(row.get("trade_date")),
        "is_mock": mode_is_mock(row),
        "ticker": ticker_text(row.get("ticker", row.get("symbol"))),
        "side": normalize_side(row.get("order_type", row.get("side"))),
        "order_no": text_value(row.get("order_no", row.get("orderNo"))),
        "exit_reason": text_value(row.get("exit_reason")),
        "last_fill_time": last_fill_time,
        "time_seconds": time_seconds(last_fill_time),
        "created_at": date_time_text(row.get("created_at")),
    }


def fill_group_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    common = (row["trade_date"], row["is_mock"], row["side"], row["ticker"])
    if row["order_no"]:
        return ("ORDER", *common, row["order_no"])
    return (
        "FALLBACK",
        *common,
        row["fill_time"],
        decimal_text(row["fill_price"]),
        row["quantity"],
    )


def order_evidence_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row["trade_date"], row["is_mock"], row["side"], row["ticker"], row["order_no"])


def financial_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        row["trade_date"], row["is_mock"], row["side"], row["ticker"], row["order_no"],
        row["fill_time"], decimal_text(row["quantity"]), decimal_text(row["fill_price"]),
        decimal_text(row["fill_amount"]), decimal_text(row["profit_usd"]),
        decimal_text(row["profit_rate"]),
    )


def weighted_value(rows: Sequence[Mapping[str, Any]], field: str) -> Decimal | None:
    if not rows or any(row.get(field) is None for row in rows):
        return None
    quantity = sum(int(row["quantity"]) for row in rows)
    if quantity <= 0:
        return None
    return sum(row[field] * int(row["quantity"]) for row in rows) / quantity


def average_decimal(values: Any) -> float | None:
    decimals = [decimal_value(value) for value in values]
    decimals = [value for value in decimals if value is not None]
    return float_value(sum(decimals, Decimal("0")) / len(decimals)) if decimals else None


def score_bucket(value: Any) -> str:
    score = decimal_value(value)
    if score is None:
        return "unknown"
    for ceiling, label in ((40, "<40"), (50, "40~50"), (60, "50~60"), (70, "60~70"), (80, "70~80")):
        if score < ceiling:
            return label
    return "80+"


def prepared_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row.get("created_at", ""), id_sort_key(row.get("source_id")), canonical(row.get("raw", row)))


def candidate_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        date_time_text(row.get("evaluation_time", row.get("created_at"))),
        id_sort_key(row.get("id")),
        canonical(row),
    )


def source_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        date_time_text(row.get("updated_at", row.get("created_at"))),
        id_sort_key(row.get("id")),
        canonical(row),
    )


def id_sort_key(value: Any) -> tuple[int, Any]:
    text = text_value(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def group_key_text(key: tuple[Any, ...]) -> str:
    return "|".join("" if value is None else str(value) for value in key)


def latest_text(rows: Sequence[Mapping[str, Any]], field: str) -> str:
    for row in reversed(rows):
        value = text_value(row.get(field))
        if value:
            return value
    return ""


def ordered_unique(values: Any) -> list[str]:
    return list(dict.fromkeys(values))


def date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = text_value(value)
    return text[:10] if text else ""


def date_time_text(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return text_value(value)


def time_seconds(value: Any) -> int | None:
    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second
    match = _TIME_RE.search(text_value(value))
    if not match:
        return None
    hour, minute, second = int(match["hour"]), int(match["minute"]), int(match["second"] or 0)
    return hour * 3600 + minute * 60 + second if hour <= 23 and minute <= 59 and second <= 59 else None


def time_distance(left: Any, right: Any) -> int | None:
    left_seconds, right_seconds = time_seconds(left), time_seconds(right)
    if left_seconds is None or right_seconds is None:
        return None
    direct = abs(left_seconds - right_seconds)
    return min(direct, 24 * 3600 - direct)


def decimal_value(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    text = text_value(value).replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def integer_value(value: Any) -> int | None:
    number = decimal_value(value)
    return int(number) if number is not None and number == number.to_integral_value() else None


def optional_bool(value: Any) -> bool | None:
    if value is None or text_value(value) == "":
        return None
    if isinstance(value, bool):
        return value
    text = text_value(value).lower()
    if text in {"1", "true", "yes", "y", "mock", "test"}:
        return True
    if text in {"0", "false", "no", "n", "real", "live"}:
        return False
    return None


def mode_is_mock(row: Mapping[str, Any]) -> bool | None:
    for field in ("is_mock", "mode"):
        if field in row and (value := optional_bool(row.get(field))) is not None:
            return value
    return None


def mode_text(row: Mapping[str, Any]) -> str:
    value = mode_is_mock(row)
    return "UNKNOWN" if value is None else ("MOCK" if value else "REAL")


def is_trusted_normalized_row(row: Mapping[str, Any]) -> bool:
    return (
        text_value(row.get("normalization_confidence")).upper() == "HIGH"
        and not truthy(row.get("excluded_from_trusted_pnl"))
    )


def is_best_effort_normalized_row(row: Mapping[str, Any]) -> bool:
    return (
        text_value(row.get("normalization_method")) != AMBIGUOUS_EXCLUDED
        and not truthy(row.get("excluded_from_best_effort_pnl"))
    )


def truthy(value: Any) -> bool:
    return bool(optional_bool(value))


def ticker_text(value: Any) -> str:
    return text_value(value).upper()


def text_value(value: Any) -> str:
    return "" if value is None else str(value).strip()


def decimal_text(value: Any) -> str:
    number = value if isinstance(value, Decimal) else decimal_value(value)
    return "" if number is None else format(number, "f")


def number_text(value: Any) -> str:
    return str(value) if isinstance(value, int) else decimal_text(value)


def float_value(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
