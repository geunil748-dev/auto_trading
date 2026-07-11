from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

try:
    from tools.strategy_review_fill_normalization_utils import (
        date_text,
        normalize_side,
        prepare_trade,
        prepared_sort_key,
        text_value,
        ticker_text,
        time_distance,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from strategy_review_fill_normalization_utils import (  # type: ignore[no-redef]
        date_text, normalize_side, prepare_trade, prepared_sort_key, text_value,
        ticker_text, time_distance,
    )


def match_exit_reasons(
    normalized_rows: Sequence[Mapping[str, Any]],
    trade_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    prepared_trades = sorted((prepare_trade(row) for row in trade_rows), key=prepared_sort_key)
    matched_rows: list[dict[str, Any]] = []
    for source in normalized_rows:
        row = deepcopy(dict(source))
        if normalize_side(row.get("side")) != "SELL":
            row.update(
                exit_reason="",
                match_method="NOT_APPLICABLE",
                match_distance_seconds=None,
                match_ambiguous=False,
            )
            matched_rows.append(row)
            continue
        is_mock = row.get("is_mock")
        base = [
            candidate
            for candidate in prepared_trades
            if candidate["trade_date"] == date_text(row.get("trade_date"))
            and candidate["ticker"] == ticker_text(row.get("ticker"))
            and candidate["side"] == "SELL"
            and candidate["is_mock"] == is_mock
        ]
        order_no = text_value(row.get("order_no"))
        order_matches = [candidate for candidate in base if order_no and candidate["order_no"] == order_no]
        chosen, method, distance, ambiguous = _choose_trade_match(
            order_matches, row.get("fill_time"), "ORDER_NO"
        )
        if chosen is None and not ambiguous:
            timed = [candidate for candidate in base if candidate["time_seconds"] is not None]
            chosen, method, distance, ambiguous = _choose_trade_match(
                timed, row.get("fill_time"), "TIME_NEAREST"
            )
        if chosen is None and not ambiguous:
            if len(base) == 1:
                chosen, method = base[0], "FALLBACK_SINGLE"
                distance = time_distance(row.get("fill_time"), chosen.get("last_fill_time"))
            elif len(base) > 1:
                ambiguous, method = True, "FALLBACK_AMBIGUOUS"
        if ambiguous:
            row.update(
                exit_reason="AMBIGUOUS",
                match_method=method or "AMBIGUOUS",
                match_distance_seconds=distance,
                match_ambiguous=True,
            )
        elif chosen is None:
            row.update(
                exit_reason="UNKNOWN",
                match_method="NO_MATCH",
                match_distance_seconds=None,
                match_ambiguous=False,
            )
        else:
            row.update(
                exit_reason=chosen["exit_reason"] or "UNKNOWN",
                match_method=method,
                match_distance_seconds=distance,
                match_ambiguous=False,
            )
        matched_rows.append(row)
    return matched_rows


def _choose_trade_match(
    candidates: Sequence[Mapping[str, Any]],
    fill_time: Any,
    method: str,
) -> tuple[Mapping[str, Any] | None, str, int | None, bool]:
    if not candidates:
        return None, "", None, False
    if len(candidates) == 1:
        candidate = candidates[0]
        return candidate, method, time_distance(fill_time, candidate.get("last_fill_time")), False
    valid = [
        (distance, candidate)
        for candidate in candidates
        if (distance := time_distance(fill_time, candidate.get("last_fill_time"))) is not None
    ]
    if valid:
        minimum = min(distance for distance, _ in valid)
        closest = [candidate for distance, candidate in valid if distance == minimum]
        if len(closest) == 1:
            nearest_method = method if method == "TIME_NEAREST" else f"{method}_TIME_NEAREST"
            return closest[0], nearest_method, minimum, False
        return None, f"{method}_TIME_AMBIGUOUS", minimum, True
    return None, f"{method}_AMBIGUOUS", None, True
