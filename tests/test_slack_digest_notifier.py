from __future__ import annotations

import pytest

from trading_bot.slack_digest_notifier import (
    SlackDigestError,
    send_slack_digest_message,
    slack_digest_message_bodies,
)


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


def test_send_slack_digest_message_posts_packet_chunks_in_order() -> None:
    calls = []
    text = "\n".join(
        [
            "[Daily Strategy Review]",
            "[AUTO_TRADING_DATA_PACKET]",
            "packet_id: packet-1",
            "report_date: 2026-07-02",
            "part: 1/2",
            "packet_complete: false",
            "chunk1",
            "[AUTO_TRADING_DATA_PACKET]",
            "packet_id: packet-1",
            "report_date: 2026-07-02",
            "part: 2/2",
            "packet_complete: true",
            "chunk2",
        ]
    )

    def post(url, *, json, timeout):
        calls.append(json["text"])
        return Response()

    assert send_slack_digest_message("https://hooks.slack.test/example", text, post=post)

    assert len(calls) == 2
    assert calls[0].startswith("[Daily Strategy Review]")
    assert "part: 1/2" in calls[0]
    assert calls[1].startswith("[AUTO_TRADING_DATA_PACKET]")
    assert "part: 2/2" in calls[1]
    assert "packet_complete: true" in calls[1]


def test_slack_digest_message_bodies_preserve_packet_headers() -> None:
    text = "\n".join(
        [
            "summary",
            "[AUTO_TRADING_DATA_PACKET]",
            "packet_id: packet-1",
            "report_date: 2026-07-02",
            "part: 1/2",
            "[AUTO_TRADING_DATA_PACKET]",
            "packet_id: packet-1",
            "report_date: 2026-07-02",
            "part: 2/2",
            "packet_complete: true",
        ]
    )

    bodies = slack_digest_message_bodies(text)

    assert len(bodies) == 2
    assert all("packet_id: packet-1" in body for body in bodies)
    assert all("report_date: 2026-07-02" in body for body in bodies)
    assert "packet_complete: true" in bodies[-1]


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
