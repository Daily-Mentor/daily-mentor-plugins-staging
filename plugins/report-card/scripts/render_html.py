"""Render the 12-tab Report Card as a single self-contained HTML file."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .models import AuditReport, Banner, Cell, RenderTree, Row, Tooltip


_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_CSS = (_PLUGIN_ROOT / "templates" / "static" / "report.css").read_text()
_JS = (_PLUGIN_ROOT / "templates" / "static" / "report.js").read_text()


def _fmt_value(c: Cell) -> str:
    if c.value is None or c.is_missing:
        return '<span class="missing">—</span>'
    if c.fmt == "currency":
        return f"{c.value:,.0f}"
    if c.fmt == "currency_dec":
        return f"{c.value:,.2f}"
    if c.fmt == "pct":
        return f"{c.value * 100:.1f}%"
    if c.fmt == "int":
        try:
            return f"{int(c.value):,}"
        except (TypeError, ValueError):
            return html.escape(str(c.value))
    return html.escape(str(c.value))


def _render_tooltip(t: Tooltip, confidence: str) -> str:
    parts = ['<span class="tt">']
    parts.append(f'<span class="tt-conf-badge {confidence}">{confidence}</span>')
    if t.formula:
        parts.append(f'<div class="tt-formula">{html.escape(t.formula)}</div>')
    if t.inputs:
        parts.append('<ul class="tt-inputs">')
        for label, val in t.inputs:
            if isinstance(val, float):
                v = f"{val:,.2f}"
            else:
                v = html.escape(str(val))
            parts.append(f'<li>{html.escape(label)}: {v}</li>')
        parts.append('</ul>')
    if t.result_expr:
        parts.append(f'<div class="tt-result">= {html.escape(t.result_expr)}</div>')
    if t.fx_note:
        parts.append(f'<div class="tt-fx">FX: {html.escape(t.fx_note)}</div>')
    if t.sources:
        parts.append(f'<div class="tt-sources">Sources: {html.escape(", ".join(t.sources))}</div>')
    if t.gotcha_refs:
        parts.append(f'<div class="tt-gotchas">Refs: {html.escape(" · ".join(t.gotcha_refs))}</div>')
    if t.confidence_note:
        parts.append(f'<div class="tt-conf">{html.escape(t.confidence_note)}</div>')
    parts.append('</span>')
    return "".join(parts)


def _render_cell(c: Cell, is_first: bool = False) -> str:
    classes: list[str] = []
    if c.bold or c.is_total: classes.append("bold")
    if c.indent: classes.append(f"indent-{c.indent}")
    cls = f' class="{" ".join(classes)}"' if classes else ""
    val = _fmt_value(c)
    dot = f'<span class="conf conf-{c.confidence}"></span>' if c.confidence not in ("derived",) and not c.section_header else ""
    if c.tooltip and not c.section_header and c.value is not None:
        body = (
            f'<span class="cell-wrap"><span class="cell-trigger" data-cell="{html.escape(c.coord)}">'
            f'{val}{_render_tooltip(c.tooltip, c.confidence)}</span>{dot}</span>'
        )
    else:
        body = f'<span class="cell-wrap">{val}{dot}</span>'
    return f'<td{cls}>{body}</td>'


def _render_row(row: Row) -> str:
    classes: list[str] = []
    if row.is_section: classes.append("section")
    if row.is_total: classes.append("total")
    cls = f' class="{" ".join(classes)}"' if classes else ""
    cells_html = "".join(_render_cell(c, i == 0) for i, c in enumerate(row.cells))
    return f'<tr{cls}>{cells_html}</tr>'


def _render_banner(b: Banner) -> str:
    return f'<div class="banner {b.severity}">{html.escape(b.text)}</div>'


def _render_table(tree: RenderTree, rows: list[Row] | None = None) -> str:
    rows = rows if rows is not None else tree.rows
    head_cells = "".join(f'<th>{html.escape(c)}</th>' for c in tree.columns)
    body = "".join(_render_row(r) for r in rows)
    return f'<table class="rc-table"><thead><tr>{head_cells}</tr></thead><tbody>{body}</tbody></table>'


def _render_tracker(tree: RenderTree) -> str:
    """Daily Tracker special: month pills + per-month tables."""
    if not tree.sub_views:
        return _render_table(tree)
    pills = '<div class="month-pills" data-target="tracker">'
    for m in tree.sub_views.keys():
        pills += f'<button data-month="{html.escape(m)}">{html.escape(m)}</button>'
    pills += "</div>"
    tables = []
    for m, rows in tree.sub_views.items():
        head_cells = "".join(f'<th>{html.escape(c)}</th>' for c in tree.columns)
        body = "".join(_render_row(r) for r in rows)
        tables.append(
            f'<div data-tracker-month="{html.escape(m)}" style="display:none">'
            f'<table class="rc-table"><thead><tr>{head_cells}</tr></thead><tbody>{body}</tbody></table>'
            f'</div>'
        )
    return pills + "".join(tables)


def _render_audit_tab(report: AuditReport) -> str:
    rows = []
    for r in report.results:
        rows.append(
            f'<div class="audit-row">'
            f'<span class="audit-status {r.status}">{r.status}</span>'
            f'<strong>{html.escape(r.check_id)}</strong> '
            f'<span>{html.escape(r.name)}</span> '
            f'<span style="color:#6c707a">— {html.escape(r.message)}</span>'
            f'</div>'
        )
    return "".join(rows)


def render(trees: list[RenderTree], audit_report: AuditReport, *, client: str, run_date) -> str:
    nav_buttons: list[str] = []
    panels: list[str] = []
    for tree in trees:
        nav_buttons.append(
            f'<button data-tab="{html.escape(tree.tab_id)}">{html.escape(tree.title)}</button>'
        )
        panel_inner = []
        if tree.subtitle:
            panel_inner.append(f'<h2 class="tab-title">{html.escape(tree.title)}</h2>')
            panel_inner.append(f'<p class="tab-subtitle">{html.escape(tree.subtitle)}</p>')
        else:
            panel_inner.append(f'<h2 class="tab-title">{html.escape(tree.title)}</h2>')
        for b in tree.banners:
            panel_inner.append(_render_banner(b))
        if tree.tab_id == "daily_tracker":
            panel_inner.append(_render_tracker(tree))
        elif tree.raw_html:
            panel_inner.append(tree.raw_html)
        else:
            panel_inner.append(_render_table(tree))
        if tree.notes:
            notes_items = "".join(f"<li>{html.escape(n)}</li>" for n in tree.notes)
            panel_inner.append(f'<div class="rc-notes"><h3>Notes</h3><ul>{notes_items}</ul></div>')
        panels.append(
            f'<section class="tab-panel" data-tab="{html.escape(tree.tab_id)}">{"".join(panel_inner)}</section>'
        )

    # Append Audit Report tab
    nav_buttons.append('<button data-tab="audit_report">Audit Report</button>')
    panels.append(
        f'<section class="tab-panel" data-tab="audit_report">'
        f'<h2 class="tab-title">Audit Report</h2>'
        f'<p class="tab-subtitle">Run {audit_report.run_id} at {audit_report.timestamp:%Y-%m-%d %H:%M}.</p>'
        f'{_render_audit_tab(audit_report)}'
        f'</section>'
    )

    title = f"Report Card — {client} — {run_date}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="rc-head">
  <span class="dm-pill alt">Daily Mentor</span>
  <div>
    <h1>{html.escape(client)}</h1>
    <span class="rc-sub">Report Card · {html.escape(str(run_date))}</span>
  </div>
  <span class="rc-meta">Generated {audit_report.timestamp:%Y-%m-%d %H:%M}</span>
</header>
<nav class="rc-tabs">{"".join(nav_buttons)}</nav>
<main class="rc-body">{"".join(panels)}</main>
<script>{_JS}</script>
</body>
</html>
"""
