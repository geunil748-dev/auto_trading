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
from trading_bot.risk import position_entry_gate
from trading_bot.scoring import position_fraction_for_score
from trading_bot.strategy import breakout_triggered


def plan_buy_intents(
    selected_scores: Iterable[ScoreRecord],
    breakout_inputs: Mapping[str, BreakoutInput | tuple[float, float, float, float]],
    account: AccountState,
    settings: TradingSettings,
    repository: object | None = None,
    trade_date: date | None = None,
    source: str = "entry_planner",
    run_id: str | None = None,
) -> list[BuyIntent]:
    intents: list[BuyIntent] = []
    invested = account.invested_usd
    cash = account.cash_usd
    for score in selected_scores:
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
                    source,
                    run_id,
                    evaluated_at,
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
                    source,
                    run_id,
                    evaluated_at,
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
                    source,
                    run_id,
                    evaluated_at,
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
                    source,
                    run_id,
                    evaluated_at,
                ),
            )
            continue

        filled_value = quantity * breakout.last_price_usd
        reason, detail = _entry_reason(score, final_score, evaluation)
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
                source,
                run_id,
                evaluated_at,
            ),
        )
        intents.append(
            BuyIntent(
                ticker=score.ticker,
                quantity=quantity,
                limit_price_usd=breakout.last_price_usd,
                order_value_usd=filled_value,
                allocation_fraction=fraction,
                entry_reason=reason,
                entry_reason_detail=detail,
            )
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
    volume_increase_insufficient = volume_increase_percent is None
    volume_pass = (
        volume_increase_percent is not None
        and volume_increase_percent >= settings.min_5m_volume_increase_percent
    )
    _apply_condition(
        volume_pass,
        _condition_mode(settings.require_5m_volume_increase, settings.volume_increase_condition_mode),
        "VOLUME_INCREASE_FAILED",
        hard,
        soft,
        logs,
    )
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
            "recent_5m_volume": breakout.current_5m_volume,
            "previous_5m_volume": breakout.previous_5m_average_volume,
            "volume_increase_percent": volume_increase_percent,
            "min5mVolumeIncreasePercent": settings.min_5m_volume_increase_percent,
            "volume_increase_insufficient": volume_increase_insufficient,
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
) -> tuple[str, str]:
    reasons = ["OPENING_BREAKOUT"]
    if score.news_score >= 60:
        reasons.append("NEWS_POSITIVE")
    if score.chart_score >= 60:
        reasons.append("CHART_POSITIVE")
    detail = (
        f"총점 {score.total_score:.1f}, "
        f"final {final_score:.1f}, "
        f"뉴스 {score.news_score:.1f}, 차트 {score.chart_score:.1f}"
    )
    if evaluation.failed_soft_reasons:
        detail += f", soft {','.join(evaluation.failed_soft_reasons)}"
    if evaluation.failed_log_reasons:
        detail += f", log {','.join(evaluation.failed_log_reasons)}"
    return "+".join(reasons), detail


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
) -> CandidateEvaluation:
    condition_results = dict(evaluation.condition_results or {}) if evaluation else {}
    hard_reasons = tuple(evaluation.failed_hard_reasons if evaluation else ())
    soft_reasons = tuple(evaluation.failed_soft_reasons if evaluation else ())
    final_score_pass = final_score >= settings.min_total_score
    reasons = tuple(reason for reason in buy_block_reasons if reason)
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
                "breakout_threshold": threshold,
                "news_score": score.news_score,
                "chart_score": score.chart_score,
                "total_score": score.total_score,
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
        if hasattr(repository, "save_log"):
            condition_results = (
                json.loads(evaluation.condition_result_json)
                if evaluation.condition_result_json
                else {}
            )
            vwap_ma20_status = condition_results.get("vwap_ma20_evaluation_status", "")
            repository.save_log(
                BotLog(
                    "INFO",
                    "candidate_evaluation",
                    "candidate_evaluation_saved "
                    f"symbol={evaluation.symbol} "
                    f"final_score={evaluation.final_score} "
                    f"buy_allowed={evaluation.buy_allowed} "
                    f"order_submitted={evaluation.order_submitted} "
                    f"buy_block_reason={evaluation.buy_block_reason or ''} "
                    f"hard_filter_failed_count={evaluation.hard_filter_failed_count} "
                    f"soft_condition_failed_count={evaluation.soft_condition_failed_count} "
                    f"vwap_ma20_status={vwap_ma20_status}",
                    symbol=evaluation.symbol,
                    reject_reason=evaluation.buy_block_reason or "",
                    actual_value=evaluation.final_score,
                    threshold_value=evaluation.min_selection_score,
                )
            )
            if vwap_ma20_status == "SKIPPED_NO_DATA":
                repository.save_log(
                    BotLog(
                        "INFO",
                        "entry_planner",
                        "vwap_ma20_skipped_no_data "
                        f"symbol={evaluation.symbol} "
                        f"current_price={condition_results.get('current_price')} "
                        f"condition_type={condition_results.get('vwapMa20ConditionType')} "
                        f"condition_mode={condition_results.get('vwapMa20ConditionMode')} "
                        f"has_vwap={condition_results.get('vwap_data_available')} "
                        f"has_intraday_ma20={condition_results.get('intraday_ma20_data_available')} "
                        "reason=VWAP_MA20_DATA_MISSING",
                        symbol=evaluation.symbol,
                        reject_reason="VWAP_MA20_DATA_MISSING",
                        actual_value=evaluation.current_price,
                    )
                )
            elif vwap_ma20_status in {"PASS", "FAIL"}:
                repository.save_log(
                    BotLog(
                        "INFO",
                        "entry_planner",
                        "vwap_ma20_evaluated "
                        f"symbol={evaluation.symbol} "
                        f"current_price={condition_results.get('current_price')} "
                        f"vwap_usd={condition_results.get('vwap_usd')} "
                        f"intraday_ma20_usd={condition_results.get('intraday_ma20_usd')} "
                        f"condition_type={condition_results.get('vwapMa20ConditionType')} "
                        f"condition_mode={condition_results.get('vwapMa20ConditionMode')} "
                        f"vwap_pass={condition_results.get('vwap_pass')} "
                        f"ma20_pass={condition_results.get('ma20_pass')} "
                        f"vwap_ma20_pass={condition_results.get('vwap_ma20_pass')}",
                        symbol=evaluation.symbol,
                        reject_reason="VWAP_MA20_EVALUATED",
                        actual_value=evaluation.current_price,
                    )
                )
    except Exception as exc:
        if hasattr(repository, "save_log"):
            try:
                repository.save_log(
                    BotLog(
                        "ERROR",
                        "candidate_evaluation",
                        f"candidate_evaluation_save_failed symbol={evaluation.symbol} error={exc}",
                        symbol=evaluation.symbol,
                        reject_reason="CANDIDATE_EVALUATION_SAVE_FAILED",
                    )
                )
            except Exception:
                pass


def _first_reason(reasons: tuple[str, ...]) -> str:
    return reasons[0] if reasons else "ORDER_NOT_SUBMITTED"
