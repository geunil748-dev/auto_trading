from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import KisWebSocketSettings


@dataclass(frozen=True)
class KisWebSocketSubscription:
    ticker: str
    channel: str


class KisWebSocketClient:
    """실투자 전 웹소켓 시세/체결 수신을 붙일 자리."""

    def __init__(self, settings: KisWebSocketSettings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return bool(
            self.settings.enabled
            and self.settings.ws_url
            and self.settings.app_key
            and self.settings.app_secret
        )
