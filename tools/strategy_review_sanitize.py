from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any


SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[^\s,;\"'}]+"),
    re.compile(
        r"(?i)\b([A-Z_]*(TOKEN|SECRET|PASSWORD|API_KEY|APP_KEY|APPSECRET|"
        r"ACCOUNT_NO|ACCOUNT_PRODUCT|CANO|ACNT_PRDT_CD|DB_PASSWORD|DSN|"
        r"BEARER|CHAT_ID)[A-Z_]*)\s*[:=]\s*[^,\s;\"'}]+"
    ),
    re.compile(r"(?i)\b(authorization)\s*[:=]\s*[^,\s;\"'}]+"),
)


def sanitize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    text = str(value)
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub(lambda match: _redacted_match(match), text)
    return text


def _redacted_match(match: re.Match[str]) -> str:
    text = match.group(0)
    if "=" in text:
        return text.split("=", 1)[0] + "=<redacted>"
    if ":" in text:
        return text.split(":", 1)[0] + ":<redacted>"
    return "<redacted>"


def _safe_error(text: str) -> str:
    return str(sanitize_value(text))
