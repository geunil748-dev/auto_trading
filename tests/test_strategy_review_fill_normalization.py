from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from tools.strategy_review_fill_normalization import (
    AMBIGUOUS_EXCLUDED,
    DELTA_ROWS_SUMMED,
    EXACT_DUPLICATE_COLLAPSED,
    LEGACY_CUMULATIVE_LATEST,
    NO_ORDER_NO_FALLBACK,
    SINGLE_ROW,
    build_normalized_review,
    normalize_side,
    normalized_side_sql,
)


def _fill(
    source_id: int | None,
    ticker: str,
    order_no: str,
    quantity: int,
    *,
    side: str = "SELL",
    fill_time: str = "10:00:00",
    fill_price: float = 10.0,
    profit_usd: float | None = -1.0,
    created_at: str | None = None,
    is_mock: bool | None = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": "2026-07-10",
        "fill_time": fill_time,
        "ticker": ticker,
        "ticker_name": f"{ticker} name",
        "side": side,
        "quantity": quantity,
        "fill_price": fill_price,
        "fill_amount": quantity * fill_price,
        "profit_usd": profit_usd,
        "profit_rate": None if profit_usd is None or quantity == 0 else profit_usd / (quantity * 100),
        "order_no": order_no,
        "is_mock": is_mock,
        "created_at": created_at or f"2026-07-10 10:00:{source_id or 0:02d}",
    }
    if source_id is not None:
        row["id"] = source_id
    return row


def _order(
    ticker: str,
    order_no: str,
    filled_qty: int,
    *,
    side: str = "SELL",
    is_mock: bool | None = True,
) -> dict[str, object]:
    return {
        "trade_date": "2026-07-10",
        "ticker": ticker,
        "side": side,
        "order_no": order_no,
        "filled_qty": filled_qty,
        "is_mock": is_mock,
    }


def test_side_aliases_and_sql_share_one_clean_vocabulary() -> None:
    for value in ("BUY", "buy", "B", "b", "매수", " 매수 "):
        assert normalize_side(value) == "BUY"
    for value in ("SELL", "sell", "S", "s", "매도", " 매도 "):
        assert normalize_side(value) == "SELL"
    assert normalize_side("구매") == "UNKNOWN"
    assert normalize_side("") == "UNKNOWN"

    sql = normalized_side_sql("fills.[side]")
    assert "fills.[side]" in sql
    assert "N'매수'" in sql
    assert "N'매도'" in sql
    assert "ELSE 'UNKNOWN'" in sql
    source = Path("tools/strategy_review_fill_normalization.py").read_text(encoding="utf-8")
    mojibake_buy = "".join(chr(codepoint) for codepoint in (0xF9CD, 0x317C, 0xB2D4))
    mojibake_sell = "".join(chr(codepoint) for codepoint in (0xF9CD, 0x317B, 0xB8C4))
    assert mojibake_buy not in source
    assert mojibake_sell not in source


def test_all_required_methods_use_independent_quantity_evidence_conservatively() -> None:
    single = _fill(1, "ONE", "O1", 10, profit_usd=2)
    duplicate_one = _fill(2, "DUP", "O2", 100, profit_usd=-5)
    duplicate_two = {**duplicate_one, "id": 3, "created_at": "2026-07-10 10:01:00"}
    cumulative_100 = _fill(4, "CUM", "O3", 100, profit_usd=-10, fill_price=10)
    cumulative_150 = _fill(
        5, "CUM", "O3", 150, profit_usd=-75, fill_price=9.5, fill_time="10:02:00"
    )
    delta_100 = _fill(6, "DEL", "O4", 100, profit_usd=-10, fill_price=10)
    delta_50 = _fill(
        7, "DEL", "O4", 50, profit_usd=-8, fill_price=9, fill_time="10:03:00"
    )
    fallback = _fill(8, "LOW", "", 5, profit_usd=3)
    ambiguous_100 = _fill(9, "AMB", "O5", 100, profit_usd=-2)
    ambiguous_150 = _fill(
        10, "AMB", "O5", 150, profit_usd=-7, fill_time="10:04:00"
    )
    result = build_normalized_review(
        [
            single, duplicate_one, duplicate_two, cumulative_100, cumulative_150,
            delta_100, delta_50, fallback, ambiguous_100, ambiguous_150,
        ],
        order_rows=[_order("CUM", "O3", 150), _order("DEL", "O4", 150)],
    )
    rows = {row["ticker"]: row for row in result.normalized_rows}

    assert rows["ONE"]["normalization_method"] == SINGLE_ROW
    assert rows["DUP"]["normalization_method"] == EXACT_DUPLICATE_COLLAPSED
    assert rows["DUP"]["source_id_list"] == "2,3"
    assert rows["DUP"]["raw_quantity_sum"] == 200
    assert rows["DUP"]["normalized_quantity"] == 100
    assert rows["CUM"]["normalization_method"] == LEGACY_CUMULATIVE_LATEST
    assert rows["CUM"]["normalized_quantity"] == 150
    assert rows["CUM"]["normalized_profit_usd"] == -75
    assert rows["DEL"]["normalization_method"] == DELTA_ROWS_SUMMED
    assert rows["DEL"]["normalized_quantity"] == 150
    assert rows["DEL"]["normalized_profit_usd"] == -18
    assert rows["LOW"]["normalization_method"] == NO_ORDER_NO_FALLBACK
    assert rows["LOW"]["excluded_from_trusted_pnl"] is True
    assert rows["LOW"]["excluded_from_best_effort_pnl"] is False
    assert rows["AMB"]["normalization_method"] == AMBIGUOUS_EXCLUDED
    assert rows["AMB"]["normalized_quantity"] is None
    assert rows["AMB"]["normalized_profit_usd"] is None
    assert rows["AMB"]["excluded_from_best_effort_pnl"] is True
    assert "AMBIGUOUS_FILLS_EXCLUDED" in result.warning_codes
    assert "SELL_WITHOUT_ORDER_NO" in result.warning_codes


def test_current_delta_and_real_partial_fills_are_not_lost() -> None:
    current_delta = [
        _fill(1, "CUR", "C1", 100, profit_usd=10),
        _fill(2, "CUR", "C1", 50, profit_usd=4, fill_time="10:01:00"),
    ]
    real_partial = [
        _fill(3, "PAR", "P1", 40, profit_usd=2),
        _fill(4, "PAR", "P1", 60, profit_usd=5, fill_price=11, fill_time="10:02:00"),
    ]
    result = build_normalized_review(
        current_delta + real_partial,
        order_rows=[_order("PAR", "P1", 100)],
    )
    rows = {row["ticker"]: row for row in result.normalized_rows}

    assert rows["CUR"]["normalization_method"] == DELTA_ROWS_SUMMED
    assert rows["CUR"]["normalization_confidence"] == "MEDIUM"
    assert rows["CUR"]["normalized_quantity"] == 150
    assert rows["CUR"]["normalized_profit_usd"] == 14
    assert rows["CUR"]["excluded_from_trusted_pnl"] is True
    assert rows["CUR"]["excluded_from_best_effort_pnl"] is False
    assert rows["CUR"]["trusted_exclusion_reason"] == "MEDIUM_CONFIDENCE_NOT_TRUSTED"
    assert rows["PAR"]["normalization_method"] == DELTA_ROWS_SUMMED
    assert rows["PAR"]["normalization_confidence"] == "HIGH"
    assert rows["PAR"]["normalized_quantity"] == 100
    assert rows["PAR"]["normalized_profit_usd"] == 7
    assert rows["PAR"]["excluded_from_trusted_pnl"] is False
    assert rows["PAR"]["trusted_exclusion_reason"] == ""
    day = result.pnl_by_day[0]
    assert (day["sell_count"], day["total_profit_usd"]) == (1, 7)
    assert (day["best_effort_sell_count"], day["best_effort_total_profit_usd"]) == (2, 21)
    audits = {row["ticker"]: row for row in result.audit_rows}
    assert audits["CUR"]["trusted_exclusion_reason"] == "MEDIUM_CONFIDENCE_NOT_TRUSTED"


def test_same_order_number_stays_separate_between_mock_and_real() -> None:
    fills = [
        _fill(1, "AAA", "O1", 10, profit_usd=5, is_mock=True),
        _fill(2, "AAA", "O1", 20, profit_usd=-7, is_mock=False),
    ]

    rows = build_normalized_review(fills).normalized_rows

    assert len(rows) == 2
    assert {(row["mode"], row["source_id_list"]) for row in rows} == {
        ("MOCK", "1"),
        ("REAL", "2"),
    }


def test_increasing_rows_without_independent_evidence_remain_ambiguous() -> None:
    result = build_normalized_review(
        [
            _fill(1, "AAA", "O1", 100, profit_usd=-10),
            _fill(2, "AAA", "O1", 150, profit_usd=-20, fill_time="10:01:00"),
        ]
    )
    row = result.normalized_rows[0]
    assert row["normalization_method"] == AMBIGUOUS_EXCLUDED
    assert "legacy cumulative snapshots or current delta fills" in row["normalization_reason"]


def test_normalization_is_deterministic_and_does_not_mutate_raw_rows() -> None:
    rows = [
        _fill(2, "AAA", "O1", 50, profit_usd=3, fill_time="10:01:00"),
        _fill(1, "AAA", "O1", 100, profit_usd=5, fill_time="10:00:00"),
    ]
    original = deepcopy(rows)
    first = build_normalized_review(rows)
    second = build_normalized_review(list(reversed(rows)))
    assert rows == original
    assert first == second
    assert first.normalized_rows[0]["source_id_list"] == "1,2"
