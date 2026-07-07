import {
  compactHashText,
  dailyLogCount,
  dailySummaryMetric,
  dailySummaryTrade,
  escapeHtml,
  hasDisplayValue,
  moneyOrDash,
  moneyText,
  negativeRatioText,
  percentOrDash,
  percentText,
  profitClass,
} from "../formatters.js";
import {
  exitReasonLabel,
  strategyVersionLabel,
  translateDailySummaryText,
} from "../ko.js";

export function renderDailySummaryRow(summary, selected = {}) {
  const payload = safeSummaryJson(summary.summaryJson);
  const isActive = selected.tradeDate === summary.tradeDate && selected.mode === summary.mode;
  return `<tr class="daily-summary-row${isActive ? " is-active" : ""}"
      data-date="${escapeHtml(summary.tradeDate || "")}"
      data-mode="${escapeHtml(summary.mode || "")}">
    <td><strong>${escapeHtml(summary.tradeDate || "-")}</strong></td>
    <td>${escapeHtml(modeText(summary.mode))}</td>
    <td>${escapeHtml(strategyVersionText(summary.strategyVersion))}</td>
    <td class="numeric">${escapeHtml(countText(summary.tradeCount))}</td>
    <td class="numeric ${profitClass(summary.totalProfitUsd)}">${escapeHtml(moneyText(summary.totalProfitUsd))}</td>
    <td class="numeric">${escapeHtml(percentText(summary.winRate))}</td>
    <td>${escapeHtml(sampleText(summary, payload))}</td>
    <td>${escapeHtml(summary.updatedAt || "-")}</td>
  </tr>`;
}

export function renderDailySummaryDetail(summary) {
  const target = document.querySelector("#dailySummaryDetail");
  if (!target) return;
  if (!summary) {
    target.innerHTML = `<p class="empty-copy">저장된 일일 요약을 선택해 주세요.</p>`;
    return;
  }
  const payload = safeSummaryJson(summary.summaryJson);
  const jsonFailed = Boolean(summary.summaryJsonParseFailed);
  const jsonSections = jsonFailed ? [] : [
    renderDailySummaryFlow(payload, summary),
    renderDailySummaryStatsSection(
      "청산 사유별 성과",
      payload.exitReasonStats,
      ["청산 사유", "건수", "총 손익", "평균 수익률", "승률", "최대 손실"],
      (item) => [
        exitReasonText(item.reason),
        countText(item.count),
        moneyText(item.totalProfitUsd),
        percentOrDash(item.averageProfitRate),
        percentOrDash(item.winRate),
        moneyOrDash(dailySummaryMetric(item, ["maxLossUsd", "maxLoss", "max_loss_usd"])),
      ],
    ),
    renderDailySummaryStatsSection(
      "전략 버전별 성과",
      payload.strategyStats,
      ["전략 버전", "거래 수", "총 손익", "평균 수익률", "승률"],
      (item) => [
        strategyVersionText(item.strategyVersion),
        countText(item.count),
        moneyText(item.totalProfitUsd),
        percentOrDash(item.averageProfitRate),
        percentOrDash(item.winRate),
      ],
    ),
    renderDailySummarySnapshotStats(payload.entryProfitSnapshotStats),
  ];
  target.innerHTML = [
    renderDailySummaryBasicInfo(summary),
    renderDailySummaryPerformance(summary, payload),
    jsonFailed ? `<p class="daily-summary-json-warning">상세 JSON을 해석할 수 없습니다.</p>` : "",
    ...jsonSections,
    renderDailySummaryText(summary.summaryText),
  ].filter(Boolean).join("");
}

export function renderDailySummaryBasicInfo(summary) {
  return renderDailySummaryCardSection("기본 정보", [
    ["기준일", summary.tradeDate || "-"],
    ["모드", modeText(summary.mode)],
    ["전략 버전", strategyVersionText(summary.strategyVersion)],
    ["설정 해시", compactHashText(summary.settingsSnapshotHash)],
    ["생성 시각", summary.createdAt || "-"],
    ["갱신 시각", summary.updatedAt || "-"],
    ["표본 충분 여부", sampleText(summary, safeSummaryJson(summary.summaryJson))],
  ]);
}

export function renderDailySummaryPerformance(summary, payload) {
  return renderDailySummaryCardSection("성과 요약", [
    ["총 손익", moneyText(summary.totalProfitUsd), profitClass(summary.totalProfitUsd)],
    ["총 수익률", percentOrDash(summary.totalProfitRate), profitClass(summary.totalProfitRate)],
    ["거래 수", countText(summary.tradeCount)],
    ["매수 수", countText(summary.buyCount)],
    ["매도 수(분할익절 포함)", countText(summary.sellCount)],
    ["승률", percentOrDash(summary.winRate)],
    ["평균 거래 수익률", percentOrDash(dailySummaryMetric(payload, ["averageProfitRate", "averageTradeProfitRate"]))],
    ["MDD", percentOrDash(dailySummaryMetric(payload, ["maxDrawdown", "mdd", "maxDrawdownRate"]))],
  ]);
}

export function renderDailySummaryCardSection(title, rows) {
  return `<section class="daily-summary-card-section">
    <h3>${escapeHtml(title)}</h3>
    <div class="daily-summary-cards metric-grid">
      ${rows.map(([label, value, extraClass]) => (
        `<dl><dt>${escapeHtml(label)}</dt><dd class="${escapeHtml(extraClass || "")}">${escapeHtml(value)}</dd></dl>`
      )).join("")}
    </div>
  </section>`;
}

export function renderDailySummaryText(summaryText) {
  return `<section class="daily-summary-card-section">
    <h3>요약 텍스트</h3>
    <pre class="daily-summary-text">${escapeHtml(dailySummaryTextForDisplay(summaryText))}</pre>
  </section>`;
}

export function renderDailySummaryFlow(payload, summary) {
  const rows = [
    ["후보 수", dailySummaryMetric(payload, ["candidateSymbolCount", "candidateCount", "candidateSummary.candidateSymbolCount", "candidateSummary.candidateCount", "candidateSummary.totalCount"])],
    ["선정 수", dailySummaryMetric(payload, ["tradedSymbolCount", "selectedCount", "finalSelectedCount", "candidateSummary.selectedCount"])],
    ["매수 의도 수", dailySummaryMetric(payload, ["buyIntentCount", "buyAllowedCount", "candidateSummary.buyIntentCount"])],
    ["주문 수", dailySummaryMetric(payload, ["orderCount", "orderSubmittedCount", "candidateSummary.orderSubmittedCount"])],
    ["체결 수", summary.tradeCount],
    ["미체결 수", dailySummaryMetric(payload, ["unfilledCount", "unfilledOrderCount"])],
    ["취소 수", dailySummaryMetric(payload, ["cancelCount", "cancelledOrderCount"])],
  ];
  return `<section class="daily-summary-card-section">
    <h3>후보/선정 흐름</h3>
    <div class="daily-summary-flow metric-grid">
      ${rows.map(([label, value]) => `<dl><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(countText(value))}</dd></dl>`).join("")}
    </div>
  </section>`;
}

export function renderDailySummaryStatsSection(title, rows, columns, mapper) {
  if (!Array.isArray(rows) || rows.length === 0) return "";
  return `<section class="daily-summary-section">
    <h3>${escapeHtml(title)}</h3>
    <div class="table-wrap">
      <table class="data-table daily-summary-detail-table">
        <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
        <tbody>${rows.map((item) => (
          `<tr>${mapper(item).map((value) => `<td>${escapeHtml(value == null ? "-" : value)}</td>`).join("")}</tr>`
        )).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

export function renderDailySummarySnapshotStats(stats) {
  if (!stats || typeof stats !== "object") return "";
  const negativeCounts = stats.negativeCounts || {};
  const finalWinRates = stats.negativeFinalWinRates || {};
  const positiveFinalWinRates = stats.positiveFinalWinRates || {};
  const sampleCount = Number(stats.sampleCount);
  const rows = ["5m", "10m", "15m", "20m", "30m"].map((key) => [
    key,
    Number.isFinite(sampleCount) ? sampleCount : "-",
    negativeCounts[key] == null ? 0 : negativeCounts[key],
    negativeRatioText(negativeCounts[key], sampleCount),
    finalWinRates[key] == null ? "-" : percentText(finalWinRates[key]),
    positiveFinalWinRates[key] == null ? "-" : percentText(positiveFinalWinRates[key]),
  ]);
  return `<section class="daily-summary-section">
    <h3>진입 후 수익률 스냅샷</h3>
    <div class="table-wrap">
      <table class="data-table daily-summary-detail-table">
        <thead><tr><th>구간</th><th>표본 수</th><th>음수 거래 수</th><th>음수 비율</th><th>음수 거래 최종 승률</th><th>양수 거래 최종 승률</th></tr></thead>
        <tbody>${rows.map((row) => (
          `<tr>${row.map((value) => `<td>${escapeHtml(value)}</td>`).join("")}</tr>`
        )).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

export function renderDailySummaryMajorTrades(payload) {
  const rows = [
    ["최대 수익 거래", dailySummaryTrade(payload, ["maxProfitTrade", "bestTrade", "topProfitTrade"])],
    ["최대 손실 거래", dailySummaryTrade(payload, ["maxLossTrade", "worstTrade", "topLossTrade"])],
  ];
  return `<section class="daily-summary-section">
    <h3>주요 거래</h3>
    <div class="table-wrap">
      <table class="data-table daily-summary-detail-table">
        <thead><tr><th>구분</th><th>종목</th><th>손익</th><th>수익률</th><th>청산 사유</th></tr></thead>
        <tbody>${rows.map(([label, trade]) => `<tr>
          <td>${escapeHtml(label)}</td>
          <td>${escapeHtml(trade.symbol || trade.ticker || "-")}</td>
          <td>${escapeHtml(moneyOrDash(dailySummaryMetric(trade, ["profitUsd", "profit", "pnlUsd"])))}</td>
          <td>${escapeHtml(percentOrDash(dailySummaryMetric(trade, ["profitRate", "returnRate", "pnlRate"])))}</td>
          <td>${escapeHtml(exitReasonText(trade.exitReason || trade.reason))}</td>
        </tr>`).join("")}</tbody>
      </table>
    </div>
  </section>`;
}

export function renderDailySummaryLogSummary(payload) {
  const logs = Array.isArray(payload.importantLogs) ? payload.importantLogs : [];
  const messages = logs.slice(0, 5).map((item) => (
    `<li>${escapeHtml([item.level, item.message].filter(Boolean).join(" - ") || "-")}</li>`
  ));
  return `<section class="daily-summary-section">
    <h3>오류/경고 로그 요약</h3>
    <div class="daily-summary-log-summary">
      <dl><dt>ERROR 수</dt><dd>${escapeHtml(countText(dailyLogCount(payload, "ERROR")))}</dd></dl>
      <dl><dt>WARNING 수</dt><dd>${escapeHtml(countText(dailyLogCount(payload, "WARNING")))}</dd></dl>
    </div>
    ${messages.length > 0 ? `<ul class="daily-summary-log-list">${messages.join("")}</ul>` : `<p class="empty-copy">주요 오류 메시지가 없습니다.</p>`}
  </section>`;
}

export function safeSummaryJson(value) {
  if (!value) return {};
  if (typeof value === "object" && !Array.isArray(value)) return value;
  try {
    const payload = JSON.parse(String(value));
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  } catch {
    return {};
  }
}

export function modeText(mode) {
  if (mode === "mock") return "모의투자";
  if (mode === "real") return "실투자";
  return mode || "-";
}

export function strategyVersionText(value) {
  return strategyVersionLabel(value);
}

export function exitReasonText(value) {
  return exitReasonLabel(value);
}

export function dailySummaryTextForDisplay(value) {
  return translateDailySummaryText(value);
}

export function countText(value) {
  return hasDisplayValue(value) ? `${value}건` : "-";
}

export function sampleText(summary, payload) {
  const stats = payload.entryProfitSnapshotStats || {};
  const count = stats.sampleCount;
  const suffix = hasDisplayValue(count) ? ` (${count}/30건)` : "";
  return summary.sampleSufficient ? `충분${suffix}` : `부족${suffix}`;
}
