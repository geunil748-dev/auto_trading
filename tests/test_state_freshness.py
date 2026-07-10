import json
import os
from datetime import datetime, timedelta, timezone

from trading_bot.scheduled_tasks import _state_freshness


def _write_state(path, last_updated: str) -> None:
    path.write_text(json.dumps({"last_updated": last_updated}), encoding="utf-8")


def test_state_freshness_prefers_recent_internal_timestamp_over_old_mtime(tmp_path) -> None:
    now = datetime(2026, 7, 10, 13, 35, tzinfo=timezone.utc)
    path = tmp_path / "state.json"
    _write_state(path, (now - timedelta(seconds=30)).isoformat())
    old = (now - timedelta(hours=1)).timestamp()
    os.utime(path, (old, old))

    freshness = _state_freshness(path, now=now)
    assert freshness["source"] == "last_updated"
    assert freshness["age_seconds"] == 30


def test_state_freshness_keeps_genuinely_old_internal_timestamp_stale(tmp_path) -> None:
    now = datetime(2026, 7, 10, 13, 35, tzinfo=timezone.utc)
    path = tmp_path / "state.json"
    _write_state(path, (now - timedelta(minutes=11)).isoformat())
    assert _state_freshness(path, now=now)["age_seconds"] == 660


def test_state_freshness_falls_back_to_mtime_for_invalid_timestamp(tmp_path, caplog) -> None:
    now = datetime(2026, 7, 10, 13, 35, tzinfo=timezone.utc)
    path = tmp_path / "state.json"
    _write_state(path, "not-a-timestamp")
    recent = (now - timedelta(seconds=45)).timestamp()
    os.utime(path, (recent, recent))

    freshness = _state_freshness(path, now=now)
    assert freshness["source"] == "file_mtime"
    assert freshness["age_seconds"] == 45
    assert "state_last_updated_parse_failed" in caplog.text


def test_state_freshness_normalizes_kst_and_naive_timestamps(tmp_path) -> None:
    now = datetime(2026, 7, 10, 13, 35, tzinfo=timezone.utc)
    path = tmp_path / "state.json"
    _write_state(path, "2026-07-10T22:34:00+09:00")
    assert _state_freshness(path, now=now)["age_seconds"] == 60

    _write_state(path, "2026-07-10T13:34:00")
    freshness = _state_freshness(path, now=now)
    assert freshness["source"] == "last_updated_naive_utc"
    assert freshness["age_seconds"] == 60
