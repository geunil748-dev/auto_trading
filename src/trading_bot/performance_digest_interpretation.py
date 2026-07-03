from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from trading_bot.performance_digest_buckets import BucketStats
from trading_bot.performance_digest_diagnostics import count_or_none


def interpretation(
    exit_stats: Mapping[str, BucketStats],
    source_stats: Mapping[str, BucketStats],
    overall: Mapping[str, float | int],
    duplicate_count: int,
    data_status_value: str,
    data_status_reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    loss_bucket = largest_negative(exit_stats)
    loss_source = largest_negative(source_stats)
    profit_bucket = largest_positive(exit_stats)
    sell_count = count_or_none(overall.get("sell_count")) or 0
    realized_pnl = float(overall.get("realized_pnl", 0.0))
    matched_ratio_status = str(overall.get("matched_ratio_status") or "WARN")
    if data_status_value != "OK":
        signal = "HOLD_STRATEGY_CHANGE_UNTIL_DATA_QUALITY_FIXED"
    elif sell_count == 0:
        signal = "no_sell_data"
    elif sell_count < 30:
        signal = "sample_below_30"
    elif realized_pnl < 0:
        signal = "negative_expectancy_review_needed"
    else:
        signal = "monitor_without_rule_change"
    confidence = "LOW" if data_status_value != "OK" else "MEDIUM" if sell_count < 30 else "HIGH"
    score_source_confidence = "LOW" if matched_ratio_status == "FAIL" else confidence
    return {
        "main_loss_driver": loss_bucket,
        "main_profit_driver": profit_bucket,
        "strategy_change_signal": signal,
        "confidence": confidence,
        "score_source_confidence": score_source_confidence,
        "reason": list(data_status_reasons or []),
        "provisional_observation": [
            f"{loss_bucket} appears to be the largest loss bucket among currently parsed sell exits"
            if loss_bucket != "none"
            else "no loss bucket is available among currently parsed sell exits",
            f"{profit_bucket} appears to be the largest profit bucket among currently parsed sell exits"
            if profit_bucket != "none"
            else "no profit bucket is available among currently parsed sell exits",
        ],
        "recommended_review_focus": (
            "fix matching/reconciliation/count consistency before changing entry/exit rules"
            if data_status_value != "OK"
            else _review_focus(loss_bucket, loss_source, duplicate_count)
        ),
    }


def largest_negative(stats: Mapping[str, BucketStats]) -> str:
    negatives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd < 0]
    return min(negatives, key=lambda item: item[1])[0] if negatives else "none"


def largest_positive(stats: Mapping[str, BucketStats]) -> str:
    positives = [(name, item.total_profit_usd) for name, item in stats.items() if item.total_profit_usd > 0]
    return max(positives, key=lambda item: item[1])[0] if positives else "none"


def _review_focus(loss_bucket: str, loss_source: str, duplicate_count: int) -> str:
    focus = []
    if loss_bucket != "none":
        focus.append(f"exit_reason={loss_bucket}")
    if loss_source != "none":
        focus.append(f"source={loss_source}")
    if duplicate_count:
        focus.append("duplicate_suspects")
    return ", ".join(focus) if focus else "collect_more_data"
