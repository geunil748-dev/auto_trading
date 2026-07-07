from trading_bot.adapters.kis_websocket import KisWebSocketSubscription
from trading_bot.adapters.kis_websocket_real import KisRealWebSocketClient
from trading_bot.config import KisWebSocketSettings


def test_real_websocket_skeleton_unconfigured_when_settings_are_empty() -> None:
    client = KisRealWebSocketClient(
        KisWebSocketSettings(
            enabled=False,
            app_key="",
            app_secret="",
            approval_key="",
            ws_url="",
            account_no="",
            account_product="01",
        )
    )

    assert client.configured() is False
    assert client.connect().connected is False


def test_real_websocket_skeleton_configured_without_external_connect() -> None:
    client = KisRealWebSocketClient(
        KisWebSocketSettings(
            enabled=True,
            app_key="app",
            app_secret="secret",
            approval_key="approval",
            ws_url="wss://kis.example",
            account_no="12345678",
            account_product="01",
        )
    )

    assert client.configured() is True
    assert client.connect().connected is False
    assert client.subscribe(KisWebSocketSubscription(" aapl ", "price")).connected is False
