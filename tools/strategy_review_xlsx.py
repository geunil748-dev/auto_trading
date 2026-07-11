from __future__ import annotations

import math
import re
import zipfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


class SimpleXlsxWriter:
    def __init__(self) -> None:
        self.sheets: list[tuple[str, list[list[Any]]]] = []

    def add_sheet(self, name: str, rows: list[dict[str, Any]]) -> None:
        sheet_name = _sheet_name(name, [item[0] for item in self.sheets])
        headers: list[str] = []
        for row in rows:
            for key in row:
                if key not in headers:
                    headers.append(key)
        values: list[list[Any]] = [headers] if headers else [["message"]]
        if rows:
            values.extend([[row.get(header) for header in headers] for row in rows])
        elif not headers:
            values.append(["no rows"])
        self.sheets.append((sheet_name, values))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types())
            archive.writestr("_rels/.rels", self._root_rels())
            archive.writestr("xl/workbook.xml", self._workbook())
            archive.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels())
            archive.writestr("xl/styles.xml", self._styles())
            for index, (_, rows) in enumerate(self.sheets, start=1):
                archive.writestr(
                    f"xl/worksheets/sheet{index}.xml",
                    self._worksheet(rows),
                )

    def _content_types(self) -> str:
        sheet_overrides = "\n".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(self.sheets) + 1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheet_overrides}
</Types>"""

    def _root_rels(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

    def _workbook(self) -> str:
        sheets = "\n".join(
            f'<sheet name="{_xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, (name, _) in enumerate(self.sheets, start=1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>{sheets}</sheets>
</workbook>"""

    def _workbook_rels(self) -> str:
        rels = "\n".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(self.sheets) + 1)
        )
        style_id = len(self.sheets) + 1
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{rels}
<Relationship Id="rId{style_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

    def _styles(self) -> str:
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3">
<numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00;[Red](&quot;$&quot;#,##0.00);-"/>
<numFmt numFmtId="165" formatCode="0.00%;[Red](0.00%);-"/>
<numFmt numFmtId="166" formatCode="#,##0;[Red](#,##0);-"/>
</numFmts>
<fonts count="2">
<font><sz val="10"/><name val="Calibri"/></font>
<font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border/>
<border><bottom style="thin"><color rgb="FF17365D"/></bottom></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right"/></xf>
</cellXfs>
</styleSheet>"""

    def _worksheet(self, rows: list[list[Any]]) -> str:
        headers = [str(value or "") for value in (rows[0] if rows else [])]
        column_styles = [_column_style(header) for header in headers]
        worksheet_rows = "\n".join(
            f'<row r="{row_index}"'
            + (' ht="30" customHeight="1"' if row_index == 1 else "")
            + ">"
            + "".join(
                _cell_xml(
                    row_index,
                    col_index,
                    value,
                    1 if row_index == 1 else column_styles[col_index - 1],
                )
                for col_index, value in enumerate(row, start=1)
            )
            + "</row>"
            for row_index, row in enumerate(rows[:1_048_576], start=1)
        )
        columns_xml = "".join(
            f'<col min="{index}" max="{index}" width="{width:.1f}" customWidth="1"/>'
            for index, width in enumerate(_column_widths(rows), start=1)
        )
        last_column = _column_name(max(1, len(headers)))
        last_row = max(1, min(len(rows), 1_048_576))
        auto_filter = f'<autoFilter ref="A1:{last_column}{last_row}"/>' if headers else ""
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetFormatPr defaultRowHeight="15"/>
<cols>{columns_xml}</cols>
<sheetData>{worksheet_rows}</sheetData>
{auto_filter}
</worksheet>"""


def _cell_xml(row: int, col: int, value: Any, style_id: int = 0) -> str:
    ref = f"{_column_name(col)}{row}"
    style = f' s="{style_id}"' if style_id else ""
    if value is None:
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{style} t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f'<c r="{ref}"{style} t="n"><v>{value}</v></c>'
    return f'<c r="{ref}"{style} t="inlineStr"><is><t>{_xml_text(str(value))}</t></is></c>'


def _column_widths(rows: list[list[Any]]) -> list[float]:
    column_count = max((len(row) for row in rows), default=1)
    widths: list[float] = []
    for column_index in range(column_count):
        sample = [
            row[column_index]
            for row in rows[:500]
            if column_index < len(row) and row[column_index] is not None
        ]
        content_width = max((_display_width(str(value)) for value in sample), default=8)
        widths.append(float(min(36, max(10, content_width + 2))))
    return widths


def _display_width(value: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in value)


def _column_style(header: str) -> int:
    normalized = header.strip().lower()
    if "rate" in normalized or "percent" in normalized or normalized.endswith("_ratio"):
        return 3
    if any(token in normalized for token in ("profit_usd", "price", "amount", "commission", "slippage")):
        return 2
    if any(
        token in normalized
        for token in ("count", "quantity", "_qty", "distance_seconds", "source_row")
    ):
        return 4
    return 0


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _sheet_name(name: str, existing: Sequence[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", name)[:31] or "sheet"
    if cleaned not in existing:
        return cleaned
    base = cleaned[:27]
    suffix = 1
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"[:31]


def _xml_text(text: str) -> str:
    cleaned = "".join(
        char
        for char in text
        if char in "\t\n\r" or ord(char) >= 32
    )
    return escape(cleaned, {'"': "&quot;"})
