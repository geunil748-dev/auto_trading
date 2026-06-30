from __future__ import annotations

import pytest

from trading_bot.slack_digest_notifier import SlackDigestError, send_slack_digest_message


class Response:
    ok = True
    status_code = 200


def test_send_slack_digest_message_posts_plain_text_only() -> None:
    calls = []

    def post(url, *, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    assert send_slack_digest_message(
        "https://hooks.slack.test/example",
        "[AUTO_TRADING_DATA_DIGEST]\nbody",
        post=post,
    )

    assert calls == [
        (
            "https://hooks.slack.test/example",
            {"text": "[AUTO_TRADING_DATA_DIGEST]\nbody"},
            10,
        )
    ]
    assert "files" not in calls[0][1]
    assert "thread_ts" not in calls[0][1]


def test_send_slack_digest_message_rejects_missing_webhook() -> None:
    with pytest.raises(SlackDigestError, match="missing_webhook"):
        send_slack_digest_message("", "body", post=lambda *args, **kwargs: Response())


def test_send_slack_digest_message_raises_safe_status_error() -> None:
    class FailedResponse:
        ok = False
        status_code = 500

    with pytest.raises(SlackDigestError, match="slack_status_500"):
        send_slack_digest_message(
            "https://hooks.slack.test/example",
            "body",
            post=lambda *args, **kwargs: FailedResponse(),
        )
