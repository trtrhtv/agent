"""Build a polished .xlsx from an LLM-generated spec (Module 2, step 2).

Spec shape (validated leniently — missing fields degrade gracefully):
{
  "product_name": str,
  "tagline": str,
  "theme": {"primary": "1F4E5F", "secondary": "EAF2F4", "accent": "F4A259"},
  "sheets": [
    {
      "name": str,                     # <= 31 chars, Excel limit
      "description": str,
      "columns": [{"header": str, "width": int, "format": "currency"|"percent"|"date"|"number"|null}],
      "rows": [[cell, ...], ...],      # strings starting with "=" become live formulas
      "totals_row": [cell, ...] | null
    }
  ],
  "how_to_use": [str, ...]
}
"""

from __future__ import annotations

import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

DEFAULT_THEME = {"primary": "1F4E5F", "secondary": "EAF2F4", "accent": "F4A259"}

NUMBER_FORMATS = {
    "currency": '"$"#,##0.00',
    "percent": "0.0%",
    "date": "yyyy-mm-dd",
    "number": "#,##0.00",
}

TITLE_ROW, TAGLINE_ROW, HEADER_ROW = 1, 2, 3
FIRST_DATA_ROW = HEADER_ROW + 1
_INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")


def _hex(color: str) -> str:
    return f"FF{str(color).lstrip('#').upper():0>6}"[:8]


def _sheet_title(name: str, index: int) -> str:
    clean = _INVALID_SHEET_CHARS.sub(" ", str(name or f"Sheet{index + 1}")).strip()
    return clean[:31] or f"Sheet{index + 1}"


def _write_data_sheet(ws: Worksheet, sheet_spec: dict, theme: dict) -> None:
    columns = sheet_spec.get("columns") or [{"header": "Item"}]
    n_cols = len(columns)
    primary = PatternFill("solid", fgColor=_hex(theme["primary"]))
    secondary = PatternFill("solid", fgColor=_hex(theme["secondary"]))
    white_bold = Font(color="FFFFFFFF", bold=True)
    thin_accent = Side(style="medium", color=_hex(theme["accent"]))

    # Title block
    ws.merge_cells(start_row=TITLE_ROW, start_column=1, end_row=TITLE_ROW, end_column=n_cols)
    title_cell = ws.cell(row=TITLE_ROW, column=1, value=str(sheet_spec.get("title") or ws.title))
    title_cell.font = Font(color="FFFFFFFF", bold=True, size=14)
    title_cell.alignment = Alignment(vertical="center")
    for col in range(1, n_cols + 1):
        ws.cell(row=TITLE_ROW, column=col).fill = primary
    ws.row_dimensions[TITLE_ROW].height = 26

    if sheet_spec.get("description"):
        ws.merge_cells(start_row=TAGLINE_ROW, start_column=1, end_row=TAGLINE_ROW, end_column=n_cols)
        tagline = ws.cell(row=TAGLINE_ROW, column=1, value=str(sheet_spec["description"]))
        tagline.font = Font(italic=True, size=10, color=_hex(theme["primary"]))

    # Header row
    formats: list[str | None] = []
    for i, col in enumerate(columns, start=1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=str(col.get("header") or f"Column {i}"))
        cell.fill = primary
        cell.font = white_bold
        cell.alignment = Alignment(horizontal="center", vertical="center")
        width = col.get("width")
        ws.column_dimensions[get_column_letter(i)].width = (
            int(width) if isinstance(width, (int, float)) and 6 <= width <= 80 else 18
        )
        formats.append(NUMBER_FORMATS.get(str(col.get("format") or "").lower()))

    # Frozen panes: title + header stay visible
    ws.freeze_panes = ws.cell(row=FIRST_DATA_ROW, column=1)

    # Data rows (strings starting with "=" are written as live formulas)
    rows = sheet_spec.get("rows") or []
    for r, row in enumerate(rows, start=FIRST_DATA_ROW):
        if not isinstance(row, list):
            continue
        for c in range(1, n_cols + 1):
            value = row[c - 1] if c - 1 < len(row) else None
            cell = ws.cell(row=r, column=c, value=value)
            if formats[c - 1] and not (isinstance(value, str) and not value.startswith("=")):
                cell.number_format = formats[c - 1]
            if r % 2 == 0:
                cell.fill = secondary

    # Totals row
    totals = sheet_spec.get("totals_row")
    if isinstance(totals, list):
        r = FIRST_DATA_ROW + len(rows)
        for c in range(1, n_cols + 1):
            value = totals[c - 1] if c - 1 < len(totals) else None
            cell = ws.cell(row=r, column=c, value=value)
            cell.font = Font(bold=True)
            cell.border = Border(top=thin_accent)
            if formats[c - 1]:
                cell.number_format = formats[c - 1]


def _write_instructions_sheet(ws: Worksheet, spec: dict, theme: dict) -> None:
    ws.merge_cells("A1:A1")
    ws.column_dimensions["A"].width = 95
    title = ws.cell(row=1, column=1, value=f"How to use: {spec.get('product_name', 'this template')}")
    title.font = Font(color="FFFFFFFF", bold=True, size=14)
    title.fill = PatternFill("solid", fgColor=_hex(theme["primary"]))
    ws.row_dimensions[1].height = 26

    steps = spec.get("how_to_use") or ["Fill in your data in the highlighted sheets."]
    row = 3
    for i, step in enumerate(steps, start=1):
        cell = ws.cell(row=row, column=1, value=f"{i}. {step}")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = max(18, 14 * (len(str(step)) // 90 + 1))
        row += 1

    footer = ws.cell(row=row + 1, column=1, value="Tip: cells with formulas update automatically — enter data, don't overwrite totals.")
    footer.font = Font(italic=True, size=10, color=_hex(theme["primary"]))


def build_xlsx(spec: dict, out_path: str) -> str:
    """Render the spec into a styled workbook; returns out_path."""
    theme = {**DEFAULT_THEME, **(spec.get("theme") or {})}
    wb = Workbook()
    wb.remove(wb.active)

    instructions = wb.create_sheet(title="Start Here")
    _write_instructions_sheet(instructions, spec, theme)

    sheets = spec.get("sheets") or []
    if not sheets:
        raise ValueError("spec has no sheets")
    for i, sheet_spec in enumerate(sheets):
        ws = wb.create_sheet(title=_sheet_title(sheet_spec.get("name"), i))
        _write_data_sheet(ws, {**sheet_spec, "title": sheet_spec.get("name")}, theme)

    wb.save(out_path)
    return out_path
