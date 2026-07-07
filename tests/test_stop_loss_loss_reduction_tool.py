from __future__ import annotations

import json
from pathlib import Path

from tools.analyze_stop_loss_loss_reduction import main


FIXTURE = Path(__file__).parent / "fixtures" / "stop_loss_loss_reduction_rows.json"


def test_stop_loss_tool_writes_json_summary_without_printing_rows(tmp_path: Path, capsys) -> None:
    output = tmp_path / "stop_loss_analysis.json"

    result = main([
        "--input",
        str(FIXTURE),
        "--output",
        str(output),
        "--format",
        "json",
    ])

    captured = capsys.readouterr()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert "rows=4" in captured.out
    assert "stop_loss=2" in captured.out
    assert "PULL" not in captured.out
    assert "WEAK" not in captured.out
    assert payload["dataScope"]["stopLossCount"] == 2
    assert payload["actionBoundary"].startswith("analysis_only:")


def test_stop_loss_tool_writes_markdown_with_explicit_create_dirs(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "stop_loss_analysis.md"

    missing_parent = main([
        "--input",
        str(FIXTURE),
        "--output",
        str(output),
        "--format",
        "markdown",
    ])
    created = main([
        "--input",
        str(FIXTURE),
        "--output",
        str(output),
        "--format",
        "markdown",
        "--create-dirs",
    ])

    text = output.read_text(encoding="utf-8")
    assert missing_parent == 2
    assert created == 0
    assert text.startswith("# STOP_LOSS Loss-Reduction Analysis")
    assert "Action boundary: analysis_only:" in text
    assert "profit_giveback_review" in text


def test_stop_loss_tool_fails_safely_for_invalid_inputs(tmp_path: Path, capsys) -> None:
    invalid_json = tmp_path / "invalid.json"
    not_a_list = tmp_path / "object.json"
    missing_required = tmp_path / "missing_required.json"
    output = tmp_path / "out.json"
    invalid_json.write_text("{", encoding="utf-8")
    not_a_list.write_text("{}", encoding="utf-8")
    missing_required.write_text('[{"ticker": "AAA"}]', encoding="utf-8")

    missing_file_result = main(["--input", str(tmp_path / "missing_file.json"), "--output", str(output)])
    invalid_json_result = main(["--input", str(invalid_json), "--output", str(output)])
    not_a_list_result = main(["--input", str(not_a_list), "--output", str(output)])
    missing_required_result = main(["--input", str(missing_required), "--output", str(output)])

    captured = capsys.readouterr()
    assert missing_file_result == 2
    assert invalid_json_result == 2
    assert not_a_list_result == 2
    assert missing_required_result == 2
    assert "input file not found" in captured.err
    assert "input JSON is invalid" in captured.err
    assert "input JSON must be a list" in captured.err
    assert "missing required field" in captured.err
