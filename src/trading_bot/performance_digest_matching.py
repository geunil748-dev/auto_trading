from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.performance_digest_buckets import is_buy, is_sell, num
from trading_bot.performance_digest_matching_utils import (
    base_ledger_row,
    buy_candidates_before_sell,
    candidate_capacity,
    confidence_count,
    copy_candidate,
    duplicate_key,
    duplicates_by_key,
    ledger_sample,
    mark_duplicate,
    mark_matched,
    mark_unmatched,
    pick_candidate,
    row_key,
    rows_by_key,
    rows_by_symbol,
    sell_sort_key,
    trade_exit_reasons,
    truthy,
    unmatched_reason,
)

LEDGER_COLUMNS = (
    "row_no",
    "trade_date",
    "symbol",
    "side",
    "sell_time",
    "sell_order_id",
    "sell_fill_id",
    "sell_qty",
    "sell_price",
    "realized_pnl",
    "exit_reason",
    "candidate_eval_id",
    "candidate_trade_date",
    "candidate_symbol",
    "candidate_score",
    "candidate_source",
    "buy_order_id",
    "buy_fill_id",
    "buy_time",
    "matched_status",
    "match_confidence",
    "match_method",
    "unmatched_reason",
    "unmatched_detail",
    "missing_fields",
)


def build_matching_ledger(
    *,
    fill_rows: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
    candidate_evaluation_rows: Sequence[Mapping[str, Any]],
    duplicate_rows: Sequence[Mapping[str, Any]],
    trade_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    sell_rows = [row for row in fill_rows if is_sell(row.get("side"))]
    buy_rows = [row for row in fill_rows if is_buy(row.get("side"))]
    buy_by_symbol = rows_by_symbol(buy_rows, symbol_field="ticker")
    capacity_by_key = candidate_capacity(candidate_rows)
    candidate_by_key = rows_by_key(candidate_rows, date_field="trade_date", symbol_field="ticker")
    eligible_evaluations = [
        row
        for row in candidate_evaluation_rows
        if truthy(row.get("buy_allowed")) or truthy(row.get("order_submitted"))
    ]
    evaluations_by_key = rows_by_key(eligible_evaluations, date_field="trading_date", symbol_field="symbol")
    evaluations_by_symbol = rows_by_symbol(candidate_evaluation_rows, symbol_field="symbol")
    duplicate_lookup = duplicates_by_key(duplicate_rows)
    exits_by_key = trade_exit_reasons(trade_rows or [])
    ledger = []
    for row_no, sell in enumerate(sorted(sell_rows, key=sell_sort_key), start=1):
        key = row_key(sell, date_field="trade_date", symbol_field="ticker")
        buys_before_sell = buy_candidates_before_sell(sell, buy_by_symbol.get(key[1], []))
        same_key_candidates = candidate_by_key.get(key, [])
        same_key_evaluations = evaluations_by_key.get(key, [])
        candidate = pick_candidate(same_key_candidates, same_key_evaluations)
        ledger_row = base_ledger_row(row_no, sell, candidate, buys_before_sell, exits_by_key.get(key))

        duplicate = duplicate_lookup.get(duplicate_key(sell))
        if duplicate:
            mark_duplicate(ledger_row, duplicate)
        elif _is_unambiguous_candidate(same_key_candidates, same_key_evaluations) and _has_score_source_capacity(
            capacity_by_key,
            key,
            candidate,
        ):
            capacity_by_key[key] -= 1
            mark_matched(ledger_row, "SYMBOL_TRADE_DATE", "HIGH", "")
        else:
            reason, detail, fallback_candidate = unmatched_reason(
                sell=sell,
                key=key,
                same_key_candidates=same_key_candidates,
                same_key_evaluations=same_key_evaluations,
                symbol_evaluations=evaluations_by_symbol.get(key[1], []),
                symbol_buy_rows=buy_by_symbol.get(key[1], []),
                buy_candidates=buys_before_sell,
            )
            if fallback_candidate:
                copy_candidate(ledger_row, fallback_candidate)
            mark_unmatched(ledger_row, reason, detail)
        ledger.append(ledger_row)
    return ledger


def matching_quality(ledger: Sequence[Mapping[str, Any]], matched_trade_count: object) -> dict[str, Any]:
    sell_count = len(ledger)
    matched = int(num(matched_trade_count))
    unknown = sum(1 for row in ledger if row.get("unmatched_reason") == "UNKNOWN")
    ambiguous = sum(1 for row in ledger if "AMBIGUOUS" in str(row.get("unmatched_reason") or ""))
    return {
        "sell_count": sell_count,
        "matched_trade_count": matched,
        "matched_ratio": matched / sell_count if sell_count else 1.0,
        "high_confidence_match_count": confidence_count(ledger, "HIGH"),
        "medium_confidence_match_count": confidence_count(ledger, "MEDIUM"),
        "low_confidence_match_count": confidence_count(ledger, "LOW"),
        "unmatched_trade_count": max(sell_count - matched, 0),
        "unknown_reason_count": unknown,
        "ambiguous_match_count": ambiguous,
    }


def unmatched_breakdown_from_ledger(ledger: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in ledger:
        if row.get("matched_status") == "MATCHED":
            continue
        grouped[str(row.get("unmatched_reason") or "UNKNOWN")].append(row)
    return {
        "count": sum(len(items) for items in grouped.values()),
        "count_basis": "matching_ledger_non_matched_rows",
        "reasons": [
            {"reason": reason, "count": len(items), "samples": [_sample_with_required_detail(item) for item in items[:5]]}
            for reason, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
    }


def matching_recommendation(
    unmatched_breakdown: Mapping[str, Any],
    duplicate_suspects: Mapping[str, Any],
    reconciliation_detail: Mapping[str, Any],
) -> dict[str, Any]:
    counts = {item["reason"]: item["count"] for item in unmatched_breakdown.get("reasons", [])}
    ambiguous_count = sum(count for reason, count in counts.items() if "AMBIGUOUS" in reason)
    missing_candidate_count = counts.get("NO_CANDIDATE_ROW_FOR_SYMBOL_DATE", 0) + counts.get("CANDIDATE_QUERY_EMPTY", 0)
    date_count = counts.get("DATE_BOUNDARY_UNCERTAIN", 0) + counts.get("TRADE_DATE_MISMATCH", 0)
    partial_count = counts.get("PARTIAL_FILL_NEEDS_AGGREGATION", 0) + int(
        duplicate_suspects.get("partial_fill_candidate_count") or 0
    )
    max_count = max([ambiguous_count, missing_candidate_count, date_count, partial_count, 0])
    if ambiguous_count and ambiguous_count == max_count:
        priority = "review execution ledger rows with multiple active candidates before score/source analysis"
        category = "matching logic problem"
    elif missing_candidate_count:
        priority = "include candidate and execution context for traded symbols in Slack data packet"
        category = "Slack packet data coverage problem"
    elif date_count:
        priority = "normalize trading session date between fills and candidates"
        category = "date/session problem"
    elif partial_count:
        priority = "aggregate partial fills before matching and PnL reconciliation"
        category = "partial fill/duplicate problem"
    elif counts:
        priority = "review matching ledger unmatched_detail for remaining ambiguous rows"
        category = "matching logic problem"
    else:
        priority = "monitor data quality"
        category = "none"
    if "daily summary basis mismatch" in reconciliation_detail.get("suspected_causes", []):
        category = f"{category}; daily summary basis mismatch"
    return {"next_data_quality_fix": priority, "category": category}


def write_matching_ledger_csv(path: Path | str, ledger: Sequence[Mapping[str, Any]]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEDGER_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ledger)
    return output


def _has_score_source_capacity(
    capacity_by_key: Mapping[tuple[str, str], int],
    key: tuple[str, str],
    candidate: Mapping[str, Any] | None,
) -> bool:
    if capacity_by_key.get(key, 0) <= 0 or not candidate:
        return False
    if candidate.get("final_score") in {None, ""}:
        return False
    return bool(str(candidate.get("source") or "").strip())


def _is_unambiguous_candidate(
    same_key_candidates: Sequence[Mapping[str, Any]],
    same_key_evaluations: Sequence[Mapping[str, Any]],
) -> bool:
    return max(len(same_key_candidates), len(same_key_evaluations)) <= 1


def _sample_with_required_detail(row: Mapping[str, Any]) -> dict[str, Any]:
    sample = ledger_sample(row)
    if row.get("unmatched_reason") == "UNKNOWN" and not sample.get("diagnostic_detail"):
        sample["diagnostic_detail"] = "diagnostic_detail_missing_for_unknown_reason"
    return sample
