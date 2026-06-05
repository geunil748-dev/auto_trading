from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_PATHS = [
    ROOT / "src",
    ROOT / "monitor",
    ROOT / "mobile" / "stock_monitor_app" / "lib",
    ROOT / "tests",
    ROOT / "tools",
    ROOT / "README.md",
    ROOT / "db",
]
MOJIBAKE_MARKERS = tuple(
    "".join(chr(codepoint) for codepoint in item)
    for item in (
        (0xFFFD,),
        (0x3F, 0x3F),
        (0x3F, 0x7642, 0x3F),
        (0x7B8C, 0x3F),
        (0x96C5, 0xB69F, 0xB216),
        (0x7B8C, 0xFF4B, 0xB5AF),
        (0x56A5, 0x226A, 0xBB84),
        (0xCC59, 0xD637),
        (0xCC58, 0xC9E7),
        (0xF9CF,),
        (0x91AB,),
        (0x8E42,),
        (0x73E5,),
        (0x4E8C, 0xC1F0),
        (0xF9E3, 0xB2FF),
        (0x6FE1, 0xC493),
        (0x00EC, 0x009E),
        (0x00EB, 0x00AA),
    )
)


def test_user_facing_text_has_no_known_mojibake() -> None:
    offenders: list[str] = []
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {marker!r}")

    assert offenders == []


def test_start_scripts_bootstrap_utf8_console() -> None:
    for path in (
        ROOT / "tools" / "start_monitor_server.ps1",
        ROOT / "tools" / "start_scheduler.ps1",
    ):
        text = path.read_text(encoding="utf-8")
        assert "scripts\\Set-Utf8Console.ps1" in text
        assert ". $utf8ConsoleScript -Quiet" in text

    for path in (
        ROOT / "tools" / "start_monitor_server.cmd",
        ROOT / "tools" / "start_scheduler.cmd",
    ):
        text = path.read_text(encoding="utf-8")
        assert "chcp 65001" in text
        assert "set PYTHONUTF8=1" in text
        assert "set PYTHONIOENCODING=utf-8" in text


def _text_files() -> list[Path]:
    files: list[Path] = []
    for root in TEXT_PATHS:
        if root.is_file():
            files.append(root)
            continue
        files.extend(
            path
            for path in root.rglob("*")
            if path.suffix in {".py", ".js", ".html", ".css", ".md", ".sql", ".ps1"}
        )
    return files
