export function formatPercentInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

export function formatScoreInput(value) {
  return Number(value).toFixed(1).replace(/\.0$/, "");
}

export function formatPriceInput(value) {
  return Number(value).toFixed(2).replace(/\.00$/, "");
}

export function formatRatioInput(value) {
  return Number(value).toFixed(2).replace(/0$/, "").replace(/\.0$/, "");
}

export function formatCountInput(value) {
  return String(Math.trunc(Number(value)));
}

export function percentText(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(1)}%` : "-";
}

export function numericStat(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function compactHashText(value, visibleLength = 12) {
  const text = String(value || "").trim();
  if (!text) return "-";
  if (text.length <= visibleLength) return text;
  return `${text.slice(0, visibleLength)}...`;
}

export function moneyText(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "$0.00";
  const sign = number < 0 ? "-" : "";
  return `${sign}$${Math.abs(number).toFixed(2)}`;
}

export function moneyOrDash(value) {
  return hasDisplayValue(value) ? moneyText(value) : "-";
}

export function profitClass(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "";
  return number > 0 ? "positive" : "negative";
}

export function percentOrDash(value) {
  return hasDisplayValue(value) ? percentText(value) : "-";
}

export function hasDisplayValue(value) {
  return value !== null && value !== undefined && value !== "" && value !== "-";
}

export function dailySummaryMetric(source, paths) {
  for (const path of paths) {
    const value = readSummaryPath(source, path);
    if (hasDisplayValue(value)) return value;
  }
  return "-";
}

export function readSummaryPath(source, path) {
  if (!source || typeof source !== "object") return undefined;
  let value = source;
  for (const key of String(path).split(".")) {
    if (!value || typeof value !== "object" || !(key in value)) return undefined;
    value = value[key];
  }
  return value;
}

export function dailyLogCount(payload, level) {
  const explicit = dailySummaryMetric(payload, [
    `${String(level).toLowerCase()}Count`,
    `${String(level).toUpperCase()}Count`,
  ]);
  if (hasDisplayValue(explicit) && explicit !== "-") return explicit;
  const logs = Array.isArray(payload.importantLogs) ? payload.importantLogs : [];
  const normalized = String(level).toUpperCase();
  return logs.filter((item) => String(item.level || "").toUpperCase() === normalized).length;
}

export function negativeRatioText(negativeCount, sampleCount) {
  const negative = Number(negativeCount);
  const sample = Number(sampleCount);
  if (!Number.isFinite(negative) || !Number.isFinite(sample) || sample <= 0) return "-";
  return `${(negative / sample * 100).toFixed(1)}%`;
}

export function dailySummaryTrade(payload, paths) {
  const trade = dailySummaryMetric(payload, paths);
  return trade && typeof trade === "object" && !Array.isArray(trade) ? trade : {};
}

export function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}
