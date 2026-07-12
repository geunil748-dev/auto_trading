from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from trading_bot.performance_digest_scope import (
    collect_scope_stats,
    filter_rows_by_date,
)
from trading_bot.performance_digest_observation import build_observation_stats

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
        "trade_history": _rows(by_name, "trade_history"),
        "candidate_orders_matched": _rows(by_name, "candidate_orders_matched"),
        "candidate_evaluations": _rows(by_name, "candidate_evaluations"),
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
    observation = build_observation_stats(
        by_name,
        daily,
        cumulative,
        report_date=report_date,
    )
    daily["performance"] = observation["daily"]["performance"]
    daily["performance_audit"] = observation["daily"]["audit"]
    daily["loss_observation"] = observation["daily"]["loss"]
    daily["intraday_observation"] = observation["daily"]["intraday"]
    cumulative["performance"] = observation["cumulative"]["performance"]
    cumulative["performance_audit"] = observation["cumulative"]["audit"]
    cumulative["loss_observation"] = observation["cumulative"]["loss"]
    cumulative["intraday_observation"] = observation["cumulative"]["intraday"]
    for scope in (daily, cumulative):
        scope["performance_basis"] = observation["performance_basis"]
        scope["observation_status"] = observation["observation_status"]
        scope["strategy_change_eligibility"] = observation["strategy_change_eligibility"]
        scope["observation_warnings"] = observation["warnings"]
        scope["real_mode_row_count"] = observation["real_mode_row_count"]
        scope["unknown_mode_row_count"] = observation["unknown_mode_row_count"]
    return {
        "daily": daily,
        "cumulative": cumulative,
        "performance_basis": observation["performance_basis"],
        "observation_status": observation["observation_status"],
        "strategy_change_eligibility": observation["strategy_change_eligibility"],
        "observation_warnings": observation["warnings"],
        "normalized_missing_sheets": observation["normalized_missing_sheets"],
        "normalized_errors": observation["normalized_errors"],
        "mode_contamination_count": observation["mode_contamination_count"],
        "real_mode_row_count": observation["real_mode_row_count"],
        "unknown_mode_row_count": observation["unknown_mode_row_count"],
        "trusted_exclusion_reason_counts": observation["trusted_exclusion_reason_counts"],
        "trusted_lineage_error_count": observation["trusted_lineage_error_count"],
        "daily_range_status": "report_date_only",
        "score_source_basis": (
            "trusted_normalized_mock_matched_candidates"
            if observation["performance_basis"] == "TRUSTED_NORMALIZED"
            else "matched_candidate_rows_only"
        ),
        "exit_reason_basis": (
            "trusted_normalized_mock_sell_orders"
            if observation["performance_basis"] == "TRUSTED_NORMALIZED"
            else "all_realized_sell_exits"
        ),
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
