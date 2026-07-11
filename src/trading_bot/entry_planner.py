from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime

from trading_bot.config import (
    CONDITION_MODE_HARD_FILTER,
    CONDITION_MODE_LOG_ONLY,
    CONDITION_MODE_OFF,
    CONDITION_MODE_SOFT_SCORE,
    INTRADAY_MISSING_DATA_POLICY_BLOCK,
    VWAP_MA20_AND,
    VWAP_MA20_MA20_ONLY,
    VWAP_MA20_OFF,
    VWAP_MA20_VWAP_ONLY,
    TradingSettings,
    resolve_intraday_missing_data_policy,
)
from trading_bot.intraday_data_quality import (
    evaluate_intraday_data_quality,
    missing_data_block_reason,
)
from trading_bot.models import (
    AccountState,
    BotLog,
    BreakoutInput,
    BuyIntent,
    CandidateEvaluation,
    IntradayConditionState,
    ScoreRecord,
)
from trading_bot.risk import MARKET_BELOW_MA20_BYPASSED, position_entry_gate
from trading_bot.scoring import position_fraction_for_score
from trading_bot.strategy import breakout_triggered
from trading_bot.trading_event_logger import record_candidate_evaluation_event

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
    missing_data_reasons: tuple[str, ...] = ()
    available_features: tuple[str, ...] = ()
    missing_features: tuple[str, ...] = ()
    intraday_missing_data_policy: str = ""
    condition_results: Mapping[str, object] | None = None


BUY_BLOCK_REASON_LABELS = {
    "BUY_ALLOWED": "매수 허용",
    "BREAKOUT_NOT_TRIGGERED": "돌파 미발생",
    "BREAKOUT_CLOSE_FAILED": "5분봉 종가 돌파 미충족",
    "BREAKOUT_HOLD_FAILED": "돌파 유지 시간 미충족",
    "BREAKOUT_CLOSE_DATA_MISSING": "5분봉 종가 데이터 없음",
    "BREAKOUT_HOLD_DATA_MISSING": "돌파 유지 시간 데이터 없음",
    "FINAL_SCORE_BELOW_THRESHOLD": "최종 점수 기준 미달",
    "ORDER_NOT_SUBMITTED": "주문 미제출",
    "OVERHEAT_LIMIT_EXCEEDED": "과열 제한 초과",
    "VOLUME_INCREASE_FAILED": "5분 거래량 증가 미충족",
    "VOLUME_INCREASE_DATA_MISSING": "5분 거래량 데이터 없음",
    "VWAP_MA20_FAILED": "VWAP/MA20 조건 미충족",
    "VWAP_MA20_DATA_MISSING": "VWAP/MA20 데이터 없음",
    "PULLBACK_REBREAK_FAILED": "눌림 후 재돌파 미충족",
    "PULLBACK_REBREAK_DATA_MISSING": "눌림 후 재돌파 데이터 없음",
    "REQUIRED_INTRADAY_DATA_MISSING": "필수 장중 데이터 없음",
    "INVALID_ORDER_VALUE": "주문 금액 오류",
    "INVALID_ACCOUNT_EQUITY": "계좌 평가금액 오류",
    "POSITION_EXPOSURE_LIMIT": "종목별 노출 한도 초과",
    "ACCOUNT_EXPOSURE_LIMIT": "계좌 노출 한도 초과",
    "MARKET_BELOW_MA20": "시장 MA20 하회",
    "MARKET_BELOW_MA20_BYPASSED": "시장 MA20 하회 우회",
    "MARKET_CONTEXT_UNRELIABLE": "시장 컨텍스트 신뢰 불가",
    "FX_VOLATILITY": "환율 변동성 초과",
    "DAILY_ACCOUNT_LOSS": "일 손실 한도 초과",
    "OPEN_POSITION_LIMIT": "보유 종목 수 한도 초과",
    "PENNY_STOCK": "가격 하한 미달",
    "PRICE_CAP": "가격 상한 초과",
    "OPENING_GAP": "시초 갭 초과",
}

VWAP_MA20_STATUS_LABELS = {
    "DISABLED": "비활성화",
    "SKIPPED_NO_DATA": "데이터 없음으로 건너뜀",
    "NO_DATA": "데이터 없음",
    "PASS": "통과",
    "FAIL": "실패",
}

CONDITION_MODE_LABELS = {
    CONDITION_MODE_HARD_FILTER: "하드필터",
    CONDITION_MODE_LOG_ONLY: "로그만",
    CONDITION_MODE_SOFT_SCORE: "소프트점수",
    CONDITION_MODE_OFF: "꺼짐",
}

VWAP_MA20_TYPE_LABELS = {
    VWAP_MA20_AND: "VWAP와 MA20 모두",
    VWAP_MA20_MA20_ONLY: "MA20만",
    VWAP_MA20_OFF: "꺼짐",
    VWAP_MA20_VWAP_ONLY: "VWAP만",
    "OR": "VWAP 또는 MA20",
}


def _entry_timing_evaluation(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> EntryTimingEvaluation:
    hard: list[str] = []
    soft: list[str] = []
    logs: list[str] = []
    intraday = evaluate_intraday_data_quality(breakout, threshold, settings)

    overheat_pass = _price_change_from_open(breakout) <= settings.max_entry_price_change
    _apply_condition(
        overheat_pass,
        settings.overheat_limit_condition_mode,
        "OVERHEAT_LIMIT_EXCEEDED",
        hard,
        soft,
        logs,
    )
    confirmation_failed_reason = None
    if intraday.close_state is IntradayConditionState.FAIL:
        confirmation_failed_reason = "BREAKOUT_CLOSE_FAILED"
    elif intraday.hold_state is IntradayConditionState.FAIL:
        confirmation_failed_reason = "BREAKOUT_HOLD_FAILED"
    if confirmation_failed_reason:
        _apply_condition(
            False,
            intraday.confirmation_mode,
            confirmation_failed_reason,
            hard,
            soft,
            logs,
    )
    _apply_condition_state(
        intraday.volume_state,
        intraday.volume_mode,
        "VOLUME_INCREASE_FAILED",
        hard,
        soft,
        logs,
    )
    _apply_condition_state(
        intraday.vwap_ma20_state,
        intraday.vwap_ma20_mode,
        "VWAP_MA20_FAILED",
        hard,
        soft,
        logs,
    )
    _apply_condition_state(
        intraday.pullback_state,
        intraday.pullback_mode,
        "PULLBACK_REBREAK_FAILED",
        hard,
        soft,
        logs,
    )
    if intraday.missing_data_reasons:
        if intraday.policy == INTRADAY_MISSING_DATA_POLICY_BLOCK:
            hard.append(missing_data_block_reason(intraday.missing_data_reasons))
        else:
            logs.extend(intraday.missing_data_reasons)
    return EntryTimingEvaluation(
        allowed=not hard,
        score_adjustment=-5.0 * len(soft),
        failed_soft_reasons=tuple(soft),
        failed_log_reasons=tuple(logs),
        failed_hard_reasons=tuple(hard),
        missing_data_reasons=intraday.missing_data_reasons,
        available_features=intraday.available_features,
        missing_features=intraday.missing_features,
        intraday_missing_data_policy=intraday.policy,
        condition_results={
            "overheat_pass": overheat_pass,
            **intraday.condition_results,
        },
    )


def _entry_timing_allowed(
    breakout: BreakoutInput,
    threshold: float,
    settings: TradingSettings,
) -> bool:
    return _entry_timing_evaluation(breakout, threshold, settings).allowed


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


def _apply_condition_state(
    state: IntradayConditionState,
    mode: str,
    reason: str,
    hard: list[str],
    soft: list[str],
    logs: list[str],
) -> None:
    if state is not IntradayConditionState.FAIL:
        return
    _apply_condition(False, mode, reason, hard, soft, logs)


def _price_change_from_open(breakout: BreakoutInput) -> float:
    if breakout.open_price_usd <= 0:
        return 0.0
    return (breakout.last_price_usd - breakout.open_price_usd) / breakout.open_price_usd


def _entry_price_vs_breakout(entry_price: float, threshold: float) -> float | None:
    if threshold <= 0:
        return None
    return entry_price / threshold - 1.0


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
    if evaluation.missing_features:
        detail += f", missing {','.join(evaluation.missing_features)}"
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
    data_evaluation = evaluation or _entry_timing_evaluation(
        breakout,
        threshold,
        settings,
    )
    condition_results = dict(data_evaluation.condition_results or {})
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
        "intradayMissingDataPolicy": resolve_intraday_missing_data_policy(
            settings.intraday_missing_data_policy,
            app_mode=settings.app_mode,
            mock_trading=settings.mock_trading,
        ),
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
        if hasattr(repository, "save_log"):
            condition_results = (
                json.loads(evaluation.condition_result_json)
                if evaluation.condition_result_json
                else {}
            )
            vwap_ma20_status = condition_results.get("vwap_ma20_evaluation_status", "")
            missing_reasons = tuple(
                str(reason)
                for reason in condition_results.get("missing_data_reasons", [])
                if reason
            )
            repository.save_log(
                BotLog(
                    "WARNING" if missing_reasons else "INFO",
                    "candidate_evaluation",
                    _candidate_evaluation_saved_message(
                        evaluation,
                        vwap_ma20_status,
                        condition_results,
                    ),
                    symbol=evaluation.symbol,
                    reject_reason=evaluation.buy_block_reason or "",
                    actual_value=evaluation.final_score,
                    threshold_value=evaluation.min_selection_score,
                )
            )
            if vwap_ma20_status in {"PASS", "FAIL"}:
                repository.save_log(
                    BotLog(
                        "INFO",
                        "entry_planner",
                        _vwap_ma20_evaluated_message(evaluation, condition_results),
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
                        f"후보평가 저장 실패: 종목={evaluation.symbol} 오류={exc}",
                        symbol=evaluation.symbol,
                        reject_reason="CANDIDATE_EVALUATION_SAVE_FAILED",
                    )
                )
            except Exception:
                pass


def _candidate_evaluation_saved_message(
    evaluation: CandidateEvaluation,
    vwap_ma20_status: object,
    condition_results: Mapping[str, object],
) -> str:
    missing_reasons = condition_results.get("missing_data_reasons") or []
    missing_label = ",".join(str(reason) for reason in missing_reasons) or "-"
    return (
        "후보평가 저장: "
        f"종목={evaluation.symbol} "
        f"최종점수={_value_label(evaluation.final_score)} "
        f"매수허용={_bool_label(evaluation.buy_allowed)} "
        f"주문제출={_bool_label(evaluation.order_submitted)} "
        f"매수판정={_buy_block_reason_label(evaluation.buy_block_reason)} "
        f"하드필터탈락={_value_label(evaluation.hard_filter_failed_count)} "
        f"소프트조건탈락={_value_label(evaluation.soft_condition_failed_count)} "
        f"VWAP/MA20상태={_vwap_ma20_status_label(vwap_ma20_status)} "
        f"데이터품질={condition_results.get('data_quality_status', '-')} "
        f"데이터누락={missing_label}"
    )


def _vwap_ma20_evaluated_message(
    evaluation: CandidateEvaluation,
    condition_results: Mapping[str, object],
) -> str:
    return (
        "VWAP/MA20 평가: "
        f"종목={evaluation.symbol} "
        f"현재가={_value_label(condition_results.get('current_price'))} "
        f"VWAP={_value_label(condition_results.get('vwap_usd'))} "
        f"장중MA20={_value_label(condition_results.get('intraday_ma20_usd'))} "
        f"조건유형={_vwap_ma20_type_label(condition_results.get('vwapMa20ConditionType'))} "
        f"조건모드={_condition_mode_label(condition_results.get('vwapMa20ConditionMode'))} "
        f"VWAP통과={_bool_label(condition_results.get('vwap_pass'))} "
        f"MA20통과={_bool_label(condition_results.get('ma20_pass'))} "
        f"종합통과={_bool_label(condition_results.get('vwap_ma20_pass'))}"
    )


def _buy_block_reason_label(reason: object) -> str:
    code = str(reason or "").strip()
    if not code:
        return "-"
    return BUY_BLOCK_REASON_LABELS.get(code, "미등록 사유")


def _vwap_ma20_status_label(status: object) -> str:
    code = str(status or "").strip()
    if not code:
        return "-"
    return VWAP_MA20_STATUS_LABELS.get(code, "미등록 상태")


def _condition_mode_label(mode: object) -> str:
    code = str(mode or "").strip()
    if not code:
        return "-"
    return CONDITION_MODE_LABELS.get(code, "미등록 모드")


def _vwap_ma20_type_label(condition_type: object) -> str:
    code = str(condition_type or "").strip()
    if not code:
        return "-"
    return VWAP_MA20_TYPE_LABELS.get(code, "미등록 유형")


def _bool_label(value: object) -> str:
    if value is True:
        return "예"
    if value is False:
        return "아니오"
    return "-"


def _value_label(value: object) -> str:
    if value is None or value == "":
        return "-"
    if value is True or value is False:
        return _bool_label(value)
    return str(value)


def _first_reason(reasons: tuple[str, ...]) -> str:
    return reasons[0] if reasons else "ORDER_NOT_SUBMITTED"
