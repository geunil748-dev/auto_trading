from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import num
from trading_bot.performance_digest_duplicates import duplicate_reason_and_confidence


def base_ledger_row(
    row_no: int,
    sell: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    buys: Sequence[Mapping[str, Any]],
    exit_reason: str | None,
) -> dict[str, Any]:
    buy = buys[-1] if buys else {}
    row = {
        "row_no": row_no,
        "trade_date": date_text(sell.get("trade_date")),
        "symbol": symbol(sell.get("ticker")),
        "side": sell.get("side"),
        "sell_time": sell.get("fill_time"),
        "sell_order_id": sell.get("order_no"),
        "sell_fill_id": sell.get("id"),
        "sell_qty": sell.get("quantity"),
        "sell_price": sell.get("fill_price"),
        "realized_pnl": sell.get("profit_usd"),
        "exit_reason": exit_reason or "UNKNOWN",
        "buy_order_id": buy.get("order_no"),
        "buy_fill_id": buy.get("id"),
        "buy_time": buy.get("fill_time"),
        "buy_qty": buy.get("quantity"),
        "buy_price": buy.get("fill_price"),
        "buy_entry_reason": buy.get("entry_reason"),
        "buy_entry_reason_detail": buy.get("entry_reason_detail"),
        "matched_status": "UNMATCHED",
        "match_confidence": "NONE",
        "match_method": "NO_MATCH",
        "unmatched_reason": "",
        "unmatched_detail": "",
        "missing_fields": "",
    }
    copy_candidate(row, candidate)
    row["missing_fields"] = ",".join(missing_fields(row))
    return row


def unmatched_reason(
    *,
    sell: Mapping[str, Any],
    key: tuple[str, str],
    same_key_candidates: Sequence[Mapping[str, Any]],
    same_key_evaluations: Sequence[Mapping[str, Any]],
    symbol_evaluations: Sequence[Mapping[str, Any]],
    symbol_buy_rows: Sequence[Mapping[str, Any]],
    buy_candidates: Sequence[Mapping[str, Any]],
) -> tuple[str, str, Mapping[str, Any] | None]:
    missing = missing_sell_fields(sell)
    if missing:
        return missing[0], f"missing_fields={','.join(missing)}", None
    candidate_row_count = max(len(same_key_candidates), len(same_key_evaluations))
    if candidate_row_count > 1:
        candidate = pick_candidate(same_key_candidates, same_key_evaluations)
        return "MULTIPLE_CANDIDATE_ROWS_AMBIGUOUS", f"candidate_rows={candidate_row_count}", candidate
    if not buy_candidates:
        if any(sort_tuple(buy.get("trade_date"), buy.get("fill_time")) > sort_tuple(sell.get("trade_date"), sell.get("fill_time")) for buy in symbol_buy_rows):
            return "SELL_BEFORE_BUY_TIME", "same_symbol_buy_fill_exists_after_sell_time", candidate_from(symbol_evaluations)
        return "MISSING_BUY_LINK", "no_buy_fill_before_sell", candidate_from(symbol_evaluations)
    if not same_key_candidates and not same_key_evaluations:
        candidate = candidate_from(symbol_evaluations)
        if candidate is None:
            return "NO_CANDIDATE_ROW_FOR_SYMBOL_DATE", "candidate_evaluations has no row for this symbol in range", None
        candidate_date = date_key(candidate, date_field="trading_date")
        if candidate_date != key[0]:
            return "DATE_BOUNDARY_UNCERTAIN", f"sell_trade_date={key[0]}; candidate_trade_date={candidate_date}", candidate
        return "CANDIDATE_QUERY_EMPTY", "candidate query returned no eligible row for symbol/date", candidate
    candidate = pick_candidate(same_key_candidates, same_key_evaluations)
    if len(buy_candidates) > 1:
        return "MULTIPLE_BUY_FILLS_AMBIGUOUS", f"buy_fill_count_before_sell={len(buy_candidates)}", candidate
    if not value(candidate, "source"):
        return "SOURCE_NOT_RECORDED", "candidate source is empty", candidate
    if value(candidate, "final_score") in {None, ""}:
        return "SCORE_NOT_RECORDED", "candidate final_score is empty", candidate
    return "PARTIAL_FILL_NEEDS_AGGREGATION", "candidate aggregate capacity already consumed by prior sell rows", candidate


def mark_matched(row: dict[str, Any], method: str, confidence: str, detail: str) -> None:
    row["matched_status"] = "MATCHED"
    row["match_confidence"] = confidence
    row["match_method"] = method
    row["unmatched_reason"] = ""
    row["unmatched_detail"] = detail


def mark_unmatched(row: dict[str, Any], reason: str, detail: str) -> None:
    row["matched_status"] = "UNMATCHED"
    row["match_confidence"] = "NONE"
    row["match_method"] = "NO_MATCH"
    row["unmatched_reason"] = reason
    row["unmatched_detail"] = detail


def mark_duplicate(row: dict[str, Any], duplicate: Mapping[str, Any]) -> None:
    default_reason, default_confidence = duplicate_reason_and_confidence(duplicate)
    reason = str(duplicate.get("duplicate_reason") or default_reason)
    confidence = str(duplicate.get("duplicate_confidence") or default_confidence)
    row["matched_status"] = "PARTIAL_FILL_GROUPED" if "PARTIAL" in reason else "DUPLICATE_SUSPECT"
    row["match_confidence"] = confidence if confidence in {"LOW", "MEDIUM", "HIGH"} else "LOW"
    row["match_method"] = "NO_MATCH"
    row["unmatched_reason"] = "PARTIAL_FILL_NEEDS_AGGREGATION" if "PARTIAL" in reason else "DUPLICATE_SELL_SUSPECT"
    row["unmatched_detail"] = f"duplicate_reason={reason}; duplicate_confidence={confidence}"


def copy_candidate(row: dict[str, Any], candidate: Mapping[str, Any] | None) -> None:
    candidate = candidate or {}
    row["candidate_eval_id"] = candidate.get("id")
    row["candidate_trade_date"] = date_text(candidate.get("trade_date") or candidate.get("trading_date"))
    row["candidate_symbol"] = symbol(candidate.get("ticker") or candidate.get("symbol"))
    row["candidate_score"] = candidate.get("final_score")
    row["candidate_source"] = candidate.get("source")


def ledger_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": row.get("trade_date"),
        "symbol": row.get("symbol"),
        "sell_time": row.get("sell_time"),
        "sell_price": row.get("sell_price"),
        "pnl": row.get("realized_pnl"),
        "order_id": row.get("sell_order_id"),
        "candidate_id": row.get("candidate_eval_id"),
        "evaluation_id": row.get("candidate_eval_id"),
        "missing_fields": row.get("missing_fields"),
        "diagnostic_detail": row.get("unmatched_detail"),
    }


def confidence_count(ledger: Sequence[Mapping[str, Any]], confidence: str) -> int:
    return sum(1 for row in ledger if row.get("matched_status") == "MATCHED" and row.get("match_confidence") == confidence)


def candidate_capacity(rows: Sequence[Mapping[str, Any]]) -> Counter[tuple[str, str]]:
    capacity: Counter[tuple[str, str]] = Counter()
    for row in rows:
        capacity[row_key(row, date_field="trade_date", symbol_field="ticker")] += int(num(row.get("sell_count")))
    return capacity


def rows_by_key(rows: Sequence[Mapping[str, Any]], *, date_field: str, symbol_field: str) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row_key(row, date_field=date_field, symbol_field=symbol_field)].append(row)
    return grouped


def rows_by_symbol(rows: Sequence[Mapping[str, Any]], *, symbol_field: str) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[symbol(row.get(symbol_field))].append(row)
    return {key: sorted(value, key=fill_sort_key) for key, value in grouped.items()}


def duplicates_by_key(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str, str, str], Mapping[str, Any]]:
    return {duplicate_key(row, symbol_field="ticker"): row for row in rows}


def duplicate_key(row: Mapping[str, Any], *, symbol_field: str = "ticker") -> tuple[str, str, str, str, str]:
    return (
        date_text(row.get("trade_date")),
        symbol(row.get(symbol_field)),
        str(row.get("side") or "").strip().upper(),
        str(row.get("order_no") or "").strip(),
        str(row.get("fill_time") or "").strip(),
    )


def trade_exit_reasons(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    result = {}
    for row in rows:
        reason = str(row.get("exit_reason") or "").strip()
        if reason:
            result[row_key(row, date_field="trade_date", symbol_field="ticker")] = reason
    return result


def buy_candidates_before_sell(sell: Mapping[str, Any], buys: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    sell_key = sort_tuple(sell.get("trade_date"), sell.get("fill_time"))
    return [buy for buy in buys if sort_tuple(buy.get("trade_date"), buy.get("fill_time")) <= sell_key]


def pick_candidate(candidates: Sequence[Mapping[str, Any]], evaluations: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if candidates:
        return candidates[-1]
    return evaluations[-1] if evaluations else None


def candidate_from(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return rows[-1] if rows else None


def missing_sell_fields(row: Mapping[str, Any]) -> list[str]:
    missing = []
    if not symbol(row.get("ticker")):
        missing.append("MISSING_SYMBOL")
    if not date_text(row.get("trade_date")):
        missing.append("MISSING_TRADE_DATE")
    if not str(row.get("order_no") or "").strip():
        missing.append("MISSING_SELL_ORDER_ID")
    if row.get("id") in {None, ""}:
        missing.append("MISSING_SELL_FILL_ID")
    return missing


def missing_fields(row: Mapping[str, Any]) -> list[str]:
    fields = []
    for key in ("sell_order_id", "sell_fill_id", "buy_order_id", "candidate_eval_id", "candidate_source"):
        if not row.get(key):
            fields.append(key)
    if row.get("candidate_score") in {None, ""}:
        fields.append("candidate_score")
    return fields


def truthy(value_: Any) -> bool:
    if isinstance(value_, bool):
        return value_
    try:
        return int(value_ or 0) == 1
    except (TypeError, ValueError):
        return str(value_ or "").strip().lower() in {"true", "yes", "y"}


def value(row: Mapping[str, Any] | None, key: str) -> Any:
    return (row or {}).get(key)


def row_key(row: Mapping[str, Any], *, date_field: str, symbol_field: str) -> tuple[str, str]:
    return (date_text(row.get(date_field)), symbol(row.get(symbol_field)))


def date_key(row: Mapping[str, Any], *, date_field: str) -> str:
    return date_text(row.get(date_field))


def date_text(value_: object) -> str:
    text = str(value_ or "").strip()
    if not text:
        return ""
    iso = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso:
        return iso.group(1)
    md = re.match(r"^(\d{2})-(\d{2})", text)
    if md:
        return f"{md.group(1)}-{md.group(2)}"
    return text[:10]


def symbol(value_: object) -> str:
    return str(value_ or "").strip().upper()


def sell_sort_key(row: Mapping[str, Any]) -> tuple[int, int, int]:
    return sort_tuple(row.get("trade_date"), row.get("fill_time"))


def fill_sort_key(row: Mapping[str, Any]) -> tuple[int, int, int]:
    return sort_tuple(row.get("trade_date"), row.get("fill_time"))


def sort_tuple(date_value: object, time_value: object) -> tuple[int, int, int]:
    date_text_value = date_text(date_value)
    month, day = 0, 0
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_text_value):
        _, month_text, day_text = date_text_value.split("-")
        month, day = int(month_text), int(day_text)
    elif re.match(r"^\d{2}-\d{2}$", date_text_value):
        month_text, day_text = date_text_value.split("-")
        month, day = int(month_text), int(day_text)
    return (month, day, seconds(time_value))


def seconds(value_: object) -> int:
    match = re.search(r"(\d{1,2}):(\d{2}):(\d{2})", str(value_ or ""))
    if not match:
        return 0
    hour, minute, second = (int(part) for part in match.groups())
    return hour * 3600 + minute * 60 + second
