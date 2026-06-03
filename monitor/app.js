// 기본 상태
const emptyTradingStats = {
  lookback_days: 30,
  total_trading_days: 0,
  candidate_days: 0,
  candidate_rate: 0,
  scoring_days: 0,
  scoring_rate: 0,
  strict_filter_days: 0,
  strict_filter_rate: 0,
  selected_days: 0,
  selected_rate: 0,
};

const emptyAccount = {
  connected: false,
  error: "",
  account: {
    cashUsd: "-",
    equityUsd: "-",
    investedUsd: "-",
    cashKrw: "-",
    equityKrw: "-",
    openPositions: "-",
    dailyProfitRate: "-",
    realizedProfitUsd: "-",
  },
  targets: [],
  holdings: [],
  orders: [],
  fills: [],
  entryReasonStats: [],
  strategyStats: [],
  exitReasonStats: [],
  recentTrades: [],
  entryProfitSnapshots: [],
  entryProfitSnapshotStats: {},
  trading_stats: emptyTradingStats,
  logs: [],
  trades: [],
};

const fallbackState = {
  accounts: {
    mock: { ...emptyAccount, label: "모의투자" },
    real: { ...emptyAccount, label: "실투자" },
  },
  runtime: {
    activeMode: "mock",
    modeLabel: "모의투자",
    realTrading: {
      envEnabled: false,
      emergencyStop: true,
      manualEnabled: false,
      ordersUnlocked: false,
      maxOrderKrw: 0,
      maxDailyOrderKrw: 0,
    },
  },
};

let currentState = fallbackState;
let historyState = {
  targets: [],
  orders: [],
  fills: [],
  logs: [],
  trades: [],
  runSummaries: [],
  entryReasonStats: [],
  strategyStats: [],
  exitReasonStats: [],
  recentTrades: [],
  entryProfitSnapshots: [],
  entryProfitSnapshotStats: {},
};
let backtestState = {
  tickers: [],
  results: [],
  message: "아직 실행하지 않았습니다.",
};
let activeAccount = "mock";
let activePage = "dashboard";
let historyDateTouched = false;
let candidateHistoryMessage = "";

const tokenStorageKey = "monitorBearerToken";
const refreshButton = document.querySelector("#refreshState");
const manualScreeningButton = document.querySelector("#manualScreening");
const tabButtons = document.querySelectorAll(".tab-button");
const navButtons = document.querySelectorAll(".nav-item");
const tokenInput = document.querySelector("#monitorToken");
const saveTokenButton = document.querySelector("#saveMonitorToken");
const authStatus = document.querySelector("#authStatus");
const securityBar = document.querySelector(".security-bar");
const historyDateInput = document.querySelector("#historyDate");
const refreshHistoryButton = document.querySelector("#refreshHistory");
const runBacktestButton = document.querySelector("#runBacktest");
const backtestTickerInput = document.querySelector("#backtestTicker");
const customBacktestTickerInput = document.querySelector("#customBacktestTicker");
const riskSettingsForm = document.querySelector("#riskSettingsForm");
const filterSettingsForm = document.querySelector("#filterSettingsForm");
const stopLossInput = document.querySelector("#stopLossPercent");
const takeProfitInput = document.querySelector("#takeProfitPercent");
const partialTakeProfitInput = document.querySelector("#partialTakeProfitEnabled");
const trailingStopActivationInput = document.querySelector("#trailingStopActivationPercent");
const minTotalScoreInput = document.querySelector("#minTotalScore");
const minPriceUsdInput = document.querySelector("#minPriceUsd");
const maxPriceUsdInput = document.querySelector("#maxPriceUsd");
const gainerRankingLimitInput = document.querySelector("#gainerRankingLimit");
const turnoverRankingLimitInput = document.querySelector("#turnoverRankingLimit");
const minOpeningPriceChangeInput = document.querySelector("#minOpeningPriceChangePercent");
const minVolumeRatioInput = document.querySelector("#minVolumeRatio");
const maxOpeningGapInput = document.querySelector("#maxOpeningGapPercent");
const intradayCandidateModeInput = document.querySelector("#intradayCandidateMode");
const maxEntryPriceChangeInput = document.querySelector("#maxEntryPriceChangePercent");
const overheatLimitConditionModeInput = document.querySelector("#overheatLimitConditionMode");
const breakoutHoldMinutesInput = document.querySelector("#breakoutHoldMinutes");
const require5mCloseInput = document.querySelector("#require5mCloseAboveBreakout");
const breakoutCloseConditionModeInput = document.querySelector("#breakoutCloseConditionMode");
const require5mVolumeInput = document.querySelector("#require5mVolumeIncrease");
const min5mVolumeIncreaseInput = document.querySelector("#min5mVolumeIncreasePercent");
const volumeIncreaseConditionModeInput = document.querySelector("#volumeIncreaseConditionMode");
const requireVwapOrMa20Input = document.querySelector("#requireVwapOrMa20");
const vwapMa20ConditionModeInput = document.querySelector("#vwapMa20ConditionMode");
const vwapMa20ConditionTypeInput = document.querySelector("#vwapMa20ConditionType");
const requirePullbackRebreakInput = document.querySelector("#requirePullbackRebreak");
const pullbackRebreakConditionModeInput = document.querySelector("#pullbackRebreakConditionMode");
const riskSettingsStatus = document.querySelector("#riskSettingsStatus");
const filterSettingsStatus = document.querySelector("#filterSettingsStatus");
const sellAllButton = document.querySelector("#sellAllPositions");
const showNoBuyLogsInput = document.querySelector("#showNoBuyLogs");
const showNoSellLogsInput = document.querySelector("#showNoSellLogs");
const panelToggleButtons = document.querySelectorAll("[data-collapse-target]");

document.body.dataset.page = activePage;
if (historyDateInput) historyDateInput.value = todayText();
if (tokenInput) tokenInput.value = localStorage.getItem(tokenStorageKey) || "";

saveTokenButton?.addEventListener("click", saveTokenAndReload);
tokenInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveTokenAndReload();
});
refreshButton?.addEventListener("click", loadState);
manualScreeningButton?.addEventListener("click", submitManualScreening);
runBacktestButton?.addEventListener("click", loadBacktest);
backtestTickerInput?.addEventListener("change", () => {
  if (customBacktestTickerInput) customBacktestTickerInput.value = "";
  loadBacktest();
});
customBacktestTickerInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadBacktest();
});
refreshHistoryButton?.addEventListener("click", loadHistory);
showNoBuyLogsInput?.addEventListener("change", () => {
  render(currentState);
});
showNoSellLogsInput?.addEventListener("change", () => {
  render(currentState);
});
panelToggleButtons.forEach((button) => {
  button.addEventListener("click", () => togglePanel(button));
});
historyDateInput?.addEventListener("change", () => {
  historyDateTouched = true;
  loadHistory();
});
riskSettingsForm?.addEventListener("submit", saveRiskSettings);
filterSettingsForm?.addEventListener("submit", saveFilterSettings);
requireVwapOrMa20Input?.addEventListener("change", syncVwapMa20Controls);
sellAllButton?.addEventListener("click", submitSellAllPositions);
window.runtimeControls?.bind(toggleRealOrderUnlock);
tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeAccount = button.dataset.account || "mock";
    tabButtons.forEach((item) => item.classList.toggle("active", item === button));
    render(currentState);
  });
});
navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activePage = button.dataset.page || "dashboard";
    renderPage();
    if (
      activePage === "activity"
      || activePage === "candidateHistory"
      || activePage === "runSummary"
      || activePage === "entryReasonStats"
      || activePage === "backtest"
    ) loadHistory();
    if (activePage === "settings") loadRiskSettings();
  });
});
document.addEventListener("click", (event) => {
  const button = event.target.closest(".manual-sell-button");
  if (button) submitManualSell(button);
});

loadState();
loadHistory();
loadRiskSettings();

function saveTokenAndReload() {
  localStorage.setItem(tokenStorageKey, bearerToken());
  setAuthStatus("토큰을 저장했습니다.");
  loadState();
}

async function loadState() {
  setButtonLoading(refreshButton, true);
  try {
    currentState = normalizeState(await fetchState());
    if (currentState.date && historyDateInput && !historyDateTouched) {
      historyDateInput.value = currentState.date;
    }
    if (currentState.runtime?.monitorAuth?.tokenConfigured === false) {
      clearSavedMonitorToken();
      setAuthStatus("");
    } else {
      setAuthStatus(bearerToken() ? "인증된 모니터입니다." : "");
    }
  } catch {
    currentState = fallbackState;
    setAuthStatus("모니터 토큰을 확인해 주세요.");
  } finally {
    setButtonLoading(refreshButton, false);
  }
  render(currentState);
}

async function loadHistory() {
  if (!refreshHistoryButton) return;
  setButtonLoading(refreshHistoryButton, true);
  try {
    historyState = normalizeHistoryState(await fetchHistory());
    candidateHistoryMessage = "";
  } catch {
    historyState = {
      targets: [],
      orders: [],
      fills: [],
      logs: [],
      trades: [],
      runSummaries: [],
      entryReasonStats: [],
      strategyStats: [],
      exitReasonStats: [],
      recentTrades: [],
      entryProfitSnapshots: [],
      entryProfitSnapshotStats: {},
    };
    setAuthStatus("DB 기록을 불러오지 못했습니다.");
  } finally {
    setButtonLoading(refreshHistoryButton, false);
  }
  render(currentState);
}

async function loadBacktest() {
  setButtonLoading(runBacktestButton, true);
  setBacktestStatus("과거 차트 데이터를 불러와 백테스트를 실행하는 중입니다.");
  try {
    const ticker = encodeURIComponent(backtestTickerValue());
    const date = encodeURIComponent(selectedHistoryDate());
    const response = await fetch(
      `/api/backtest?ts=${Date.now()}&date=${date}&ticker=${ticker}`,
      fetchOptions("/api/backtest"),
    );
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || payload.message || "백테스트 실행에 실패했습니다.");
    }
    backtestState = {
      tickers: payload.tickers || [],
      results: payload.results || [],
      message: payload.message || "백테스트를 완료했습니다.",
    };
  } catch (error) {
    backtestState = {
      tickers: [],
      results: [],
      message: error.message || "백테스트 실행에 실패했습니다.",
    };
  } finally {
    setButtonLoading(runBacktestButton, false);
  }
  renderBacktest();
}

function backtestTickerValue() {
  const custom = (customBacktestTickerInput?.value || "").trim().toUpperCase();
  return custom || backtestTickerInput?.value || "ALL";
}

async function submitManualScreening() {
  setButtonLoading(manualScreeningButton, true);
  setAuthStatus("수동 리스트업을 요청하는 중입니다.");
  try {
    const response = await fetch(
      "/api/manual-screening",
      fetchOptions("/api/manual-screening", { method: "POST" }),
    );
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || payload.message || "수동 리스트업 요청 실패");
    }
    setAuthStatus(payload.message || "수동 리스트업을 백그라운드에서 시작했습니다.");
    await pollManualScreeningStatus();
    await loadState();
    await loadHistory();
  } catch (error) {
    const message = error.message || "수동 리스트업 요청에 실패했습니다.";
    setAuthStatus(message);
    candidateHistoryMessage = message;
    render(currentState);
  } finally {
    setButtonLoading(manualScreeningButton, false);
  }
}

// 데이터 조회
async function pollManualScreeningStatus() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    await wait(attempt === 0 ? 1500 : 5000);
    const response = await fetch(
      `/api/manual-screening?ts=${Date.now()}`,
      fetchOptions("/api/manual-screening"),
    );
    if (!response.ok) throw new Error("수동 리스트업 상태 확인 실패");
    const payload = await response.json();
    const status = payload.status || {};
    if (status.message) setAuthStatus(status.message);
    if (!status.running) {
      if (status.ok === false) throw new Error(status.message || "수동 리스트업 실패");
      return status;
    }
  }
  throw new Error("수동 리스트업 시간이 오래 걸리고 있습니다. 잠시 후 새로고침해 주세요.");
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function setButtonLoading(button, isLoading) {
  if (!button) return;
  button.disabled = isLoading;
  button.classList.toggle("is-loading", isLoading);
  document
    .querySelector(`[data-spinner-for="${button.id}"]`)
    ?.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
}

async function fetchState() {
  const urls = [`/api/state?ts=${Date.now()}`, `./state.json?ts=${Date.now()}`];
  for (const url of urls) {
    const response = await fetch(url, fetchOptions(url));
    if (response.ok) return response.json();
    if (response.status === 401 || response.status === 403) {
      throw new Error("monitor token rejected");
    }
  }
  throw new Error("monitor state request failed");
}

async function fetchHistory() {
  const url = `/api/history?ts=${Date.now()}&date=${encodeURIComponent(selectedHistoryDate())}`;
  const response = await fetch(url, fetchOptions(url));
  if (!response.ok) throw new Error("history request failed");
  return response.json();
}

async function loadRiskSettings() {
  if (!riskSettingsForm && !filterSettingsForm) return;
  try {
    const response = await fetch(`/api/trading-settings?ts=${Date.now()}`, fetchOptions("/api/trading-settings"));
    if (!response.ok) throw new Error("settings request failed");
    const payload = await response.json();
    applyRiskSettings(payload.settings || {});
    setRiskSettingsStatus("현재 설정을 불러왔습니다.");
    setFilterSettingsStatus("현재 설정을 불러왔습니다.");
  } catch {
    setRiskSettingsStatus("설정을 불러오지 못했습니다.");
    setFilterSettingsStatus("설정을 불러오지 못했습니다.");
  }
}

async function saveRiskSettings(event) {
  event.preventDefault();
  const button = document.querySelector("#saveRiskSettings");
  if (button) button.disabled = true;
  try {
    const payload = await postTradingSettings({
      stopLossPercent: Number(stopLossInput?.value || 0),
      takeProfitPercent: Number(takeProfitInput?.value || 0),
      partialTakeProfitEnabled: Boolean(partialTakeProfitInput?.checked),
      trailingStopActivationPercent: Number(trailingStopActivationInput?.value || 0),
      maxEntryPriceChangePercent: Number(maxEntryPriceChangeInput?.value || 0),
      overheatLimitConditionMode: overheatLimitConditionModeInput?.value || "HARD_FILTER",
      breakoutHoldMinutes: Number(breakoutHoldMinutesInput?.value || 0),
      require5mCloseAboveBreakout: Boolean(require5mCloseInput?.checked),
      breakoutCloseConditionMode: breakoutCloseConditionModeInput?.value || "SOFT_SCORE",
      require5mVolumeIncrease: Boolean(require5mVolumeInput?.checked),
      min5mVolumeIncreasePercent: Number(min5mVolumeIncreaseInput?.value || 0),
      volumeIncreaseConditionMode: volumeIncreaseConditionModeInput?.value || "SOFT_SCORE",
      requireVwapOrMa20: Boolean(requireVwapOrMa20Input?.checked),
      vwapMa20ConditionMode: vwapMa20ConditionModeInput?.value || "HARD_FILTER",
      vwapMa20ConditionType: vwapMa20ConditionTypeInput?.value || "OR",
      requirePullbackRebreak: Boolean(requirePullbackRebreakInput?.checked),
      pullbackRebreakConditionMode: pullbackRebreakConditionModeInput?.value || "SOFT_SCORE",
    });
    applyRiskSettings(payload.settings || {});
    setRiskSettingsStatus("매수/매도 조건을 저장했습니다. 다음 감시 루프부터 반영됩니다.");
  } catch (error) {
    setRiskSettingsStatus(error.message || "설정 저장에 실패했습니다.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function saveFilterSettings(event) {
  event.preventDefault();
  const button = document.querySelector("#saveFilterSettings");
  if (button) button.disabled = true;
  try {
    const payload = await postTradingSettings({
      minTotalScore: Number(minTotalScoreInput?.value || 0),
      minPriceUsd: Number(minPriceUsdInput?.value || 0),
      maxPriceUsd: Number(maxPriceUsdInput?.value || 0),
      gainerRankingLimit: Number(gainerRankingLimitInput?.value || 0),
      turnoverRankingLimit: Number(turnoverRankingLimitInput?.value || 0),
      minOpeningPriceChangePercent: Number(minOpeningPriceChangeInput?.value || 0),
      minVolumeRatio: Number(minVolumeRatioInput?.value || 0),
      maxOpeningGapPercent: Number(maxOpeningGapInput?.value || 0),
      refreshIntradayCandidates: (intradayCandidateModeInput?.value || "refresh") === "refresh",
      candidateSelectionMode: intradayCandidateModeInput?.value || "refresh",
    });
    applyRiskSettings(payload.settings || {});
    setFilterSettingsStatus("종목 수집 조건을 저장했습니다. 다음 리스트업부터 반영됩니다.");
  } catch (error) {
    setFilterSettingsStatus(error.message || "필수값 저장에 실패했습니다.");
  } finally {
    if (button) button.disabled = false;
  }
}

async function postTradingSettings(body) {
  const response = await fetch(
    "/api/trading-settings",
    fetchOptions("/api/trading-settings", {
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    }),
  );
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || "설정 저장 실패");
  }
  return payload;
}

async function toggleRealOrderUnlock() {
  const current = currentState.runtime?.realTrading?.manualEnabled === true;
  window.runtimeControls?.setBusy(true);
  try {
    const response = await fetch(
      "/api/real-trading-control",
      fetchOptions("/api/real-trading-control", {
        body: JSON.stringify({ enabled: !current }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }),
    );
    if (!response.ok) throw new Error("real trading control request failed");
    const payload = await response.json();
    currentState = { ...currentState, runtime: payload.runtime };
    render(currentState);
  } catch {
    setAuthStatus("실투자 주문 제어 토큰을 확인해 주세요.");
  } finally {
    window.runtimeControls?.setBusy(false);
  }
}

async function submitManualSell(button) {
  if (activeAccount !== "mock") {
    setAuthStatus("수동 매도는 현재 모의투자 계좌에서만 사용할 수 있습니다.");
    return;
  }
  const ticker = button.dataset.ticker || "";
  const quantity = button.dataset.quantity || "";
  const ok = window.confirm(`${ticker} ${quantity}주를 모의투자로 수동 매도 접수할까요?`);
  if (!ok) return;

  button.disabled = true;
  button.textContent = "접수 중";
  try {
    const response = await fetch(
      "/api/manual-mock-sell",
      fetchOptions("/api/manual-mock-sell", {
        body: JSON.stringify({ ticker, quantity }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }),
    );
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "수동 매도 접수 실패");
    }
    setAuthStatus(`${ticker} 수동 매도 주문을 접수했습니다.`);
    await loadState();
    await loadHistory();
  } catch (error) {
    setAuthStatus(error.message || "수동 매도 접수에 실패했습니다.");
  } finally {
    button.disabled = false;
    button.textContent = "수동 매도";
  }
}

async function submitSellAllPositions() {
  if (activeAccount !== "mock") {
    setAuthStatus("전량 매도는 현재 모의투자 계좌에서만 사용할 수 있습니다.");
    return;
  }
  const holdings = currentState.accounts?.mock?.holdings || [];
  const count = holdings.length;
  const ok = window.confirm(`모의투자 보유 종목 ${count}개를 전량 매도 접수할까요?`);
  if (!ok) return;

  sellAllButton.disabled = true;
  sellAllButton.textContent = "접수 중";
  try {
    const response = await fetch(
      "/api/manual-mock-sell-all",
      fetchOptions("/api/manual-mock-sell-all", {
        body: JSON.stringify({}),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }),
    );
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "전량 매도 접수 실패");
    }
    setAuthStatus(`전량 매도 ${payload.count || 0}건을 접수했습니다.`);
    await loadState();
    await loadHistory();
  } catch (error) {
    setAuthStatus(error.message || "전량 매도 접수에 실패했습니다.");
  } finally {
    sellAllButton.disabled = false;
    sellAllButton.textContent = "전량 매도";
  }
}

function bearerToken() {
  return (tokenInput?.value || "").trim();
}

function clearSavedMonitorToken() {
  localStorage.removeItem(tokenStorageKey);
  if (tokenInput) tokenInput.value = "";
}

function fetchOptions(url, options = {}) {
  const token = bearerToken();
  if (!token || !url.startsWith("/api/")) return options;
  return { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } };
}

function setAuthStatus(message) {
  const text = message || "";
  const shouldShowAuth = text.includes("토큰") || text.includes("인증");
  if (securityBar) securityBar.hidden = !shouldShowAuth;
  if (authStatus) authStatus.textContent = shouldShowAuth ? text : "";
}

function setRiskSettingsStatus(message) {
  if (riskSettingsStatus) riskSettingsStatus.textContent = message;
}

function setFilterSettingsStatus(message) {
  if (filterSettingsStatus) filterSettingsStatus.textContent = message;
}

function applyRiskSettings(settings) {
  if (stopLossInput && settings.stopLossPercent != null) {
    stopLossInput.value = formatPercentInput(settings.stopLossPercent);
  }
  if (takeProfitInput && settings.takeProfitPercent != null) {
    takeProfitInput.value = formatPercentInput(settings.takeProfitPercent);
  }
  if (partialTakeProfitInput && settings.partialTakeProfitEnabled != null) {
    partialTakeProfitInput.checked = Boolean(settings.partialTakeProfitEnabled);
  }
  if (trailingStopActivationInput && settings.trailingStopActivationPercent != null) {
    trailingStopActivationInput.value = formatPercentInput(settings.trailingStopActivationPercent);
  }
  if (minTotalScoreInput && settings.minTotalScore != null) {
    minTotalScoreInput.value = formatScoreInput(settings.minTotalScore);
  }
  if (minPriceUsdInput && settings.minPriceUsd != null) {
    minPriceUsdInput.value = formatPriceInput(settings.minPriceUsd);
  }
  if (maxPriceUsdInput && settings.maxPriceUsd != null) {
    maxPriceUsdInput.value = formatPriceInput(settings.maxPriceUsd);
  }
  if (gainerRankingLimitInput && settings.gainerRankingLimit != null) {
    gainerRankingLimitInput.value = formatCountInput(settings.gainerRankingLimit);
  }
  if (turnoverRankingLimitInput && settings.turnoverRankingLimit != null) {
    turnoverRankingLimitInput.value = formatCountInput(settings.turnoverRankingLimit);
  }
  if (minOpeningPriceChangeInput && settings.minOpeningPriceChangePercent != null) {
    minOpeningPriceChangeInput.value = formatPercentInput(settings.minOpeningPriceChangePercent);
  }
  if (minVolumeRatioInput && settings.minVolumeRatio != null) {
    minVolumeRatioInput.value = formatRatioInput(settings.minVolumeRatio);
  }
  if (maxOpeningGapInput && settings.maxOpeningGapPercent != null) {
    maxOpeningGapInput.value = formatPercentInput(settings.maxOpeningGapPercent);
  }
  if (intradayCandidateModeInput) {
    intradayCandidateModeInput.value = settings.candidateSelectionMode
      || (settings.refreshIntradayCandidates ? "refresh" : "fixed");
  }
  if (maxEntryPriceChangeInput && settings.maxEntryPriceChangePercent != null) {
    maxEntryPriceChangeInput.value = formatPercentInput(settings.maxEntryPriceChangePercent);
  }
  if (overheatLimitConditionModeInput && settings.overheatLimitConditionMode) {
    overheatLimitConditionModeInput.value = settings.overheatLimitConditionMode;
  }
  if (breakoutHoldMinutesInput && settings.breakoutHoldMinutes != null) {
    breakoutHoldMinutesInput.value = formatScoreInput(settings.breakoutHoldMinutes);
  }
  if (require5mCloseInput && settings.require5mCloseAboveBreakout != null) {
    require5mCloseInput.checked = Boolean(settings.require5mCloseAboveBreakout);
  }
  if (breakoutCloseConditionModeInput && settings.breakoutCloseConditionMode) {
    breakoutCloseConditionModeInput.value = settings.breakoutCloseConditionMode;
  }
  if (require5mVolumeInput && settings.require5mVolumeIncrease != null) {
    require5mVolumeInput.checked = Boolean(settings.require5mVolumeIncrease);
  }
  if (min5mVolumeIncreaseInput && settings.min5mVolumeIncreasePercent != null) {
    min5mVolumeIncreaseInput.value = formatPercentInput(settings.min5mVolumeIncreasePercent);
  }
  if (volumeIncreaseConditionModeInput && settings.volumeIncreaseConditionMode) {
    volumeIncreaseConditionModeInput.value = settings.volumeIncreaseConditionMode;
  }
  if (requireVwapOrMa20Input && settings.requireVwapOrMa20 != null) {
    requireVwapOrMa20Input.checked = Boolean(settings.requireVwapOrMa20);
  }
  if (vwapMa20ConditionModeInput && settings.vwapMa20ConditionMode) {
    vwapMa20ConditionModeInput.value = settings.vwapMa20ConditionMode;
  }
  if (vwapMa20ConditionTypeInput && settings.vwapMa20ConditionType) {
    vwapMa20ConditionTypeInput.value = settings.vwapMa20ConditionType;
  }
  syncVwapMa20Controls();
  if (requirePullbackRebreakInput && settings.requirePullbackRebreak != null) {
    requirePullbackRebreakInput.checked = Boolean(settings.requirePullbackRebreak);
  }
  if (pullbackRebreakConditionModeInput && settings.pullbackRebreakConditionMode) {
    pullbackRebreakConditionModeInput.value = settings.pullbackRebreakConditionMode;
  }
}

function syncVwapMa20Controls() {
  const enabled = Boolean(requireVwapOrMa20Input?.checked);
  if (vwapMa20ConditionModeInput) vwapMa20ConditionModeInput.disabled = !enabled;
  if (vwapMa20ConditionTypeInput) vwapMa20ConditionTypeInput.disabled = !enabled;
  document.querySelector(".condition-row-vwap")?.classList.toggle("is-disabled", !enabled);
}

function formatPercentInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function formatScoreInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function formatPriceInput(value) {
  return Number(value).toFixed(2).replace(/\.00$/, "");
}

function formatRatioInput(value) {
  return Number(value).toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
}

function formatCountInput(value) {
  return String(Math.trunc(Number(value)));
}

function selectedHistoryDate() {
  return (historyDateInput?.value || todayText()).trim();
}

function todayText() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function normalizeState(state) {
  if (state.accounts) return state;
  return {
    accounts: {
      mock: { ...emptyAccount, ...state, label: "모의투자", connected: true },
      real: { ...emptyAccount, label: "실투자" },
    },
  };
}

function normalizeHistoryState(state) {
  return {
    date: state.date || selectedHistoryDate(),
    targets: state.targets || [],
    orders: state.orders || [],
    fills: state.fills || [],
    logs: state.logs || [],
    trades: state.trades || [],
    runSummaries: state.runSummaries || [],
    entryReasonStats: state.entryReasonStats || [],
    strategyStats: state.strategyStats || [],
    exitReasonStats: state.exitReasonStats || [],
    recentTrades: state.recentTrades || [],
    entryProfitSnapshots: state.entryProfitSnapshots || [],
    entryProfitSnapshotStats: state.entryProfitSnapshotStats || {},
  };
}

function render(state) {
  const accountState = state.accounts?.[activeAccount] || emptyAccount;
  renderRuntime(state.runtime || fallbackState.runtime);
  renderSummary(accountState);
  renderTradingStats(accountState.trading_stats || state.trading_stats || emptyTradingStats);
  renderTables(accountState);
  renderPage();
}

// 화면 렌더링
function renderPage() {
  document.body.dataset.page = activePage;
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.page === activePage));
}

function renderRuntime(runtime) {
  window.runtimeControls?.render(runtime);
  const isRealMode = runtime.activeMode === "real";
  document.querySelector(".runtime")?.classList.toggle("is-real", isRealMode);
  document.querySelector("#accountStatus")?.classList.toggle("is-real", isRealMode);
}

function renderSummary(accountState) {
  const account = accountState.account || emptyAccount.account;
  const accountStatus = document.querySelector("#accountStatus");
  accountStatus.textContent = accountState.connected ? "연결됨" : "미연결";
  accountStatus.classList.toggle("is-offline", !accountState.connected);
  setText("#cashUsd", account.cashUsd);
  setText("#equityUsd", account.equityUsd);
  setText("#cashKrw", account.cashKrw);
  setText("#investedUsd", account.investedUsd);
  setText("#openPositions", account.openPositions);
  setText("#dailyProfitRate", account.dailyProfitRate);
  setText("#realizedProfitUsd", account.realizedProfitUsd);
  document.querySelectorAll("[data-real-only]").forEach((item) => {
    item.hidden = activeAccount !== "real";
  });
  const error = document.querySelector("#accountError");
  error.hidden = !accountState.error;
  error.textContent = accountState.error || "";
}

function renderTradingStats(stats = emptyTradingStats) {
  const totalDays = numericStat(stats.total_trading_days);
  setText("#statsTradingDays", `${totalDays}일`);
  setText(
    "#statsCandidateRate",
    tradingRateText(stats.candidate_days, stats.candidate_rate, totalDays),
  );
  setText(
    "#statsScoringRate",
    tradingRateText(stats.scoring_days, stats.scoring_rate, totalDays),
  );
  setText(
    "#statsStrictFilterRate",
    tradingRateText(stats.strict_filter_days, stats.strict_filter_rate, totalDays),
  );
  setText(
    "#statsSelectedRate",
    tradingRateText(stats.selected_days, stats.selected_rate, totalDays),
  );
}

function tradingRateText(days, rate, totalDays) {
  return `${percentText(rate)} (${numericStat(days)}/${numericStat(totalDays)}일)`;
}

function percentText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : "-";
}

function numericStat(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function renderTables(accountState) {
  const names = tickerNames(accountState);
  renderRows("#targetRows", accountState.targets, (row) => renderTargetRow(row, names), 8, "오늘 조건에 맞는 종목 없음");
  renderRows(
    "#candidateHistoryRows",
    historyState.targets,
    (row) => renderTargetRow(row, names),
    8,
    candidateHistoryMessage || "저장된 후보 리스트가 없습니다",
  );
  renderRows("#holdingRows", accountState.holdings, renderHoldingRow, 8, "보유 종목이 없습니다");

  const activityLogs = activePage === "activity" ? historyState.logs : accountState.logs;
  const visibleLogs = filterVisibleLogs(activityLogs || []);
  renderList("#logRows", visibleLogs, renderLogRow, "표시할 체결 시도 로그가 없습니다");
  const orders = activePage === "activity"
    ? historyState.trades
    : (accountState.orders || []).length > 0 ? accountState.orders : accountState.trades;
  renderList("#orderRows", orders, renderOrderRow, "주문 내역이 없습니다");
  const fills = activePage === "activity" ? historyState.fills : accountState.fills;
  renderList("#fillRows", fills, renderFillRow, "체결 내역이 없습니다");
  renderList("#runSummaryRows", historyState.runSummaries, renderRunSummaryRow, "저장된 일별 운용 결과가 없습니다");
  renderRows(
    "#strategyStatRows",
    historyState.strategyStats?.length ? historyState.strategyStats : accountState.strategyStats,
    renderStrategyStatRow,
    7,
    "전략별 성과 기록이 없습니다",
  );
  renderRows(
    "#exitReasonStatRows",
    historyState.exitReasonStats?.length ? historyState.exitReasonStats : accountState.exitReasonStats,
    renderExitReasonStatRow,
    5,
    "청산 사유 성과 기록이 없습니다",
  );
  renderRows(
    "#recentTradeRows",
    historyState.recentTrades?.length ? historyState.recentTrades : accountState.recentTrades,
    renderRecentTradeRow,
    10,
    "최근 거래 기록이 없습니다",
  );
  const entryProfitSnapshots = historyState.entryProfitSnapshots?.length
    ? historyState.entryProfitSnapshots
    : accountState.entryProfitSnapshots;
  renderEntryProfitSnapshotStats(
    historyState.entryProfitSnapshotStats?.sampleCount != null
      ? historyState.entryProfitSnapshotStats
      : accountState.entryProfitSnapshotStats,
  );
  renderRows(
    "#entryProfitSnapshotRows",
    entryProfitSnapshots,
    renderEntryProfitSnapshotRow,
    12,
    "저장된 진입 후 수익률 추적 데이터가 없습니다",
  );
  renderBacktestTickerOptions();
  renderBacktest();
}

function renderRows(selector, rows, renderer, colspan, emptyText) {
  document.querySelector(selector).innerHTML = (rows || []).length === 0
    ? `<tr><td class="empty-copy" colspan="${colspan}">${emptyText}</td></tr>`
    : rows.map(renderer).join("");
}

function renderList(selector, rows, renderer, emptyText) {
  document.querySelector(selector).innerHTML = (rows || []).length === 0
    ? `<section class="trade-empty empty-copy">${escapeHtml(emptyText)}</section>`
    : rows.map(renderer).join("");
}

function renderTargetRow(row, names = {}) {
  const [ticker, name, price, volume, volumeRatio, gap, score, state] =
    row.length >= 8
      ? row
      : row.length >= 7
        ? [row[0], row[1], row[2], "-", ...row.slice(3)]
        : [row[0], names[row[0]] || "-", row[1], "-", ...row.slice(2)];
  return `<tr>
    <td><strong>${escapeHtml(name && name !== "-" ? name : names[ticker] || "-")}</strong></td>
    <td>${escapeHtml(ticker)}</td><td>${escapeHtml(price)}</td><td>${escapeHtml(volume)}</td>
    <td>${escapeHtml(volumeRatio)}</td><td>${escapeHtml(gap)}</td><td class="score">${escapeHtml(score)}</td>
    <td><span class="trade-state">${escapeHtml(state)}</span></td>
  </tr>`;
}

function renderHoldingRow(holding) {
  const ticker = escapeHtml(holding.ticker || "");
  const quantity = escapeHtml(holding.quantity || "0");
  return `<tr>
    <td><strong>${escapeHtml(holding.name || "-")}</strong></td>
    <td>${ticker}</td><td>${quantity}주</td><td>${escapeHtml(holding.averagePrice || "-")}</td>
    <td>${escapeHtml(holding.openPrice || "-")}</td><td>${escapeHtml(holding.closePrice || "-")}</td>
    <td>${escapeHtml(holding.totalPrice || "-")}</td>
    <td><button class="manual-sell-button" type="button" data-ticker="${ticker}" data-quantity="${quantity}">수동 매도</button></td>
  </tr>`;
}

function renderLogRow([time, level, message]) {
  return `<div class="log-row"><time>${escapeHtml(time)}</time><span class="log-level">${escapeHtml(level)}</span><span>${escapeHtml(message)}</span></div>`;
}

function filterVisibleLogs(logs) {
  return logs.filter((row) => {
    const message = row?.[2];
    if (!showNoBuyLogsInput?.checked && isNoBuyOrderLog(message)) return false;
    if (!showNoSellLogsInput?.checked && isNoSellOrderLog(message)) return false;
    return true;
  });
}

function isNoBuyOrderLog(message) {
  return String(message || "").includes("매수 주문 0건: 실행할 매수 후보가 없습니다.");
}

function isNoSellOrderLog(message) {
  return String(message || "").includes("매도 주문 0건: 매도 조건을 만족한 보유 종목이 없습니다.");
}

function togglePanel(button) {
  const target = button.dataset.collapseTarget;
  const panel = target ? document.querySelector(`.panel.${target}`) : null;
  if (!panel) return;
  const collapsed = !panel.classList.contains("is-collapsed");
  panel.classList.toggle("is-collapsed", collapsed);
  button.setAttribute("aria-expanded", String(!collapsed));
  button.textContent = collapsed ? "펼치기" : "접기";
}

function renderOrderRow(order) {
  const detail = [order.exitReason || "접수", order.profitUsd].filter(Boolean).join(" / ");
  const orderedAt = order.orderedAt || [order.date, order.time].filter(Boolean).join(" ") || "-";
  return `<section class="trade-row">
    <time>${escapeHtml(orderedAt)}</time><strong>${escapeHtml(order.name || "-")}</strong>
    <span>${escapeHtml(order.ticker)}</span><span>${escapeHtml(order.side || order.type)}</span>
    <b>${escapeHtml(order.price)}</b><small>${escapeHtml(order.quantity)}주</small>
    <em>${escapeHtml(order.unfilled ? `미체결 ${order.unfilled}주` : detail)}</em>
  </section>`;
}

function renderFillRow(fill) {
  const filledAt = fill.filledAt || [fill.date, fill.time].filter(Boolean).join(" ");
  const result = [fill.total, fill.profitUsd, fill.entryReason].filter(Boolean).join(" / ");
  return `<section class="trade-row fill-row">
    <time>${escapeHtml(filledAt || "-")}</time><strong>${escapeHtml(fill.name || "-")}</strong>
    <span>${escapeHtml(fill.ticker)}</span><span>${escapeHtml(fill.side)}</span>
    <b>${escapeHtml(fill.price)}</b><small>${escapeHtml(fill.quantity)}주</small>
    <em>${escapeHtml(result)}</em>
  </section>`;
}

function renderRunSummaryRow(summary) {
  return `<section class="trade-row run-summary-row">
    <time>${escapeHtml(summary.date || "-")}</time><strong>${escapeHtml(summary.mode || "-")}</strong>
    <span>${escapeHtml(summary.stopLossPercent || "-")}</span>
    <span>${escapeHtml(summary.takeProfitPercent || "-")}</span>
    <span>${escapeHtml(summary.partialTakeProfit || "-")}</span>
    <span>${escapeHtml(summary.minTotalScore || "-")}</span>
    <span>${escapeHtml(summary.priceRange || "-")}</span>
    <span>${escapeHtml(summary.minOpeningPriceChangePercent || "-")}</span>
    <span>${escapeHtml(summary.minVolumeRatio || "-")}</span>
    <span>${escapeHtml(summary.maxOpeningGapPercent || "-")}</span>
    <b>${escapeHtml(summary.profitUsd || "$0.00")}</b>
    <span>${escapeHtml(summary.profitRate || "0.00%")}</span>
    <small>${escapeHtml(summary.buyFillCount || "0")}건</small>
    <small>${escapeHtml(summary.sellFillCount || "0")}건</small>
  </section>`;
}

function renderEntryReasonRow(item) {
  return `<tr>
    <td><strong>${escapeHtml(item.reason || "-")}</strong></td>
    <td>${escapeHtml(item.count || "0")}건</td>
    <td>${escapeHtml(item.totalProfitUsd || "$0.00")}</td>
    <td>${escapeHtml(item.averageProfitRate || "0.00%")}</td>
    <td>${escapeHtml(item.winRate || "0.0%")}</td>
  </tr>`;
}

function renderStrategyStatRow(item) {
  return `<tr>
    <td><strong>${escapeHtml(item.strategyText || item.strategy || "-")}</strong></td>
    <td>${escapeHtml(item.count || "0")}건</td>
    <td>${escapeHtml(item.winRate || "0.0%")}</td>
    <td>${escapeHtml(item.averageProfitRate || "0.00%")}</td>
    <td>${escapeHtml(item.totalProfitUsd || "$0.00")}</td>
    <td>${escapeHtml(item.averageHoldingMinutes || "-")}</td>
    <td>${escapeHtml(item.maxDrawdown || "0.00%")}</td>
  </tr>`;
}

function renderExitReasonStatRow(item) {
  return `<tr>
    <td><strong>${escapeHtml(item.exitReasonText || item.exitReason || "-")}</strong></td>
    <td>${escapeHtml(item.count || "0")}건</td>
    <td>${escapeHtml(item.winRate || "0.0%")}</td>
    <td>${escapeHtml(item.averageProfitRate || "0.00%")}</td>
    <td>${escapeHtml(item.totalProfitUsd || "$0.00")}</td>
  </tr>`;
}

function renderRecentTradeRow(item) {
  const symbol = [item.name, item.ticker].filter(Boolean).join(" / ");
  return `<tr>
    <td>${escapeHtml(item.entryAt || "-")}</td>
    <td>${escapeHtml(item.exitAt || "-")}</td>
    <td><strong>${escapeHtml(symbol || "-")}</strong></td>
    <td>${escapeHtml(item.entryStrategyText || item.entryStrategy || "-")}</td>
    <td>${escapeHtml(item.strategyVersion || "-")}</td>
    <td>${escapeHtml(item.entryTags || "-")}</td>
    <td>${escapeHtml(item.exitReasonText || item.exitReason || "-")}</td>
    <td>${escapeHtml(item.holdingTime || "-")}</td>
    <td>${escapeHtml(item.profitRate || "0.00%")}</td>
    <td>${escapeHtml(item.profitUsd || "$0.00")}</td>
  </tr>`;
}

function renderEntryProfitSnapshotStats(stats = {}) {
  const target = document.querySelector("#entryProfitSnapshotStats");
  if (!target) return;
  const warning = stats.sampleWarning
    ? `<strong class="sample-warning">${escapeHtml(stats.sampleWarning)}</strong>`
    : "";
  const statRows = (stats.negativeStats || []).map((item) => (
    `<span>${escapeHtml(item.minutes)}분 음수 ${escapeHtml(item.negativeCount || "0")}건 / 최종 승률 ${escapeHtml(item.finalWinRate || "-")}</span>`
  ));
  target.innerHTML = [
    `<span>분석 완료 표본 ${escapeHtml(String(stats.sampleCount == null ? 0 : stats.sampleCount))}건</span>`,
    warning,
    ...statRows,
  ].filter(Boolean).join("");
}

function renderEntryProfitSnapshotRow(item) {
  const symbol = [item.ticker_name, item.ticker].filter(Boolean).join(" / ");
  return `<tr>
    <td><strong>${escapeHtml(symbol || "-")}</strong></td>
    <td>${escapeHtml(item.entry_time || "-")}</td>
    <td>${escapeHtml(item.entry_price || "-")}</td>
    <td>${escapeHtml(item.profit_after_5m || "-")}</td>
    <td>${escapeHtml(item.profit_after_10m || "-")}</td>
    <td>${escapeHtml(item.profit_after_15m || "-")}</td>
    <td>${escapeHtml(item.profit_after_20m || "-")}</td>
    <td>${escapeHtml(item.profit_after_30m || "-")}</td>
    <td>${escapeHtml(item.profit_after_60m || "-")}</td>
    <td>${escapeHtml(item.final_exit_reason || "-")}</td>
    <td>${escapeHtml(item.final_profit_rate || "-")}</td>
    <td>${escapeHtml(item.strategy_version || "-")}</td>
  </tr>`;
}

function renderBacktest() {
  setBacktestStatus(backtestState.message || "아직 실행하지 않았습니다.");
  renderRows(
    "#backtestRows",
    backtestState.results,
    renderBacktestRow,
    9,
    "백테스트 결과가 없습니다",
  );
}

function renderBacktestTickerOptions() {
  if (!backtestTickerInput) return;
  const previous = backtestTickerInput.value || "ALL";
  const candidates = candidateOptionsFromHistory();
  const options = [
    `<option value="ALL">후보 전체</option>`,
    ...candidates.map((item) => {
      const label = item.name && item.name !== "-"
        ? `${item.ticker} · ${item.name}`
        : item.ticker;
      return `<option value="${escapeHtml(item.ticker)}">${escapeHtml(label)}</option>`;
    }),
  ];
  backtestTickerInput.innerHTML = options.join("");
  const values = new Set(["ALL", ...candidates.map((item) => item.ticker)]);
  backtestTickerInput.value = values.has(previous) ? previous : "ALL";
}

function candidateOptionsFromHistory() {
  const rows = historyState.targets?.length ? historyState.targets : currentState.accounts?.mock?.targets || [];
  const seen = new Set();
  const candidates = [];
  for (const row of rows) {
    const ticker = targetTicker(row);
    if (!ticker || seen.has(ticker)) continue;
    candidates.push({ ticker, name: targetName(row) });
    seen.add(ticker);
  }
  return candidates;
}

function targetTicker(row) {
  if (row && typeof row === "object" && !Array.isArray(row)) {
    return String(row.ticker || "").trim().toUpperCase();
  }
  return Array.isArray(row) ? String(row[0] || "").trim().toUpperCase() : "";
}

function targetName(row) {
  if (row && typeof row === "object" && !Array.isArray(row)) {
    return String(row.name || "").trim();
  }
  return Array.isArray(row) ? String(row[1] || "").trim() : "";
}

function renderBacktestRow(item) {
  return `<tr>
    <td>${escapeHtml(item.years)}년</td>
    <td>${escapeHtml(item.tickers)}</td>
    <td>${escapeHtml(item.trades)}</td>
    <td>${escapeHtml(item.winRate)}</td>
    <td class="score">${escapeHtml(item.returnRate)}</td>
    <td>${escapeHtml(item.profitUsd)}</td>
    <td>${escapeHtml(item.endingEquityUsd)}</td>
    <td>${escapeHtml(item.averageTradeReturn)}</td>
    <td>${escapeHtml(item.maxDrawdown)}</td>
  </tr>`;
}

function setBacktestStatus(message) {
  const status = document.querySelector("#backtestStatus");
  if (status) status.textContent = message;
}

function tickerNames(accountState) {
  const names = {};
  for (const row of [...(accountState.holdings || []), ...(accountState.orders || []), ...(accountState.fills || [])]) {
    if (row.ticker && row.name) names[row.ticker] = row.name;
  }
  return names;
}

function setText(selector, value) {
  document.querySelector(selector).textContent = value || "-";
}

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
