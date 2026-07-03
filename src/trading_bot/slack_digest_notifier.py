from __future__ import annotations

from typing import Any, Protocol

try:
    import requests
except ImportError:  # pragma: no cover - dependency absence is handled at runtime.
    requests = None

SLACK_DIGEST_TIMEOUT_SECONDS = 10


class SlackPost(Protocol):
    def __call__(self, url: str, *, json: dict[str, str], timeout: int) -> Any: ...


class SlackDigestError(RuntimeError):
    pass


def send_slack_digest_message(
    webhook_url: str,
    text: str,
    *,
    post: SlackPost | None = None,
) -> bool:
    url = webhook_url.strip()
    if not url:
        raise SlackDigestError("missing_webhook")
    sender = post
    if sender is None:
        if requests is None:
            raise SlackDigestError("requests_unavailable")
        sender = requests.post
    for body in slack_digest_message_bodies(text):
        response = sender(
            url,
            json={"text": body},
            timeout=SLACK_DIGEST_TIMEOUT_SECONDS,
        )
        if not getattr(response, "ok", False):
            status_code = getattr(response, "status_code", "unknown")
            raise SlackDigestError(f"slack_status_{status_code}")
    return True


def slack_digest_message_bodies(text: str) -> list[str]:
    marker = "[AUTO_TRADING_DATA_PACKET]"
    if text.count(marker) <= 1:
        return [text]
    prefix, first_packet = text.split(marker, 1)
    packets = [marker + part for part in first_packet.split(marker)]
    packets[0] = prefix + packets[0]
    return packets
