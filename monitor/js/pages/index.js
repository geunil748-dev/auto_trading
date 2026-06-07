export const HISTORY_PAGES = new Set([
  "activity",
  "candidateHistory",
  "runSummary",
  "entryReasonStats",
  "backtest",
]);

export function shouldLoadHistoryForPage(page) {
  return HISTORY_PAGES.has(page);
}
