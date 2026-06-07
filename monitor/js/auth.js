export const MONITOR_TOKEN_STORAGE_KEY = "monitorBearerToken";

export function readStoredMonitorToken() {
  try {
    return localStorage.getItem(MONITOR_TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function storeMonitorToken(token) {
  try {
    localStorage.setItem(MONITOR_TOKEN_STORAGE_KEY, token || "");
  } catch {
    // 브라우저 저장소를 사용할 수 없는 환경에서는 현재 입력값만 사용한다.
  }
}

export function removeStoredMonitorToken() {
  try {
    localStorage.removeItem(MONITOR_TOKEN_STORAGE_KEY);
  } catch {
    // 브라우저 저장소를 사용할 수 없는 환경에서는 무시한다.
  }
}

export function authorizationHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}
