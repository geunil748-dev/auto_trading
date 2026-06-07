export function initSidebar({ container, items, activePage, onNavigate }) {
  if (!container) return [];

  const menuContainer = container.querySelector("#sideNavMenu") || container;
  menuContainer.querySelectorAll(".nav-item").forEach((item) => item.remove());

  const buttons = items.map((item) => {
    const button = document.createElement("button");
    button.className = "nav-item";
    button.type = "button";
    button.dataset.page = item.page;
    button.dataset.icon = item.icon;
    button.classList.toggle("active", item.page === activePage);
    button.setAttribute("aria-current", item.page === activePage ? "page" : "false");

    const label = document.createElement("span");
    label.textContent = item.label;
    button.appendChild(label);

    button.addEventListener("click", () => onNavigate?.(item.page));

    menuContainer.appendChild(button);
    return button;
  });

  return buttons;
}

export function setActiveSidebarItem(container, activePage) {
  if (!container) return;
  container.querySelectorAll(".nav-item").forEach((button) => {
    const isActive = button.dataset.page === activePage;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
  });
}
