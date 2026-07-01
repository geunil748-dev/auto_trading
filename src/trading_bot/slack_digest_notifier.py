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
    response = sender(
        url,
        json={"text": text},
        timeout=SLACK_DIGEST_TIMEOUT_SECONDS,
    )
    if getattr(response, "ok", False):
        return True
    status_code = getattr(response, "status_code", "unknown")
    raise SlackDigestError(f"slack_status_{status_code}")
