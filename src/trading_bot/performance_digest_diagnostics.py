from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import UNKNOWN, num

UNMATCHED_SAMPLE_LIMIT = 5
MATCHED_RATIO_FAIL_THRESHOLD = 0.50
MATCHED_RATIO_WARN_THRESHOLD = 0.80


def matched_ratio_metrics(realized_exit_count: object, matched_trade_count: object) -> dict[str, Any]:
    realized = count_or_none(realized_exit_count)
    matched = count_or_none(matched_trade_count)
    if realized is None or matched is None:
        return {"ratio": UNKNOWN, "status": "WARN"}
    if realized <= 0:
        return {"ratio": 1.0, "status": "OK"}
    ratio = max(min(matched / realized, 1.0), 0.0)
    if ratio < MATCHED_RATIO_FAIL_THRESHOLD:
        status = "FAIL"
    elif ratio < MATCHED_RATIO_WARN_THRESHOLD:
        status = "WARN"
    else:
        status = "OK"
    return {"ratio": ratio, "status": status}


def build_unmatched_breakdown(
    *,
    sell_rows: Sequence[Mapping[str, Any]],
    buy_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    candidate_evaluation_rows: Sequence[Mapping[str, Any]],
    duplicate_rows: Sequence[Mapping[str, Any]],
    realized_exit_count: object,
    matched_trade_count: object,
) -> dict[str, Any]:
    realized = count_or_none(realized_exit_count)
    matched = count_or_none(matched_trade_count)
    expected_unmatched = None if realized is None or matched is None else max(realized - matched, 0)
    if expected_unmatched == 0:
        return {"count": 0, "count_basis": "realized_exit_count_minus_matched_trade_count", "reasons": []}

    if not sell_rows:
        count = expected_unmatched if expected_unmatched is not None else 0
        return {
            "count": count,
            "count_basis": "realized_exit_count_minus_matched_trade_count",
            "reasons": [
                {
                    "reason": "SELL_FILL_MISSING",
                    "count": count,
                    "samples": [],
                }
            ]
            if count
            else [],
        }

    candidate_capacity = _candidate_capacity(candidate_rows)
    candidates_by_key = _rows_by_key(candidate_rows, date_field="trade_date", symbol_field="ticker")
    evaluations_by_key = _latest_evaluations(candidate_evaluation_rows)
    buy_keys = {_row_key(row, date_field="trade_date", symbol_field="ticker") for row in buy_rows}
    duplicate_keys = _duplicate_keys(duplicate_rows)
    candidate_dates_by_symbol = _dates_by_symbol(candidate_rows, date_field="trade_date", symbol_field="ticker")
    candidate_symbols_by_date = _symbols_by_date(candidate_rows, date_field="trade_date", symbol_field="ticker")
    sell_group_sizes = Counter(_sell_group_key(row) for row in sell_rows)

    reason_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(sell_rows, key=_sell_sort_key):
        key = _row_key(row, date_field="trade_date", symbol_field="ticker")
        if candidate_capacity[key] > 0:
            candidate_capacity[key] -= 1
            continue
        reason = _unmatched_reason(
            row,
            key,
            candidates_by_key,
            evaluations_by_key,
            buy_keys,
            duplicate_keys,
            candidate_dates_by_symbol,
            candidate_symbols_by_date,
            sell_group_sizes,
        )
        reason_counts[reason] += 1
        if len(samples[reason]) < UNMATCHED_SAMPLE_LIMIT:
            samples[reason].append(_unmatched_sample(row, candidates_by_key.get(key), evaluations_by_key.get(key)))

    classified_count = sum(reason_counts.values())
    if expected_unmatched is not None and expected_unmatched > classified_count:
        reason_counts["UNKNOWN"] += expected_unmatched - classified_count
    return {
        "count": expected_unmatched if expected_unmatched is not None else classified_count,
        "count_basis": "realized_exit_count_minus_matched_trade_count",
        "reasons": [
            {"reason": reason, "count": count, "samples": samples.get(reason, [])}
            for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
            if count
        ],
    }


def count_or_none(value: object) -> int | None:
    if value == UNKNOWN:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _candidate_capacity(rows: Sequence[Mapping[str, Any]]) -> Counter[tuple[str, str]]:
    capacity: Counter[tuple[str, str]] = Counter()
    for row in rows:
        key = _row_key(row, date_field="trade_date", symbol_field="ticker")
        capacity[key] += int(num(row.get("sell_count")))
    return capacity


def _rows_by_key(
    rows: Sequence[Mapping[str, Any]],
    *,
    date_field: str,
    symbol_field: str,
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        result[_row_key(row, date_field=date_field, symbol_field=symbol_field)].append(row)
    return result


def _latest_evaluations(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in rows:
        key = _row_key(row, date_field="trading_date", symbol_field="symbol")
        latest[key] = row
    return latest


def _row_key(row: Mapping[str, Any], *, date_field: str, symbol_field: str) -> tuple[str, str]:
    return (_date_text(row.get(date_field)), _symbol_text(row.get(symbol_field)))


def _sell_group_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _date_text(row.get("trade_date")),
        _symbol_text(row.get("ticker")),
        str(row.get("order_no") or "").strip(),
    )


def _duplicate_keys(rows: Sequence[Mapping[str, Any]]) -> set[tuple[str, str, str, str, str]]:
    return {
        (
            _date_text(row.get("trade_date")),
            _symbol_text(row.get("ticker")),
            str(row.get("side") or "").strip().upper(),
            str(row.get("order_no") or "").strip(),
            str(row.get("fill_time") or "").strip(),
        )
        for row in rows
    }


def _dates_by_symbol(rows: Sequence[Mapping[str, Any]], *, date_field: str, symbol_field: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        result[_symbol_text(row.get(symbol_field))].add(_date_text(row.get(date_field)))
    return result


def _symbols_by_date(rows: Sequence[Mapping[str, Any]], *, date_field: str, symbol_field: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        result[_date_text(row.get(date_field))].add(_symbol_text(row.get(symbol_field)))
    return result


def _unmatched_reason(
    row: Mapping[str, Any],
    key: tuple[str, str],
    candidates_by_key: Mapping[tuple[str, str], list[Mapping[str, Any]]],
    evaluations_by_key: Mapping[tuple[str, str], Mapping[str, Any]],
    buy_keys: set[tuple[str, str]],
    duplicate_keys: set[tuple[str, str, str, str, str]],
    candidate_dates_by_symbol: Mapping[str, set[str]],
    candidate_symbols_by_date: Mapping[str, set[str]],
    sell_group_sizes: Counter[tuple[str, str, str]],
) -> str:
    duplicate_key = (
        key[0],
        key[1],
        str(row.get("side") or "").strip().upper(),
        str(row.get("order_no") or "").strip(),
        str(row.get("fill_time") or "").strip(),
    )
    if duplicate_key in duplicate_keys:
        return "DUPLICATE_SELL_SUSPECT"
    candidates = candidates_by_key.get(key, [])
    evaluation = evaluations_by_key.get(key)
    if not candidates and evaluation is None:
        if key[0] in candidate_dates_by_symbol.get(key[1], set()):
            return "SYMBOL_MISMATCH"
        if candidate_dates_by_symbol.get(key[1]):
            return "TRADE_DATE_MISMATCH"
        if candidate_symbols_by_date.get(key[0]):
            return "SYMBOL_MISMATCH"
        return "NO_CANDIDATE_ROW_FOR_SYMBOL_DATE"
    if key not in buy_keys:
        return "BUY_FILL_MISSING"
    if not str(row.get("order_no") or "").strip():
        return "ORDER_ID_MISSING"
    source = _first_value(candidates, "source") or (evaluation or {}).get("source")
    score = _first_value(candidates, "final_score") or (evaluation or {}).get("final_score")
    if not source:
        return "SOURCE_MISSING"
    if score in {None, ""}:
        return "SCORE_MISSING"
    if sell_group_sizes[_sell_group_key(row)] > 1:
        return "PARTIAL_FILL_OR_SPLIT_ORDER"
    return "UNKNOWN"


def _unmatched_sample(
    row: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]] | None,
    evaluation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidate = candidate_rows[0] if candidate_rows else {}
    return {
        "trade_date": _date_text(row.get("trade_date")),
        "symbol": _symbol_text(row.get("ticker")),
        "sell_time": row.get("fill_time"),
        "sell_price": row.get("fill_price"),
        "pnl": row.get("profit_usd"),
        "order_id": row.get("order_no") or (evaluation or {}).get("order_id"),
        "candidate_id": (evaluation or {}).get("id"),
        "evaluation_id": (evaluation or {}).get("id") or candidate.get("id"),
    }


def _first_value(rows: Sequence[Mapping[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return None


def _sell_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (_date_text(row.get("trade_date")), _symbol_text(row.get("ticker")), str(row.get("fill_time") or ""))


def _date_text(value: object) -> str:
    return str(value or "")[:10]


def _symbol_text(value: object) -> str:
    return str(value or "").strip().upper()
