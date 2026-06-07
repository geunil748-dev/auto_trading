export function createRouter({ defaultPage = "dashboard", allowedPages = [], onPageChange } = {}) {
  const allowed = new Set(allowedPages);
  let current = defaultPage;

  function normalize(page) {
    if (!page) return defaultPage;
    if (allowed.size === 0 || allowed.has(page)) return page;
    return defaultPage;
  }

  function navigate(page) {
    const next = normalize(page);
    const changed = next !== current;
    current = next;
    onPageChange?.(current, { changed });
    return current;
  }

  function currentPage() {
    return current;
  }

  function render() {
    onPageChange?.(current, { changed: false });
    return current;
  }

  return { navigate, currentPage, render };
}
