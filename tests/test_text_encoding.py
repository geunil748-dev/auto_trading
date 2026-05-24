from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_PATHS = [
    ROOT / "src",
    ROOT / "monitor",
    ROOT / "README.md",
    ROOT / "db",
]
MOJIBAKE_MARKERS = (
    "\ufffd",
    "?",
    "?먯",
    "?쒖",
    "?섏",
    "紐",
    "醫",
    "蹂",
    "珥",
    "二쇰",
    "泥닿",
    "濡쒓",
    "ì",
    "ëª",
)


def test_user_facing_text_has_no_known_mojibake() -> None:
    offenders: list[str] = []
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker!r}")

    assert offenders == []


def _text_files() -> list[Path]:
    files: list[Path] = []
    for root in TEXT_PATHS:
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.suffix in {".py", ".js", ".html", ".css", ".md", ".sql"}
        )
    return files
