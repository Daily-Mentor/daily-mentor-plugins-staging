"""Render the 12-tab Report Card as a single self-contained HTML file."""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .models import AuditReport, Banner, Cell, RenderTree, Row, Tooltip


_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_CSS = (_PLUGIN_ROOT / "templates" / "static" / "report.css").read_text()
_JS = (_PLUGIN_ROOT / "templates" / "static" / "report.js").read_text()


def _logo_data_uri() -> str | None:
    """Daily Mentor logo, base64-embedded so the HTML stays a single self-contained file."""
    import base64
    path = _PLUGIN_ROOT / "templates" / "assets" / "dm-logo.avif"
    if not path.exists():
        return None
    return "data:image/avif;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _colorize_status(s: str) -> str:
    """Green ✓ / red ✗ wherever a status glyph appears (benchmark pass/fail)."""
    return (s.replace("✓", '<span class="status-pass">✓</span>')
             .replace("✗", '<span class="status-fail">✗</span>'))


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
            return _colorize_status(html.escape(str(c.value)))
    return _colorize_status(html.escape(str(c.value)))


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
    # Mentor-editable input: renders an <input> that live-compares to its target.
    if c.editable:
        unit = f'<span class="mentor-unit">{html.escape(c.unit)}</span>' if c.unit else ""
        tgt = "" if c.target_value is None else html.escape(str(c.target_value))
        dir_ = "max" if c.target_max else "min"
        inp = (f'<input class="mentor-input" type="number" step="any" inputmode="decimal" '
               f'data-mentor-key="{html.escape(c.coord)}" data-target="{tgt}" data-dir="{dir_}" '
               f'placeholder="enter" aria-label="mentor input" />')
        return f'<td{cls}><span class="cell-wrap mentor-cell">{inp}{unit}</span></td>'
    # Status cell mirroring a mentor input — JS flips its glyph as the input changes.
    if c.mentor_status_key:
        return (f'<td{cls}><span class="cell-wrap"><span class="mentor-status" '
                f'data-mentor-status="{html.escape(c.mentor_status_key)}">{_fmt_value(c)}</span></span></td>')
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
    attrs = ""
    if row.is_section: classes.append("section")
    if row.is_total: classes.append("total")
    if row.expandable_key:
        classes.append("expandable")
        attrs += f' data-expand-key="{html.escape(row.expandable_key)}"'
    if row.sub_of:
        # Child detail row — collapsed until its parent is toggled open.
        classes.extend(["sub-row", "hidden-by-parent"])
        attrs += f' data-sub-of="{html.escape(row.sub_of)}"'
    cls = f' class="{" ".join(classes)}"' if classes else ""
    cells_html = "".join(_render_cell(c, i == 0) for i, c in enumerate(row.cells))
    return f'<tr{cls}{attrs}>{cells_html}</tr>'


def _render_table(tree: RenderTree, rows: list[Row] | None = None) -> str:
    rows = rows if rows is not None else tree.rows
    head_cells = "".join(f'<th>{html.escape(c)}</th>' for c in tree.columns)
    body = "".join(_render_row(r) for r in rows)
    return f'<table class="rc-table"><thead><tr>{head_cells}</tr></thead><tbody>{body}</tbody></table>'


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
    # Banners no longer sit above each tab body — they're collected and shown
    # on the Audit Report tab as per-tab notices.
    tab_notices: list[tuple[str, Banner]] = []
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
        tab_notices.extend((tree.title, b) for b in tree.banners)
        if tree.raw_html:
            panel_inner.append(tree.raw_html)
        else:
            panel_inner.append(_render_table(tree))
        if tree.notes:
            notes_items = "".join(f"<li>{html.escape(n)}</li>" for n in tree.notes)
            panel_inner.append(f'<div class="rc-notes"><h3>Notes</h3><ul>{notes_items}</ul></div>')
        panels.append(
            f'<section class="tab-panel" data-tab="{html.escape(tree.tab_id)}">{"".join(panel_inner)}</section>'
        )

    # Append Audit Report tab (audit checks + the per-tab notices moved off the page bodies)
    notices_html = ""
    if tab_notices:
        notices_html = '<h3 class="audit-subhead">Tab Notices</h3>' + "".join(
            f'<div class="banner {b.severity}"><strong>{html.escape(tab)}:</strong> {html.escape(b.text)}</div>'
            for tab, b in tab_notices
        )
    nav_buttons.append('<button data-tab="audit_report">Audit Report</button>')
    panels.append(
        f'<section class="tab-panel" data-tab="audit_report">'
        f'<h2 class="tab-title">Audit Report</h2>'
        f'<p class="tab-subtitle">Run {audit_report.run_id} at {audit_report.timestamp:%Y-%m-%d %H:%M}.</p>'
        f'{_render_audit_tab(audit_report)}'
        f'{notices_html}'
        f'</section>'
    )

    title = f"Report Card — {client} — {run_date}"
    logo = _logo_data_uri()
    brand = (f'<img class="dm-logo" src="{logo}" alt="Daily Mentor" />' if logo
             else '<span class="dm-pill alt">Daily Mentor</span>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{html.escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="rc-head">
  {brand}
  <div>
    <h1>{html.escape(client)}</h1>
    <span class="rc-sub">Report Card · {html.escape(str(run_date))}</span>
  </div>
  <span class="rc-meta">Generated {audit_report.timestamp:%Y-%m-%d %H:%M}</span>
</header>
<div class="rc-disclaimer">Disclaimer: This Report Card is a directional tool only, it is not a legal document, does not constitute tax advice or confirm liabilities, and may contain errors; always verify with a qualified tax professional :)</div>
<nav class="rc-tabs">{"".join(nav_buttons)}</nav>
<main class="rc-body">{"".join(panels)}</main>
<script>{_JS}</script>
</body>
</html>
"""
