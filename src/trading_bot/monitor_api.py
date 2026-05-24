from __future__ import annotations

import json
from pathlib import Path


class MonitorStateReader:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def read(self) -> dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))


def authorize_bearer(header: str | None, expected_token: str) -> bool:
    if not expected_token:
        return False
    return header == f"Bearer {expected_token}"
