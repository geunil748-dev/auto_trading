from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 로컬 규칙 테스트에서 선택 의존성을 허용한다.
    load_dotenv = None

from trading_bot.manual_buy_list import DEFAULT_MANUAL_BUY_LIST_PATH

RUNTIME_SETTINGS_PATH = Path("monitor/trading_settings.json")
MIN_PRICE_USD_FLOOR = 10.0
APP_MODE_TEST = "test"
APP_MODE_REAL = "real"
APP_MODES = {APP_MODE_TEST, APP_MODE_REAL}
KIS_MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"
KIS_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"

# 화면에서 조정 가능한 매매 설정 키. 런타임 저장소와 .env 값을 같은 이름으로 맞춘다.
RUNTIME_SETTING_KEYS = {
    "max_position_loss",
    "take_profit_rate",
    "strategy_preset",
    "allow_relaxed_candidate_filter",
    "relax_opening_change_only",
    "enable_pyramiding",
    "partial_take_profit_enabled",
    "trailing_stop_activation_rate",
    "min_total_score",
    "min_price_usd",
    "max_price_usd",
    "gainer_ranking_limit",
    "turnover_ranking_limit",
    "ranking_selection_mode",
    "initial_ranked_evaluation_limit",
    "ranked_evaluation_batch_size",
    "max_ranked_evaluation_candidates",
    "target_filtered_candidates",
    "candidate_eval_timeout_seconds",
    "min_opening_price_change",
    "min_volume_ratio",
    "max_opening_gap",
    "refresh_intraday_candidates",
    "candidate_selection_mode",
    "max_entry_price_change",
    "overheat_limit_condition_mode",
    "breakout_hold_minutes",
    "require_5m_close_above_breakout",
    "breakout_close_condition_mode",
    "require_5m_volume_increase",
    "min_5m_volume_increase_percent",
    "volume_increase_condition_mode",
    "require_vwap_or_ma20",
    "vwap_ma20_condition_mode",
    "vwap_ma20_condition_type",
    "require_pullback_rebreak",
    "pullback_rebreak_condition_mode",
    "stop_loss_cooldown_minutes",
    "max_consecutive_stop_loss_count",
    "max_bid_ask_spread_rate",
    "max_expected_fill_price_gap_rate",
    "max_order_retry_count",
    "order_retry_delay_seconds",
    "partial_fill_policy",
    "unfilled_cancel_after_seconds",
}

CANDIDATE_MODE_REFRESH = "refresh"
CANDIDATE_MODE_FIXED = "fixed"
CANDIDATE_MODE_HYBRID = "hybrid"
CANDIDATE_SELECTION_MODES = {
    CANDIDATE_MODE_REFRESH,
    CANDIDATE_MODE_FIXED,
    CANDIDATE_MODE_HYBRID,
}
RANKING_SELECTION_INTERSECTION = "intersection"
RANKING_SELECTION_COMPOSITE = "composite"
RANKING_SELECTION_MODES = {
    RANKING_SELECTION_INTERSECTION,
    RANKING_SELECTION_COMPOSITE,
}
STRATEGY_PRESET_CURRENT = "current"
STRATEGY_PRESET_CONSERVATIVE_INTRADAY = "conservative_intraday"
STRATEGY_PRESET_BALANCED_INTRADAY = "balanced_intraday"
STRATEGY_PRESETS = {
    STRATEGY_PRESET_CURRENT,
    STRATEGY_PRESET_CONSERVATIVE_INTRADAY,
    STRATEGY_PRESET_BALANCED_INTRADAY,
}
PARTIAL_FILL_POLICY_KEEP = "KEEP_REMAINING"
PARTIAL_FILL_POLICY_CANCEL = "CANCEL_REMAINING"
PARTIAL_FILL_POLICIES = {PARTIAL_FILL_POLICY_KEEP, PARTIAL_FILL_POLICY_CANCEL}
CONDITION_MODE_OFF = "OFF"
CONDITION_MODE_LOG_ONLY = "LOG_ONLY"
CONDITION_MODE_SOFT_SCORE = "SOFT_SCORE"
CONDITION_MODE_HARD_FILTER = "HARD_FILTER"
CONDITION_MODES = {
    CONDITION_MODE_OFF,
    CONDITION_MODE_LOG_ONLY,
    CONDITION_MODE_SOFT_SCORE,
    CONDITION_MODE_HARD_FILTER,
}
VWAP_MA20_OR = "OR"
VWAP_MA20_AND = "AND"
VWAP_MA20_VWAP_ONLY = "VWAP_ONLY"
VWAP_MA20_MA20_ONLY = "MA20_ONLY"
VWAP_MA20_OFF = "OFF"
VWAP_MA20_TYPES = {
    VWAP_MA20_OR,
    VWAP_MA20_AND,
    VWAP_MA20_VWAP_ONLY,
    VWAP_MA20_MA20_ONLY,
    VWAP_MA20_OFF,
}


@dataclass(frozen=True)
class TradingSettings:
    app_mode: str = APP_MODE_TEST
    mock_trading: bool = True
    min_price_usd: float = MIN_PRICE_USD_FLOOR
    max_price_usd: float = 300.0
    gainer_ranking_limit: int = 100
    turnover_ranking_limit: int = 100
    ranking_selection_mode: str = RANKING_SELECTION_INTERSECTION
    initial_ranked_evaluation_limit: int = 50
    ranked_evaluation_batch_size: int = 25
    max_ranked_evaluation_candidates: int = 125
    target_filtered_candidates: int = 15
    candidate_eval_timeout_seconds: float = 120.0
    manual_buy_list_enabled: bool = True
    manual_buy_list_path: str = DEFAULT_MANUAL_BUY_LIST_PATH
    max_manual_buy_tickers: int = 20
    max_manual_selected_candidates: int = 20
    max_open_positions: int = 5
    min_selected_candidates: int = 3
    max_selected_candidates: int = 5
    max_account_exposure: float = 0.80
    max_position_exposure: float = 0.20
    max_position_loss: float = -0.05
    take_profit_rate: float = 0.10
    strategy_preset: str = STRATEGY_PRESET_CURRENT
    allow_relaxed_candidate_filter: bool = True
    relax_opening_change_only: bool = False
    enable_pyramiding: bool = False
    partial_take_profit_enabled: bool = True
    trailing_stop_activation_rate: float = 0.03
    max_daily_account_loss: float = -0.03
    max_fx_change: float = 0.02
    max_opening_gap: float = 0.30
    min_opening_price_change: float = 0.0
    min_volume_ratio: float = 1.00
    min_total_score: float = 35.0
    trailing_stop_drop: float = 0.03
    breakout_k: float = 0.50
    max_intraday_entry_rounds: int = 2
    max_intraday_buy_intents_per_round: int = 1
    refresh_intraday_candidates: bool = False
    candidate_selection_mode: str = CANDIDATE_MODE_FIXED
    opening_fixed_candidate_limit: int = 5
    intraday_refresh_candidate_limit: int = 3
    hybrid_candidate_limit: int = 8
    min_pyramiding_profit_rate: float = 0.03
    max_entry_price_change: float = 0.15
    overheat_limit_condition_mode: str = CONDITION_MODE_HARD_FILTER
    breakout_hold_minutes: float = 1.0
    require_5m_close_above_breakout: bool = True
    breakout_close_condition_mode: str = CONDITION_MODE_SOFT_SCORE
    require_5m_volume_increase: bool = True
    min_5m_volume_increase_percent: float = 5.0
    volume_increase_condition_mode: str = CONDITION_MODE_SOFT_SCORE
    require_vwap_or_ma20: bool = False
    vwap_ma20_condition_mode: str = CONDITION_MODE_HARD_FILTER
    vwap_ma20_condition_type: str = VWAP_MA20_OR
    require_pullback_rebreak: bool = True
    pullback_rebreak_condition_mode: str = CONDITION_MODE_SOFT_SCORE
    mock_unfilled_reorder_minutes: int = 2
    mock_unfilled_reorder_limit: int = 1
    real_unfilled_reorder_minutes: int = 1
    stop_loss_cooldown_minutes: int = 30
    max_consecutive_stop_loss_count: int = 3
    max_bid_ask_spread_rate: float = 1.0
    max_expected_fill_price_gap_rate: float = 1.0
    max_order_retry_count: int = 2
    order_retry_delay_seconds: int = 3
    partial_fill_policy: str = PARTIAL_FILL_POLICY_KEEP
    unfilled_cancel_after_seconds: int = 60
    news_cache_ttl_minutes: int = 30
    real_trading_enabled: bool = False
    real_max_order_krw: int = 100000
    real_max_daily_order_krw: int = 300000
    real_emergency_stop: bool = True
    early_exit_diagnostics_enabled: bool = False
    profit_protection_exit_enabled: bool = False
    profit_protection_trigger_rate: float = 0.02
    profit_protection_floor_rate: float = -0.003
    time_stop_exit_enabled: bool = False
    time_stop_minutes: int = 30
    time_stop_min_profit_rate: float = 0.0
    early_negative_exit_enabled: bool = False
    early_negative_exit_minutes: int = 10
    early_negative_exit_rate: float = 0.0
    low_profit_60m_exit_enabled: bool = False
    low_profit_60m_minutes: int = 60
    low_profit_60m_min_profit_rate: float = 0.01
    partial_take_profit_sim_trigger_rate: float = 0.03
    partial_take_profit_sim_fraction: float = 0.5


@dataclass(frozen=True)
class KisSettings:
    app_key: str
    app_secret: str
    account_no: str
    account_product: str
    base_url: str


@dataclass(frozen=True)
class KisWebSocketSettings:
    enabled: bool
    app_key: str
    app_secret: str
    approval_key: str
    ws_url: str
    account_no: str
    account_product: str
    reconnect_seconds: int = 5


@dataclass(frozen=True)
class NotificationSettings:
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def load_settings() -> TradingSettings:
    if load_dotenv is not None:
        load_dotenv()

    app_mode = _app_mode_env()
    real_trading_requested = _bool_env("REAL_TRADING_ENABLED", False)
    max_selected_candidates = _max_selected_candidates_env("MAX_SELECTED_CANDIDATES", 5)
    target_filtered_default = max(15, max_selected_candidates * 3)
    settings = _validate_candidate_evaluation_settings(TradingSettings(
        app_mode=app_mode,
        mock_trading=_bool_env("MOCK_TRADING", True),
        min_price_usd=_min_price_env("MIN_PRICE_USD", MIN_PRICE_USD_FLOOR),
        max_price_usd=_float_env("MAX_PRICE_USD", 300.0),
        gainer_ranking_limit=_ranking_limit_env("GAINER_RANKING_LIMIT", 100),
        turnover_ranking_limit=_ranking_limit_env("TURNOVER_RANKING_LIMIT", 100),
        ranking_selection_mode=_ranking_selection_mode_env(),
        initial_ranked_evaluation_limit=_candidate_eval_count_env(
            "INITIAL_RANKED_EVALUATION_LIMIT",
            50,
        ),
        ranked_evaluation_batch_size=_candidate_eval_count_env(
            "RANKED_EVALUATION_BATCH_SIZE",
            25,
        ),
        max_ranked_evaluation_candidates=_candidate_eval_count_env(
            "MAX_RANKED_EVALUATION_CANDIDATES",
            125,
        ),
        target_filtered_candidates=_candidate_eval_count_env(
            "TARGET_FILTERED_CANDIDATES",
            target_filtered_default,
        ),
        candidate_eval_timeout_seconds=_candidate_eval_timeout_env(
            "CANDIDATE_EVAL_TIMEOUT_SECONDS",
            120.0,
        ),
        manual_buy_list_enabled=_bool_env("MANUAL_BUY_LIST_ENABLED", True),
        manual_buy_list_path=os.getenv(
            "MANUAL_BUY_LIST_PATH",
            DEFAULT_MANUAL_BUY_LIST_PATH,
        ).strip() or DEFAULT_MANUAL_BUY_LIST_PATH,
        max_manual_buy_tickers=_candidate_eval_count_env(
            "MAX_MANUAL_BUY_TICKERS",
            20,
        ),
        max_manual_selected_candidates=_candidate_eval_count_env(
            "MAX_MANUAL_SELECTED_CANDIDATES",
            20,
        ),
        max_open_positions=_int_env("MAX_OPEN_POSITIONS", 5),
        max_selected_candidates=max_selected_candidates,
        max_account_exposure=_float_env("MAX_ACCOUNT_EXPOSURE", 0.80),
        max_position_exposure=_float_env("MAX_POSITION_EXPOSURE", 0.20),
        max_opening_gap=_float_env("MAX_OPENING_GAP", 0.30),
        min_opening_price_change=_float_env("MIN_OPENING_PRICE_CHANGE", 0.0),
        min_volume_ratio=_float_env("MIN_VOLUME_RATIO", 1.00),
        min_total_score=_float_env("MIN_TOTAL_SCORE", 35.0),
        max_intraday_entry_rounds=_int_env("MAX_INTRADAY_ENTRY_ROUNDS", 2),
        max_intraday_buy_intents_per_round=_int_env(
            "MAX_INTRADAY_BUY_INTENTS_PER_ROUND",
            1,
        ),
        refresh_intraday_candidates=_bool_env("REFRESH_INTRADAY_CANDIDATES", False),
        candidate_selection_mode=_candidate_mode_env(),
        opening_fixed_candidate_limit=_int_env("OPENING_FIXED_CANDIDATE_LIMIT", 5),
        intraday_refresh_candidate_limit=_int_env("INTRADAY_REFRESH_CANDIDATE_LIMIT", 3),
        hybrid_candidate_limit=_int_env("HYBRID_CANDIDATE_LIMIT", 8),
        min_pyramiding_profit_rate=_float_env("MIN_PYRAMIDING_PROFIT_RATE", 0.03),
        max_entry_price_change=_float_env("MAX_ENTRY_PRICE_CHANGE", 0.15),
        overheat_limit_condition_mode=_condition_mode_env(
            "OVERHEAT_LIMIT_CONDITION_MODE",
            CONDITION_MODE_HARD_FILTER,
        ),
        breakout_hold_minutes=_float_env("BREAKOUT_HOLD_MINUTES", 1.0),
        require_5m_close_above_breakout=_bool_env("REQUIRE_5M_CLOSE_ABOVE_BREAKOUT", True),
        breakout_close_condition_mode=_condition_mode_env(
            "BREAKOUT_CLOSE_CONDITION_MODE",
            CONDITION_MODE_SOFT_SCORE,
        ),
        require_5m_volume_increase=_bool_env("REQUIRE_5M_VOLUME_INCREASE", True),
        min_5m_volume_increase_percent=_float_env("MIN_5M_VOLUME_INCREASE_PERCENT", 5.0),
        volume_increase_condition_mode=_condition_mode_env(
            "VOLUME_INCREASE_CONDITION_MODE",
            CONDITION_MODE_SOFT_SCORE,
        ),
        require_vwap_or_ma20=_bool_env("REQUIRE_VWAP_OR_MA20", False),
        vwap_ma20_condition_mode=_condition_mode_env(
            "VWAP_MA20_CONDITION_MODE",
            CONDITION_MODE_HARD_FILTER,
        ),
        vwap_ma20_condition_type=_vwap_ma20_type_env(),
        require_pullback_rebreak=_bool_env("REQUIRE_PULLBACK_REBREAK", True),
        pullback_rebreak_condition_mode=_condition_mode_env(
            "PULLBACK_REBREAK_CONDITION_MODE",
            CONDITION_MODE_SOFT_SCORE,
        ),
        mock_unfilled_reorder_minutes=_int_env("MOCK_UNFILLED_REORDER_MINUTES", 2),
        mock_unfilled_reorder_limit=_int_env("MOCK_UNFILLED_REORDER_LIMIT", 1),
        real_unfilled_reorder_minutes=_int_env("REAL_UNFILLED_REORDER_MINUTES", 1),
        stop_loss_cooldown_minutes=_int_env("STOP_LOSS_COOLDOWN_MINUTES", 30),
        max_consecutive_stop_loss_count=_int_env("MAX_CONSECUTIVE_STOP_LOSS_COUNT", 3),
        max_bid_ask_spread_rate=_float_env("MAX_BID_ASK_SPREAD_RATE", 1.0),
        max_expected_fill_price_gap_rate=_float_env("MAX_EXPECTED_FILL_PRICE_GAP_RATE", 1.0),
        max_order_retry_count=_int_env("MAX_ORDER_RETRY_COUNT", 2),
        order_retry_delay_seconds=_int_env("ORDER_RETRY_DELAY_SECONDS", 3),
        partial_fill_policy=_partial_fill_policy_env(),
        unfilled_cancel_after_seconds=_int_env("UNFILLED_CANCEL_AFTER_SECONDS", 60),
        news_cache_ttl_minutes=_int_env("NEWS_CACHE_TTL_MINUTES", 30),
        take_profit_rate=_float_env("TAKE_PROFIT_RATE", 0.10),
        strategy_preset=_strategy_preset_env(),
        allow_relaxed_candidate_filter=_bool_env("ALLOW_RELAXED_CANDIDATE_FILTER", True),
        relax_opening_change_only=_bool_env("RELAX_OPENING_CHANGE_ONLY", False),
        enable_pyramiding=_bool_env("ENABLE_PYRAMIDING", False),
        partial_take_profit_enabled=_bool_env("PARTIAL_TAKE_PROFIT_ENABLED", True),
        trailing_stop_activation_rate=_float_env("TRAILING_STOP_ACTIVATION_RATE", 0.03),
        early_exit_diagnostics_enabled=_bool_env("EARLY_EXIT_DIAGNOSTICS_ENABLED", False),
        profit_protection_exit_enabled=_bool_env("PROFIT_PROTECTION_EXIT_ENABLED", False),
        profit_protection_trigger_rate=_float_env("PROFIT_PROTECTION_TRIGGER_RATE", 0.02),
        profit_protection_floor_rate=_float_env("PROFIT_PROTECTION_FLOOR_RATE", -0.003),
        time_stop_exit_enabled=_bool_env("TIME_STOP_EXIT_ENABLED", False),
        time_stop_minutes=_int_env("TIME_STOP_MINUTES", 30),
        time_stop_min_profit_rate=_float_env("TIME_STOP_MIN_PROFIT_RATE", 0.0),
        early_negative_exit_enabled=_bool_env("EARLY_NEGATIVE_EXIT_ENABLED", False),
        early_negative_exit_minutes=_int_env("EARLY_NEGATIVE_EXIT_MINUTES", 10),
        early_negative_exit_rate=_float_env("EARLY_NEGATIVE_EXIT_RATE", 0.0),
        low_profit_60m_exit_enabled=_bool_env("LOW_PROFIT_60M_EXIT_ENABLED", False),
        low_profit_60m_minutes=_int_env("LOW_PROFIT_60M_MINUTES", 60),
        low_profit_60m_min_profit_rate=_float_env("LOW_PROFIT_60M_MIN_PROFIT_RATE", 0.01),
        partial_take_profit_sim_trigger_rate=_float_env(
            "PARTIAL_TAKE_PROFIT_SIM_TRIGGER_RATE",
            0.03,
        ),
        partial_take_profit_sim_fraction=_float_env(
            "PARTIAL_TAKE_PROFIT_SIM_FRACTION",
            0.5,
        ),
        real_trading_enabled=real_trading_requested if app_mode == APP_MODE_REAL else False,
        real_max_order_krw=_int_env("REAL_MAX_ORDER_KRW", 100000),
        real_max_daily_order_krw=_int_env("REAL_MAX_DAILY_ORDER_KRW", 300000),
        real_emergency_stop=(
            _bool_env("REAL_EMERGENCY_STOP", True)
            if app_mode == APP_MODE_REAL
            else True
        ),
    ))
    return _validate_candidate_evaluation_settings(
        _apply_strategy_preset(_apply_runtime_settings(settings))
    )


def runtime_risk_settings_payload(
    settings: TradingSettings | None = None,
) -> dict[str, float]:
    current = settings or load_settings()
    return {
        "stopLossRate": current.max_position_loss,
        "stopLossPercent": abs(current.max_position_loss * 100),
        "takeProfitRate": current.take_profit_rate,
        "takeProfitPercent": current.take_profit_rate * 100,
        "strategyPreset": current.strategy_preset,
        "allowRelaxedCandidateFilter": bool(current.allow_relaxed_candidate_filter),
        "relaxOpeningChangeOnly": bool(current.relax_opening_change_only),
        "enablePyramiding": bool(current.enable_pyramiding),
        "partialTakeProfitEnabled": bool(current.partial_take_profit_enabled),
        "trailingStopActivationRate": current.trailing_stop_activation_rate,
        "trailingStopActivationPercent": current.trailing_stop_activation_rate * 100,
        "minTotalScore": current.min_total_score,
        "minPriceUsd": current.min_price_usd,
        "maxPriceUsd": current.max_price_usd,
        "gainerRankingLimit": current.gainer_ranking_limit,
        "turnoverRankingLimit": current.turnover_ranking_limit,
        "rankingSelectionMode": current.ranking_selection_mode,
        "initialRankedEvaluationLimit": current.initial_ranked_evaluation_limit,
        "rankedEvaluationBatchSize": current.ranked_evaluation_batch_size,
        "maxRankedEvaluationCandidates": current.max_ranked_evaluation_candidates,
        "targetFilteredCandidates": current.target_filtered_candidates,
        "candidateEvalTimeoutSeconds": current.candidate_eval_timeout_seconds,
        "minOpeningPriceChangePercent": current.min_opening_price_change * 100,
        "minVolumeRatio": current.min_volume_ratio,
        "maxOpeningGapPercent": current.max_opening_gap * 100,
        "refreshIntradayCandidates": bool(current.refresh_intraday_candidates),
        "candidateSelectionMode": current.candidate_selection_mode,
        "maxEntryPriceChangePercent": current.max_entry_price_change * 100,
        "overheatLimitConditionMode": current.overheat_limit_condition_mode,
        "breakoutHoldMinutes": current.breakout_hold_minutes,
        "require5mCloseAboveBreakout": bool(current.require_5m_close_above_breakout),
        "breakoutCloseConditionMode": current.breakout_close_condition_mode,
        "require5mVolumeIncrease": bool(current.require_5m_volume_increase),
        "min5mVolumeIncreasePercent": current.min_5m_volume_increase_percent,
        "volumeIncreaseConditionMode": current.volume_increase_condition_mode,
        "requireVwapOrMa20": bool(current.require_vwap_or_ma20),
        "vwapMa20ConditionMode": current.vwap_ma20_condition_mode,
        "vwapMa20ConditionType": current.vwap_ma20_condition_type,
        "requirePullbackRebreak": bool(current.require_pullback_rebreak),
        "pullbackRebreakConditionMode": current.pullback_rebreak_condition_mode,
        "stopLossCooldownMinutes": current.stop_loss_cooldown_minutes,
        "maxConsecutiveStopLossCount": current.max_consecutive_stop_loss_count,
        "maxBidAskSpreadRate": current.max_bid_ask_spread_rate,
        "maxExpectedFillPriceGapRate": current.max_expected_fill_price_gap_rate,
        "maxOrderRetryCount": current.max_order_retry_count,
        "orderRetryDelaySeconds": current.order_retry_delay_seconds,
        "partialFillPolicy": current.partial_fill_policy,
        "unfilledCancelAfterSeconds": current.unfilled_cancel_after_seconds,
    }


def save_runtime_risk_settings(
    stop_loss_percent: float,
    take_profit_percent: float,
    min_total_score: float | None = None,
    min_price_usd: float | None = None,
    max_price_usd: float | None = None,
    min_opening_price_change_percent: float | None = None,
    min_volume_ratio: float | None = None,
    max_opening_gap_percent: float | None = None,
    refresh_intraday_candidates: bool | None = None,
    candidate_selection_mode: str | None = None,
    partial_take_profit_enabled: bool | None = None,
    trailing_stop_activation_percent: float | None = None,
    max_entry_price_change_percent: float | None = None,
    breakout_hold_minutes: float | None = None,
    require_5m_close_above_breakout: bool | None = None,
    require_5m_volume_increase: bool | None = None,
    require_vwap_or_ma20: bool | None = None,
    require_pullback_rebreak: bool | None = None,
    gainer_ranking_limit: float | None = None,
    turnover_ranking_limit: float | None = None,
    overheat_limit_condition_mode: str | None = None,
    breakout_close_condition_mode: str | None = None,
    volume_increase_condition_mode: str | None = None,
    min_5m_volume_increase_percent: float | None = None,
    vwap_ma20_condition_mode: str | None = None,
    vwap_ma20_condition_type: str | None = None,
    pullback_rebreak_condition_mode: str | None = None,
    stop_loss_cooldown_minutes: float | None = None,
    max_consecutive_stop_loss_count: float | None = None,
    max_bid_ask_spread_rate: float | None = None,
    max_expected_fill_price_gap_rate: float | None = None,
    max_order_retry_count: float | None = None,
    order_retry_delay_seconds: float | None = None,
    partial_fill_policy: str | None = None,
    unfilled_cancel_after_seconds: float | None = None,
    strategy_preset: str | None = None,
    allow_relaxed_candidate_filter: bool | None = None,
    relax_opening_change_only: bool | None = None,
    enable_pyramiding: bool | None = None,
    ranking_selection_mode: str | None = None,
    path: Path = RUNTIME_SETTINGS_PATH,
) -> dict[str, float]:
    stop = _validate_percent(stop_loss_percent, "손절 비율")
    profit = _validate_percent(take_profit_percent, "익절 비율")
    payload = _runtime_settings_from_settings(load_settings())
    payload.update({
        "max_position_loss": -(stop / 100),
        "take_profit_rate": profit / 100,
    })
    if strategy_preset is not None:
        payload["strategy_preset"] = _strategy_preset_to_float(strategy_preset)
    if allow_relaxed_candidate_filter is not None:
        payload["allow_relaxed_candidate_filter"] = (
            1.0 if allow_relaxed_candidate_filter else 0.0
        )
    if relax_opening_change_only is not None:
        payload["relax_opening_change_only"] = 1.0 if relax_opening_change_only else 0.0
    if enable_pyramiding is not None:
        payload["enable_pyramiding"] = 1.0 if enable_pyramiding else 0.0
    if min_total_score is not None:
        payload["min_total_score"] = _validate_score(min_total_score, "선정점수")
    if min_price_usd is not None or max_price_usd is not None:
        current_min = min_price_usd if min_price_usd is not None else payload.get("min_price_usd")
        current_max = max_price_usd if max_price_usd is not None else payload.get("max_price_usd")
        min_price, max_price = _validate_price_range(current_min, current_max)
        payload["min_price_usd"] = min_price
        payload["max_price_usd"] = max_price
    if gainer_ranking_limit is not None:
        payload["gainer_ranking_limit"] = _validate_positive_count(
            gainer_ranking_limit,
            "상승률 랭킹 수",
            1000,
        )
    if turnover_ranking_limit is not None:
        payload["turnover_ranking_limit"] = _validate_positive_count(
            turnover_ranking_limit,
            "거래량 랭킹 수",
            1000,
        )
    if ranking_selection_mode is not None:
        payload["ranking_selection_mode"] = _ranking_selection_mode_to_float(
            ranking_selection_mode
        )
    if min_opening_price_change_percent is not None:
        payload["min_opening_price_change"] = (
            _validate_percent_range(min_opening_price_change_percent, "장초반 상승률") / 100
        )
    if min_volume_ratio is not None:
        payload["min_volume_ratio"] = _validate_volume_ratio(min_volume_ratio, "거래량 비율")
    if max_opening_gap_percent is not None:
        payload["max_opening_gap"] = (
            _validate_percent_range(max_opening_gap_percent, "시가 갭 상한") / 100
        )
    if refresh_intraday_candidates is not None:
        payload["refresh_intraday_candidates"] = 1.0 if refresh_intraday_candidates else 0.0
    if candidate_selection_mode is not None:
        mode = _validate_candidate_mode(candidate_selection_mode)
        payload["candidate_selection_mode"] = _candidate_mode_to_float(mode)
        payload["refresh_intraday_candidates"] = 0.0 if mode == CANDIDATE_MODE_FIXED else 1.0
    if partial_take_profit_enabled is not None:
        payload["partial_take_profit_enabled"] = 1.0 if partial_take_profit_enabled else 0.0
    if trailing_stop_activation_percent is not None:
        payload["trailing_stop_activation_rate"] = (
            _validate_percent_range(trailing_stop_activation_percent, "트레일링 시작 수익률") / 100
        )
    if max_entry_price_change_percent is not None:
        payload["max_entry_price_change"] = (
            _validate_percent_range(max_entry_price_change_percent, "매수 과열 상한") / 100
        )
    if overheat_limit_condition_mode is not None:
        payload["overheat_limit_condition_mode"] = _condition_mode_to_float(
            overheat_limit_condition_mode
        )
    if breakout_hold_minutes is not None:
        payload["breakout_hold_minutes"] = _validate_minutes(
            breakout_hold_minutes,
            "돌파 유지 시간",
        )
    if require_5m_close_above_breakout is not None:
        payload["require_5m_close_above_breakout"] = (
            1.0 if require_5m_close_above_breakout else 0.0
        )
    if breakout_close_condition_mode is not None:
        payload["breakout_close_condition_mode"] = _condition_mode_to_float(
            breakout_close_condition_mode
        )
    if require_5m_volume_increase is not None:
        payload["require_5m_volume_increase"] = 1.0 if require_5m_volume_increase else 0.0
    if min_5m_volume_increase_percent is not None:
        payload["min_5m_volume_increase_percent"] = _validate_percent_range(
            min_5m_volume_increase_percent,
            "5분 거래량 증가 기준",
        )
    if volume_increase_condition_mode is not None:
        payload["volume_increase_condition_mode"] = _condition_mode_to_float(
            volume_increase_condition_mode
        )
    if require_vwap_or_ma20 is not None:
        payload["require_vwap_or_ma20"] = 1.0 if require_vwap_or_ma20 else 0.0
    if vwap_ma20_condition_mode is not None:
        payload["vwap_ma20_condition_mode"] = _condition_mode_to_float(
            vwap_ma20_condition_mode
        )
    if vwap_ma20_condition_type is not None:
        payload["vwap_ma20_condition_type"] = _vwap_ma20_type_to_float(
            vwap_ma20_condition_type
        )
    if require_pullback_rebreak is not None:
        payload["require_pullback_rebreak"] = 1.0 if require_pullback_rebreak else 0.0
    if pullback_rebreak_condition_mode is not None:
        payload["pullback_rebreak_condition_mode"] = _condition_mode_to_float(
            pullback_rebreak_condition_mode
        )
    if stop_loss_cooldown_minutes is not None:
        payload["stop_loss_cooldown_minutes"] = _validate_minutes(
            stop_loss_cooldown_minutes,
            "손절 후 재진입 제한 시간",
        )
    if max_consecutive_stop_loss_count is not None:
        payload["max_consecutive_stop_loss_count"] = _validate_count(
            max_consecutive_stop_loss_count,
            "연속 손절 제한 횟수",
            10,
        )
    if max_bid_ask_spread_rate is not None:
        payload["max_bid_ask_spread_rate"] = _validate_percent_range(
            max_bid_ask_spread_rate,
            "호가 스프레드 제한",
        )
    if max_expected_fill_price_gap_rate is not None:
        payload["max_expected_fill_price_gap_rate"] = _validate_percent_range(
            max_expected_fill_price_gap_rate,
            "예상 체결가 괴리 제한",
        )
    if max_order_retry_count is not None:
        payload["max_order_retry_count"] = _validate_count(max_order_retry_count, "주문 재시도 횟수", 10)
    if order_retry_delay_seconds is not None:
        payload["order_retry_delay_seconds"] = _validate_count(
            order_retry_delay_seconds,
            "주문 재시도 대기 시간",
            60,
        )
    if partial_fill_policy is not None:
        payload["partial_fill_policy"] = _partial_fill_policy_to_float(partial_fill_policy)
    if unfilled_cancel_after_seconds is not None:
        payload["unfilled_cancel_after_seconds"] = _validate_count(
            unfilled_cancel_after_seconds,
            "미체결 취소 대기 시간",
            3600,
        )
    if not _save_runtime_settings_to_db(payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    current = load_settings()
    updated = replace(
        current,
        max_position_loss=payload["max_position_loss"],
        take_profit_rate=payload["take_profit_rate"],
        strategy_preset=_strategy_preset_from_float(
            payload.get(
                "strategy_preset",
                _strategy_preset_to_float(current.strategy_preset),
            )
        ),
        allow_relaxed_candidate_filter=bool(
            payload.get(
                "allow_relaxed_candidate_filter",
                float(current.allow_relaxed_candidate_filter),
            )
        ),
        relax_opening_change_only=bool(
            payload.get(
                "relax_opening_change_only",
                float(current.relax_opening_change_only),
            )
        ),
        enable_pyramiding=bool(
            payload.get("enable_pyramiding", float(current.enable_pyramiding))
        ),
        min_total_score=payload.get("min_total_score", current.min_total_score),
        min_price_usd=payload.get("min_price_usd", current.min_price_usd),
        max_price_usd=payload.get("max_price_usd", current.max_price_usd),
        gainer_ranking_limit=int(
            payload.get("gainer_ranking_limit", current.gainer_ranking_limit)
        ),
        turnover_ranking_limit=int(
            payload.get("turnover_ranking_limit", current.turnover_ranking_limit)
        ),
        ranking_selection_mode=_ranking_selection_mode_from_float(
            payload.get(
                "ranking_selection_mode",
                _ranking_selection_mode_to_float(current.ranking_selection_mode),
            )
        ),
        initial_ranked_evaluation_limit=int(
            payload.get(
                "initial_ranked_evaluation_limit",
                current.initial_ranked_evaluation_limit,
            )
        ),
        ranked_evaluation_batch_size=int(
            payload.get(
                "ranked_evaluation_batch_size",
                current.ranked_evaluation_batch_size,
            )
        ),
        max_ranked_evaluation_candidates=int(
            payload.get(
                "max_ranked_evaluation_candidates",
                current.max_ranked_evaluation_candidates,
            )
        ),
        target_filtered_candidates=int(
            payload.get("target_filtered_candidates", current.target_filtered_candidates)
        ),
        candidate_eval_timeout_seconds=payload.get(
            "candidate_eval_timeout_seconds",
            current.candidate_eval_timeout_seconds,
        ),
        min_opening_price_change=payload.get(
            "min_opening_price_change",
            current.min_opening_price_change,
        ),
        min_volume_ratio=payload.get("min_volume_ratio", current.min_volume_ratio),
        max_opening_gap=payload.get("max_opening_gap", current.max_opening_gap),
        refresh_intraday_candidates=bool(
            payload.get(
                "refresh_intraday_candidates",
                float(current.refresh_intraday_candidates),
            )
        ),
        candidate_selection_mode=_candidate_mode_from_float(
            payload.get(
                "candidate_selection_mode",
                _candidate_mode_to_float(current.candidate_selection_mode),
            )
        ),
        partial_take_profit_enabled=bool(
            payload.get(
                "partial_take_profit_enabled",
                float(current.partial_take_profit_enabled),
            )
        ),
        trailing_stop_activation_rate=payload.get(
            "trailing_stop_activation_rate",
            current.trailing_stop_activation_rate,
        ),
        max_entry_price_change=payload.get(
            "max_entry_price_change",
            current.max_entry_price_change,
        ),
        overheat_limit_condition_mode=_condition_mode_from_float(
            payload.get(
                "overheat_limit_condition_mode",
                _condition_mode_to_float(current.overheat_limit_condition_mode),
            )
        ),
        breakout_hold_minutes=payload.get(
            "breakout_hold_minutes",
            current.breakout_hold_minutes,
        ),
        require_5m_close_above_breakout=bool(
            payload.get(
                "require_5m_close_above_breakout",
                float(current.require_5m_close_above_breakout),
            )
        ),
        breakout_close_condition_mode=_condition_mode_from_float(
            payload.get(
                "breakout_close_condition_mode",
                _condition_mode_to_float(current.breakout_close_condition_mode),
            )
        ),
        require_5m_volume_increase=bool(
            payload.get(
                "require_5m_volume_increase",
                float(current.require_5m_volume_increase),
            )
        ),
        min_5m_volume_increase_percent=payload.get(
            "min_5m_volume_increase_percent",
            current.min_5m_volume_increase_percent,
        ),
        volume_increase_condition_mode=_condition_mode_from_float(
            payload.get(
                "volume_increase_condition_mode",
                _condition_mode_to_float(current.volume_increase_condition_mode),
            )
        ),
        require_vwap_or_ma20=bool(
            payload.get("require_vwap_or_ma20", float(current.require_vwap_or_ma20))
        ),
        vwap_ma20_condition_mode=_condition_mode_from_float(
            payload.get(
                "vwap_ma20_condition_mode",
                _condition_mode_to_float(current.vwap_ma20_condition_mode),
            )
        ),
        vwap_ma20_condition_type=_vwap_ma20_type_from_float(
            payload.get(
                "vwap_ma20_condition_type",
                _vwap_ma20_type_to_float(current.vwap_ma20_condition_type),
            )
        ),
        require_pullback_rebreak=bool(
            payload.get(
                "require_pullback_rebreak",
                float(current.require_pullback_rebreak),
            )
        ),
        pullback_rebreak_condition_mode=_condition_mode_from_float(
            payload.get(
                "pullback_rebreak_condition_mode",
                _condition_mode_to_float(current.pullback_rebreak_condition_mode),
            )
        ),
        stop_loss_cooldown_minutes=int(
            payload.get(
                "stop_loss_cooldown_minutes",
                current.stop_loss_cooldown_minutes,
            )
        ),
        max_consecutive_stop_loss_count=int(
            payload.get(
                "max_consecutive_stop_loss_count",
                current.max_consecutive_stop_loss_count,
            )
        ),
        max_bid_ask_spread_rate=payload.get(
            "max_bid_ask_spread_rate",
            current.max_bid_ask_spread_rate,
        ),
        max_expected_fill_price_gap_rate=payload.get(
            "max_expected_fill_price_gap_rate",
            current.max_expected_fill_price_gap_rate,
        ),
        max_order_retry_count=int(
            payload.get("max_order_retry_count", current.max_order_retry_count)
        ),
        order_retry_delay_seconds=int(
            payload.get(
                "order_retry_delay_seconds",
                current.order_retry_delay_seconds,
            )
        ),
        partial_fill_policy=_partial_fill_policy_from_float(
            payload.get(
                "partial_fill_policy",
                _partial_fill_policy_to_float(current.partial_fill_policy),
            )
        ),
        unfilled_cancel_after_seconds=int(
            payload.get(
                "unfilled_cancel_after_seconds",
                current.unfilled_cancel_after_seconds,
            )
        ),
    )
    return runtime_risk_settings_payload(_apply_strategy_preset(updated))


def load_notification_settings() -> NotificationSettings:
    if load_dotenv is not None:
        load_dotenv()

    return NotificationSettings(
        discord_webhook_url=os.getenv("ALERT_DISCORD_WEBHOOK_URL", ""),
        telegram_bot_token=os.getenv("ALERT_TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("ALERT_TELEGRAM_CHAT_ID", ""),
    )


def load_kis_settings() -> KisSettings:
    if load_dotenv is not None:
        load_dotenv()
    base_url = os.getenv("KIS_BASE_URL", KIS_MOCK_BASE_URL).rstrip("/")
    _validate_mock_kis_base_url(base_url)

    return KisSettings(
        app_key=_required_env("KIS_APP_KEY"),
        app_secret=_required_env("KIS_APP_SECRET"),
        account_no=_required_env("KIS_ACCOUNT_NO"),
        account_product=os.getenv("KIS_ACCOUNT_PRODUCT", "01"),
        base_url=base_url,
    )


def load_real_kis_settings() -> KisSettings:
    if load_dotenv is not None:
        load_dotenv()
    _require_real_app_mode("KIS_REAL settings")

    return KisSettings(
        app_key=_required_env("KIS_REAL_APP_KEY"),
        app_secret=_required_env("KIS_REAL_APP_SECRET"),
        account_no=_required_env("KIS_REAL_ACCOUNT_NO"),
        account_product=os.getenv("KIS_REAL_ACCOUNT_PRODUCT", "01"),
        base_url=os.getenv(
            "KIS_REAL_BASE_URL",
            KIS_REAL_BASE_URL,
        ).rstrip("/"),
    )


def load_kis_websocket_settings(real: bool = False) -> KisWebSocketSettings:
    if load_dotenv is not None:
        load_dotenv()

    if real:
        _require_real_app_mode("KIS_REAL websocket settings")

    prefix = "KIS_REAL_WS" if real else "KIS_WS"
    kis_prefix = "KIS_REAL" if real else "KIS"

    return KisWebSocketSettings(
        enabled=_bool_env(f"{prefix}_ENABLED", False),
        app_key=os.getenv(f"{prefix}_APP_KEY") or os.getenv(f"{kis_prefix}_APP_KEY", ""),
        app_secret=os.getenv(f"{prefix}_APP_SECRET")
        or os.getenv(f"{kis_prefix}_APP_SECRET", ""),
        approval_key=os.getenv(f"{prefix}_APPROVAL_KEY", ""),
        ws_url=os.getenv(f"{prefix}_URL", "").rstrip("/"),
        account_no=os.getenv(f"{prefix}_ACCOUNT_NO")
        or os.getenv(f"{kis_prefix}_ACCOUNT_NO", ""),
        account_product=os.getenv(f"{prefix}_ACCOUNT_PRODUCT")
        or os.getenv(f"{kis_prefix}_ACCOUNT_PRODUCT", "01"),
        reconnect_seconds=_int_env(f"{prefix}_RECONNECT_SECONDS", 5),
    )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _app_mode_env() -> str:
    raw = os.getenv("APP_MODE", APP_MODE_TEST)
    value = raw.strip().lower() if raw is not None else APP_MODE_TEST
    if not value:
        return APP_MODE_TEST
    if value not in APP_MODES:
        raise ValueError("APP_MODE must be either 'test' or 'real'")
    return value


def _require_real_app_mode(context: str) -> None:
    if _app_mode_env() != APP_MODE_REAL:
        raise ValueError(f"{context} requires APP_MODE=real")


def _validate_mock_kis_base_url(base_url: str) -> None:
    if _app_mode_env() != APP_MODE_TEST:
        return
    if base_url.rstrip("/").lower() == KIS_REAL_BASE_URL.lower():
        raise ValueError("APP_MODE=test cannot use the KIS real-trading base URL")


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


def _min_price_env(name: str, default: float) -> float:
    value = _float_env(name, default)
    if value < MIN_PRICE_USD_FLOOR:
        raise ValueError(f"{name}는 {MIN_PRICE_USD_FLOOR:g} 이상으로 입력해 주세요.")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _ranking_limit_env(name: str, default: int) -> int:
    return _validate_positive_count(_int_env(name, default), name, 1000)


def _candidate_eval_count_env(name: str, default: int) -> int:
    return _validate_positive_count(_int_env(name, default), name, 10000)


def _max_selected_candidates_env(name: str, default: int) -> int:
    return _validate_positive_count(_int_env(name, default), name, 10000)


def _candidate_eval_timeout_env(name: str, default: float) -> float:
    value = _float_env(name, default)
    if value <= 0:
        raise ValueError(f"{name}는 0보다 크게 입력해 주세요.")
    return value


def _candidate_mode_env() -> str:
    raw = os.getenv("CANDIDATE_SELECTION_MODE")
    if raw:
        return _validate_candidate_mode(raw)
    return CANDIDATE_MODE_REFRESH if _bool_env("REFRESH_INTRADAY_CANDIDATES", False) else CANDIDATE_MODE_FIXED


def _ranking_selection_mode_env() -> str:
    return _validate_ranking_selection_mode(
        os.getenv("RANKING_SELECTION_MODE", RANKING_SELECTION_INTERSECTION)
    )


def _condition_mode_env(name: str, default: str) -> str:
    return _validate_condition_mode(os.getenv(name, default))


def _vwap_ma20_type_env() -> str:
    return _validate_vwap_ma20_type(os.getenv("VWAP_MA20_CONDITION_TYPE", VWAP_MA20_OR))


def _strategy_preset_env() -> str:
    return _validate_strategy_preset(os.getenv("STRATEGY_PRESET", STRATEGY_PRESET_CURRENT))


def _partial_fill_policy_env() -> str:
    return _validate_partial_fill_policy(os.getenv("PARTIAL_FILL_POLICY", PARTIAL_FILL_POLICY_KEEP))


def _required_env(name: str) -> str:
    raw = os.getenv(name)
    if not raw:
        raise ValueError(f"{name} is required")
    return raw


def _apply_runtime_settings(settings: TradingSettings) -> TradingSettings:
    overrides = _read_runtime_settings()
    overrides = _complete_runtime_settings(settings, overrides)
    if "refresh_intraday_candidates" in overrides:
        overrides["refresh_intraday_candidates"] = bool(overrides["refresh_intraday_candidates"])
    if "allow_relaxed_candidate_filter" in overrides:
        overrides["allow_relaxed_candidate_filter"] = bool(
            overrides["allow_relaxed_candidate_filter"]
        )
    if "relax_opening_change_only" in overrides:
        overrides["relax_opening_change_only"] = bool(overrides["relax_opening_change_only"])
    if "enable_pyramiding" in overrides:
        overrides["enable_pyramiding"] = bool(overrides["enable_pyramiding"])
    if "partial_take_profit_enabled" in overrides:
        overrides["partial_take_profit_enabled"] = bool(overrides["partial_take_profit_enabled"])
    for key in (
        "require_5m_close_above_breakout",
        "require_5m_volume_increase",
        "require_vwap_or_ma20",
        "require_pullback_rebreak",
    ):
        if key in overrides:
            overrides[key] = bool(overrides[key])
    if "candidate_selection_mode" in overrides:
        overrides["candidate_selection_mode"] = _candidate_mode_from_float(
            overrides["candidate_selection_mode"]
        )
    if "ranking_selection_mode" in overrides:
        overrides["ranking_selection_mode"] = _ranking_selection_mode_from_float(
            overrides["ranking_selection_mode"]
        )
    if "strategy_preset" in overrides:
        overrides["strategy_preset"] = _strategy_preset_from_float(overrides["strategy_preset"])
    if "partial_fill_policy" in overrides:
        overrides["partial_fill_policy"] = _partial_fill_policy_from_float(
            overrides["partial_fill_policy"]
        )
    for key in (
        "overheat_limit_condition_mode",
        "breakout_close_condition_mode",
        "volume_increase_condition_mode",
        "vwap_ma20_condition_mode",
        "pullback_rebreak_condition_mode",
    ):
        if key in overrides:
            overrides[key] = _condition_mode_from_float(overrides[key])
    if "vwap_ma20_condition_type" in overrides:
        overrides["vwap_ma20_condition_type"] = _vwap_ma20_type_from_float(
            overrides["vwap_ma20_condition_type"]
        )
    for key in (
        "stop_loss_cooldown_minutes",
        "max_consecutive_stop_loss_count",
        "gainer_ranking_limit",
        "turnover_ranking_limit",
        "initial_ranked_evaluation_limit",
        "ranked_evaluation_batch_size",
        "max_ranked_evaluation_candidates",
        "target_filtered_candidates",
        "max_order_retry_count",
        "order_retry_delay_seconds",
        "unfilled_cancel_after_seconds",
    ):
        if key in overrides:
            overrides[key] = int(overrides[key])
    return _normalize_candidate_mode(replace(settings, **overrides))


def _normalize_candidate_mode(settings: TradingSettings) -> TradingSettings:
    if settings.candidate_selection_mode != CANDIDATE_MODE_REFRESH:
        return settings
    if not settings.refresh_intraday_candidates:
        return replace(settings, candidate_selection_mode=CANDIDATE_MODE_FIXED)
    return settings


def _validate_candidate_evaluation_settings(settings: TradingSettings) -> TradingSettings:
    _validate_ranking_selection_mode(settings.ranking_selection_mode)
    for field, label in (
        ("max_selected_candidates", "MAX_SELECTED_CANDIDATES"),
        ("initial_ranked_evaluation_limit", "INITIAL_RANKED_EVALUATION_LIMIT"),
        ("ranked_evaluation_batch_size", "RANKED_EVALUATION_BATCH_SIZE"),
        ("max_ranked_evaluation_candidates", "MAX_RANKED_EVALUATION_CANDIDATES"),
        ("target_filtered_candidates", "TARGET_FILTERED_CANDIDATES"),
    ):
        _validate_positive_count(getattr(settings, field), label, 10000)
    if settings.candidate_eval_timeout_seconds <= 0:
        raise ValueError("CANDIDATE_EVAL_TIMEOUT_SECONDS는 0보다 크게 입력해 주세요.")
    if settings.initial_ranked_evaluation_limit > settings.max_ranked_evaluation_candidates:
        raise ValueError(
            "INITIAL_RANKED_EVALUATION_LIMIT는 "
            "MAX_RANKED_EVALUATION_CANDIDATES 이하로 입력해 주세요."
        )
    return settings


def _runtime_settings_from_settings(settings: TradingSettings) -> dict[str, float]:
    return {
        "max_position_loss": settings.max_position_loss,
        "take_profit_rate": settings.take_profit_rate,
        "strategy_preset": _strategy_preset_to_float(settings.strategy_preset),
        "allow_relaxed_candidate_filter": (
            1.0 if settings.allow_relaxed_candidate_filter else 0.0
        ),
        "relax_opening_change_only": 1.0 if settings.relax_opening_change_only else 0.0,
        "enable_pyramiding": 1.0 if settings.enable_pyramiding else 0.0,
        "partial_take_profit_enabled": 1.0 if settings.partial_take_profit_enabled else 0.0,
        "trailing_stop_activation_rate": settings.trailing_stop_activation_rate,
        "min_total_score": settings.min_total_score,
        "min_price_usd": settings.min_price_usd,
        "max_price_usd": settings.max_price_usd,
        "gainer_ranking_limit": float(settings.gainer_ranking_limit),
        "turnover_ranking_limit": float(settings.turnover_ranking_limit),
        "ranking_selection_mode": _ranking_selection_mode_to_float(
            settings.ranking_selection_mode
        ),
        "initial_ranked_evaluation_limit": float(settings.initial_ranked_evaluation_limit),
        "ranked_evaluation_batch_size": float(settings.ranked_evaluation_batch_size),
        "max_ranked_evaluation_candidates": float(settings.max_ranked_evaluation_candidates),
        "target_filtered_candidates": float(settings.target_filtered_candidates),
        "candidate_eval_timeout_seconds": settings.candidate_eval_timeout_seconds,
        "min_opening_price_change": settings.min_opening_price_change,
        "min_volume_ratio": settings.min_volume_ratio,
        "max_opening_gap": settings.max_opening_gap,
        "refresh_intraday_candidates": 1.0 if settings.refresh_intraday_candidates else 0.0,
        "candidate_selection_mode": _candidate_mode_to_float(settings.candidate_selection_mode),
        "max_entry_price_change": settings.max_entry_price_change,
        "overheat_limit_condition_mode": _condition_mode_to_float(
            settings.overheat_limit_condition_mode
        ),
        "breakout_hold_minutes": settings.breakout_hold_minutes,
        "require_5m_close_above_breakout": (
            1.0 if settings.require_5m_close_above_breakout else 0.0
        ),
        "breakout_close_condition_mode": _condition_mode_to_float(
            settings.breakout_close_condition_mode
        ),
        "require_5m_volume_increase": 1.0 if settings.require_5m_volume_increase else 0.0,
        "min_5m_volume_increase_percent": settings.min_5m_volume_increase_percent,
        "volume_increase_condition_mode": _condition_mode_to_float(
            settings.volume_increase_condition_mode
        ),
        "require_vwap_or_ma20": 1.0 if settings.require_vwap_or_ma20 else 0.0,
        "vwap_ma20_condition_mode": _condition_mode_to_float(
            settings.vwap_ma20_condition_mode
        ),
        "vwap_ma20_condition_type": _vwap_ma20_type_to_float(
            settings.vwap_ma20_condition_type
        ),
        "require_pullback_rebreak": 1.0 if settings.require_pullback_rebreak else 0.0,
        "pullback_rebreak_condition_mode": _condition_mode_to_float(
            settings.pullback_rebreak_condition_mode
        ),
        "stop_loss_cooldown_minutes": float(settings.stop_loss_cooldown_minutes),
        "max_consecutive_stop_loss_count": float(settings.max_consecutive_stop_loss_count),
        "max_bid_ask_spread_rate": settings.max_bid_ask_spread_rate,
        "max_expected_fill_price_gap_rate": settings.max_expected_fill_price_gap_rate,
        "max_order_retry_count": float(settings.max_order_retry_count),
        "order_retry_delay_seconds": float(settings.order_retry_delay_seconds),
        "partial_fill_policy": _partial_fill_policy_to_float(settings.partial_fill_policy),
        "unfilled_cancel_after_seconds": float(settings.unfilled_cancel_after_seconds),
    }


def _complete_runtime_settings(
    settings: TradingSettings,
    overrides: dict[str, float],
    path: Path = RUNTIME_SETTINGS_PATH,
) -> dict[str, float]:
    # 화면에서 관리하는 매매 설정은 런타임 저장소(DB 또는 설정 파일)를 기준으로 운용합니다.
    # 저장소가 비어 있거나 일부 키가 빠진 경우에만 현재 안전값으로 한 번 채워 넣습니다.
    complete = _runtime_settings_from_settings(settings)
    complete.update(overrides)
    missing_keys = set(RUNTIME_SETTING_KEYS) - set(overrides)
    if missing_keys:
        if _runtime_settings_db_configured():
            _try_save_runtime_settings_to_db(complete)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(complete, ensure_ascii=False, indent=2), encoding="utf-8")
    return complete


def _read_runtime_settings(path: Path = RUNTIME_SETTINGS_PATH) -> dict[str, float]:
    values = _read_runtime_settings_file(path)
    values.update(_read_runtime_settings_from_db())
    return values


def _read_runtime_settings_file(path: Path = RUNTIME_SETTINGS_PATH) -> dict[str, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    values: dict[str, float] = {}
    for key in RUNTIME_SETTING_KEYS:
        if key in payload:
            if key == "ranking_selection_mode" and isinstance(payload[key], str):
                values[key] = _ranking_selection_mode_to_float(payload[key])
            else:
                values[key] = float(payload[key])
    return values


def _read_runtime_settings_from_db() -> dict[str, float]:
    try:
        from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
        from trading_bot.runtime_settings_store import RuntimeSettingsStore

        if not _mssql_env_configured() or not mssql_dsn_from_env():
            return {}
        return RuntimeSettingsStore(pyodbc_connect_factory()).read(RUNTIME_SETTING_KEYS)
    except Exception:
        return {}


def _save_runtime_settings_to_db(payload: dict[str, float]) -> bool:
    try:
        from trading_bot.database import mssql_dsn_from_env, pyodbc_connect_factory
        from trading_bot.runtime_settings_store import RuntimeSettingsStore

        if not _mssql_env_configured() or not mssql_dsn_from_env():
            return False
        RuntimeSettingsStore(pyodbc_connect_factory()).save(payload)
        return True
    except Exception as exc:
        raise RuntimeError(f"설정 DB 저장 실패: {exc}") from exc


def _try_save_runtime_settings_to_db(payload: dict[str, float]) -> bool:
    try:
        return _save_runtime_settings_to_db(payload)
    except RuntimeError:
        return False


def _runtime_settings_db_configured() -> bool:
    try:
        from trading_bot.database import mssql_dsn_from_env

        return _mssql_env_configured() and bool(mssql_dsn_from_env())
    except Exception:
        return False


def _mssql_env_configured() -> bool:
    if os.getenv("MSSQL_DSN", "").strip():
        return True
    return all(
        os.getenv(name, "").strip()
        for name in ("MSSQL_HOST", "MSSQL_DATABASE", "MSSQL_USERNAME", "MSSQL_PASSWORD")
    )


def _validate_percent(value: float, label: str) -> float:
    percent = float(value)
    if percent <= 0 or percent > 50:
        raise ValueError(f"{label}은 0보다 크고 50 이하로 입력해 주세요.")
    return percent


def _validate_score(value: float, label: str) -> float:
    score = float(value)
    if score < 0 or score > 100:
        raise ValueError(f"{label}는 0점 이상 100점 이하로 입력해 주세요.")
    return score


def _validate_candidate_mode(value: str) -> str:
    mode = str(value).strip().lower()
    if mode not in CANDIDATE_SELECTION_MODES:
        raise ValueError("후보선정방식은 refresh, fixed, hybrid 중 하나여야 합니다.")
    return mode


def _validate_ranking_selection_mode(value: str) -> str:
    mode = str(value).strip().lower()
    if mode not in RANKING_SELECTION_MODES:
        raise ValueError(
            "RANKING_SELECTION_MODE must be either 'intersection' or 'composite'"
        )
    return mode


def _candidate_mode_to_float(mode: str) -> float:
    return {
        CANDIDATE_MODE_REFRESH: 1.0,
        CANDIDATE_MODE_FIXED: 2.0,
        CANDIDATE_MODE_HYBRID: 3.0,
    }[_validate_candidate_mode(mode)]


def _ranking_selection_mode_to_float(mode: str) -> float:
    return {
        RANKING_SELECTION_INTERSECTION: 1.0,
        RANKING_SELECTION_COMPOSITE: 2.0,
    }[_validate_ranking_selection_mode(mode)]


def _ranking_selection_mode_from_float(value: float) -> str:
    if int(float(value)) == 2:
        return RANKING_SELECTION_COMPOSITE
    return RANKING_SELECTION_INTERSECTION


def _candidate_mode_from_float(value: float) -> str:
    code = int(float(value))
    if code == 2:
        return CANDIDATE_MODE_FIXED
    if code == 3:
        return CANDIDATE_MODE_HYBRID
    return CANDIDATE_MODE_REFRESH


def _validate_condition_mode(value: str) -> str:
    mode = str(value).strip().upper()
    if mode not in CONDITION_MODES:
        raise ValueError("조건 모드는 OFF, LOG_ONLY, SOFT_SCORE, HARD_FILTER 중 하나여야 합니다.")
    return mode


def _condition_mode_to_float(mode: str) -> float:
    return {
        CONDITION_MODE_OFF: 0.0,
        CONDITION_MODE_LOG_ONLY: 1.0,
        CONDITION_MODE_SOFT_SCORE: 2.0,
        CONDITION_MODE_HARD_FILTER: 3.0,
    }[_validate_condition_mode(mode)]


def _condition_mode_from_float(value: float) -> str:
    code = int(float(value))
    if code == 1:
        return CONDITION_MODE_LOG_ONLY
    if code == 2:
        return CONDITION_MODE_SOFT_SCORE
    if code == 3:
        return CONDITION_MODE_HARD_FILTER
    return CONDITION_MODE_OFF


def _validate_vwap_ma20_type(value: str) -> str:
    condition_type = str(value).strip().upper()
    if condition_type not in VWAP_MA20_TYPES:
        raise ValueError("VWAP/MA20 방식은 OR, AND, VWAP_ONLY, MA20_ONLY, OFF 중 하나여야 합니다.")
    return condition_type


def _vwap_ma20_type_to_float(condition_type: str) -> float:
    return {
        VWAP_MA20_OFF: 0.0,
        VWAP_MA20_OR: 1.0,
        VWAP_MA20_AND: 2.0,
        VWAP_MA20_VWAP_ONLY: 3.0,
        VWAP_MA20_MA20_ONLY: 4.0,
    }[_validate_vwap_ma20_type(condition_type)]


def _vwap_ma20_type_from_float(value: float) -> str:
    code = int(float(value))
    if code == 2:
        return VWAP_MA20_AND
    if code == 3:
        return VWAP_MA20_VWAP_ONLY
    if code == 4:
        return VWAP_MA20_MA20_ONLY
    if code == 0:
        return VWAP_MA20_OFF
    return VWAP_MA20_OR


def _validate_strategy_preset(value: str) -> str:
    preset = str(value).strip().lower()
    if preset not in STRATEGY_PRESETS:
        raise ValueError("전략 프리셋은 current 또는 conservative_intraday 중 하나여야 합니다.")
    return preset


def _strategy_preset_to_float(preset: str) -> float:
    validated = _validate_strategy_preset(preset)
    if validated == STRATEGY_PRESET_CONSERVATIVE_INTRADAY:
        return 2.0
    if validated == STRATEGY_PRESET_BALANCED_INTRADAY:
        return 3.0
    return 1.0


def _strategy_preset_from_float(value: float) -> str:
    code = int(float(value))
    if code == 2:
        return STRATEGY_PRESET_CONSERVATIVE_INTRADAY
    if code == 3:
        return STRATEGY_PRESET_BALANCED_INTRADAY
    return STRATEGY_PRESET_CURRENT


def _apply_strategy_preset(settings: TradingSettings) -> TradingSettings:
    if settings.strategy_preset == STRATEGY_PRESET_CONSERVATIVE_INTRADAY:
        return replace(
            settings,
            max_position_loss=-0.025,
            take_profit_rate=0.03,
            trailing_stop_activation_rate=0.02,
            trailing_stop_drop=0.015,
        )
    if settings.strategy_preset == STRATEGY_PRESET_BALANCED_INTRADAY:
        return replace(
            settings,
            max_position_loss=-0.035,
            take_profit_rate=0.04,
            trailing_stop_activation_rate=0.025,
            trailing_stop_drop=0.02,
        )
    return settings


def _validate_partial_fill_policy(value: str) -> str:
    policy = str(value).strip().upper()
    if policy not in PARTIAL_FILL_POLICIES:
        raise ValueError("부분 체결 정책은 KEEP_REMAINING 또는 CANCEL_REMAINING 중 하나여야 합니다.")
    return policy


def _partial_fill_policy_to_float(policy: str) -> float:
    return 2.0 if _validate_partial_fill_policy(policy) == PARTIAL_FILL_POLICY_CANCEL else 1.0


def _partial_fill_policy_from_float(value: float) -> str:
    return PARTIAL_FILL_POLICY_CANCEL if int(float(value)) == 2 else PARTIAL_FILL_POLICY_KEEP


def _validate_price_range(
    min_value: float | None,
    max_value: float | None,
) -> tuple[float, float]:
    if min_value is None or max_value is None:
        raise ValueError("최저 가격과 최고 가격을 모두 입력해 주세요.")
    min_price = float(min_value)
    max_price = float(max_value)
    if min_price <= 0 or max_price <= 0:
        raise ValueError("가격 조건은 0보다 크게 입력해 주세요.")
    if min_price < MIN_PRICE_USD_FLOOR:
        raise ValueError(f"최저 가격은 {MIN_PRICE_USD_FLOOR:g} 이상으로 입력해 주세요.")
    if min_price >= max_price:
        raise ValueError("최저 가격은 최고 가격보다 작아야 합니다.")
    return min_price, max_price


def _validate_percent_range(value: float, label: str) -> float:
    percent = float(value)
    if percent < 0 or percent > 500:
        raise ValueError(f"{label}은 0 이상 500 이하로 입력해 주세요.")
    return percent


def _validate_volume_ratio(value: float, label: str) -> float:
    ratio = float(value)
    if ratio <= 0 or ratio > 100:
        raise ValueError(f"{label}은 0보다 크고 100 이하로 입력해 주세요.")
    return ratio


def _validate_minutes(value: float, label: str) -> float:
    minutes = float(value)
    if minutes < 0 or minutes > 60:
        raise ValueError(f"{label}은 0 이상 60 이하로 입력해 주세요.")
    return minutes


def _validate_count(value: float, label: str, max_value: int) -> int:
    count = int(float(value))
    if count < 0 or count > max_value:
        raise ValueError(f"{label}은 0 이상 {max_value} 이하로 입력해 주세요.")
    return count


def _validate_positive_count(value: float, label: str, max_value: int) -> int:
    count = int(float(value))
    if count <= 0 or count > max_value:
        raise ValueError(f"{label}는 1 이상 {max_value} 이하로 입력해 주세요.")
    return count
