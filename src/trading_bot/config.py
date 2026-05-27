from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 로컬 규칙 테스트에서 선택 의존성을 허용한다.
    load_dotenv = None

RUNTIME_SETTINGS_PATH = Path("monitor/trading_settings.json")
RUNTIME_SETTING_KEYS = {
    "max_position_loss",
    "take_profit_rate",
    "min_total_score",
    "min_price_usd",
    "max_price_usd",
    "min_opening_price_change",
    "min_volume_ratio",
    "max_opening_gap",
}


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
    min_total_score: float = 70.0
    trailing_stop_drop: float = 0.03
    breakout_k: float = 0.50
    max_intraday_entry_rounds: int = 2
    max_intraday_buy_intents_per_round: int = 1
    min_pyramiding_profit_rate: float = 0.03
    news_cache_ttl_minutes: int = 30
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
class KisWebSocketSettings:
    enabled: bool
    app_key: str
    app_secret: str
    approval_key: str
    ws_url: str
    account_no: str
    account_product: str
    reconnect_seconds: int = 5


@dataclass(frozen=True)
class NotificationSettings:
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


def load_settings() -> TradingSettings:
    if load_dotenv is not None:
        load_dotenv()

    settings = TradingSettings(
        mock_trading=_bool_env("MOCK_TRADING", True),
        min_price_usd=_float_env("MIN_PRICE_USD", 5.0),
        max_price_usd=_float_env("MAX_PRICE_USD", 50.0),
        max_open_positions=_int_env("MAX_OPEN_POSITIONS", 5),
        max_selected_candidates=_int_env("MAX_SELECTED_CANDIDATES", 5),
        max_account_exposure=_float_env("MAX_ACCOUNT_EXPOSURE", 0.80),
        max_position_exposure=_float_env("MAX_POSITION_EXPOSURE", 0.20),
        max_opening_gap=_float_env("MAX_OPENING_GAP", 0.20),
        min_opening_price_change=_float_env("MIN_OPENING_PRICE_CHANGE", 0.03),
        min_volume_ratio=_float_env("MIN_VOLUME_RATIO", 1.50),
        min_total_score=_float_env("MIN_TOTAL_SCORE", 70.0),
        max_intraday_entry_rounds=_int_env("MAX_INTRADAY_ENTRY_ROUNDS", 2),
        max_intraday_buy_intents_per_round=_int_env(
            "MAX_INTRADAY_BUY_INTENTS_PER_ROUND",
            1,
        ),
        min_pyramiding_profit_rate=_float_env("MIN_PYRAMIDING_PROFIT_RATE", 0.03),
        news_cache_ttl_minutes=_int_env("NEWS_CACHE_TTL_MINUTES", 30),
        take_profit_rate=_float_env("TAKE_PROFIT_RATE", 0.05),
        real_trading_enabled=_bool_env("REAL_TRADING_ENABLED", False),
        real_max_order_krw=_int_env("REAL_MAX_ORDER_KRW", 100000),
        real_max_daily_order_krw=_int_env("REAL_MAX_DAILY_ORDER_KRW", 300000),
        real_emergency_stop=_bool_env("REAL_EMERGENCY_STOP", True),
    )
    return _apply_runtime_settings(settings)


def runtime_risk_settings_payload(
    settings: TradingSettings | None = None,
) -> dict[str, float]:
    current = settings or load_settings()
    return {
        "stopLossRate": current.max_position_loss,
        "stopLossPercent": abs(current.max_position_loss * 100),
        "takeProfitRate": current.take_profit_rate,
        "takeProfitPercent": current.take_profit_rate * 100,
        "minTotalScore": current.min_total_score,
        "minPriceUsd": current.min_price_usd,
        "maxPriceUsd": current.max_price_usd,
        "minOpeningPriceChangePercent": current.min_opening_price_change * 100,
        "minVolumeRatio": current.min_volume_ratio,
        "maxOpeningGapPercent": current.max_opening_gap * 100,
    }


def save_runtime_risk_settings(
    stop_loss_percent: float,
    take_profit_percent: float,
    min_total_score: float | None = None,
    min_price_usd: float | None = None,
    max_price_usd: float | None = None,
    min_opening_price_change_percent: float | None = None,
    min_volume_ratio: float | None = None,
    max_opening_gap_percent: float | None = None,
    path: Path = RUNTIME_SETTINGS_PATH,
) -> dict[str, float]:
    stop = _validate_percent(stop_loss_percent, "손절 비율")
    profit = _validate_percent(take_profit_percent, "익절 비율")
    payload = _read_runtime_settings(path)
    payload.update({
        "max_position_loss": -(stop / 100),
        "take_profit_rate": profit / 100,
    })
    if min_total_score is not None:
        payload["min_total_score"] = _validate_score(min_total_score, "선정점수")
    if min_price_usd is not None or max_price_usd is not None:
        current_min = min_price_usd if min_price_usd is not None else payload.get("min_price_usd")
        current_max = max_price_usd if max_price_usd is not None else payload.get("max_price_usd")
        min_price, max_price = _validate_price_range(current_min, current_max)
        payload["min_price_usd"] = min_price
        payload["max_price_usd"] = max_price
    if min_opening_price_change_percent is not None:
        payload["min_opening_price_change"] = (
            _validate_percent_range(min_opening_price_change_percent, "장초반 상승률") / 100
        )
    if min_volume_ratio is not None:
        payload["min_volume_ratio"] = _validate_volume_ratio(min_volume_ratio, "거래량 비율")
    if max_opening_gap_percent is not None:
        payload["max_opening_gap"] = (
            _validate_percent_range(max_opening_gap_percent, "시가 갭 상한") / 100
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    current = load_settings()
    return runtime_risk_settings_payload(
        replace(
            current,
            max_position_loss=payload["max_position_loss"],
            take_profit_rate=payload["take_profit_rate"],
            min_total_score=payload.get("min_total_score", current.min_total_score),
            min_price_usd=payload.get("min_price_usd", current.min_price_usd),
            max_price_usd=payload.get("max_price_usd", current.max_price_usd),
            min_opening_price_change=payload.get(
                "min_opening_price_change",
                current.min_opening_price_change,
            ),
            min_volume_ratio=payload.get("min_volume_ratio", current.min_volume_ratio),
            max_opening_gap=payload.get("max_opening_gap", current.max_opening_gap),
        )
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


def load_kis_websocket_settings(real: bool = False) -> KisWebSocketSettings:
    if load_dotenv is not None:
        load_dotenv()

    prefix = "KIS_REAL_WS" if real else "KIS_WS"
    kis_prefix = "KIS_REAL" if real else "KIS"

    return KisWebSocketSettings(
        enabled=_bool_env(f"{prefix}_ENABLED", False),
        app_key=os.getenv(f"{prefix}_APP_KEY") or os.getenv(f"{kis_prefix}_APP_KEY", ""),
        app_secret=os.getenv(f"{prefix}_APP_SECRET")
        or os.getenv(f"{kis_prefix}_APP_SECRET", ""),
        approval_key=os.getenv(f"{prefix}_APPROVAL_KEY", ""),
        ws_url=os.getenv(f"{prefix}_URL", "").rstrip("/"),
        account_no=os.getenv(f"{prefix}_ACCOUNT_NO")
        or os.getenv(f"{kis_prefix}_ACCOUNT_NO", ""),
        account_product=os.getenv(f"{prefix}_ACCOUNT_PRODUCT")
        or os.getenv(f"{kis_prefix}_ACCOUNT_PRODUCT", "01"),
        reconnect_seconds=_int_env(f"{prefix}_RECONNECT_SECONDS", 5),
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


def _apply_runtime_settings(settings: TradingSettings) -> TradingSettings:
    overrides = _read_runtime_settings()
    if not overrides:
        return settings
    return replace(settings, **overrides)


def _read_runtime_settings(path: Path = RUNTIME_SETTINGS_PATH) -> dict[str, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    values: dict[str, float] = {}
    for key in RUNTIME_SETTING_KEYS:
        if key in payload:
            values[key] = float(payload[key])
    return values


def _validate_percent(value: float, label: str) -> float:
    percent = float(value)
    if percent <= 0 or percent > 50:
        raise ValueError(f"{label}은 0보다 크고 50 이하로 입력해 주세요.")
    return percent


def _validate_score(value: float, label: str) -> float:
    score = float(value)
    if score < 0 or score > 100:
        raise ValueError(f"{label}는 0점 이상 100점 이하로 입력해 주세요.")
    return score


def _validate_price_range(
    min_value: float | None,
    max_value: float | None,
) -> tuple[float, float]:
    if min_value is None or max_value is None:
        raise ValueError("최저 가격과 최고 가격을 모두 입력해 주세요.")
    min_price = float(min_value)
    max_price = float(max_value)
    if min_price <= 0 or max_price <= 0:
        raise ValueError("가격 조건은 0보다 크게 입력해 주세요.")
    if min_price >= max_price:
        raise ValueError("최저 가격은 최고 가격보다 작아야 합니다.")
    return min_price, max_price


def _validate_percent_range(value: float, label: str) -> float:
    percent = float(value)
    if percent < 0 or percent > 500:
        raise ValueError(f"{label}은 0 이상 500 이하로 입력해 주세요.")
    return percent


def _validate_volume_ratio(value: float, label: str) -> float:
    ratio = float(value)
    if ratio <= 0 or ratio > 100:
        raise ValueError(f"{label}은 0보다 크고 100 이하로 입력해 주세요.")
    return ratio
