from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from trading_bot.performance_digest_scope import (
    collect_scope_stats,
    filter_rows_by_date,
)

EXPECTED_SHEETS = (
    "fill_history",
    "pnl_by_day",
    "pnl_by_exit_reason",
    "pnl_by_score_bucket",
    "pnl_by_source",
    "duplicate_suspects",
    "summary_reconciliation",
)


def collect_strategy_review_digest_stats(
    sheet_results: Sequence[object],
    failures: Sequence[tuple[str, str]] | None = None,
    *,
    report_date: date | str | None = None,
) -> dict[str, Any]:
    by_name = _sheet_results_by_name(sheet_results)
    missing = [name for name in EXPECTED_SHEETS if name not in by_name]
    errors = [
        f"{name}:{_sheet_error(result)}"
        for name, result in by_name.items()
        if _sheet_error(result)
    ]
    failure_notes = [f"{sheet}:{error}" for sheet, error in failures or ()]
    fill_sheet_available = "fill_history" in by_name and not _sheet_error(by_name["fill_history"])
    score_sheet_available = "pnl_by_score_bucket" in by_name and not _sheet_error(by_name["pnl_by_score_bucket"])
    source_sheet_available = "pnl_by_source" in by_name and not _sheet_error(by_name["pnl_by_source"])
    all_rows = {
        "pnl_by_day": _rows(by_name, "pnl_by_day"),
        "pnl_by_exit_reason": _rows(by_name, "pnl_by_exit_reason"),
        "pnl_by_score_bucket": _rows(by_name, "pnl_by_score_bucket"),
        "pnl_by_source": _rows(by_name, "pnl_by_source"),
        "fill_history": _rows(by_name, "fill_history"),
        "summary_reconciliation": _rows(by_name, "summary_reconciliation"),
        "duplicate_suspects": _rows(by_name, "duplicate_suspects"),
    }
    daily_rows = {
        name: filter_rows_by_date(rows, report_date)
        for name, rows in all_rows.items()
    }
    cumulative = collect_scope_stats(
        all_rows,
        missing=missing,
        errors=errors,
        failure_notes=failure_notes,
        fill_sheet_available=fill_sheet_available,
        score_sheet_available=score_sheet_available,
        source_sheet_available=source_sheet_available,
    )
    daily = collect_scope_stats(
        daily_rows,
        missing=missing,
        errors=errors,
        failure_notes=failure_notes,
        fill_sheet_available=fill_sheet_available,
        score_sheet_available=score_sheet_available,
        source_sheet_available=source_sheet_available,
    )
    return {
        "daily": daily,
        "cumulative": cumulative,
        "daily_range_status": "report_date_only",
        "score_source_basis": "matched_candidate_rows_only",
        "exit_reason_basis": "all_realized_sell_exits",
        "missing_or_limited": sorted(
            set(daily["missing_or_limited"]) | set(cumulative["missing_or_limited"])
        ),
    }


def _sheet_results_by_name(results: Sequence[object]) -> dict[str, object]:
    by_name: dict[str, object] = {}
    for result in results:
        name = _sheet_name(result)
        if name:
            by_name[name] = result
    return by_name


def _sheet_name(result: object) -> str:
    if isinstance(result, Mapping):
        return str(result.get("name") or "")
    return str(getattr(result, "name", "") or "")


def _sheet_error(result: object) -> str:
    if isinstance(result, Mapping):
        return str(result.get("error") or "")
    return str(getattr(result, "error", "") or "")


def _rows(by_name: Mapping[str, object], name: str) -> list[dict[str, Any]]:
    result = by_name.get(name)
    if result is None:
        return []
    rows = result.get("rows", []) if isinstance(result, Mapping) else getattr(result, "rows", [])
    return [dict(row) for row in rows if isinstance(row, Mapping)]
