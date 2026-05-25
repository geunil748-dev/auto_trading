from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 로컬 규칙 테스트에서 선택 의존성을 허용한다.
    load_dotenv = None


@dataclass(frozen=True)
class TradingSettings:
    mock_trading: bool = True
    min_price_usd: float = 5.0
    max_price_usd: float = 50.0
    max_open_positions: int = 5
    min_selected_candidates: int = 3
    max_selected_candidates: int = 5
    max_account_exposure: float = 0.80
    max_position_exposure: float = 0.20
    max_position_loss: float = -0.05
    take_profit_rate: float = 0.05
    max_daily_account_loss: float = -0.03
    max_fx_change: float = 0.02
    max_opening_gap: float = 0.20
    min_opening_price_change: float = 0.03
    min_volume_ratio: float = 1.50
    trailing_stop_drop: float = 0.03
    breakout_k: float = 0.50
    max_intraday_entry_rounds: int = 2
    max_intraday_buy_intents_per_round: int = 1
    min_pyramiding_profit_rate: float = 0.03
    real_trading_enabled: bool = False
    real_max_order_krw: int = 100000
    real_max_daily_order_krw: int = 300000
    real_emergency_stop: bool = True


@dataclass(frozen=True)
class KisSettings:
    app_key: str
    app_secret: str
    account_no: str
    account_product: str
    base_url: str


@dataclass(frozen=True)
class NotificationSettings:
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def load_settings() -> TradingSettings:
    if load_dotenv is not None:
        load_dotenv()

    return TradingSettings(
        mock_trading=_bool_env("MOCK_TRADING", True),
        max_open_positions=_int_env("MAX_OPEN_POSITIONS", 5),
        max_account_exposure=_float_env("MAX_ACCOUNT_EXPOSURE", 0.80),
        max_position_exposure=_float_env("MAX_POSITION_EXPOSURE", 0.20),
        max_intraday_entry_rounds=_int_env("MAX_INTRADAY_ENTRY_ROUNDS", 2),
        max_intraday_buy_intents_per_round=_int_env(
            "MAX_INTRADAY_BUY_INTENTS_PER_ROUND",
            1,
        ),
        min_pyramiding_profit_rate=_float_env("MIN_PYRAMIDING_PROFIT_RATE", 0.03),
        take_profit_rate=_float_env("TAKE_PROFIT_RATE", 0.05),
        real_trading_enabled=_bool_env("REAL_TRADING_ENABLED", False),
        real_max_order_krw=_int_env("REAL_MAX_ORDER_KRW", 100000),
        real_max_daily_order_krw=_int_env("REAL_MAX_DAILY_ORDER_KRW", 300000),
        real_emergency_stop=_bool_env("REAL_EMERGENCY_STOP", True),
    )


def load_notification_settings() -> NotificationSettings:
    if load_dotenv is not None:
        load_dotenv()

    return NotificationSettings(
        discord_webhook_url=os.getenv("ALERT_DISCORD_WEBHOOK_URL", ""),
        telegram_bot_token=os.getenv("ALERT_TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("ALERT_TELEGRAM_CHAT_ID", ""),
    )


def load_kis_settings() -> KisSettings:
    if load_dotenv is not None:
        load_dotenv()

    return KisSettings(
        app_key=_required_env("KIS_APP_KEY"),
        app_secret=_required_env("KIS_APP_SECRET"),
        account_no=_required_env("KIS_ACCOUNT_NO"),
        account_product=os.getenv("KIS_ACCOUNT_PRODUCT", "01"),
        base_url=os.getenv(
            "KIS_BASE_URL",
            "https://openapivts.koreainvestment.com:29443",
        ).rstrip("/"),
    )


def load_real_kis_settings() -> KisSettings:
    if load_dotenv is not None:
        load_dotenv()

    return KisSettings(
        app_key=_required_env("KIS_REAL_APP_KEY"),
        app_secret=_required_env("KIS_REAL_APP_SECRET"),
        account_no=_required_env("KIS_REAL_ACCOUNT_NO"),
        account_product=os.getenv("KIS_REAL_ACCOUNT_PRODUCT", "01"),
        base_url=os.getenv(
            "KIS_REAL_BASE_URL",
            "https://openapi.koreainvestment.com:9443",
        ).rstrip("/"),
    )


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    return default if raw is None else float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    return default if raw is None else int(raw)


def _required_env(name: str) -> str:
    raw = os.getenv(name)
    if not raw:
        raise ValueError(f"{name} is required")
    return raw
