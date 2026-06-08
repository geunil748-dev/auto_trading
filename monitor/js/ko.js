export const KO_LABELS = {
  reasons: {
    ACCOUNT_EXPOSURE_LIMIT: "계좌 투자비중 초과",
    API_ERROR: "API 오류",
    BUY_ALLOWED: "매수 허용",
    BREAKOUT_NOT_TRIGGERED: "돌파 미발생",
    BREAKOUT_CLOSE_FAILED: "5분봉 종가 돌파 미충족",
    CANDIDATE_EVALUATION_SAVE_FAILED: "후보 평가 저장 실패",
    CANDIDATE_SNAPSHOT_EMPTY: "후보 스냅샷 없음",
    CANDIDATE_SNAPSHOT_SAVE_FAILED: "후보 스냅샷 저장 실패",
    CANDIDATE_SNAPSHOT_SAVED: "후보 스냅샷 저장 완료",
    DAILY_ACCOUNT_LOSS: "일일 손실 제한 도달",
    EXPECTED_FILL_PRICE_GAP_TOO_HIGH: "예상 체결가 차이 초과",
    FINAL_SCORE_BELOW_THRESHOLD: "최종 점수 기준 미달",
    FX_VOLATILITY: "환율 변동성 초과",
    INVALID_ACCOUNT_EQUITY: "계좌 평가금액 확인 불가",
    INVALID_ORDER_VALUE: "주문 금액 오류",
    LOW_OPENING_CHANGE: "장초반 상승률 부족",
    LOW_OPENING_VOLUME: "장초반 거래량 부족",
    MARKET_BELOW_MA20: "시장 20일선 하회",
    MISSING_SNAPSHOT: "시세 스냅샷 없음",
    OPENING_GAP: "시가 갭 과다",
    OPEN_POSITION_LIMIT: "최대 보유 종목 수 초과",
    ORDER_FAILED: "주문 실패",
    ORDER_NOT_SUBMITTED: "주문 미제출",
    OVERHEAT_LIMIT_EXCEEDED: "과열 제한 초과",
    PENNY_STOCK: "가격 하한 미달",
    POSITION_EXPOSURE_LIMIT: "종목별 투자비중 초과",
    PRICE_CAP: "가격 상한 초과",
    PULLBACK_REBREAK_FAILED: "눌림 후 재돌파 미충족",
    QUOTE_LOOKUP_FAILED: "호가 조회 실패",
    RANKING_FETCH_FAILED: "랭킹 조회 실패",
    RETRY: "재시도",
    RECHECK_NOT_AVAILABLE: "재평가 없음",
    ORDER_SUBMITTED: "주문 제출",
    STRICT_FILTER_NO_CANDIDATES: "엄격 필터 후보 부족",
    UNKNOWN_BLOCK_REASON: "차단 사유 미확인",
    VOLUME_INCREASE_FAILED: "5분 거래량 증가 미충족",
    VWAP_MA20_FAILED: "VWAP/MA20 조건 미충족",
    VWAP_MA20_DATA_MISSING: "VWAP/MA20 데이터 없음",
    VWAP_MA20_EVALUATED: "VWAP/MA20 평가",
  },
  conditionModes: {
    HARD_FILTER: "매수 차단",
    SOFT_SCORE: "점수 감산",
    LOG_ONLY: "기록만",
    OFF: "비활성화",
  },
  conditionStatuses: {
    DISABLED: "비활성화",
    SKIPPED_NO_DATA: "데이터 없음",
    PASS: "통과",
    FAIL: "실패",
  },
  conditionTypes: {
    AND: "VWAP와 MA20 모두",
    OR: "VWAP 또는 MA20",
    VWAP_ONLY: "VWAP만",
    MA20_ONLY: "MA20만",
    OFF: "꺼짐",
  },
  recheckStatuses: {
    RECHECK_NOT_AVAILABLE: "재평가 없음",
    BUY_ALLOWED: "매수 판단 통과",
    ORDER_SUBMITTED: "주문 제출",
    BLOCKED: "매수 차단",
  },
  recheckSources: {
    fixed_recheck: "장초반 고정 후보 재평가",
    hybrid_recheck: "하이브리드 재평가",
    dry_run: "신규 후보 재수집",
  },
  strategyVersions: {
    LEGACY_RELAXED: "기존 완화 전략",
    STRICT_FIXED_NO_PYRAMIDING: "엄격 고정 전략",
    STRICT_FIXED: "엄격 고정 전략",
    STRICT: "엄격 전략",
    RELAXED: "완화 전략",
  },
  entryTags: {
    CHART_POSITIVE: "차트 조건 양호",
    HYBRID_CANDIDATE: "장초반+15분 후보",
    INTRADAY_RECHECK: "15분 재평가",
    NEWS_POSITIVE: "뉴스 긍정",
    OPENING_BREAKOUT: "장초반 돌파",
    OPENING_FIXED: "장초반 고정 후보",
    PYRAMIDING: "불타기 추가매수",
    RANKED_LIST: "랭킹 후보",
    REFRESH_CANDIDATE: "15분 신규 후보",
    VOLUME_SURGE: "거래량 급증",
    VWAP_ABOVE: "VWAP 상단",
  },
  exitReasons: {
    STOP_LOSS: "손절",
    TAKE_PROFIT: "익절",
    TRAILING_STOP: "트레일링 스탑",
    PARTIAL_TAKE_PROFIT: "분할 익절",
    EOD: "종가 청산",
    END_OF_DAY: "종가 청산",
    MANUAL_SELL: "수동 매도",
    MANUAL_SELL_ALL: "수동 전량 매도",
    MANUAL: "수동 처리",
    UNKNOWN: "미확인",
  },
};

export function labelFromMap(map, code, fallback = "-") {
  if (code === null || code === undefined || code === "") return fallback;
  const text = String(code).trim();
  if (!text) return fallback;
  return map[text] || text;
}

export function reasonLabel(code) {
  return labelFromMap(KO_LABELS.reasons, code);
}

export function conditionModeLabel(code) {
  return labelFromMap(KO_LABELS.conditionModes, code);
}

export function conditionStatusLabel(code) {
  return labelFromMap(KO_LABELS.conditionStatuses, code);
}

export function conditionTypeLabel(code) {
  return labelFromMap(KO_LABELS.conditionTypes, code);
}

export function recheckStatusLabel(code) {
  return labelFromMap(KO_LABELS.recheckStatuses, code);
}

export function recheckSourceLabel(code) {
  return labelFromMap(KO_LABELS.recheckSources, code);
}

export function strategyVersionLabel(code) {
  return labelFromMap(KO_LABELS.strategyVersions, code);
}

export function exitReasonLabel(code) {
  return labelFromMap(KO_LABELS.exitReasons, code);
}

export function yesNoLabel(value) {
  const text = String(value || "").trim().toLowerCase();
  if (text === "true") return "예";
  if (text === "false") return "아니오";
  if (!text || text === "none" || text === "null") return "-";
  return String(value);
}

export function translateStructuredLogMessage(message) {
  const text = String(message || "");
  if (text.startsWith("candidate_evaluation_saved ")) {
    const values = keyValuePairs(text.replace("candidate_evaluation_saved ", ""));
    return [
      "후보평가 저장:",
      `종목=${values.symbol || "-"}`,
      `최종점수=${values.final_score || "-"}`,
      `매수허용=${yesNoLabel(values.buy_allowed)}`,
      `주문제출=${yesNoLabel(values.order_submitted)}`,
      `매수판정=${reasonLabel(values.buy_block_reason)}`,
      `하드필터탈락=${values.hard_filter_failed_count || "-"}`,
      `소프트조건탈락=${values.soft_condition_failed_count || "-"}`,
      `VWAP/MA20상태=${conditionStatusLabel(values.vwap_ma20_status)}`,
    ].join(" ");
  }
  if (text.startsWith("vwap_ma20_skipped_no_data ")) {
    const values = keyValuePairs(text.replace("vwap_ma20_skipped_no_data ", ""));
    return [
      "VWAP/MA20 데이터 부족:",
      `종목=${values.symbol || "-"}`,
      `현재가=${values.current_price || "-"}`,
      `조건유형=${conditionTypeLabel(values.condition_type)}`,
      `조건모드=${conditionModeLabel(values.condition_mode)}`,
      `VWAP데이터=${yesNoLabel(values.has_vwap)}`,
      `장중MA20데이터=${yesNoLabel(values.has_intraday_ma20)}`,
      `사유=${reasonLabel(values.reason)}`,
    ].join(" ");
  }
  if (text.startsWith("vwap_ma20_evaluated ")) {
    const values = keyValuePairs(text.replace("vwap_ma20_evaluated ", ""));
    return [
      "VWAP/MA20 평가:",
      `종목=${values.symbol || "-"}`,
      `현재가=${values.current_price || "-"}`,
      `VWAP=${values.vwap_usd || "-"}`,
      `장중MA20=${values.intraday_ma20_usd || "-"}`,
      `조건유형=${conditionTypeLabel(values.condition_type)}`,
      `조건모드=${conditionModeLabel(values.condition_mode)}`,
      `VWAP통과=${yesNoLabel(values.vwap_pass)}`,
      `MA20통과=${yesNoLabel(values.ma20_pass)}`,
      `종합통과=${yesNoLabel(values.vwap_ma20_pass)}`,
    ].join(" ");
  }
  return text;
}

export function translateDailySummaryText(value) {
  let text = value || "저장된 요약 텍스트가 없습니다.";
  for (const code of Object.keys(KO_LABELS.strategyVersions)) {
    text = text.replaceAll(code, strategyVersionLabel(code));
  }
  for (const code of Object.keys(KO_LABELS.exitReasons)) {
    text = text.replaceAll(code, exitReasonLabel(code));
  }
  return text;
}

function keyValuePairs(text) {
  return String(text || "").split(/\s+/).reduce((pairs, part) => {
    const index = part.indexOf("=");
    if (index <= 0) return pairs;
    pairs[part.slice(0, index)] = part.slice(index + 1);
    return pairs;
  }, {});
}
