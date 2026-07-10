from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from trading_bot.config import (
    CONDITION_MODE_HARD_FILTER,
    CONDITION_MODE_OFF,
    CONDITION_MODE_SOFT_SCORE,
    VWAP_MA20_AND,
    VWAP_MA20_MA20_ONLY,
    VWAP_MA20_OFF,
    VWAP_MA20_VWAP_ONLY,
    TradingSettings,
)
from trading_bot.models import AccountState, BreakoutInput, BotLog, BuyIntent, CandidateEvaluation, ScoreRecord
from trading_bot.risk import MARKET_BELOW_MA20_BYPASSED, position_entry_gate
from trading_bot.scoring import position_fraction_for_score
from trading_bot.strategy import breakout_triggered
from trading_bot.trading_event_logger import (
    record_candidate_evaluation_event,
    record_order_intent_created,
)

ENTRY_REASON_MAX_LENGTH = 80


def plan_buy_intents(
    selected_scores: Iterable[ScoreRecord],
    breakout_inputs: Mapping[str, BreakoutInput | tuple[float, float, float, float]],
    account: AccountState,
    settings: TradingSettings,
    repository: object | None = None,
    trade_date: date | None = None,
    source: str = "entry_planner",
    source_by_ticker: Mapping[str, str] | None = None,
    run_id: str | None = None,
    entry_reason_tags: tuple[str, ...] = (),
) -> list[BuyIntent]:
    intents: list[BuyIntent] = []
    invested = account.invested_usd
    cash = account.cash_usd
    for score in selected_scores:
        evaluation_source = (
            source_by_ticker.get(score.ticker, source) if source_by_ticker else source
        )
        evaluated_at = datetime.now(UTC)
        breakout = _breakout_input(breakout_inputs[score.ticker])
        threshold = _breakout_threshold(breakout, settings)
        if not breakout_triggered(
            breakout.last_price_usd,
            breakout.open_price_usd,
            breakout.previous_high_usd,
            breakout.previous_low_usd,
            settings.breakout_k,
        ):
            _safe_save_candidate_evaluation(
                repository,
                _candidate_evaluation(
                    score,
                    breakout,
                    threshold,
                    settings,
                    None,
                    score.total_score,
                    False,
                    "BREAKOUT_NOT_TRIGGERED",
                    ("BREAKOUT_NOT_TRIGGERED",),
                    trade_date,
                    evaluation_source,
                    run_id,
                    evaluated_at,
                    entry_reason_tags,
                ),
            )
            continue
        evaluation = _entry_timing_evaluation(breakout, threshold, settings)
        final_score = max(0.0, score.total_score + evaluation.score_adjustment)
        if not evaluation.allowed:
            _safe_save_candidate_evaluation(
                repository,
                _candidate_evaluation(
                    score,
                    breakout,
                    threshold,
                    settings,
                    evaluation,
                    final_score,
                    False,
                    _first_reason(evaluation.failed_hard_reasons),
                    evaluation.failed_hard_reasons,
                    trade_date,
                    evaluation_source,
                    run_id,
                    evaluated_at,
                    entry_reason_tags,
                ),
            )
            continue
        final_score_pass = final_score >= settings.min_total_score
        if not final_score_pass:
            _safe_save_candidate_evaluation(
                repository,
                _candidate_evaluation(
                    score,
                    breakout,
                    threshold,
                    settings,
                    evaluation,
                    final_score,
                    False,
                    "FINAL_SCORE_BELOW_THRESHOLD",
                    ("FINAL_SCORE_BELOW_THRESHOLD",),
                    trade_date,
                    evaluation_source,
                    run_id,
                    evaluated_at,
                    entry_reason_tags,
                ),
            )
            continue

        fraction = min(
            position_fraction_for_score(final_score, settings),
            settings.max_position_exposure,
        )
        order_value = min(cash, account.equity_usd * fraction)
        decision = position_entry_gate(
            _with_invested(account, invested),
            order_value,
            settings,
        )
        quantity = int(order_value // breakout.last_price_usd)
        if not decision.allowed or quantity < 1:
            reason = decision.reason or "ORDER_NOT_SUBMITTED"
            _safe_save_candidate_evaluation(
                repository,
                _candidate_evaluation(
                    score,
                    breakout,
                    threshold,
                    settings,
                    evaluation,
                    final_score,
                    False,
                    reason,
                    (reason,),
                    trade_date,
                    evaluation_source,
                    run_id,
                    evaluated_at,
                    entry_reason_tags,
                ),
            )
            continue

        filled_value = quantity * breakout.last_price_usd
        reason, detail = _entry_reason(
            score,
            final_score,
            evaluation,
            manual_watchlist=_is_manual_source(evaluation_source),
            extra_tags=entry_reason_tags,
        )
        _safe_save_candidate_evaluation(
            repository,
            _candidate_evaluation(
                score,
                breakout,
                threshold,
                settings,
                evaluation,
                final_score,
                True,
                "BUY_ALLOWED",
                (),
                trade_date,
                evaluation_source,
                run_id,
                evaluated_at,
                entry_reason_tags,
            ),
        )
        intent = BuyIntent(
            ticker=score.ticker,
            quantity=quantity,
            limit_price_usd=breakout.last_price_usd,
            order_value_usd=filled_value,
            allocation_fraction=fraction,
            entry_reason=reason,
            entry_reason_detail=detail,
            run_id=run_id,
            source=evaluation_source,
        )
        intents.append(intent)
        record_order_intent_created(
            repository,
            intent,
            trade_date=trade_date,
            run_id=run_id,
            source=evaluation_source,
            fallback_bot_log=False,
        )
        invested += filled_value
        cash -= filled_value
    return intents


def _breakout_input(value: BreakoutInput | tuple[float, float, float, float]) -> BreakoutInput:
    if isinstance(value, BreakoutInput):
        return value
    last, open_price, previous_high, previous_low = value
    return BreakoutInput(last, open_price, previous_high, previous_low)


def _breakout_threshold(breakout: BreakoutInput, settings: TradingSettings) -> float:
    return breakout.open_price_usd + (
        breakout.previous_high_usd - breakout.previous_low_usd
    ) * settings.breakout_k


@dataclass(frozen=True)
class EntryTimingEvaluation:
    allowed: bool
    score_adjustment: float = 0.0
    failed_soft_reasons: tuple[str, ...] = ()
    failed_log_reasons: tuple[str, ...] = ()
    failed_hard_reasons: tuple[str, ...] = ()
    condition_results: Mapping[str, bool | None] | None = None


def _entry_timing_evaluation(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> EntryTimingEvaluation:
    hard: list[str] = []
    soft: list[str] = []
    logs: list[str] = []

    overheat_pass = _price_change_from_open(breakout) <= settings.max_entry_price_change
    _apply_condition(
        overheat_pass,
        settings.overheat_limit_condition_mode,
        "OVERHEAT_LIMIT_EXCEEDED",
        hard,
        soft,
        logs,
    )
    hold_pass = not (
        settings.breakout_hold_minutes > 0
        and breakout.minutes_above_breakout > 0
        and breakout.minutes_above_breakout < settings.breakout_hold_minutes
    )
    close_pass = not (
        breakout.recent_5m_close_usd is not None and breakout.recent_5m_close_usd < threshold
    )
    _apply_condition(
        hold_pass and close_pass,
        _condition_mode(settings.require_5m_close_above_breakout, settings.breakout_close_condition_mode),
        "BREAKOUT_CLOSE_FAILED",
        hard,
        soft,
        logs,
    )
    volume_increase_percent = _volume_increase_percent(breakout)
    volume_data_available = volume_increase_percent is not None
    volume_pass = (
        None
        if not volume_data_available
        else volume_increase_percent >= settings.min_5m_volume_increase_percent
    )
    volume_mode = _condition_mode(
        settings.require_5m_volume_increase,
        settings.volume_increase_condition_mode,
    )
    if volume_data_available:
        _apply_condition(
            bool(volume_pass),
            volume_mode,
            "VOLUME_INCREASE_FAILED",
            hard,
            soft,
            logs,
        )
    elif volume_mode == CONDITION_MODE_HARD_FILTER:
        hard.append("VOLUME_DATA_UNAVAILABLE")
    vwap_pass = _vwap_pass(breakout)
    ma20_pass = _ma20_pass(breakout)
    vwap_ma20_status = _vwap_ma20_evaluation_status(breakout, settings)
    vwap_ma20_pass = None
    if vwap_ma20_status == "PASS":
        vwap_ma20_pass = True
    elif vwap_ma20_status == "FAIL":
        vwap_ma20_pass = False
    _apply_condition(
        vwap_ma20_status != "FAIL",
        _condition_mode(settings.require_vwap_or_ma20, settings.vwap_ma20_condition_mode),
        "VWAP_MA20_FAILED",
        hard,
        soft,
        logs,
    )
    pullback_pass = not (
        breakout.pulled_back_after_breakout is not None
        and not breakout.pulled_back_after_breakout
    )
    _apply_condition(
        pullback_pass,
        _condition_mode(settings.require_pullback_rebreak, settings.pullback_rebreak_condition_mode),
        "PULLBACK_REBREAK_FAILED",
        hard,
        soft,
        logs,
    )
    return EntryTimingEvaluation(
        allowed=not hard,
        score_adjustment=-5.0 * len(soft),
        failed_soft_reasons=tuple(soft),
        failed_log_reasons=tuple(logs),
        failed_hard_reasons=tuple(hard),
        condition_results={
            "overheat_pass": overheat_pass,
            "breakout_close_pass": hold_pass and close_pass,
            "volume_increase_pass": volume_pass,
            "volume_condition_result": (
                "UNKNOWN" if volume_pass is None else "PASS" if volume_pass else "FAIL"
            ),
            "volume_data_available": volume_data_available,
            "volume_data_missing_reason": (
                breakout.volume_data_missing_reason or _volume_missing_reason(breakout)
                if not volume_data_available
                else None
            ),
            "data_quality_warning": (
                "VOLUME_DATA_UNAVAILABLE" if not volume_data_available else None
            ),
            "recent_5m_volume": breakout.current_5m_volume,
            "previous_5m_volume": breakout.previous_5m_average_volume,
            "volume_increase_percent": volume_increase_percent,
            "min5mVolumeIncreasePercent": settings.min_5m_volume_increase_percent,
            "volume_increase_insufficient": bool(
                volume_data_available and volume_pass is False
            ),
            "current_price": breakout.last_price_usd,
            "vwap_usd": breakout.vwap_usd,
            "intraday_ma20_usd": breakout.intraday_ma20_usd,
            "vwap_data_available": _has_vwap_data(breakout),
            "intraday_ma20_data_available": _has_ma20_data(breakout),
            "vwap_ma20_data_available": _has_vwap_ma20_data_for_type(breakout, settings),
            "vwap_ma20_evaluation_status": vwap_ma20_status,
            "vwap_pass": vwap_pass,
            "ma20_pass": ma20_pass,
            "vwap_ma20_pass": vwap_ma20_pass,
            "vwapMa20ConditionType": settings.vwap_ma20_condition_type,
            "vwapMa20ConditionMode": settings.vwap_ma20_condition_mode,
            "vwap_ma20_compare_operator": ">=",
            "ma20_source": None,
            "ma20_interval": None,
            "ma20_period": 20,
            "ma20_candle_count": None,
            "ma20_insufficient": not _has_ma20_data(breakout),
            "pullback_rebreak_pass": pullback_pass,
        },
    )


def _entry_timing_allowed(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> bool:
    return _entry_timing_evaluation(breakout, threshold, settings).allowed


def _condition_mode(enabled: bool, mode: str) -> str:
    if not enabled:
        return CONDITION_MODE_OFF
    return mode


def _apply_condition(
    passed: bool,
    mode: str,
    reason: str,
    hard: list[str],
    soft: list[str],
    logs: list[str],
) -> None:
    if passed or mode == CONDITION_MODE_OFF:
        return
    if mode == CONDITION_MODE_HARD_FILTER:
        hard.append(reason)
    elif mode == CONDITION_MODE_SOFT_SCORE:
        soft.append(reason)
    else:
        logs.append(reason)


def _price_change_from_open(breakout: BreakoutInput) -> float:
    if breakout.open_price_usd <= 0:
        return 0.0
    return (breakout.last_price_usd - breakout.open_price_usd) / breakout.open_price_usd


def _entry_price_vs_breakout(entry_price: float, threshold: float) -> float | None:
    if threshold <= 0:
        return None
    return entry_price / threshold - 1.0


def _volume_increase_percent(breakout: BreakoutInput) -> float | None:
    if (
        breakout.current_5m_volume is None
        or breakout.previous_5m_average_volume is None
        or breakout.previous_5m_average_volume <= 0
    ):
        return None
    return (
        (breakout.current_5m_volume - breakout.previous_5m_average_volume)
        / breakout.previous_5m_average_volume
    ) * 100


def _volume_missing_reason(breakout: BreakoutInput) -> str:
    if breakout.current_5m_volume is None:
        return "CURRENT_5M_VOLUME_NULL"
    if breakout.current_5m_volume < 0:
        return "INVALID_VOLUME_VALUE"
    if breakout.previous_5m_average_volume is None:
        return "PREVIOUS_VOLUME_HISTORY_EMPTY"
    if breakout.previous_5m_average_volume <= 0:
        return "INVALID_VOLUME_VALUE"
    return "VOLUME_DATA_UNAVAILABLE"


def _above_vwap_or_ma20(breakout: BreakoutInput) -> bool:
    refs = [
        value
        for value in (breakout.vwap_usd, breakout.intraday_ma20_usd)
        if value is not None and value > 0
    ]
    return bool(refs) and any(breakout.last_price_usd >= value for value in refs)


def _has_vwap_or_ma20_data(breakout: BreakoutInput) -> bool:
    return _has_vwap_data(breakout) or _has_ma20_data(breakout)


def _has_vwap_data(breakout: BreakoutInput) -> bool:
    return breakout.vwap_usd is not None and breakout.vwap_usd > 0


def _has_ma20_data(breakout: BreakoutInput) -> bool:
    return breakout.intraday_ma20_usd is not None and breakout.intraday_ma20_usd > 0


def _vwap_pass(breakout: BreakoutInput) -> bool | None:
    if not _has_vwap_data(breakout):
        return None
    return breakout.last_price_usd >= breakout.vwap_usd


def _ma20_pass(breakout: BreakoutInput) -> bool | None:
    if not _has_ma20_data(breakout):
        return None
    return breakout.last_price_usd >= breakout.intraday_ma20_usd


def _above_vwap_ma20_by_type(breakout: BreakoutInput, settings: TradingSettings) -> bool:
    if settings.vwap_ma20_condition_type == VWAP_MA20_OFF:
        return True
    vwap_pass = bool(_vwap_pass(breakout))
    ma20_pass = bool(_ma20_pass(breakout))
    if settings.vwap_ma20_condition_type == VWAP_MA20_AND:
        return vwap_pass and ma20_pass
    if settings.vwap_ma20_condition_type == VWAP_MA20_VWAP_ONLY:
        return vwap_pass
    if settings.vwap_ma20_condition_type == VWAP_MA20_MA20_ONLY:
        return ma20_pass
    return vwap_pass or ma20_pass


def _has_vwap_ma20_data_for_type(breakout: BreakoutInput, settings: TradingSettings) -> bool:
    if settings.vwap_ma20_condition_type == VWAP_MA20_OFF:
        return False
    if settings.vwap_ma20_condition_type == VWAP_MA20_AND:
        return _has_vwap_data(breakout) and _has_ma20_data(breakout)
    if settings.vwap_ma20_condition_type == VWAP_MA20_VWAP_ONLY:
        return _has_vwap_data(breakout)
    if settings.vwap_ma20_condition_type == VWAP_MA20_MA20_ONLY:
        return _has_ma20_data(breakout)
    return _has_vwap_or_ma20_data(breakout)


def _vwap_ma20_evaluation_status(breakout: BreakoutInput, settings: TradingSettings) -> str:
    if not settings.require_vwap_or_ma20 or settings.vwap_ma20_condition_type == VWAP_MA20_OFF:
        return "DISABLED"
    if not _has_vwap_ma20_data_for_type(breakout, settings):
        return "SKIPPED_NO_DATA"
    return "PASS" if _above_vwap_ma20_by_type(breakout, settings) else "FAIL"


def _entry_reason(
    score: ScoreRecord,
    final_score: float,
    evaluation: EntryTimingEvaluation,
    *,
    manual_watchlist: bool = False,
    extra_tags: tuple[str, ...] = (),
) -> tuple[str, str]:
    reasons = ["OPENING_BREAKOUT"]
    if manual_watchlist:
        reasons.insert(0, "MANUAL_WATCHLIST")
    if score.news_score >= 60:
        reasons.append("NEWS_POSITIVE")
    if score.chart_score >= 60:
        reasons.append("CHART_POSITIVE")
    detail_tags = []
    for tag in extra_tags:
        if not tag or tag in reasons:
            continue
        detail_tags.append(tag)
        candidate_reasons = [*reasons, tag]
        if len("+".join(candidate_reasons)) <= ENTRY_REASON_MAX_LENGTH:
            reasons.append(tag)
    detail = (
        f"총점 {score.total_score:.1f}, "
        f"final {final_score:.1f}, "
        f"뉴스 {score.news_score:.1f}, 차트 {score.chart_score:.1f}"
    )
    if evaluation.failed_soft_reasons:
        detail += f", soft {','.join(evaluation.failed_soft_reasons)}"
    if evaluation.failed_log_reasons:
        detail += f", log {','.join(evaluation.failed_log_reasons)}"
    if detail_tags:
        detail += f", tags {','.join(detail_tags)}"
    return "+".join(reasons), detail


def _is_manual_source(source: str | None) -> bool:
    return source in {"manual_buy_list", "both"}


def _with_invested(account: AccountState, invested_usd: float) -> AccountState:
    return AccountState(
        cash_usd=account.cash_usd,
        equity_usd=account.equity_usd,
        invested_usd=invested_usd,
        open_positions=account.open_positions,
        daily_profit_rate=account.daily_profit_rate,
    )


def _candidate_evaluation(
    score: ScoreRecord,
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
    evaluation: EntryTimingEvaluation | None,
    final_score: float,
    buy_allowed: bool,
    buy_block_reason: str | None,
    buy_block_reasons: tuple[str, ...],
    trade_date: date | None,
    source: str,
    run_id: str | None,
    evaluated_at: datetime,
    entry_reason_tags: tuple[str, ...] = (),
) -> CandidateEvaluation:
    condition_results = dict(evaluation.condition_results or {}) if evaluation else {}
    hard_reasons = tuple(evaluation.failed_hard_reasons if evaluation else ())
    soft_reasons = tuple(evaluation.failed_soft_reasons if evaluation else ())
    final_score_pass = final_score >= settings.min_total_score
    reasons = tuple(reason for reason in buy_block_reasons if reason)
    entry_price_vs_breakout = _entry_price_vs_breakout(breakout.last_price_usd, threshold)
    manual_candidate = _is_manual_source(source)
    market_bypass_reason = (
        MARKET_BELOW_MA20_BYPASSED
        if MARKET_BELOW_MA20_BYPASSED in entry_reason_tags
        else None
    )
    analysis_context = {
        "candidate_source": source,
        "ranking_selection_mode": settings.ranking_selection_mode,
        "manual_candidate": manual_candidate,
        "opening_price_change": _price_change_from_open(breakout),
        "opening_volume_ratio": None,
        "opening_gap": None,
        "selection_score": score.total_score,
        "chart_score": score.chart_score,
        "news_score": score.news_score,
        "total_score": score.total_score,
        "final_score": final_score,
        "breakout_threshold": threshold,
        "entry_price_vs_breakout": entry_price_vs_breakout,
        "max_entry_price_change": settings.max_entry_price_change,
        "breakout_k": settings.breakout_k,
        "min_total_score": settings.min_total_score,
        "min_volume_ratio": settings.min_volume_ratio,
        "max_opening_gap": settings.max_opening_gap,
        "min_opening_price_change": settings.min_opening_price_change,
        "bid_ask_spread_rate": None,
        "expected_fill_price_gap_rate": None,
        "order_protection_checked": False,
        "order_protection_source": "not_checked_at_entry_planner",
        "market_nasdaq_price": None,
        "market_nasdaq_ma20": None,
        "fx_change_rate": None,
        "minutes_since_market_open": None,
        "entry_time_timezone_assumption": "Asia/Seoul",
        "market_below_ma20_bypassed": market_bypass_reason is not None,
        "market_bypass_reason": market_bypass_reason,
        "analysis_group": "market_bypass_trades" if market_bypass_reason else "normal_trades",
        "entry_reason_tags": list(entry_reason_tags),
    }
    return CandidateEvaluation(
        run_id=run_id,
        evaluation_time=evaluated_at,
        trading_date=trade_date,
        source=source,
        symbol=score.ticker,
        current_price=breakout.last_price_usd,
        selection_score=score.total_score,
        soft_score_adjustment=evaluation.score_adjustment if evaluation else 0.0,
        final_score=final_score,
        min_price=settings.min_price_usd,
        max_price=settings.max_price_usd,
        price_change_top=settings.gainer_ranking_limit,
        volume_top=settings.turnover_ranking_limit,
        min_selection_score=settings.min_total_score,
        min_opening_price_change_percent=settings.min_opening_price_change * 100,
        min_volume_ratio=settings.min_volume_ratio,
        max_opening_gap_percent=settings.max_opening_gap * 100,
        overheat_condition_mode=settings.overheat_limit_condition_mode,
        breakout_close_condition_mode=settings.breakout_close_condition_mode,
        volume_increase_condition_mode=settings.volume_increase_condition_mode,
        vwap_ma20_condition_mode=settings.vwap_ma20_condition_mode,
        vwap_ma20_condition_type=settings.vwap_ma20_condition_type,
        pullback_rebreak_condition_mode=settings.pullback_rebreak_condition_mode,
        overheat_pass=condition_results.get("overheat_pass"),
        breakout_close_pass=condition_results.get("breakout_close_pass"),
        volume_increase_pass=condition_results.get("volume_increase_pass"),
        vwap_pass=condition_results.get("vwap_pass"),
        ma20_pass=condition_results.get("ma20_pass"),
        vwap_ma20_pass=condition_results.get("vwap_ma20_pass"),
        pullback_rebreak_pass=condition_results.get("pullback_rebreak_pass"),
        final_score_pass=final_score_pass,
        buy_allowed=buy_allowed,
        buy_block_reason=buy_block_reason,
        buy_block_reasons=json.dumps(list(reasons), ensure_ascii=False),
        hard_filter_failed_count=len(hard_reasons),
        soft_condition_failed_count=len(soft_reasons),
        final_decision="BUY_ALLOWED" if buy_allowed else (buy_block_reason or "ORDER_NOT_SUBMITTED"),
        settings_snapshot_json=json.dumps(_settings_snapshot(settings), ensure_ascii=False),
        condition_result_json=json.dumps(
            {
                **condition_results,
                **analysis_context,
                "failed_hard_reasons": list(hard_reasons),
                "failed_soft_reasons": list(soft_reasons),
                "failed_log_reasons": list(evaluation.failed_log_reasons if evaluation else ()),
                "final_score_pass": final_score_pass,
            },
            ensure_ascii=False,
        ),
        raw_candidate_json=json.dumps(
            {
                "ticker": score.ticker,
                "last_price_usd": breakout.last_price_usd,
                "open_price_usd": breakout.open_price_usd,
                "previous_high_usd": breakout.previous_high_usd,
                "previous_low_usd": breakout.previous_low_usd,
                "candidate_source": source,
                "ranking_selection_mode": settings.ranking_selection_mode,
                "manual_candidate": manual_candidate,
                "breakout_threshold": threshold,
                "entry_price_vs_breakout": entry_price_vs_breakout,
                "opening_price_change": _price_change_from_open(breakout),
                "opening_volume_ratio": None,
                "opening_gap": None,
                "selection_score": score.total_score,
                "news_score": score.news_score,
                "chart_score": score.chart_score,
                "total_score": score.total_score,
                "final_score": final_score,
                "market_below_ma20_bypassed": market_bypass_reason is not None,
                "market_bypass_reason": market_bypass_reason,
                "analysis_group": "market_bypass_trades" if market_bypass_reason else "normal_trades",
                "entry_reason_tags": list(entry_reason_tags),
                "gain_rank": None,
                "turnover_rank": None,
                "trade_value_rank": None,
                "ranking_presence_count": None,
                "bid_ask_spread_rate": None,
                "expected_fill_price_gap_rate": None,
                "order_protection_checked": False,
                "entry_time_timezone_assumption": "Asia/Seoul",
            },
            ensure_ascii=False,
        ),
    )


def _settings_snapshot(settings: TradingSettings) -> dict[str, object]:
    return {
        "minPriceUsd": settings.min_price_usd,
        "maxPriceUsd": settings.max_price_usd,
        "gainerRankingLimit": settings.gainer_ranking_limit,
        "turnoverRankingLimit": settings.turnover_ranking_limit,
        "minTotalScore": settings.min_total_score,
        "minOpeningPriceChangePercent": settings.min_opening_price_change * 100,
        "minVolumeRatio": settings.min_volume_ratio,
        "maxOpeningGapPercent": settings.max_opening_gap * 100,
        "rankingSelectionMode": settings.ranking_selection_mode,
        "maxEntryPriceChange": settings.max_entry_price_change,
        "breakoutK": settings.breakout_k,
        "maxBidAskSpreadRate": settings.max_bid_ask_spread_rate,
        "maxExpectedFillPriceGapRate": settings.max_expected_fill_price_gap_rate,
        "min_total_score": settings.min_total_score,
        "min_volume_ratio": settings.min_volume_ratio,
        "max_opening_gap": settings.max_opening_gap,
        "min_opening_price_change": settings.min_opening_price_change,
        "max_entry_price_change": settings.max_entry_price_change,
        "breakout_k": settings.breakout_k,
        "ranking_selection_mode": settings.ranking_selection_mode,
        "overheatLimitConditionMode": settings.overheat_limit_condition_mode,
        "breakoutCloseConditionMode": settings.breakout_close_condition_mode,
        "volumeIncreaseConditionMode": settings.volume_increase_condition_mode,
        "vwapMa20ConditionMode": settings.vwap_ma20_condition_mode,
        "vwapMa20ConditionType": settings.vwap_ma20_condition_type,
        "pullbackRebreakConditionMode": settings.pullback_rebreak_condition_mode,
    }


def _safe_save_candidate_evaluation(
    repository: object | None,
    evaluation: CandidateEvaluation,
) -> None:
    if repository is None or not hasattr(repository, "save_candidate_evaluations"):
        return
    try:
        repository.save_candidate_evaluations([evaluation])
        record_candidate_evaluation_event(repository, evaluation, fallback_bot_log=False)
    except Exception as exc:
        if hasattr(repository, "save_log"):
            try:
                repository.save_log(
                    BotLog(
                        "ERROR",
                        "candidate_evaluation",
                        f"후보평가 저장 실패: 종목={evaluation.symbol} 오류={exc}",
                        symbol=evaluation.symbol,
                        reject_reason="CANDIDATE_EVALUATION_SAVE_FAILED",
                    )
                )
            except Exception:
                pass


def _first_reason(reasons: tuple[str, ...]) -> str:
    return reasons[0] if reasons else "ORDER_NOT_SUBMITTED"
