from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trading_bot.stop_loss_loss_reduction_analysis import (  # noqa: E402
    analyze_stop_loss_loss_reduction,
)


REQUIRED_FIELD_GROUPS = (
    ("trade_date", "tradeDate"),
    ("ticker", "symbol"),
    ("final_exit_reason", "finalExitReason", "exit_reason"),
    ("final_profit_rate", "finalProfitRate", "profit_rate"),
)


class ToolError(Exception):
    pass


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rows = load_rows(args.input)
        payload = analyze_stop_loss_loss_reduction(rows)
        write_output(payload, args.output, args.format, create_dirs=args.create_dirs)
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    scope = payload["dataScope"]
    print(
        "Wrote STOP_LOSS analysis "
        f"to {args.output} "
        f"(rows={scope['rowCount']}, completed={scope['completedCount']}, "
        f"stop_loss={scope['stopLossCount']}, warnings={len(payload['warnings'])})"
    )
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze already-exported STOP_LOSS/trade rows from a local JSON file.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Local JSON file containing a list of row objects.")
    parser.add_argument("--output", required=True, type=Path, help="Output path for JSON or Markdown analysis.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument(
        "--create-dirs",
        action="store_true",
        help="Create the output parent directory when it does not exist.",
    )
    return parser.parse_args(argv)


def load_rows(path: Path) -> list[Mapping[str, Any]]:
    if not path.exists():
        raise ToolError(f"input file not found: {path}")
    if not path.is_file():
        raise ToolError(f"input path is not a file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"input JSON is invalid at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(payload, list):
        raise ToolError("input JSON must be a list of row objects")
    rows: list[Mapping[str, Any]] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, Mapping):
            raise ToolError(f"input row {index} must be an object")
        _validate_row(item, index)
        rows.append(item)
    return rows


def write_output(payload: Mapping[str, Any], path: Path, output_format: str, *, create_dirs: bool) -> None:
    parent = path.parent
    if parent and not parent.exists():
        if not create_dirs:
            raise ToolError(f"output parent directory does not exist: {parent}; use --create-dirs to create it")
        parent.mkdir(parents=True, exist_ok=True)

    if output_format == "markdown":
        rendered = render_markdown(payload)
    else:
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    path.write_text(rendered + "\n", encoding="utf-8")


def render_markdown(payload: Mapping[str, Any]) -> str:
    scope = payload["dataScope"]
    baseline = payload["baseline"]
    lines = [
        "# STOP_LOSS Loss-Reduction Analysis",
        "",
        f"- Generated: {payload['generatedAt']}",
        f"- Action boundary: {payload['actionBoundary']}",
        f"- Rows: {scope['rowCount']}",
        f"- Completed rows: {scope['completedCount']}",
        f"- STOP_LOSS rows: {scope['stopLossCount']}",
        f"- STOP_LOSS share of completed losses: {_pct(baseline['stopLossShareOfLossRate'])}",
        f"- Total STOP_LOSS loss rate: {_pct(baseline['totalStopLossLossRate'])}",
        "",
        "## Opportunity Signals",
    ]
    signals = payload.get("opportunitySignals") or {}
    if signals:
        lines.extend(
            f"- {name}: count={stats['count']}, total_loss_rate={_pct(stats['totalStopLossLossRate'])}"
            for name, stats in signals.items()
        )
    else:
        lines.append("- No STOP_LOSS opportunity signals found.")
    lines.extend(["", "## Warnings"])
    warnings = list(payload.get("warnings", []))
    lines.extend(f"- {warning}" for warning in warnings) if warnings else lines.append("- None")
    lines.extend(["", "## Evidence Checklist"])
    lines.extend(f"- [ ] {item}" for item in payload.get("evidenceChecklist", []))
    return "\n".join(lines)


def _validate_row(row: Mapping[str, Any], index: int) -> None:
    for names in REQUIRED_FIELD_GROUPS:
        if _first_present(row, names) is None:
            raise ToolError(f"input row {index} is missing required field: {'/'.join(names)}")
    if _rate(_first_present(row, ("final_profit_rate", "finalProfitRate", "profit_rate"))) is None:
        raise ToolError(f"input row {index} has malformed final profit rate")


def _first_present(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    return next((row.get(name) for name in names if name in row and row.get(name) not in (None, "")), None)


def _rate(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.startswith("+"):
        text = text[1:]
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _pct(value: Any) -> str:
    number = float(value or 0)
    return f"{number * 100:.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
