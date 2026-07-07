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
<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="1"><fill><patternFill patternType="none"/></fill></fills>
<borders count="1"><border/></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>"""

    def _worksheet(self, rows: list[list[Any]]) -> str:
        worksheet_rows = "\n".join(
            f'<row r="{row_index}">'
            + "".join(
                _cell_xml(row_index, col_index, value)
                for col_index, value in enumerate(row, start=1)
            )
            + "</row>"
            for row_index, row in enumerate(rows[:1_048_576], start=1)
        )
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
<sheetData>{worksheet_rows}</sheetData>
</worksheet>"""


def _cell_xml(row: int, col: int, value: Any) -> str:
    ref = f"{_column_name(col)}{row}"
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return f'<c r="{ref}" t="n"><v>{value}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{_xml_text(str(value))}</t></is></c>'


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
