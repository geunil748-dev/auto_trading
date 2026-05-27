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
let historyState = { targets: [], orders: [], fills: [], logs: [], trades: [] };
let activeAccount = "mock";
let activePage = "dashboard";

const tokenStorageKey = "monitorBearerToken";
const refreshButton = document.querySelector("#refreshState");
const tabButtons = document.querySelectorAll(".tab-button");
const navButtons = document.querySelectorAll(".nav-item");
const sideNav = document.querySelector("#sideNav");
const sideScrim = document.querySelector("#sideScrim");
const toggleSideNavButton = document.querySelector("#toggleSideNav");
const tokenInput = document.querySelector("#monitorToken");
const saveTokenButton = document.querySelector("#saveMonitorToken");
const authStatus = document.querySelector("#authStatus");
const historyDateInput = document.querySelector("#historyDate");
const refreshHistoryButton = document.querySelector("#refreshHistory");
const historyStatus = document.querySelector("#historyStatus");
const riskSettingsForm = document.querySelector("#riskSettingsForm");
const stopLossInput = document.querySelector("#stopLossPercent");
const takeProfitInput = document.querySelector("#takeProfitPercent");
const riskSettingsStatus = document.querySelector("#riskSettingsStatus");
const sellAllButton = document.querySelector("#sellAllPositions");

document.body.dataset.page = activePage;
if (historyDateInput) historyDateInput.value = todayText();
if (tokenInput) tokenInput.value = localStorage.getItem(tokenStorageKey) || "";

saveTokenButton?.addEventListener("click", saveTokenAndReload);
tokenInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") saveTokenAndReload();
});
refreshButton?.addEventListener("click", loadState);
refreshHistoryButton?.addEventListener("click", loadHistory);
riskSettingsForm?.addEventListener("submit", saveRiskSettings);
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
    if (activePage === "activity" || activePage === "candidateHistory") loadHistory();
    if (activePage === "settings") loadRiskSettings();
  });
});
toggleSideNavButton?.addEventListener("click", () => {
  setSideNavOpen(sideNav?.classList.contains("is-collapsed"));
});
sideScrim?.addEventListener("click", () => setSideNavOpen(false));
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
  if (refreshButton) refreshButton.disabled = true;
  try {
    currentState = normalizeState(await fetchState());
    setAuthStatus(bearerToken() ? "인증된 모니터입니다." : "");
  } catch {
    currentState = fallbackState;
    setAuthStatus("모니터 토큰을 확인해 주세요.");
  } finally {
    if (refreshButton) refreshButton.disabled = false;
  }
  render(currentState);
}

async function loadHistory() {
  if (!refreshHistoryButton) return;
  refreshHistoryButton.disabled = true;
  setHistoryStatus("DB 조회 중...");
  try {
    historyState = normalizeHistoryState(await fetchHistory());
    setHistoryStatus(`${historyState.date || selectedHistoryDate()} 기준`);
  } catch {
    historyState = { targets: [], orders: [], fills: [], logs: [], trades: [] };
    setHistoryStatus("DB 기록을 불러오지 못했습니다.");
  } finally {
    refreshHistoryButton.disabled = false;
  }
  render(currentState);
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
  if (!riskSettingsForm) return;
  try {
    const response = await fetch(`/api/trading-settings?ts=${Date.now()}`, fetchOptions("/api/trading-settings"));
    if (!response.ok) throw new Error("settings request failed");
    const payload = await response.json();
    applyRiskSettings(payload.settings || {});
    setRiskSettingsStatus("현재 설정을 불러왔습니다.");
  } catch {
    setRiskSettingsStatus("설정을 불러오지 못했습니다.");
  }
}

async function saveRiskSettings(event) {
  event.preventDefault();
  const button = document.querySelector("#saveRiskSettings");
  if (button) button.disabled = true;
  try {
    const response = await fetch(
      "/api/trading-settings",
      fetchOptions("/api/trading-settings", {
        body: JSON.stringify({
          stopLossPercent: Number(stopLossInput?.value || 0),
          takeProfitPercent: Number(takeProfitInput?.value || 0),
        }),
        headers: { "Content-Type": "application/json" },
        method: "POST",
      }),
    );
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "설정 저장 실패");
    }
    applyRiskSettings(payload.settings || {});
    setRiskSettingsStatus("저장했습니다. 다음 감시 루프부터 반영됩니다.");
  } catch (error) {
    setRiskSettingsStatus(error.message || "설정 저장에 실패했습니다.");
  } finally {
    if (button) button.disabled = false;
  }
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

function fetchOptions(url, options = {}) {
  const token = bearerToken();
  if (!token || !url.startsWith("/api/")) return options;
  return { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } };
}

function setAuthStatus(message) {
  if (authStatus) authStatus.textContent = message;
}

function setHistoryStatus(message) {
  if (historyStatus) historyStatus.textContent = message;
}

function setRiskSettingsStatus(message) {
  if (riskSettingsStatus) riskSettingsStatus.textContent = message;
}

function applyRiskSettings(settings) {
  if (stopLossInput && settings.stopLossPercent != null) {
    stopLossInput.value = formatPercentInput(settings.stopLossPercent);
  }
  if (takeProfitInput && settings.takeProfitPercent != null) {
    takeProfitInput.value = formatPercentInput(settings.takeProfitPercent);
  }
}

function formatPercentInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

function selectedHistoryDate() {
  return (historyDateInput?.value || todayText()).trim();
}

function todayText() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function setSideNavOpen(open) {
  sideNav?.classList.toggle("is-collapsed", !open);
  document.body.classList.toggle("side-collapsed", !open);
  toggleSideNavButton?.setAttribute("aria-label", open ? "왼쪽 메뉴 닫기" : "왼쪽 메뉴 열기");
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
  };
}

function render(state) {
  const accountState = state.accounts?.[activeAccount] || emptyAccount;
  renderRuntime(state.runtime || fallbackState.runtime);
  renderSummary(accountState);
  renderTables(accountState);
  renderPage();
}

function renderPage() {
  document.body.dataset.page = activePage;
  navButtons.forEach((button) => button.classList.toggle("active", button.dataset.page === activePage));
}

function renderRuntime(runtime) {
  window.runtimeControls?.render(runtime);
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

function renderTables(accountState) {
  const names = tickerNames(accountState);
  renderRows("#targetRows", accountState.targets, (row) => renderTargetRow(row, names), 7, "오늘 조건에 맞는 종목 없음");
  renderRows("#candidateHistoryRows", historyState.targets, (row) => renderTargetRow(row, names), 7, "저장된 후보 리스트가 없습니다");
  renderRows("#holdingRows", accountState.holdings, renderHoldingRow, 8, "보유 종목이 없습니다");

  const activityLogs = activePage === "activity" ? historyState.logs : accountState.logs;
  document.querySelector("#logRows").innerHTML = (activityLogs || []).map(renderLogRow).join("");
  const orders = activePage === "activity"
    ? historyState.trades
    : (accountState.orders || []).length > 0 ? accountState.orders : accountState.trades;
  renderList("#orderRows", orders, renderOrderRow, "주문 내역이 없습니다");
  const fills = activePage === "activity" ? historyState.fills : accountState.fills;
  renderList("#fillRows", fills, renderFillRow, "체결 내역이 없습니다");
}

function renderRows(selector, rows, renderer, colspan, emptyText) {
  document.querySelector(selector).innerHTML = (rows || []).length === 0
    ? `<tr><td class="empty-copy" colspan="${colspan}">${emptyText}</td></tr>`
    : rows.map(renderer).join("");
}

function renderList(selector, rows, renderer, emptyText) {
  document.querySelector(selector).innerHTML = (rows || []).length === 0
    ? `<p class="empty-copy">${emptyText}</p>`
    : rows.map(renderer).join("");
}

function renderTargetRow(row, names = {}) {
  const [ticker, name, price, volume, gap, score, state] =
    row.length >= 7 ? row : [row[0], names[row[0]] || "-", ...row.slice(1)];
  return `<tr>
    <td><strong>${escapeHtml(name && name !== "-" ? name : names[ticker] || "-")}</strong></td>
    <td>${escapeHtml(ticker)}</td><td>${escapeHtml(price)}</td><td>${escapeHtml(volume)}</td>
    <td>${escapeHtml(gap)}</td><td class="score">${escapeHtml(score)}</td>
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

function renderOrderRow(order) {
  const detail = [order.exitReason || "접수", order.profitUsd].filter(Boolean).join(" / ");
  return `<section class="trade-row">
    <strong>${escapeHtml(order.ticker)}</strong><span>${escapeHtml(order.side || order.type)}</span>
    <b>${escapeHtml(order.price)}</b><small>${escapeHtml(order.quantity)}주</small>
    <em>${escapeHtml(order.unfilled ? `미체결 ${order.unfilled}주` : detail)}</em>
  </section>`;
}

function renderFillRow(fill) {
  const filledAt = fill.filledAt || [fill.date, fill.time].filter(Boolean).join(" ");
  const result = fill.profitUsd ? `${fill.total} / ${fill.profitUsd}` : fill.total;
  return `<section class="trade-row fill-row">
    <strong>${escapeHtml(fill.ticker)}</strong><span>${escapeHtml(fill.side)}</span>
    <b>${escapeHtml(fill.price)}</b><small>${escapeHtml(fill.quantity)}주</small>
    <em>${escapeHtml(result)}</em><time>${escapeHtml(filledAt || "-")}</time>
  </section>`;
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
