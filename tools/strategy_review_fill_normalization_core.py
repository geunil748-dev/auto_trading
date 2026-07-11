from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

try:
    from tools.strategy_review_fill_normalization_utils import (
        AMBIGUOUS_EXCLUDED,
        AMBIGUOUS_WARNING,
        DELTA_ROWS_SUMMED,
        EXACT_DUPLICATE_COLLAPSED,
        HANGUL_RE,
        LEGACY_CUMULATIVE_LATEST,
        NO_ORDER_NO_FALLBACK,
        SINGLE_ROW,
        canonical,
        decimal_value,
        financial_signature,
        fill_group_key,
        float_value,
        group_key_text,
        integer_value,
        latest_text,
        normalize_side,
        number_text,
        optional_bool,
        order_evidence_key,
        ordered_unique,
        prepare_fill,
        prepared_sort_key,
        text_value,
        ticker_text,
        weighted_value,
        date_text,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from strategy_review_fill_normalization_utils import (  # type: ignore[no-redef]
        AMBIGUOUS_EXCLUDED, AMBIGUOUS_WARNING, DELTA_ROWS_SUMMED,
        EXACT_DUPLICATE_COLLAPSED, HANGUL_RE, LEGACY_CUMULATIVE_LATEST,
        NO_ORDER_NO_FALLBACK, SINGLE_ROW, canonical, date_text, decimal_value,
        financial_signature, fill_group_key, float_value, group_key_text,
        integer_value, latest_text, normalize_side, number_text, optional_bool,
        order_evidence_key, ordered_unique, prepare_fill, prepared_sort_key,
        text_value, ticker_text, weighted_value,
    )


def normalize_fill_groups(
    fill_rows: Sequence[Mapping[str, Any]],
    order_rows: Sequence[Mapping[str, Any]],
    warnings: set[str],
) -> list[dict[str, Any]]:
    prepared = [prepare_fill(row) for row in fill_rows]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in prepared:
        groups[fill_group_key(row)].append(row)
    id_groups: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    for group_key, rows in groups.items():
        for row in rows:
            if row["source_id"]:
                id_groups[row["source_id"]].add(group_key)
    cross_group_ids = {source_id for source_id, keys in id_groups.items() if len(keys) > 1}
    if cross_group_ids:
        warnings.add("DUPLICATE_SOURCE_ID_LINEAGE")
    evidence = _order_quantity_evidence(order_rows)
    return [
        _normalize_group(
            key,
            sorted(groups[key], key=prepared_sort_key),
            evidence,
            cross_group_ids,
            warnings,
        )
        for key in sorted(groups, key=canonical)
    ]


def _normalize_group(
    group_key: tuple[Any, ...],
    rows: list[dict[str, Any]],
    order_evidence: dict[tuple[Any, ...], set[int]],
    cross_group_ids: set[str],
    warnings: set[str],
) -> dict[str, Any]:
    latest = rows[-1]
    source_ids = ordered_unique(row["source_id"] for row in rows if row["source_id"])
    missing_lineage = len(source_ids) != len(rows)
    lineage_conflict = any(source_id in cross_group_ids for source_id in source_ids)
    if missing_lineage:
        warnings.add("SOURCE_ID_LINEAGE_MISSING")
    signature_rows = {financial_signature(row): row for row in rows}
    unique_rows = sorted(signature_rows.values(), key=prepared_sort_key)
    quantities = [row["quantity"] for row in unique_rows]
    invalid_quantity = any(quantity is None or quantity <= 0 for quantity in quantities)
    if invalid_quantity:
        warnings.add("NON_POSITIVE_NORMALIZED_QUANTITY")
    side = latest["side"]
    if side == "UNKNOWN":
        warnings.add("UNKNOWN_SIDE")
        if any(HANGUL_RE.search(row["raw_side"]) for row in rows):
            warnings.add("UNKNOWN_KOREAN_SIDE")
    evidence_values = (
        sorted(order_evidence.get(order_evidence_key(latest), set())) if latest["order_no"] else []
    )
    evidence = evidence_values[0] if len(evidence_values) == 1 else None
    evidence_conflict = len(evidence_values) > 1
    if evidence_conflict:
        warnings.add("ORDER_QUANTITY_EVIDENCE_CONFLICT")

    method, confidence, reason, selected = AMBIGUOUS_EXCLUDED, "NONE", "", []
    if lineage_conflict:
        reason = "a source id belongs to more than one normalized order group"
    elif missing_lineage:
        reason = "one or more source rows have no original id lineage"
    elif side == "UNKNOWN":
        reason = "side is not one of BUY/B/매수 or SELL/S/매도"
    elif invalid_quantity:
        reason = "one or more source quantities are missing or non-positive"
    elif evidence_conflict:
        reason = "independent order snapshots disagree on filled quantity"
    elif not latest["order_no"]:
        if len(unique_rows) == 1:
            method, confidence, selected = NO_ORDER_NO_FALLBACK, "LOW", unique_rows
            reason = "order number is absent; exact fallback identity is best-effort only"
        else:
            reason = "fallback identity rows disagree on financial payload"
    elif len(unique_rows) == 1:
        method = EXACT_DUPLICATE_COLLAPSED if len(rows) > 1 else SINGLE_ROW
        confidence, selected = "HIGH", unique_rows
        reason = (
            "all source rows have the same financial execution payload"
            if method == EXACT_DUPLICATE_COLLAPSED
            else "one source row has a broker order number"
        )
    else:
        q_sum = sum(int(quantity) for quantity in quantities if quantity is not None)
        latest_q = int(quantities[-1])
        increasing = all(left < right for left, right in zip(quantities, quantities[1:]))
        decreasing = all(left > right for left, right in zip(quantities, quantities[1:]))
        if evidence is not None and evidence == q_sum and evidence != latest_q:
            method, confidence, selected = DELTA_ROWS_SUMMED, "HIGH", unique_rows
            reason = "independent filled quantity equals the sum of nonduplicate delta rows"
        elif evidence is not None and increasing and evidence == latest_q and evidence != q_sum:
            method, confidence, selected = LEGACY_CUMULATIVE_LATEST, "HIGH", [unique_rows[-1]]
            reason = "independent filled quantity equals the latest increasing cumulative snapshot"
        elif evidence is None and decreasing:
            method, confidence, selected = DELTA_ROWS_SUMMED, "MEDIUM", unique_rows
            reason = "quantity decreases, which is incompatible with a cumulative snapshot sequence"
        elif evidence is None and increasing:
            reason = "increasing rows can be either legacy cumulative snapshots or current delta fills"
        elif evidence is not None:
            reason = "independent filled quantity matches neither a safe latest nor delta-sum interpretation"
        else:
            reason = "multiple distinct rows have no deterministic cumulative-versus-delta interpretation"
    if method == AMBIGUOUS_EXCLUDED:
        warnings.add(AMBIGUOUS_WARNING)
    if side == "SELL" and not latest["order_no"]:
        warnings.add("SELL_WITHOUT_ORDER_NO")

    quantity, price, amount, profit, rate = _selected_metrics(method, selected, side)
    missing_profit = side == "SELL" and method != AMBIGUOUS_EXCLUDED and profit is None
    if missing_profit:
        warnings.add("MISSING_SELL_PROFIT")
    excluded_trusted = method in {NO_ORDER_NO_FALLBACK, AMBIGUOUS_EXCLUDED} or missing_profit
    excluded_best = method == AMBIGUOUS_EXCLUDED or missing_profit
    raw_profit = sum((row["profit_usd"] or Decimal("0")) for row in rows)
    return {
        "normalization_group_key": group_key_text(group_key),
        "trade_date": latest["trade_date"], "is_mock": latest["is_mock"],
        "ticker": latest["ticker"], "ticker_name": latest_text(rows, "ticker_name"),
        "side": side, "normalized_side": side, "order_no": latest["order_no"],
        "fill_time": latest_text(selected or rows, "fill_time"), "quantity": quantity,
        "fill_price": price, "fill_amount": amount, "profit_usd": profit,
        "profit_rate": rate, "entry_reason": latest_text(rows, "entry_reason"),
        "entry_reason_detail": latest_text(rows, "entry_reason_detail"),
        "source_row_count": len(rows), "source_id_list": ",".join(source_ids),
        "source_id_count": len(source_ids),
        "quantity_list": ",".join(number_text(row["quantity"]) for row in rows),
        "fill_price_list": ",".join(number_text(row["fill_price"]) for row in rows),
        "fill_time_list": ",".join(row["fill_time"] for row in rows),
        "created_at_list": ",".join(row["created_at"] for row in rows),
        "raw_side_list": ",".join(row["raw_side"] for row in rows),
        "normalization_method": method, "normalization_confidence": confidence,
        "normalization_reason": reason, "exact_duplicate_count": len(rows) - len(unique_rows),
        "order_quantity_evidence_list": ",".join(str(value) for value in evidence_values),
        "expected_filled_quantity": evidence,
        "raw_quantity_sum": sum(row["quantity"] or 0 for row in rows),
        "normalized_quantity": quantity, "raw_profit_usd_sum": float_value(raw_profit),
        "normalized_profit_usd": profit,
        "trusted_profit_usd": None if excluded_trusted else profit,
        "best_effort_profit_usd": None if excluded_best else profit,
        "excluded_from_trusted_pnl": excluded_trusted,
        "excluded_from_best_effort_pnl": excluded_best,
    }


def _selected_metrics(
    method: str,
    rows: Sequence[Mapping[str, Any]],
    side: str,
) -> tuple[int | None, float | None, float | None, float | None, float | None]:
    if method == AMBIGUOUS_EXCLUDED or not rows:
        return None, None, None, None, None
    quantity = sum(int(row["quantity"]) for row in rows)
    amounts = [row["fill_amount"] for row in rows]
    amount = sum(amounts, Decimal("0")) if all(value is not None for value in amounts) else None
    profits = [row["profit_usd"] for row in rows]
    profit = sum(profits, Decimal("0")) if profits and all(value is not None for value in profits) else None
    return (
        quantity, float_value(weighted_value(rows, "fill_price")), float_value(amount),
        float_value(profit), float_value(weighted_value(rows, "profit_rate")),
    )


def _order_quantity_evidence(
    order_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[Any, ...], set[int]]:
    result: dict[tuple[Any, ...], set[int]] = defaultdict(set)
    for source in order_rows:
        row = dict(source)
        side = normalize_side(row.get("side") if "side" in row else row.get("order_type"))
        order_no = text_value(row.get("order_no") if "order_no" in row else row.get("orderNo"))
        if side == "UNKNOWN" or not order_no:
            continue
        filled = integer_value(row.get("filled_qty"))
        if filled is None:
            order_qty, remaining = integer_value(row.get("order_qty")), integer_value(row.get("remaining_qty"))
            if order_qty is not None and remaining is not None:
                filled = order_qty - remaining
        if filled is None:
            quantity = integer_value(row.get("quantity"))
            unfilled = integer_value(row.get("unfilled_quantity", row.get("unfilled")))
            if quantity is not None and unfilled is not None:
                filled = quantity - unfilled
        if filled is None or filled < 0:
            continue
        key = (
            date_text(row.get("trade_date", row.get("order_date"))),
            optional_bool(row.get("is_mock")) if "is_mock" in row else None,
            side, ticker_text(row.get("ticker", row.get("symbol"))), order_no,
        )
        result[key].add(filled)
    return result
