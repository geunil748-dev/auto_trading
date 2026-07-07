from __future__ import annotations

from dataclasses import dataclass

from trading_bot.adapters.kis_websocket import KisWebSocketSubscription
from trading_bot.config import KisWebSocketSettings


@dataclass(frozen=True)
class KisRealWebSocketStatus:
    configured: bool
    connected: bool
    message: str


class KisRealWebSocketClient:
    """실투자 WebSocket 연동을 위한 안전 skeleton.

    현재 단계에서는 외부 연결을 만들지 않고 설정/구독 인터페이스만 고정한다.
    """

    def __init__(self, settings: KisWebSocketSettings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.enabled
            and self.settings.ws_url
            and self.settings.app_key
            and self.settings.app_secret
            and self.settings.approval_key
            and self.settings.account_no
        )

    def connect(self) -> KisRealWebSocketStatus:
        return KisRealWebSocketStatus(
            configured=self.configured(),
            connected=False,
            message="실투자 WebSocket skeleton은 아직 외부 연결을 만들지 않습니다.",
        )

    def subscribe(self, subscription: KisWebSocketSubscription) -> KisRealWebSocketStatus:
        ticker = subscription.ticker.strip().upper()
        channel = subscription.channel.strip()
        configured = self.configured() and bool(ticker and channel)
        return KisRealWebSocketStatus(
            configured=configured,
            connected=False,
            message="실투자 WebSocket 구독은 아직 자동매매에 연결되지 않았습니다.",
        )
