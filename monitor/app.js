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

document.body.dataset.page = activePage;

if (historyDateInput) {
  historyDateInput.value = todayText();
}

if (tokenInput) {
  tokenInput.value = localStorage.getItem(tokenStorageKey) || "";
}

saveTokenButton?.addEventListener("click", () => {
  localStorage.setItem(tokenStorageKey, bearerToken());
  setAuthStatus("토큰을 저장했습니다.");
  loadState();
});
tokenInput?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    localStorage.setItem(tokenStorageKey, bearerToken());
    setAuthStatus("토큰을 저장했습니다.");
    loadState();
  }
});
refreshButton.addEventListener("click", loadState);
refreshHistoryButton?.addEventListener("click", loadHistory);
window.runtimeControls?.bind(toggleRealOrderUnlock);
tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeAccount = button.dataset.account;
    tabButtons.forEach((item) => item.classList.toggle("active", item === button));
    render(currentState);
  });
});
navButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activePage = button.dataset.page || "dashboard";
    renderPage();
    if (activePage === "activity" || activePage === "candidateHistory") {
      loadHistory();
    }
  });
});
toggleSideNavButton?.addEventListener("click", () => {
  setSideNavOpen(sideNav?.classList.contains("is-collapsed"));
});
sideScrim?.addEventListener("click", () => setSideNavOpen(false));
loadState();
loadHistory();

async function loadState() {
  refreshButton.disabled = true;
  try {
    currentState = normalizeState(await fetchState());
    setAuthStatus(bearerToken() ? "인증된 모니터입니다." : "");
  } catch {
    currentState = fallbackState;
    setAuthStatus("모니터 토큰을 확인해 주세요.");
  } finally {
    refreshButton.disabled = false;
  }
  render(currentState);
}

async function loadHistory() {
  if (!refreshHistoryButton) {
    return;
  }
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
  const apiQuery = `/api/state?ts=${Date.now()}`;
  const urls = [apiQuery, `./state.json?ts=${Date.now()}`];
  for (const url of urls) {
    const response = await fetch(url, fetchOptions(url));
    if (response.ok) {
      return response.json();
    }
    if (response.status === 401 || response.status === 403) {
      throw new Error("monitor token rejected");
    }
  }
  throw new Error("monitor state request failed");
}

async function fetchHistory() {
  const historyDate = selectedHistoryDate();
  const url = `/api/history?ts=${Date.now()}&date=${encodeURIComponent(historyDate)}`;
  const response = await fetch(url, fetchOptions(url));
  if (!response.ok) {
    throw new Error("history request failed");
  }
  return response.json();
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
    if (!response.ok) {
      throw new Error("real trading control request failed");
    }
    const payload = await response.json();
    currentState = { ...currentState, runtime: payload.runtime };
    render(currentState);
  } catch {
    setAuthStatus("실투자 주문 제어 토큰을 확인해 주세요.");
  } finally {
    window.runtimeControls?.setBusy(false);
  }
}

function bearerToken() {
  return (tokenInput?.value || "").trim();
}

function fetchOptions(url, options = {}) {
  const token = bearerToken();
  if (!token || !url.startsWith("/api/")) {
    return options;
  }
  return {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  };
}

function setAuthStatus(message) {
  if (authStatus) {
    authStatus.textContent = message;
  }
}

function setHistoryStatus(message) {
  if (historyStatus) {
    historyStatus.textContent = message;
  }
}

function selectedHistoryDate() {
  return (historyDateInput?.value || todayText()).trim();
}

function todayText() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function setSideNavOpen(open) {
  sideNav?.classList.toggle("is-collapsed", !open);
  document.body.classList.toggle("side-collapsed", !open);
  toggleSideNavButton?.setAttribute("aria-label", open ? "왼쪽 메뉴 닫기" : "왼쪽 메뉴 열기");
}

function normalizeState(state) {
  if (state.accounts) {
    return state;
  }
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
  renderTables(accountState, state.sql || {});
  renderPage();
}

function renderPage() {
  document.body.dataset.page = activePage;
  navButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.page === activePage);
  });
}

function renderRuntime(runtime) {
  window.runtimeControls?.render(runtime);
}

function renderSummary(accountState) {
  const account = accountState.account || emptyAccount.account;
  const accountStatus = document.querySelector("#accountStatus");
  accountStatus.textContent = accountState.connected ? "연결됨" : "미연결";
  accountStatus.classList.toggle("is-offline", !accountState.connected);
  document.querySelector("#cashUsd").textContent = account.cashUsd || "-";
  document.querySelector("#equityUsd").textContent = account.equityUsd || "-";
  document.querySelector("#cashKrw").textContent = account.cashKrw || "-";
  document.querySelector("#investedUsd").textContent = account.investedUsd || "-";
  document.querySelector("#openPositions").textContent = account.openPositions || "-";
  document.querySelector("#dailyProfitRate").textContent = account.dailyProfitRate || "-";

  document.querySelectorAll("[data-real-only]").forEach((item) => {
    item.hidden = activeAccount !== "real";
  });

  const error = document.querySelector("#accountError");
  error.hidden = !accountState.error;
  error.textContent = accountState.error || "";
}

function renderTables(accountState, sqlState) {
  const trades = accountState.trades || [];
  const targets = accountState.targets || [];
  const names = tickerNames(accountState);
  document.querySelector("#targetRows").innerHTML =
    targets.length === 0
      ? `<tr><td class="empty-copy" colspan="7">오늘 조건에 맞는 종목 없음</td></tr>`
      : targets.map((row) => renderTargetRow(row, names)).join("");

  const candidateHistory = historyState.targets || [];
  document.querySelector("#candidateHistoryRows").innerHTML =
    candidateHistory.length === 0
      ? `<tr><td class="empty-copy" colspan="7">저장된 후보 리스트가 없습니다</td></tr>`
      : candidateHistory.map((row) => renderTargetRow(row, names)).join("");

  const holdings = accountState.holdings || [];
  document.querySelector("#holdingRows").innerHTML =
    holdings.length === 0
      ? `<tr><td class="empty-copy" colspan="7">보유 종목이 없습니다</td></tr>`
      : holdings.map(renderHoldingRow).join("");

  const activityLogs = activePage === "activity" ? historyState.logs || [] : accountState.logs || [];
  document.querySelector("#logRows").innerHTML = activityLogs
    .map(renderLogRow)
    .join("");

  const accountOrders = accountState.orders || [];
  const orders =
    activePage === "activity"
      ? historyState.trades || []
      : accountOrders.length > 0
        ? accountOrders
        : trades;
  document.querySelector("#orderRows").innerHTML =
    orders.length === 0
      ? `<p class="empty-copy">주문 내역이 없습니다</p>`
      : orders.map(renderOrderRow).join("");

  const fills = activePage === "activity" ? historyState.fills || [] : accountState.fills || [];
  document.querySelector("#fillRows").innerHTML =
    fills.length === 0
      ? `<p class="empty-copy">체결 내역이 없습니다</p>`
      : fills.map(renderFillRow).join("");
}

function renderTargetRow(row, names = {}) {
  const [ticker, name, price, volume, gap, score, currentState] =
    row.length >= 7 ? row : [row[0], names[row[0]] || "-", ...row.slice(1)];
  const displayName = name && name !== "-" ? name : names[ticker] || "-";
  return `
    <tr>
      <td><strong>${displayName}</strong></td>
      <td>${ticker}</td>
      <td>${price}</td>
      <td>${volume}</td>
      <td>${gap}</td>
      <td class="score">${score}</td>
      <td><span class="trade-state">${currentState}</span></td>
    </tr>`;
}

function tickerNames(accountState) {
  const names = {};
  for (const row of [
    ...(accountState.holdings || []),
    ...(accountState.orders || []),
    ...(accountState.fills || []),
  ]) {
    if (row.ticker && row.name) {
      names[row.ticker] = row.name;
    }
  }
  return names;
}

function renderHoldingRow(holding) {
  return `
    <tr>
      <td><strong>${holding.name || "-"}</strong></td>
      <td>${holding.ticker}</td>
      <td>${holding.quantity}주</td>
      <td>${holding.averagePrice}</td>
      <td>${holding.openPrice || "-"}</td>
      <td>${holding.closePrice || "-"}</td>
      <td>${holding.totalPrice}</td>
    </tr>`;
}

function renderLogRow([time, level, message]) {
  return `
    <div class="log-row">
      <time>${time}</time>
      <span class="log-level">${level}</span>
      <span>${message}</span>
    </div>`;
}

function renderOrderRow(order) {
  return `
    <section class="trade-row">
      <strong>${order.ticker}</strong>
      <span>${order.side || order.type}</span>
      <b>${order.price}</b>
      <small>${order.quantity}주</small>
      <em>${order.unfilled ? `미체결 ${order.unfilled}주` : order.exitReason || "접수"}</em>
    </section>`;
}

function renderFillRow(fill) {
  const filledAt = fill.filledAt || [fill.date, fill.time].filter(Boolean).join(" ");
  return `
    <section class="trade-row fill-row">
      <strong>${fill.ticker}</strong>
      <span>${fill.side}</span>
      <b>${fill.price}</b>
      <small>${fill.quantity}주</small>
      <em>${fill.total}</em>
      <time>${filledAt || "-"}</time>
    </section>`;
}
