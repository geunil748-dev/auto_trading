from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

try:
    from tools.strategy_review_fill_matching import match_exit_reasons
    from tools.strategy_review_fill_normalization_core import normalize_fill_groups
    from tools.strategy_review_fill_normalization_utils import (
        AMBIGUOUS_EXCLUDED,
        DELTA_ROWS_SUMMED,
        EXACT_DUPLICATE_COLLAPSED,
        LEGACY_CUMULATIVE_LATEST,
        NO_ORDER_NO_FALLBACK,
        SINGLE_ROW,
        is_best_effort_normalized_row,
        is_trusted_normalized_row,
        mode_text,
        normalize_side,
        normalized_side_sql,
        score_bucket,
        text_value,
    )
    from tools.strategy_review_fill_pnl import (
        aggregate_candidate_pnl,
        aggregate_fill_pnl,
        candidate_review_rows,
    )
    from tools.strategy_review_fill_reconciliation import audit_row, reconciliation_rows
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from strategy_review_fill_matching import match_exit_reasons  # type: ignore[no-redef]
    from strategy_review_fill_normalization_core import normalize_fill_groups  # type: ignore[no-redef]
    from strategy_review_fill_normalization_utils import (  # type: ignore[no-redef]
        AMBIGUOUS_EXCLUDED, DELTA_ROWS_SUMMED, EXACT_DUPLICATE_COLLAPSED,
        LEGACY_CUMULATIVE_LATEST, NO_ORDER_NO_FALLBACK, SINGLE_ROW,
        is_best_effort_normalized_row, is_trusted_normalized_row, mode_text,
        normalize_side, normalized_side_sql, score_bucket, text_value,
    )
    from strategy_review_fill_pnl import (  # type: ignore[no-redef]
        aggregate_candidate_pnl, aggregate_fill_pnl, candidate_review_rows,
    )
    from strategy_review_fill_reconciliation import (  # type: ignore[no-redef]
        audit_row, reconciliation_rows,
    )


@dataclass(frozen=True)
class NormalizedReviewResult:
    normalized_rows: list[dict[str, Any]]
    audit_rows: list[dict[str, Any]]
    pnl_by_day: list[dict[str, Any]]
    pnl_by_ticker: list[dict[str, Any]]
    pnl_by_exit_reason: list[dict[str, Any]]
    candidate_rows: list[dict[str, Any]]
    pnl_by_score_bucket: list[dict[str, Any]]
    pnl_by_source: list[dict[str, Any]]
    reconciliation_rows: list[dict[str, Any]]
    warning_codes: list[str]


def build_normalized_review(
    fill_rows: Sequence[Mapping[str, Any]],
    order_rows: Sequence[Mapping[str, Any]] = (),
    trade_rows: Sequence[Mapping[str, Any]] = (),
    daily_summary_rows: Sequence[Mapping[str, Any]] = (),
    trade_summary_rows: Sequence[Mapping[str, Any]] = (),
    candidate_rows: Sequence[Mapping[str, Any]] = (),
    candidate_mode_default: str | None = None,
) -> NormalizedReviewResult:
    """Build deterministic analysis sheets without mutating source rows."""
    fills = [deepcopy(dict(row)) for row in fill_rows]
    orders = [deepcopy(dict(row)) for row in order_rows]
    trades = [deepcopy(dict(row)) for row in trade_rows]
    daily_summaries = [deepcopy(dict(row)) for row in daily_summary_rows]
    trade_summaries = [deepcopy(dict(row)) for row in trade_summary_rows]
    candidates = [deepcopy(dict(row)) for row in candidate_rows]
    warnings: set[str] = set()
    normalized = match_exit_reasons(normalize_fill_groups(fills, orders, warnings), trades)
    matched_candidates = candidate_review_rows(
        normalized, candidates, candidate_mode_default=candidate_mode_default
    )
    return NormalizedReviewResult(
        normalized_rows=normalized,
        audit_rows=[audit_row(row) for row in normalized],
        pnl_by_day=aggregate_fill_pnl(normalized, ("trade_date", "mode")),
        pnl_by_ticker=aggregate_fill_pnl(normalized, ("ticker", "mode")),
        pnl_by_exit_reason=aggregate_fill_pnl(
            normalized, ("trade_date", "mode", "exit_reason")
        ),
        candidate_rows=matched_candidates,
        pnl_by_score_bucket=aggregate_candidate_pnl(
            matched_candidates, "score_bucket", lambda row: score_bucket(row.get("final_score"))
        ),
        pnl_by_source=aggregate_candidate_pnl(
            matched_candidates, "source", lambda row: text_value(row.get("source")) or "unknown"
        ),
        reconciliation_rows=reconciliation_rows(
            fills, normalized, daily_summaries, trade_summaries, warnings
        ),
        warning_codes=sorted(warnings),
    )


__all__ = [
    "AMBIGUOUS_EXCLUDED",
    "DELTA_ROWS_SUMMED",
    "EXACT_DUPLICATE_COLLAPSED",
    "LEGACY_CUMULATIVE_LATEST",
    "NO_ORDER_NO_FALLBACK",
    "NormalizedReviewResult",
    "SINGLE_ROW",
    "build_normalized_review",
    "is_best_effort_normalized_row",
    "is_trusted_normalized_row",
    "match_exit_reasons",
    "mode_text",
    "normalize_side",
    "normalized_side_sql",
]
