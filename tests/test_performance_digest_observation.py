from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from trading_bot.performance_digest import build_strategy_review_digest
from trading_bot.performance_digest_intraday_observation import collect_intraday_observation
from trading_bot.performance_digest_stats import collect_strategy_review_digest_stats


@dataclass
class Result:
    name: str
    rows: list[dict[str, object]]
    error: str = ""


def test_trusted_normalized_is_headline_and_raw_is_audit_only(tmp_path) -> None:
    stats = collect_strategy_review_digest_stats(_results(), report_date="2026-07-11")
    digest = build_strategy_review_digest(
        _results(), report_date="2026-07-11", date_from="2026-07-11",
        date_to="2026-07-11", source_xlsx=tmp_path / "strategy_review.xlsx",
    )

    assert stats["performance_basis"] == "TRUSTED_NORMALIZED"
    assert stats["observation_status"] == "WARN"
    assert stats["cumulative"]["performance"]["overall"]["realized_pnl"] == 5
    assert "performance_basis: TRUSTED_NORMALIZED" in digest
    assert "trusted_profit_usd: 5.00" in digest
    assert "best_effort_profit_usd: 8.00" in digest
    assert "raw_profit_usd: 17.00" in digest
    assert "cumulative_overall:\n- buy_count: 0\n- sell_count: 2" in digest
    assert "- realized_pnl: 5.00" in digest


def test_missing_one_normalized_sheet_falls_back_as_one_raw_scope() -> None:
    results = [row for row in _results() if row.name != "pnl_by_source_normalized"]
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["performance_basis"] == "RAW_FALLBACK"
    assert stats["observation_status"] == "WARN"
    assert stats["cumulative"]["performance"]["overall"]["realized_pnl"] == 17
    assert stats["cumulative"]["performance"]["source_stats"]["auto"].total_profit_usd == 17
    assert stats["cumulative"]["loss_observation"]["basis"] == "RAW_FALLBACK"
    assert stats["cumulative"]["loss_observation"]["total_profit_usd"] == 17
    assert "NORMALIZED_PNL_UNAVAILABLE_RAW_FALLBACK" in stats["observation_warnings"]


def test_normalized_sheet_error_is_not_treated_as_zero() -> None:
    results = _results()
    target = next(row for row in results if row.name == "pnl_by_day_normalized")
    target.error = "query failed"
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["performance_basis"] == "RAW_FALLBACK"
    assert stats["observation_status"] == "BLOCKED"
    assert stats["normalized_errors"] == ["pnl_by_day_normalized:query failed"]


def test_medium_and_ambiguous_rows_never_enter_trusted_headline() -> None:
    stats = collect_strategy_review_digest_stats(_results(), report_date="2026-07-11")
    audit = stats["cumulative"]["performance_audit"]

    assert audit["trusted_sell_order_count"] == 2
    assert audit["trusted_profit_usd"] == 5
    assert audit["best_effort_sell_order_count"] == 3
    assert audit["best_effort_profit_usd"] == 8
    assert audit["ambiguous_sell_order_count"] == 1
    assert audit["ambiguous_profit_usd"] == 9


def test_real_mode_is_excluded_and_blocks_observation() -> None:
    results = _results()
    ledger = next(row for row in results if row.name == "fill_history_normalized")
    ledger.rows.append(_normalized_sell("REAL", "R1", 99, "HIGH"))
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["mode_contamination_count"] == 1
    assert stats["observation_status"] == "BLOCKED"
    assert stats["cumulative"]["performance_audit"]["trusted_profit_usd"] == 5


def test_aggregate_real_mode_contamination_is_not_summed() -> None:
    results = _results(sell_count=30)
    day = next(row for row in results if row.name == "pnl_by_day_normalized")
    day.rows.append({"trade_date": "2026-07-11", "mode": "REAL", "sell_count": 1, "total_profit_usd": 999})
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["mode_contamination_count"] >= 1
    assert stats["observation_status"] == "BLOCKED"
    assert stats["cumulative"]["performance"]["overall"]["realized_pnl"] != 999


def test_raw_sells_with_zero_normalized_sells_emit_warning() -> None:
    results = _results()
    next(row for row in results if row.name == "fill_history_normalized").rows = []
    for name in (
        "pnl_by_day_normalized", "pnl_by_exit_reason_normalized",
        "pnl_by_score_bucket_normalized", "pnl_by_source_normalized",
    ):
        next(row for row in results if row.name == name).rows = []
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["performance_basis"] == "TRUSTED_NORMALIZED"
    assert "NORMALIZED_ZERO_WITH_RAW_SELL_ROWS" in stats["observation_warnings"]
    assert stats["cumulative"]["performance"]["overall"]["sell_count"] == 0


def test_raw_fallback_without_raw_source_is_blocked() -> None:
    stats = collect_strategy_review_digest_stats([], report_date="2026-07-11")

    assert stats["performance_basis"] == "RAW_FALLBACK"
    assert stats["observation_status"] == "BLOCKED"
    assert "RAW_PNL_UNAVAILABLE" in stats["observation_warnings"]


def test_no_data_false_failure_checks_all_reason_fields() -> None:
    details = {
        "mock_trading": True,
        "required_data_quality_status": "INCOMPLETE",
        "data_quality_status": "INCOMPLETE",
        "intraday_missing_data_policy": "LOG_ONLY",
        "missing_data_reasons": ["VOLUME_INCREASE_DATA_MISSING"],
        "condition_states": {"VOLUME_INCREASE": "NO_DATA"},
        "failed_soft_reasons": ["VOLUME_INCREASE_FAILED"],
    }
    result = collect_intraday_observation([
        {"id": 1, "condition_result_json": json.dumps(details)},
        {"id": 2, "condition_result_json": "{broken"},
    ])

    assert result["candidate_evaluation_count"] == 1
    assert result["required_data_incomplete_count"] == 1
    assert result["policy_log_only_count"] == 1
    assert result["feature_missing_counts"]["VOLUME_INCREASE_DATA_MISSING"] == 1
    assert result["false_failure_count"] == 1
    assert result["malformed_json_count"] == 1


def test_intraday_counts_multiple_missing_disabled_state_and_block_policy() -> None:
    details = {
        "mock_trading": True, "required_data_quality_status": "INCOMPLETE",
        "data_quality_status": "INCOMPLETE", "intraday_missing_data_policy": "BLOCK",
        "missing_data_reasons": [
            "BREAKOUT_CLOSE_DATA_MISSING", "VWAP_MA20_DATA_MISSING",
            "REQUIRED_INTRADAY_DATA_MISSING",
        ],
        "condition_states": {
            "BREAKOUT_CLOSE": "NO_DATA", "BREAKOUT_HOLD": "DISABLED",
            "VWAP_MA20": "NO_DATA",
        },
        "failed_hard_reasons": [],
    }
    result = collect_intraday_observation([
        {"condition_result_json": json.dumps(details), "is_mock": True}
    ])

    assert result["policy_block_count"] == 1
    assert result["feature_missing_counts"]["BREAKOUT_CLOSE_DATA_MISSING"] == 1
    assert result["feature_missing_counts"]["VWAP_MA20_DATA_MISSING"] == 1
    assert result["feature_missing_counts"]["REQUIRED_INTRADAY_DATA_MISSING"] == 1
    assert result["condition_state_counts"]["BREAKOUT_HOLD"]["DISABLED"] == 1
    assert result["false_failure_count"] == 0


def test_intraday_daily_and_cumulative_counts_are_separate() -> None:
    results = _results(sell_count=30)
    candidates = next(row for row in results if row.name == "candidate_evaluations")
    older = dict(candidates.rows[0])
    older["trade_date"] = "2026-07-10"
    candidates.rows.append(older)
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["daily"]["intraday_observation"]["candidate_evaluation_count"] == 1
    assert stats["cumulative"]["intraday_observation"]["candidate_evaluation_count"] == 2


@pytest.mark.parametrize(
    ("sell_count", "eligibility"),
    [(14, "HOLD_INSUFFICIENT_SAMPLE"), (15, "SHADOW_ANALYSIS_ONLY"),
     (29, "SHADOW_ANALYSIS_ONLY"), (30, "REVIEW_ELIGIBLE")],
)
def test_strategy_change_gate_has_exact_trade_thresholds(sell_count: int, eligibility: str) -> None:
    results = _results(sell_count=sell_count)
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")

    assert stats["observation_status"] == (
        "READY_FOR_MOCK_OBSERVATION" if sell_count >= 30 else "WARN"
    )
    assert stats["strategy_change_eligibility"] == eligibility


def test_zero_loss_denominators_are_safe() -> None:
    results = _results(sell_count=1)
    ledger = next(row for row in results if row.name == "fill_history_normalized")
    ledger.rows = [_normalized_sell("MOCK", "WIN", 4, "HIGH")]
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")
    loss = stats["cumulative"]["loss_observation"]

    assert loss["gross_loss"] == 0
    assert loss["profit_factor"] == float("inf")
    assert loss["stop_loss_share_of_gross_loss"] == 0


def test_ambiguous_exit_is_not_assigned_to_stop_or_other_exit() -> None:
    results = _results(sell_count=1)
    ledger = next(row for row in results if row.name == "fill_history_normalized")
    ledger.rows[0]["match_ambiguous"] = True
    ledger.rows[0]["exit_reason"] = "STOP_LOSS"
    stats = collect_strategy_review_digest_stats(results, report_date="2026-07-11")
    loss = stats["cumulative"]["loss_observation"]

    assert loss["ambiguous_exit_count"] == 1
    assert loss["stop_loss_count"] == 0
    assert loss["other_exit_reasons"] == []


def _results(sell_count: int = 2) -> list[Result]:
    profits = [10 if index % 2 == 0 else -5 for index in range(sell_count)]
    trusted = [
        _normalized_sell("MOCK", f"T{index}", profit, "HIGH")
        for index, profit in enumerate(profits)
    ]
    if sell_count == 2:
        trusted.extend([
            _normalized_sell("MOCK", "MED", 3, "MEDIUM", trusted_excluded=True),
            _normalized_sell(
                "MOCK", "AMB", None, "NONE", trusted_excluded=True,
                best_excluded=True, method="AMBIGUOUS_EXCLUDED", raw_profit=9,
            ),
        ])
    total = sum(profits)
    wins = [value for value in profits if value > 0]
    losses = [value for value in profits if value < 0]
    daily = {
        "trade_date": "2026-07-11", "mode": "MOCK", "sell_count": sell_count,
        "total_profit_usd": total, "win_count": len(wins), "loss_count": len(losses),
        "avg_win": sum(wins) / len(wins) if wins else 0,
        "avg_loss": sum(losses) / len(losses) if losses else 0,
        "max_win": max(wins, default=0), "max_loss": min(losses, default=0),
    }
    candidate = {
        "trade_date": "2026-07-11", "is_mock": True, "buy_allowed": True,
        "order_submitted": False,
        "condition_result_json": json.dumps({
            "mock_trading": True, "required_data_quality_status": "COMPLETE",
            "data_quality_status": "COMPLETE", "intraday_missing_data_policy": "LOG_ONLY",
            "missing_data_reasons": [],
            "condition_states": {"VOLUME_INCREASE": "PASS"},
            "failed_hard_reasons": [], "failed_soft_reasons": [], "failed_log_reasons": [],
        }),
    }
    return [
        Result("fill_history", [
            {"trade_date": "2026-07-11", "side": "SELL", "profit_usd": value}
            for value in ([10, -5, 3, 9] if sell_count == 2 else profits)
        ]),
        Result("pnl_by_day", [{**daily, "sell_count": 4 if sell_count == 2 else sell_count, "total_profit_usd": 17 if sell_count == 2 else total}]),
        Result("pnl_by_exit_reason", [{"trade_date": "2026-07-11", "exit_reason": "STOP_LOSS", "sell_count": 4 if sell_count == 2 else sell_count, "total_profit_usd": 17 if sell_count == 2 else total}]),
        Result("pnl_by_score_bucket", [{"trade_date": "2026-07-11", "score_bucket": "50_60", "sell_count": 4 if sell_count == 2 else sell_count, "total_profit_usd": 17 if sell_count == 2 else total}]),
        Result("pnl_by_source", [{"trade_date": "2026-07-11", "source": "auto", "sell_count": 4 if sell_count == 2 else sell_count, "total_profit_usd": 17 if sell_count == 2 else total}]),
        Result("duplicate_suspects", []), Result("summary_reconciliation", []),
        Result("candidate_evaluations", [candidate]),
        Result("fill_history_normalized", trusted),
        Result("pnl_by_day_normalized", [daily]),
        Result("pnl_by_exit_reason_normalized", [{"trade_date": "2026-07-11", "mode": "MOCK", "exit_reason": "STOP_LOSS", "sell_count": sell_count, "total_profit_usd": total, "win_rate": len(wins) / sell_count if sell_count else 0}]),
        Result("pnl_by_score_bucket_normalized", [{"trade_date": "2026-07-11", "mode": "MOCK", "score_bucket": "50~60", "sell_count": sell_count, "total_profit_usd": total}]),
        Result("pnl_by_source_normalized", [{"trade_date": "2026-07-11", "mode": "MOCK", "source": "auto", "sell_count": sell_count, "total_profit_usd": total}]),
        Result("summary_reconciliation_normalized", [{
            "trade_date": "2026-07-11", "mode": "MOCK",
            "raw_sell_row_count": 4 if sell_count == 2 else sell_count,
            "raw_profit_usd": 17 if sell_count == 2 else total,
            "normalized_profit_usd": total,
        }]),
        Result("fill_normalization_warnings", []),
    ]


def _normalized_sell(
    mode: str, order_no: str, profit: int | None, confidence: str,
    *, trusted_excluded: bool = False, best_excluded: bool = False,
    method: str = "SINGLE_ROW", raw_profit: int | None = None,
) -> dict[str, object]:
    return {
        "trade_date": "2026-07-11", "mode": mode, "side": "SELL",
        "order_no": order_no, "source_id_list": order_no,
        "normalization_group_key": order_no, "normalization_method": method,
        "normalization_confidence": confidence,
        "excluded_from_trusted_pnl": trusted_excluded,
        "excluded_from_best_effort_pnl": best_excluded,
        "normalized_profit_usd": profit, "raw_profit_usd_sum": raw_profit,
        "normalized_quantity": 1, "fill_price": 10,
        "exit_reason": "STOP_LOSS" if profit is not None and profit < 0 else "TRAILING_STOP",
    }
