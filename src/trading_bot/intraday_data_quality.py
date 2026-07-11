from dataclasses import dataclass
from trading_bot.config import (
    CONDITION_MODE_OFF,
    VWAP_MA20_AND,
    VWAP_MA20_MA20_ONLY,
    VWAP_MA20_OFF,
    VWAP_MA20_OR,
    VWAP_MA20_VWAP_ONLY,
    TradingSettings,
    resolve_intraday_missing_data_policy,
)
from trading_bot.models import BreakoutInput, IntradayConditionState


@dataclass(frozen=True)
class IntradayDataQualityEvaluation:
    close_state: IntradayConditionState
    hold_state: IntradayConditionState
    volume_state: IntradayConditionState
    vwap_ma20_state: IntradayConditionState
    pullback_state: IntradayConditionState
    confirmation_mode: str
    hold_mode: str
    volume_mode: str
    vwap_ma20_mode: str
    pullback_mode: str
    policy: str
    missing_data_reasons: tuple[str, ...]
    available_features: tuple[str, ...]
    missing_features: tuple[str, ...]
    condition_results: dict[str, object]


def evaluate_intraday_data_quality(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> IntradayDataQualityEvaluation:
    policy = resolve_intraday_missing_data_policy(
        settings.intraday_missing_data_policy,
        app_mode=settings.app_mode,
        mock_trading=settings.mock_trading,
    )
    close_state = _optional_state(
        breakout.recent_5m_close_usd,
        breakout.recent_5m_close_usd is not None
        and breakout.recent_5m_close_usd >= threshold,
    )
    hold_state = _optional_state(
        breakout.minutes_above_breakout,
        breakout.minutes_above_breakout is not None
        and breakout.minutes_above_breakout >= settings.breakout_hold_minutes,
    )
    volume_increase_percent = _volume_increase_percent(breakout)
    volume_state = _optional_state(
        volume_increase_percent,
        volume_increase_percent is not None
        and volume_increase_percent >= settings.min_5m_volume_increase_percent,
    )
    vwap_pass = _vwap_pass(breakout)
    ma20_pass = _ma20_pass(breakout)
    vwap_ma20_state = _vwap_ma20_state(vwap_pass, ma20_pass, settings)
    pullback_state = _optional_state(
        breakout.pulled_back_after_breakout,
        breakout.pulled_back_after_breakout is True,
    )

    confirmation_mode = _condition_mode(
        settings.require_5m_close_above_breakout,
        settings.breakout_close_condition_mode,
    )
    hold_mode = confirmation_mode if settings.breakout_hold_minutes > 0 else CONDITION_MODE_OFF
    volume_mode = _condition_mode(
        settings.require_5m_volume_increase,
        settings.volume_increase_condition_mode,
    )
    vwap_enabled = (
        settings.require_vwap_or_ma20
        and settings.vwap_ma20_condition_type != VWAP_MA20_OFF
    )
    vwap_ma20_mode = _condition_mode(vwap_enabled, settings.vwap_ma20_condition_mode)
    pullback_mode = _condition_mode(
        settings.require_pullback_rebreak,
        settings.pullback_rebreak_condition_mode,
    )
    missing_data_reasons = _missing_reasons(
        (
            (close_state, confirmation_mode, "BREAKOUT_CLOSE_DATA_MISSING"),
            (hold_state, hold_mode, "BREAKOUT_HOLD_DATA_MISSING"),
            (volume_state, volume_mode, "VOLUME_INCREASE_DATA_MISSING"),
            (vwap_ma20_state, vwap_ma20_mode, "VWAP_MA20_DATA_MISSING"),
            (pullback_state, pullback_mode, "PULLBACK_REBREAK_DATA_MISSING"),
        )
    )
    feature_availability = _feature_availability(breakout)
    available_features = tuple(key for key, value in feature_availability.items() if value)
    missing_features = tuple(key for key, value in feature_availability.items() if not value)
    vwap_status = _vwap_legacy_status(vwap_ma20_state, settings)
    condition_results = {
        "recent_5m_close_usd": breakout.recent_5m_close_usd,
        "breakout_threshold": threshold,
        "minutes_above_breakout": breakout.minutes_above_breakout,
        "breakout_hold_minutes": settings.breakout_hold_minutes,
        "breakout_close_pass": _combined_enabled_pass(
            (close_state, confirmation_mode),
            (hold_state, hold_mode),
        ),
        "breakout_close_only_pass": _pass_value(close_state),
        "breakout_hold_pass": _pass_value(hold_state),
        "breakout_confirmation_pass": _combined_enabled_pass(
            (close_state, confirmation_mode),
            (hold_state, hold_mode),
        ),
        "volume_increase_pass": _pass_value(volume_state),
        "recent_5m_volume": breakout.current_5m_volume,
        "previous_5m_volume": breakout.previous_5m_average_volume,
        "volume_increase_percent": volume_increase_percent,
        "min5mVolumeIncreasePercent": settings.min_5m_volume_increase_percent,
        "volume_increase_insufficient": volume_state is IntradayConditionState.NO_DATA,
        "current_price": breakout.last_price_usd,
        "vwap_usd": breakout.vwap_usd,
        "intraday_ma20_usd": breakout.intraday_ma20_usd,
        "vwap_data_available": _has_vwap_data(breakout),
        "intraday_ma20_data_available": _has_ma20_data(breakout),
        "vwap_ma20_data_available": vwap_ma20_state is not IntradayConditionState.NO_DATA,
        "vwap_ma20_evaluation_status": vwap_status,
        "vwap_pass": vwap_pass,
        "ma20_pass": ma20_pass,
        "vwap_ma20_pass": (
            _pass_value(vwap_ma20_state)
            if vwap_ma20_mode != CONDITION_MODE_OFF
            else None
        ),
        "vwapMa20ConditionType": settings.vwap_ma20_condition_type,
        "vwapMa20ConditionMode": settings.vwap_ma20_condition_mode,
        "vwap_ma20_compare_operator": ">=",
        "ma20_source": None,
        "ma20_interval": None,
        "ma20_period": 20,
        "ma20_candle_count": None,
        "ma20_insufficient": not _has_ma20_data(breakout),
        "pulled_back_after_breakout": breakout.pulled_back_after_breakout,
        "pullback_rebreak_pass": _pass_value(pullback_state),
        "condition_states": {
            "BREAKOUT_CLOSE": _reported_state(close_state, confirmation_mode),
            "BREAKOUT_HOLD": _reported_state(hold_state, hold_mode),
            "VOLUME_INCREASE": _reported_state(volume_state, volume_mode),
            "VWAP_MA20": _reported_state(vwap_ma20_state, vwap_ma20_mode),
            "PULLBACK_REBREAK": _reported_state(pullback_state, pullback_mode),
        },
        "breakout_close_state": _reported_state(close_state, confirmation_mode),
        "breakout_hold_state": _reported_state(hold_state, hold_mode),
        "volume_increase_state": _reported_state(volume_state, volume_mode),
        "vwap_ma20_state": _reported_state(vwap_ma20_state, vwap_ma20_mode),
        "pullback_rebreak_state": _reported_state(pullback_state, pullback_mode),
        "data_quality_status": "INCOMPLETE" if missing_features else "COMPLETE",
        "required_data_quality_status": "INCOMPLETE" if missing_data_reasons else "COMPLETE",
        "missing_data_reasons": list(missing_data_reasons),
        "available_features": list(available_features),
        "missing_features": list(missing_features),
        "intraday_missing_data_policy": policy,
        "app_mode": settings.app_mode,
        "mock_trading": settings.mock_trading,
    }
    return IntradayDataQualityEvaluation(
        close_state=close_state,
        hold_state=hold_state,
        volume_state=volume_state,
        vwap_ma20_state=vwap_ma20_state,
        pullback_state=pullback_state,
        confirmation_mode=confirmation_mode,
        hold_mode=hold_mode,
        volume_mode=volume_mode,
        vwap_ma20_mode=vwap_ma20_mode,
        pullback_mode=pullback_mode,
        policy=policy,
        missing_data_reasons=missing_data_reasons,
        available_features=available_features,
        missing_features=missing_features,
        condition_results=condition_results,
    )


def missing_data_block_reason(reasons: tuple[str, ...]) -> str:
    return "REQUIRED_INTRADAY_DATA_MISSING" if len(reasons) > 1 else reasons[0]


def _condition_mode(enabled: bool, mode: str) -> str:
    return mode if enabled else CONDITION_MODE_OFF


def _optional_state(value: object | None, passed: bool) -> IntradayConditionState:
    if value is None:
        return IntradayConditionState.NO_DATA
    return IntradayConditionState.PASS if passed else IntradayConditionState.FAIL


def _vwap_ma20_state(
    vwap_pass: bool | None,
    ma20_pass: bool | None,
    settings: TradingSettings,
) -> IntradayConditionState:
    condition_type = settings.vwap_ma20_condition_type
    if condition_type == VWAP_MA20_OFF:
        return IntradayConditionState.NO_DATA
    if condition_type == VWAP_MA20_VWAP_ONLY:
        return _optional_state(vwap_pass, vwap_pass is True)
    if condition_type == VWAP_MA20_MA20_ONLY:
        return _optional_state(ma20_pass, ma20_pass is True)
    if condition_type == VWAP_MA20_AND:
        if vwap_pass is False or ma20_pass is False:
            return IntradayConditionState.FAIL
        if vwap_pass is True and ma20_pass is True:
            return IntradayConditionState.PASS
        return IntradayConditionState.NO_DATA
    if condition_type == VWAP_MA20_OR:
        if vwap_pass is True or ma20_pass is True:
            return IntradayConditionState.PASS
        if vwap_pass is False and ma20_pass is False:
            return IntradayConditionState.FAIL
    return IntradayConditionState.NO_DATA


def _missing_reasons(conditions) -> tuple[str, ...]:
    return tuple(
        reason
        for state, mode, reason in conditions
        if state is IntradayConditionState.NO_DATA and mode != CONDITION_MODE_OFF
    )


def _pass_value(state: IntradayConditionState) -> bool | None:
    if state is IntradayConditionState.NO_DATA:
        return None
    return state is IntradayConditionState.PASS


def _combined_enabled_pass(
    *conditions: tuple[IntradayConditionState, str],
) -> bool | None:
    states = tuple(state for state, mode in conditions if mode != CONDITION_MODE_OFF)
    if not states:
        return None
    if any(state is IntradayConditionState.FAIL for state in states):
        return False
    if any(state is IntradayConditionState.NO_DATA for state in states):
        return None
    return True


def _reported_state(state: IntradayConditionState, mode: str) -> str:
    return "DISABLED" if mode == CONDITION_MODE_OFF else state.value


def _volume_increase_percent(breakout: BreakoutInput) -> float | None:
    previous = breakout.previous_5m_average_volume
    current = breakout.current_5m_volume
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def _has_vwap_data(breakout: BreakoutInput) -> bool:
    return breakout.vwap_usd is not None and breakout.vwap_usd > 0


def _has_ma20_data(breakout: BreakoutInput) -> bool:
    return breakout.intraday_ma20_usd is not None and breakout.intraday_ma20_usd > 0


def _vwap_pass(breakout: BreakoutInput) -> bool | None:
    return breakout.last_price_usd >= breakout.vwap_usd if _has_vwap_data(breakout) else None


def _ma20_pass(breakout: BreakoutInput) -> bool | None:
    return breakout.last_price_usd >= breakout.intraday_ma20_usd if _has_ma20_data(breakout) else None


def _vwap_legacy_status(
    state: IntradayConditionState,
    settings: TradingSettings,
) -> str:
    if not settings.require_vwap_or_ma20 or settings.vwap_ma20_condition_type == VWAP_MA20_OFF:
        return "DISABLED"
    return "SKIPPED_NO_DATA" if state is IntradayConditionState.NO_DATA else state.value


def _feature_availability(breakout: BreakoutInput) -> dict[str, bool]:
    return {
        "recent_5m_close_usd": breakout.recent_5m_close_usd is not None,
        "minutes_above_breakout": breakout.minutes_above_breakout is not None,
        "current_5m_volume": breakout.current_5m_volume is not None,
        "previous_5m_average_volume": breakout.previous_5m_average_volume is not None
        and breakout.previous_5m_average_volume > 0,
        "vwap_usd": _has_vwap_data(breakout),
        "intraday_ma20_usd": _has_ma20_data(breakout),
        "pulled_back_after_breakout": breakout.pulled_back_after_breakout is not None,
    }
