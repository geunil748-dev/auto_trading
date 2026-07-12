from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from trading_bot.performance_digest_aggregates import bucket_stats, overall_metrics
from trading_bot.performance_digest_buckets import (
    EXIT_REASON_BUCKETS, SCORE_BUCKETS, SOURCE_BUCKETS, exit_reason_bucket,
    is_buy, is_sell, num, score_bucket, source_bucket,
)
from trading_bot.performance_digest_intraday_observation import collect_intraday_observation
from trading_bot.performance_digest_loss_observation import (
    collect_loss_observation,
    raw_loss_rows,
)
from trading_bot.performance_digest_scope import filter_rows_by_date

TRUSTED_NORMALIZED = "TRUSTED_NORMALIZED"
RAW_FALLBACK = "RAW_FALLBACK"
FALLBACK_WARNING = "NORMALIZED_PNL_UNAVAILABLE_RAW_FALLBACK"
REQUIRED_NORMALIZED_SHEETS = (
    "fill_history_normalized", "pnl_by_day_normalized",
    "pnl_by_exit_reason_normalized", "pnl_by_score_bucket_normalized",
    "pnl_by_source_normalized", "summary_reconciliation_normalized",
    "fill_normalization_warnings",
)


def build_observation_stats(
    by_name: Mapping[str, object],
    raw_daily: dict[str, Any],
    raw_cumulative: dict[str, Any],
    *,
    report_date: date | str | None,
) -> dict[str, Any]:
    missing = [name for name in REQUIRED_NORMALIZED_SHEETS if name not in by_name]
    errors = [f"{name}:{_error(by_name[name])}" for name in REQUIRED_NORMALIZED_SHEETS if name in by_name and _error(by_name[name])]
    basis = TRUSTED_NORMALIZED if not missing and not errors else RAW_FALLBACK
    warnings = [FALLBACK_WARNING] if basis == RAW_FALLBACK else []
    normalization_warning_codes = sorted({
        str(row.get("warning_code") or row.get("code") or "").strip()
        for row in _rows(by_name, "fill_normalization_warnings")
        if str(row.get("warning_code") or row.get("code") or "").strip()
    })
    warnings.extend(f"NORMALIZATION_WARNING:{code}" for code in normalization_warning_codes)
    normalized = _rows(by_name, "fill_history_normalized")
    non_mock_sells = [row for row in normalized if _side(row) == "SELL" and _mode(row) != "MOCK"]
    aggregate_contamination = sum(
        1 for name in REQUIRED_NORMALIZED_SHEETS[1:6]
        for row in _rows(by_name, name) if _mode(row) != "MOCK"
    )
    mock_rows = [row for row in normalized if _mode(row) == "MOCK"]
    trusted = [row for row in mock_rows if _trusted(row)]
    best_effort = [row for row in mock_rows if _best_effort(row)]
    trusted_sells = [row for row in trusted if _side(row) == "SELL"]
    lineage_errors = [
        str(row.get("normalization_group_key") or row.get("order_no") or "unknown")
        for row in trusted_sells
        if row.get("normalized_profit_usd") is None or not str(row.get("source_id_list") or "").strip()
    ]
    if non_mock_sells or aggregate_contamination:
        warnings.append("NORMALIZED_MODE_CONTAMINATION_EXCLUDED")
    if lineage_errors:
        warnings.append("TRUSTED_NORMALIZED_LINEAGE_OR_PROFIT_MISSING")
    candidate_rows = _rows(by_name, "candidate_evaluations")
    daily_candidates = filter_rows_by_date(candidate_rows, report_date)
    intraday_cumulative = collect_intraday_observation(candidate_rows)
    intraday_daily = collect_intraday_observation(daily_candidates)
    if intraday_cumulative["malformed_json_count"]:
        warnings.append("MALFORMED_CONDITION_RESULT_JSON")
    if intraday_cumulative["false_failure_count"]:
        warnings.append("NO_DATA_FALSE_FAILURE_DETECTED")
    cumulative = _scope(
        by_name, raw_cumulative, basis=basis, normalized_rows=mock_rows,
        trusted_rows=trusted, best_effort_rows=best_effort, report_date=None,
    )
    daily = _scope(
        by_name, raw_daily, basis=basis,
        normalized_rows=filter_rows_by_date(mock_rows, report_date),
        trusted_rows=filter_rows_by_date(trusted, report_date),
        best_effort_rows=filter_rows_by_date(best_effort, report_date),
        report_date=report_date,
    )
    raw_sell_count = int(num(raw_cumulative["overall"].get("sell_count")))
    if basis == TRUSTED_NORMALIZED and raw_sell_count > 0 and not trusted_sells:
        warnings.append("NORMALIZED_ZERO_WITH_RAW_SELL_ROWS")
    ambiguous_count = cumulative["audit"]["ambiguous_sell_order_count"]
    malformed_count = intraday_cumulative["malformed_json_count"]
    high_incomplete = intraday_cumulative["required_data_incomplete_rate"] > 0.5
    raw_available = any(
        name in by_name and not _error(by_name[name])
        for name in ("fill_history", "pnl_by_day")
    )
    if ambiguous_count:
        warnings.append("AMBIGUOUS_SELL_EXCLUDED")
    if high_incomplete:
        warnings.append("HIGH_REQUIRED_DATA_INCOMPLETE_RATE")
    if basis == RAW_FALLBACK and not raw_available:
        warnings.append("RAW_PNL_UNAVAILABLE")
    critical = bool(
        errors or lineage_errors or non_mock_sells or aggregate_contamination
        or intraday_cumulative["false_failure_count"]
        or (basis == RAW_FALLBACK and not raw_available)
    )
    if critical:
        status = "BLOCKED"
    elif basis == RAW_FALLBACK or normalization_warning_codes or ambiguous_count or malformed_count or high_incomplete or len(trusted_sells) < 30:
        status = "WARN"
    else:
        status = "READY_FOR_MOCK_OBSERVATION"
    trusted_count = cumulative["performance"]["overall"]["sell_count"]
    quality_issue = (
        status == "BLOCKED" or basis == RAW_FALLBACK or ambiguous_count > 0
        or malformed_count > 0 or high_incomplete or bool(normalization_warning_codes)
    )
    if quality_issue:
        eligibility = "HOLD_DATA_QUALITY"
    elif trusted_count < 15:
        eligibility = "HOLD_INSUFFICIENT_SAMPLE"
    elif trusted_count < 30:
        eligibility = "SHADOW_ANALYSIS_ONLY"
    else:
        eligibility = "REVIEW_ELIGIBLE"
    return {
        "performance_basis": basis,
        "observation_status": status,
        "strategy_change_eligibility": eligibility,
        "warnings": sorted(set(warnings)),
        "normalized_missing_sheets": missing,
        "normalized_errors": errors,
        "mode_contamination_count": len(non_mock_sells) + aggregate_contamination,
        "trusted_lineage_error_count": len(lineage_errors),
        "daily": {**daily, "intraday": intraday_daily},
        "cumulative": {**cumulative, "intraday": intraday_cumulative},
    }


def _scope(
    by_name: Mapping[str, object], raw: dict[str, Any], *, basis: str,
    normalized_rows: list[dict[str, Any]], trusted_rows: list[dict[str, Any]],
    best_effort_rows: list[dict[str, Any]], report_date: date | str | None,
) -> dict[str, Any]:
    if basis == RAW_FALLBACK:
        performance = {
            "overall": dict(raw["overall"]), "exit_stats": raw["exit_stats"],
            "score_stats": raw["score_stats"], "source_stats": raw["source_stats"],
            "reconciliation": dict(raw["reconciliation"]),
        }
    else:
        performance = _normalized_performance(by_name, trusted_rows, report_date)
    audit = _audit_metrics(by_name, raw, normalized_rows, trusted_rows, best_effort_rows, report_date)
    loss_rows = trusted_rows if basis == TRUSTED_NORMALIZED else raw_loss_rows(raw)
    loss_basis = "TRUSTED_NORMALIZED_MOCK" if basis == TRUSTED_NORMALIZED else RAW_FALLBACK
    loss = collect_loss_observation(loss_rows, basis=loss_basis)
    return {"performance": performance, "audit": audit, "loss": loss}


def _normalized_performance(by_name: Mapping[str, object], trusted_rows: list[dict[str, Any]], report_date: date | str | None) -> dict[str, Any]:
    def sheet(name: str) -> list[dict[str, Any]]:
        rows = [row for row in _rows(by_name, name) if _mode(row) == "MOCK"]
        return filter_rows_by_date(rows, report_date) if report_date is not None else rows
    ledger_sells = [_display_fill(row) for row in trusted_rows if _side(row) == "SELL"]
    ledger_buys = [_display_fill(row) for row in trusted_rows if _side(row) == "BUY"]
    daily_rows = sheet("pnl_by_day_normalized")
    overall = overall_metrics(daily_rows, ledger_sells, ledger_buys)
    count = int(overall["sell_count"])
    score_stats = bucket_stats(sheet("pnl_by_score_bucket_normalized"), key_name="score_bucket", buckets=SCORE_BUCKETS, normalizer=score_bucket)
    source_stats = bucket_stats(sheet("pnl_by_source_normalized"), key_name="source", buckets=SOURCE_BUCKETS, normalizer=source_bucket)
    matched = sum(item.sell_count for item in score_stats.values())
    overall.update({
        "realized_exit_count": count, "matched_trade_count": matched,
        "unmatched_trade_count": max(0, count - matched),
        "matched_ratio": matched / count if count else 0.0,
        "matched_ratio_status": "OK" if not count or matched / count >= 0.5 else "FAIL",
        "fill_history_buy_rows": len(ledger_buys), "fill_history_sell_rows": len(ledger_sells),
    })
    for field in (
        "realized_pnl_from_fill_history", "realized_pnl_from_daily_summary",
        "realized_pnl_from_raw_sell_fills", "realized_pnl_from_matched_trades_only",
        "realized_pnl_from_daily_ops_summary", "realized_pnl_from_strategy_review_sheet",
        "realized_pnl_from_exit_reason_sum",
    ):
        overall[field] = overall["realized_pnl"]
    recon_rows = sheet("summary_reconciliation_normalized")
    recon_profit = sum(num(row.get("normalized_profit_usd")) for row in recon_rows)
    gap = num(overall["realized_pnl"]) - recon_profit
    reconciliation = {
        "reconciliation_gap": gap, "reconciliation_gap_abs": abs(gap),
        "reconciliation_gap_pct": abs(gap) / abs(recon_profit) if recon_profit else 0.0,
        "reconciliation_gap_basis": "trusted_normalized_vs_normalized_reconciliation",
        "status": "OK" if abs(gap) <= 0.01 else "FAIL",
    }
    return {
        "overall": overall,
        "exit_stats": bucket_stats(sheet("pnl_by_exit_reason_normalized"), key_name="exit_reason", buckets=EXIT_REASON_BUCKETS, normalizer=exit_reason_bucket),
        "score_stats": score_stats, "source_stats": source_stats,
        "reconciliation": reconciliation,
    }


def _audit_metrics(by_name, raw, normalized_rows, trusted_rows, best_effort_rows, report_date):
    recon = [row for row in _rows(by_name, "summary_reconciliation_normalized") if _mode(row) == "MOCK"]
    if report_date is not None:
        recon = filter_rows_by_date(recon, report_date)
    raw_count = sum(int(num(row.get("raw_sell_row_count"))) for row in recon)
    raw_profit = sum(num(row.get("raw_profit_usd")) for row in recon)
    if not recon:
        raw_count = int(num(raw["overall"].get("sell_count")))
        raw_profit = num(raw["overall"].get("realized_pnl"))
    trusted_sells = [row for row in trusted_rows if _side(row) == "SELL"]
    best_sells = [row for row in best_effort_rows if _side(row) == "SELL"]
    trusted_profit = sum(num(row.get("normalized_profit_usd")) for row in trusted_sells)
    best_profit = sum(num(row.get("normalized_profit_usd")) for row in best_sells)
    ambiguous = [row for row in normalized_rows if str(row.get("normalization_method")) == "AMBIGUOUS_EXCLUDED" and _side(row) == "SELL"]
    ambiguous_profit = sum(num(row.get("raw_profit_usd_sum")) for row in ambiguous)
    return {
        "raw_sell_row_count": raw_count, "raw_profit_usd": raw_profit,
        "trusted_sell_order_count": len(trusted_sells), "trusted_profit_usd": trusted_profit,
        "best_effort_sell_order_count": len(best_sells), "best_effort_profit_usd": best_profit,
        "raw_vs_trusted_count_difference": raw_count - len(trusted_sells),
        "raw_vs_trusted_profit_difference": raw_profit - trusted_profit,
        "ambiguous_sell_order_count": len(ambiguous), "ambiguous_profit_usd": ambiguous_profit,
    }


def _rows(by_name: Mapping[str, object], name: str) -> list[dict[str, Any]]:
    result = by_name.get(name)
    rows = result.get("rows", []) if isinstance(result, Mapping) else getattr(result, "rows", []) if result else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _error(result: object) -> str:
    return str(result.get("error") or "") if isinstance(result, Mapping) else str(getattr(result, "error", "") or "")


def _mode(row: Mapping[str, Any]) -> str:
    value = str(row.get("mode") or "").strip().upper()
    if value:
        return value
    if "is_mock" in row:
        return "MOCK" if str(row.get("is_mock")).lower() in {"true", "1"} else "REAL"
    return "UNKNOWN"


def _side(row: Mapping[str, Any]) -> str:
    value = row.get("normalized_side") or row.get("side")
    return "SELL" if is_sell(value) else "BUY" if is_buy(value) else "UNKNOWN"


def _trusted(row: Mapping[str, Any]) -> bool:
    return str(row.get("normalization_confidence") or "").upper() == "HIGH" and not _truthy(row.get("excluded_from_trusted_pnl")) and (_side(row) != "SELL" or row.get("normalized_profit_usd") is not None)


def _best_effort(row: Mapping[str, Any]) -> bool:
    return not _truthy(row.get("excluded_from_best_effort_pnl")) and str(row.get("normalization_method") or "") != "AMBIGUOUS_EXCLUDED" and (_side(row) != "SELL" or row.get("normalized_profit_usd") is not None)


def _truthy(value: object) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _display_fill(row: Mapping[str, Any]) -> dict[str, Any]:
    quantity = num(row.get("normalized_quantity"))
    price = num(row.get("normalized_fill_price") or row.get("fill_price"))
    return {**row, "side": _side(row), "profit_usd": row.get("normalized_profit_usd"), "fill_amount": quantity * price}
