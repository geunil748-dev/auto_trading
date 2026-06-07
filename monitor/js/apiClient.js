import { authorizationHeaders } from "./auth.js";

export function createApiClient({ getToken }) {
  function fetchOptions(url, options = {}) {
    const token = getToken?.() || "";
    if (!token || !String(url).startsWith("/api/")) return options;
    return {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...authorizationHeaders(token),
      },
    };
  }

  return { fetchOptions };
}
