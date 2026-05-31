from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from trading_bot.config import (
    CANDIDATE_MODE_FIXED,
    STRATEGY_PRESET_CURRENT,
    TradingSettings,
)


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_version: str
    settings_snapshot_hash: str
    settings_snapshot_json: str


def settings_snapshot(settings: TradingSettings) -> dict[str, object]:
    return {
        "strategyVersion": strategy_version_from_settings(settings),
        "candidateSelectionMode": settings.candidate_selection_mode,
        "strategyPreset": settings.strategy_preset,
        "allowRelaxedCandidateFilter": bool(settings.allow_relaxed_candidate_filter),
        "enablePyramiding": bool(settings.enable_pyramiding),
        "stopLossPercent": abs(settings.max_position_loss * 100),
        "takeProfitPercent": settings.take_profit_rate * 100,
        "trailingStopActivationPercent": settings.trailing_stop_activation_rate * 100,
        "trailingStopDropPercent": settings.trailing_stop_drop * 100,
        "partialTakeProfitEnabled": settings.partial_take_profit_enabled,
        "minTotalScore": settings.min_total_score,
        "minPriceUsd": settings.min_price_usd,
        "maxPriceUsd": settings.max_price_usd,
        "minOpeningPriceChangePercent": settings.min_opening_price_change * 100,
        "minVolumeRatio": settings.min_volume_ratio,
        "maxOpeningGapPercent": settings.max_opening_gap * 100,
        "openingFixedCandidateLimit": settings.opening_fixed_candidate_limit,
        "intradayRefreshCandidateLimit": settings.intraday_refresh_candidate_limit,
        "hybridCandidateLimit": settings.hybrid_candidate_limit,
        "stopLossCooldownMinutes": settings.stop_loss_cooldown_minutes,
        "maxConsecutiveStopLossCount": settings.max_consecutive_stop_loss_count,
        "maxBidAskSpreadRate": settings.max_bid_ask_spread_rate,
        "maxExpectedFillPriceGapRate": settings.max_expected_fill_price_gap_rate,
        "maxOrderRetryCount": settings.max_order_retry_count,
        "orderRetryDelaySeconds": settings.order_retry_delay_seconds,
        "partialFillPolicy": settings.partial_fill_policy,
        "unfilledCancelAfterSeconds": settings.unfilled_cancel_after_seconds,
    }


def strategy_metadata_from_settings(settings: TradingSettings) -> StrategyMetadata:
    snapshot = settings_snapshot(settings)
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return StrategyMetadata(
        strategy_version=str(snapshot["strategyVersion"]),
        settings_snapshot_hash=hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
        settings_snapshot_json=snapshot_json,
    )


def strategy_version_from_settings(settings: TradingSettings) -> str:
    if _looks_relaxed(settings):
        return "LEGACY_RELAXED"
    if settings.candidate_selection_mode == CANDIDATE_MODE_FIXED:
        if not settings.enable_pyramiding:
            return "STRICT_FIXED_NO_PYRAMIDING"
        return "STRICT_FIXED"
    if settings.strategy_preset != STRATEGY_PRESET_CURRENT:
        return "STRICT_V2"
    return "STRICT_V1"


def _looks_relaxed(settings: TradingSettings) -> bool:
    return (
        settings.allow_relaxed_candidate_filter
        or settings.min_price_usd < 5.0
        or settings.max_price_usd > 50.0
        or settings.min_volume_ratio < 1.5
        or settings.max_opening_gap > 0.20
        or settings.min_total_score < 40.0
    )
