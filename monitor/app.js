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
let activeAccount = "mock";

const tokenStorageKey = "monitorBearerToken";
const refreshButton = document.querySelector("#refreshState");
const tabButtons = document.querySelectorAll(".tab-button");
const tokenInput = document.querySelector("#monitorToken");
const saveTokenButton = document.querySelector("#saveMonitorToken");
const authStatus = document.querySelector("#authStatus");

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
window.runtimeControls?.bind(toggleRealOrderUnlock);
tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeAccount = button.dataset.account;
    tabButtons.forEach((item) => item.classList.toggle("active", item === button));
    render(currentState);
  });
});
loadState();

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

async function fetchState() {
  for (const url of [`/api/state?ts=${Date.now()}`, `./state.json?ts=${Date.now()}`]) {
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

function render(state) {
  const accountState = state.accounts?.[activeAccount] || emptyAccount;
  renderRuntime(state.runtime || fallbackState.runtime);
  renderSummary(accountState);
  renderTables(accountState);
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
  document.querySelector("#equityKrw").textContent = account.equityKrw || "-";
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

function renderTables(accountState) {
  const trades = accountState.trades || [];
  const targets = accountState.targets || [];
  document.querySelector("#targetRows").innerHTML =
    targets.length === 0
      ? `<tr><td class="empty-copy" colspan="6">수집된 종목이 없습니다</td></tr>`
      : targets.map(renderTargetRow).join("");

  const holdings = accountState.holdings || [];
  document.querySelector("#holdingRows").innerHTML =
    holdings.length === 0
      ? `<tr><td class="empty-copy" colspan="7">보유 종목이 없습니다</td></tr>`
      : holdings.map(renderHoldingRow).join("");

  document.querySelector("#logRows").innerHTML = (accountState.logs || [])
    .map(renderLogRow)
    .join("");

  const orders = accountState.orders || trades;
  document.querySelector("#orderRows").innerHTML =
    orders.length === 0
      ? `<p class="empty-copy">주문 내역이 없습니다</p>`
      : orders.map(renderOrderRow).join("");

  const fills = accountState.fills || [];
  document.querySelector("#fillRows").innerHTML =
    fills.length === 0
      ? `<p class="empty-copy">체결 내역이 없습니다</p>`
      : fills.map(renderFillRow).join("");
}

function renderTargetRow([ticker, price, volume, gap, score, currentState]) {
  return `
    <tr>
      <td><strong>${ticker}</strong></td>
      <td>${price}</td>
      <td>${volume}</td>
      <td>${gap}</td>
      <td class="score">${score}</td>
      <td><span class="trade-state">${currentState}</span></td>
    </tr>`;
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
  return `
    <section class="trade-row fill-row">
      <strong>${fill.ticker}</strong>
      <span>${fill.side}</span>
      <b>${fill.price}</b>
      <small>${fill.quantity}주</small>
      <em>${fill.total}</em>
    </section>`;
}
