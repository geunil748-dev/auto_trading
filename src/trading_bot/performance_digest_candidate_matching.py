from __future__ import annotations

import csv
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from trading_bot.performance_digest_buckets import num
from trading_bot.performance_digest_candidate_matching_columns import (
    AMBIGUOUS_ANALYSIS_COLUMNS,
    LEDGER_V2_COLUMNS,
)
from trading_bot.performance_digest_matching_utils import date_text, seconds, symbol

SUBMITTED_DECISIONS = {"ORDER_SUBMITTED", "BUY_SUBMITTED", "SUBMITTED", "ORDER_FILLED", "FILLED"}
ALLOWED_DECISIONS = SUBMITTED_DECISIONS | {"BUY_ALLOWED", "SELECTED", ""}
BLOCKED_TOKENS = ("BLOCK", "FAILED", "REJECT", "NOT_", "COOLDOWN", "DENY")


def build_candidate_matching_diagnostics(
    ledger: Sequence[Mapping[str, Any]],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates_by_key = _candidates_by_key(candidate_rows)
    v2_rows = []
    ambiguous_rows = []
    for row in ledger:
        key = (date_text(row.get("trade_date")), symbol(row.get("symbol")))
        candidates = candidates_by_key.get(key, [])
        resolved = resolve_active_candidate(row, candidates)
        v2 = _v2_row(row, resolved)
        v2_rows.append(v2)
        if row.get("unmatched_reason") == "MULTIPLE_CANDIDATE_ROWS_AMBIGUOUS":
            ambiguous_rows.append(_analysis_row(row, candidates, resolved))
    quality = _quality(v2_rows, ambiguous_rows)
    breakdown = _breakdown(ambiguous_rows)
    return {
        "ledger_v2": v2_rows,
        "ambiguous_analysis": ambiguous_rows,
        "candidate_matching_quality": quality,
        "candidate_ambiguity_breakdown": breakdown,
        "linkage_limitations": _linkage_limitations(quality),
    }


def resolve_active_candidate(row: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(candidates, key=_candidate_sort_key)
    buy_time = row.get("buy_time")
    before = [item for item in ordered if _candidate_before_or_at(item, buy_time)]
    after = [item for item in ordered if not _candidate_before_or_at(item, buy_time)]
    blocked = [item for item in before if _is_blocked(item)]
    active = [item for item in before if not _is_blocked(item)]
    explicit = _explicit_link_candidates(row, active)
    if len(explicit) == 1:
        return _resolved(row, ordered, before, after, blocked, explicit[0], "EXPLICIT_ORDER_ID", "HIGH", "explicit order_id matches buy/sell order")
    if len(explicit) > 1:
        return _unresolved(row, ordered, before, after, blocked, "AMBIGUOUS_MULTIPLE_ACTIVE_CANDIDATES", "multiple explicit order_id candidates")
    submitted = [item for item in active if _is_submitted(item)]
    if len(submitted) == 1:
        return _resolved(row, ordered, before, after, blocked, submitted[0], "UNIQUE_SUBMITTED_CANDIDATE", "HIGH", "single submitted candidate before buy_time")
    if len(submitted) > 1:
        return _unresolved(row, ordered, before, after, blocked, "AMBIGUOUS_MULTIPLE_ACTIVE_CANDIDATES", "multiple submitted candidates before buy_time")
    if len(active) == 1 and len(before) == 1:
        return _resolved(row, ordered, before, after, blocked, active[0], "NEAREST_CANDIDATE_BEFORE_BUY", "MEDIUM", "single active candidate before buy_time without explicit order link")
    source_match = _source_entry_match(row, active)
    if len(source_match) == 1:
        return _resolved(row, ordered, before, after, blocked, source_match[0], "SOURCE_ENTRY_REASON_ASSISTED", "LOW", "source matches entry_reason only")
    if len(active) > 1:
        return _unresolved(row, ordered, before, after, blocked, "AMBIGUOUS_MULTIPLE_ACTIVE_CANDIDATES", f"active_candidate_count={len(active)}")
    return _unresolved(row, ordered, before, after, blocked, "NO_ACTIVE_CANDIDATE_FOUND", "no unblocked candidate before buy_time")


def write_rows_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output


def _v2_row(row: Mapping[str, Any], resolved: Mapping[str, Any]) -> dict[str, Any]:
    confidence = str(resolved["active_candidate_confidence"])
    included = confidence == "HIGH"
    previous_reason = str(row.get("unmatched_reason") or "")
    new_reason = "" if included else str(resolved["ambiguity_reason"] or previous_reason)
    return {
        **{key: row.get(key) for key in row},
        "session_date": row.get("trade_date"),
        "previous_unmatched_reason": previous_reason,
        "new_unmatched_reason": new_reason,
        "active_candidate_eval_id": resolved.get("active_candidate_candidate_id"),
        "active_candidate_score": resolved.get("active_candidate_score"),
        "active_candidate_source": resolved.get("active_candidate_source"),
        "active_candidate_final_decision": resolved.get("active_candidate_final_decision"),
        "active_candidate_time": resolved.get("active_candidate_time"),
        "candidate_count_for_symbol_session": resolved["candidate_count_for_symbol_session"],
        "candidate_before_buy_count": resolved["candidate_before_buy_count"],
        "candidate_after_buy_count": resolved["candidate_after_buy_count"],
        "match_method": resolved["match_method"],
        "match_confidence": confidence,
        "is_included_in_score_source_analysis": included,
        "exclusion_reason_from_score_source_analysis": "" if included else _exclusion_reason(confidence, new_reason),
        "diagnostic_detail": resolved["diagnostic_detail"],
    }


def _analysis_row(row: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]], resolved: Mapping[str, Any]) -> dict[str, Any]:
    before = [item for item in candidates if _candidate_before_or_at(item, row.get("buy_time"))]
    nearest = sorted(before, key=_candidate_sort_key)[-1] if before else {}
    return {
        "row_no": row.get("row_no"),
        "trade_date": row.get("trade_date"),
        "session_date": row.get("trade_date"),
        "symbol": row.get("symbol"),
        "sell_time": row.get("sell_time"),
        "buy_time": row.get("buy_time"),
        "sell_order_id": row.get("sell_order_id"),
        "buy_order_id": row.get("buy_order_id"),
        "sell_fill_id": row.get("sell_fill_id"),
        "buy_fill_id": row.get("buy_fill_id"),
        "realized_pnl": row.get("realized_pnl"),
        "exit_reason": row.get("exit_reason"),
        "candidate_count_for_symbol_session": len(candidates),
        "candidate_eval_ids": _join(candidates, "id"),
        "candidate_created_times": _join(candidates, "created_at"),
        "candidate_updated_times": _join(candidates, "updated_at"),
        "candidate_scores": _join(candidates, "final_score"),
        "candidate_sources": _join(candidates, "source"),
        "candidate_final_decisions": _join(candidates, "final_decision"),
        "candidate_order_statuses": _join(candidates, "order_status"),
        "candidate_entry_reasons": _join(candidates, "entry_reason"),
        "candidate_buy_block_reasons": _join(candidates, "buy_block_reason"),
        "candidate_order_ids_if_any": _join(candidates, "order_id"),
        "nearest_candidate_before_buy": nearest.get("id", ""),
        "candidate_after_buy_count": resolved["candidate_after_buy_count"],
        "candidate_before_buy_count": resolved["candidate_before_buy_count"],
        "active_candidate_candidate_id": resolved.get("active_candidate_candidate_id"),
        "active_candidate_confidence": resolved["active_candidate_confidence"],
        "ambiguity_reason": resolved["ambiguity_reason"],
        "diagnostic_detail": resolved["diagnostic_detail"],
    }


def _quality(v2_rows: Sequence[Mapping[str, Any]], ambiguous_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    methods = Counter(str(row.get("ambiguity_reason") or "") for row in ambiguous_rows)
    still = sum(1 for row in ambiguous_rows if row.get("active_candidate_confidence") in {"NONE", "LOW"})
    eligible = sum(1 for row in v2_rows if row.get("is_included_in_score_source_analysis") is True)
    excluded = len(v2_rows) - eligible
    return {
        "multiple_candidate_ambiguous_count": len(ambiguous_rows),
        "resolved_by_explicit_link_count": methods["EXPLICIT_ORDER_ID"] + methods["EXPLICIT_CANDIDATE_ID"],
        "resolved_by_unique_submitted_candidate_count": methods["UNIQUE_SUBMITTED_CANDIDATE"],
        "resolved_by_time_lifecycle_count": methods["NEAREST_CANDIDATE_BEFORE_BUY"],
        "still_ambiguous_count": still,
        "candidate_after_buy_excluded_count": sum(int(num(row.get("candidate_after_buy_count"))) for row in ambiguous_rows),
        "candidate_blocked_excluded_count": sum(1 for row in ambiguous_rows if "blocked_candidate_count=" in str(row.get("diagnostic_detail") or "")),
        "candidate_missing_link_count": sum(1 for row in ambiguous_rows if row.get("active_candidate_confidence") != "HIGH"),
        "score_source_analysis_eligible_count": eligible,
        "score_source_analysis_excluded_count": excluded,
        "ambiguous_rows_realized_pnl_sum": round(sum(num(row.get("realized_pnl")) for row in ambiguous_rows), 2),
        "score_source_excluded_pnl_sum": round(sum(num(row.get("realized_pnl")) for row in v2_rows if row.get("is_included_in_score_source_analysis") is not True), 2),
        "next_required_link_field": "explicit candidate/order link not present in Slack packet",
    }


def _breakdown(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("ambiguity_reason") or "UNKNOWN")].append(row)
    return {
        "reasons": [
            {"reason": reason, "count": len(items), "samples": [_sample(item) for item in items[:5]]}
            for reason, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ],
        "next_required_link_field": "use execution ledger and diagnostic_detail before score/source interpretation",
    }


def _linkage_limitations(quality: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "explicit_candidate_order_link_available": False,
        "effect": "score/source analysis confidence remains low when multiple candidates map to one symbol/session",
        "action_for_chatgpt": "use execution ledger and diagnostic_detail; do not change strategy based only on score/source buckets",
        "still_ambiguous_count": int(num(quality.get("still_ambiguous_count"))),
    }


def _resolved(row: Mapping[str, Any], candidates, before, after, blocked, candidate, method: str, confidence: str, detail: str) -> dict[str, Any]:
    return _result(row, candidates, before, after, blocked, candidate, method, confidence, method, detail)


def _unresolved(row: Mapping[str, Any], candidates, before, after, blocked, reason: str, detail: str) -> dict[str, Any]:
    return _result(row, candidates, before, after, blocked, None, "NO_MATCH" if reason == "NO_ACTIVE_CANDIDATE_FOUND" else reason, "NONE", reason, detail)


def _result(row, candidates, before, after, blocked, candidate, method, confidence, reason, detail) -> dict[str, Any]:
    return {
        "candidate_count_for_symbol_session": len(candidates),
        "candidate_before_buy_count": len(before),
        "candidate_after_buy_count": len(after),
        "active_candidate_candidate_id": (candidate or {}).get("id"),
        "active_candidate_score": (candidate or {}).get("final_score"),
        "active_candidate_source": (candidate or {}).get("source"),
        "active_candidate_final_decision": (candidate or {}).get("final_decision"),
        "active_candidate_time": _candidate_time(candidate or {}),
        "match_method": method,
        "active_candidate_confidence": confidence,
        "ambiguity_reason": reason,
        "diagnostic_detail": f"{detail}; candidate_count={len(candidates)}; before_buy={len(before)}; after_buy={len(after)}; blocked_candidate_count={len(blocked)}",
    }


def _candidates_by_key(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(date_text(row.get("trading_date") or row.get("trade_date")), symbol(row.get("symbol") or row.get("ticker")))].append(row)
    return {key: sorted(items, key=_candidate_sort_key) for key, items in grouped.items()}


def _candidate_sort_key(row: Mapping[str, Any]) -> tuple[int, int]:
    return (seconds(_candidate_time(row)), int(num(row.get("id"))))


def _candidate_time(row: Mapping[str, Any]) -> str:
    return str(row.get("evaluation_time") or row.get("created_at") or row.get("updated_at") or "")


def _candidate_before_or_at(row: Mapping[str, Any], buy_time: object) -> bool:
    if not buy_time:
        return True
    return seconds(_candidate_time(row)) <= seconds(buy_time)


def _explicit_link_candidates(row: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    order_ids = {str(row.get("buy_order_id") or "").strip(), str(row.get("sell_order_id") or "").strip()}
    order_ids.discard("")
    return [item for item in candidates if str(item.get("order_id") or "").strip() in order_ids]


def _is_submitted(row: Mapping[str, Any]) -> bool:
    decision = str(row.get("final_decision") or "").strip().upper()
    return str(row.get("order_submitted") or "").strip() in {"1", "True", "true"} or bool(row.get("order_id")) or decision in SUBMITTED_DECISIONS


def _is_blocked(row: Mapping[str, Any]) -> bool:
    reason = str(row.get("buy_block_reason") or "").strip().upper()
    decision = str(row.get("final_decision") or "").strip().upper()
    if reason and reason != "BUY_ALLOWED":
        return True
    return decision not in ALLOWED_DECISIONS and any(token in decision for token in BLOCKED_TOKENS)


def _source_entry_match(row: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    entry = str(row.get("buy_entry_reason") or row.get("entry_reason") or "").strip().lower()
    if not entry:
        return []
    return [item for item in candidates if str(item.get("source") or "").strip().lower() == entry]


def _exclusion_reason(confidence: str, new_reason: str) -> str:
    if confidence == "MEDIUM":
        return "medium_confidence_excluded_from_strategy_signal"
    if confidence == "LOW":
        return "low_confidence_excluded_from_strategy_signal"
    return new_reason or "not_high_confidence"


def _join(rows: Sequence[Mapping[str, Any]], key: str) -> str:
    return ";".join(str(row.get(key) or "") for row in rows)


def _sample(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row_no": row.get("row_no"),
        "trade_date": row.get("trade_date"),
        "symbol": row.get("symbol"),
        "buy_time": row.get("buy_time"),
        "sell_time": row.get("sell_time"),
        "active_candidate_candidate_id": row.get("active_candidate_candidate_id"),
        "diagnostic_detail": row.get("diagnostic_detail"),
    }
