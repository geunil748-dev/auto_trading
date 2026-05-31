window.runtimeControls = (() => {
  const toggleButton = document.querySelector("#toggleRealOrders");
  const securityBar = document.querySelector(".security-bar");
  if (securityBar && ["localhost", "127.0.0.1", "::1"].includes(location.hostname)) {
    securityBar.hidden = true;
  }

  function bind(onToggle) {
    toggleButton?.addEventListener("click", onToggle);
  }

  function setBusy(busy) {
    if (toggleButton) {
      toggleButton.disabled = busy;
    }
  }

  function render(runtime) {
    const fallback = {
      envEnabled: false,
      emergencyStop: true,
      manualEnabled: false,
      ordersUnlocked: false,
      maxOrderKrw: 0,
      maxDailyOrderKrw: 0,
    };
    const realTrading = runtime.realTrading || fallback;
    const monitorAuth = runtime.monitorAuth || {};
    const ordersUnlocked = realTrading.ordersUnlocked === true;
    const modeLabel = runtime.modeLabel || (ordersUnlocked ? "실투자 대기" : "모의투자");
    const status = orderStatusText(realTrading);
    document.querySelector("#operatingMode").textContent = modeLabel;
    document.querySelector("#realOrderStatus").textContent = ordersUnlocked ? status : "";
    if (securityBar) {
      securityBar.hidden =
        monitorAuth.localBypass === true || monitorAuth.tokenConfigured !== true;
    }
    if (toggleButton) {
      toggleButton.textContent = realTrading.manualEnabled
        ? "실투자 주문 잠금"
        : "실투자 주문 허용";
      toggleButton.classList.toggle("is-unlocked", realTrading.manualEnabled);
    }
  }

  function orderStatusText(realTrading) {
    if (!realTrading.envEnabled) {
      return ".env의 REAL_TRADING_ENABLED가 꺼져 있어 실투자 주문이 막혀 있습니다.";
    }
    if (realTrading.emergencyStop) {
      return ".env의 REAL_EMERGENCY_STOP이 켜져 있어 실투자 주문이 막혀 있습니다.";
    }
    if (!realTrading.manualEnabled) {
      return "화면 버튼이 꺼져 있어 실투자 주문이 막혀 있습니다.";
    }
    return `실투자 주문 대기 중입니다. 1회 ${formatKrw(realTrading.maxOrderKrw)} / 일일 ${formatKrw(realTrading.maxDailyOrderKrw)} 한도`;
  }

  function formatKrw(value) {
    return `${Number(value || 0).toLocaleString("ko-KR")}원`;
  }

  return { bind, render, setBusy };
})();
