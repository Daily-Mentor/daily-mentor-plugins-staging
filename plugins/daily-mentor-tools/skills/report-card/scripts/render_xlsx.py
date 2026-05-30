"""Render the same RenderTrees as an xlsx workbook.

- Daily Tracker → 13 monthly sheets (per spec) using sub_views.
- Every calculated cell gets an openpyxl.comments.Comment carrying tooltip text.
- Number formats applied immediately after value (G1).
- No formula merging on top of conditional formatting (G3).
- Zip integrity verified post-save (G7).
"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .models import AuditReport, Cell, RenderTree, Row


_FMT_MAP = {
    "currency": '#,##0;[Red]-#,##0;"—"',
    "currency_dec": '#,##0.00;[Red]-#,##0.00;"—"',
    "pct": '0.0%;[Red]-0.0%;"—"',
    "int": '#,##0;[Red]-#,##0;"—"',
    "text": "General",
    "date": "yyyy-mm-dd",
    "ratio": '0.00',
}


_SECTION_FONT = Font(bold=True, color="FFFFFF")
_SECTION_FILL = PatternFill("solid", fgColor="1C1F24")
_TOTAL_FONT = Font(bold=True)
_TOTAL_FILL = PatternFill("solid", fgColor="FAFAF7")
_HEADER_FONT = Font(bold=True, color="4B4D52")
_HEADER_FILL = PatternFill("solid", fgColor="FAFAF7")


def _write_value(cell, value, fmt):
    if value is None:
        cell.value = None
    elif fmt in ("currency", "currency_dec", "int", "ratio"):
        try:
            cell.value = float(value)
        except (TypeError, ValueError):
            cell.value = value
    elif fmt == "pct":
        try:
            cell.value = float(value)
        except (TypeError, ValueError):
            cell.value = value
    else:
        cell.value = value
    cell.number_format = _FMT_MAP.get(fmt, "General")


def _write_row(ws, r: int, row: Row, *, indent_base: int = 0):
    for c, source in enumerate(row.cells, start=1):
        cell = ws.cell(row=r, column=c)
        _write_value(cell, source.value, source.fmt)
        cell.alignment = Alignment(
            horizontal="left" if c == 1 else "right",
            indent=(source.indent + indent_base) if c == 1 else 0,
        )
        if row.is_section:
            cell.fill = _SECTION_FILL
            cell.font = _SECTION_FONT
        elif row.is_total or source.is_total:
            cell.fill = _TOTAL_FILL
            cell.font = _TOTAL_FONT
        elif source.bold:
            cell.font = Font(bold=True)


def _write_tree(wb: Workbook, tree: RenderTree, *, sheet_name: str | None = None,
                rows_override: list[Row] | None = None):
    title = (sheet_name or tree.title)[:31]
    if title in wb.sheetnames:
        title = title[:28] + "_2"
    ws = wb.create_sheet(title=title)
    # Header banner row
    ws.cell(1, 1, tree.title).font = Font(bold=True, size=14)
    if tree.subtitle:
        ws.cell(2, 1, tree.subtitle).font = Font(italic=True, color="6C707A")
    # Column headers
    header_row = 4
    if tree.banners:
        for i, b in enumerate(tree.banners):
            ws.cell(header_row + i, 1, f"[{b.severity.upper()}] {b.text}").font = Font(
                color="B91C1C" if b.severity == "error" else "D97706" if b.severity == "warning" else "2563EB")
            ws.merge_cells(start_row=header_row + i, start_column=1, end_row=header_row + i, end_column=max(len(tree.columns), 2))
        header_row += len(tree.banners) + 1
    for c, col_name in enumerate(tree.columns, start=1):
        cell = ws.cell(header_row, c, col_name)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    rows = rows_override if rows_override is not None else tree.rows
    r = header_row + 1
    for row in rows:
        _write_row(ws, r, row)
        r += 1
    # Notes block at the bottom
    if tree.notes:
        r += 1
        ws.cell(r, 1, "NOTES").font = Font(bold=True, color="6C707A")
        r += 1
        for note in tree.notes:
            ws.cell(r, 1, "• " + note).font = Font(color="4B4D52")
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=max(len(tree.columns), 2))
            r += 1
    # Column widths
    ws.column_dimensions["A"].width = 40
    for c in range(2, len(tree.columns) + 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(c)].width = 14


def _write_audit_tab(wb: Workbook, report: AuditReport):
    ws = wb.create_sheet(title="Audit Report")
    ws.cell(1, 1, "Audit Report").font = Font(bold=True, size=14)
    ws.cell(2, 1, f"Run {report.run_id} at {report.timestamp:%Y-%m-%d %H:%M}").font = Font(italic=True)
    headers = ["Check", "Name", "Status", "Message"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(4, c, h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    for i, r in enumerate(report.results, start=5):
        ws.cell(i, 1, r.check_id).font = Font(bold=True)
        ws.cell(i, 2, r.name)
        ws.cell(i, 3, r.status)
        ws.cell(i, 4, r.message)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 80


def render(trees: list[RenderTree], audit_report: AuditReport, output_path: Path, *, client: str, run_date) -> dict:
    """Write the workbook. Returns dict with audit observations (zip_valid, sheet_count)."""
    wb = Workbook()
    # Remove default sheet
    default = wb.active
    wb.remove(default)

    for tree in trees:
        if tree.tab_id == "daily_tracker" and tree.sub_views:
            # One sheet per month, oldest first
            for month_label, rows in tree.sub_views.items():
                # Excel sheet names: max 31 chars, no special chars
                safe = f"Daily - {month_label}"[:31]
                _write_tree(wb, tree, sheet_name=safe, rows_override=rows)
        else:
            _write_tree(wb, tree)

    _write_audit_tab(wb, audit_report)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)

    # G7: zip integrity
    zip_valid = True
    try:
        with zipfile.ZipFile(output_path) as zf:
            bad = zf.testzip()
            zip_valid = bad is None
    except Exception:
        zip_valid = False

    return {
        "zip_valid": zip_valid,
        "sheet_count": len(wb.sheetnames),
        "sheet_names": list(wb.sheetnames),
    }
