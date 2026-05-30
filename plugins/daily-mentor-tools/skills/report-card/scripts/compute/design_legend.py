"""Design Legend — static reference for colour + symbol conventions."""
from __future__ import annotations

from ..models import RenderTree
from .helpers import make_row, section_cell, text_cell


def compute(bundle) -> RenderTree:
    tree = RenderTree(tab_id="design_legend", title="Design Legend", subtitle="How to read this Report Card.")
    tree.columns = ["Element", "Meaning", "When you'll see it"]

    rows = [
        ("Section header", "Group label — bold, no value", "Top of each block (e.g. 'REVENUE', 'COGS')."),
        ("Total row", "Aggregates of the rows above", "End of each section. Bold."),
        ("`—`", "No data available", "When inputs are partial; hover for explanation."),
        ("Tooltip", "Calculation + source", "Hover any calculated cell."),
        ("Red banner", "Whole-tab problem", "Tab requires data you haven't provided."),
        ("Yellow / warning banner", "Partial data, proceed with caution", "Coverage gap or sample-thin period."),
        ("Blue / info banner", "Methodology note", "Conversion, defaults, scope of an assumption."),
        ("✓ / ✗ / —", "Benchmark status", "Final Report Card and Homepage — vs target."),
        ("Confidence badge", "How trustworthy a cell is", "`reconciled`, `provisional`, `mentor_input`, `missing`. Hover to see which."),
    ]
    for el, mean, when in rows:
        tree.rows.append(make_row([
            text_cell(f"dl.{el}.a", el, bold=True),
            text_cell(f"dl.{el}.b", mean),
            text_cell(f"dl.{el}.c", when),
        ]))

    tree.rows.append(make_row([section_cell("dl.gotchas.h", "Gotcha References"), text_cell("dl.gotchas.b", ""), text_cell("dl.gotchas.c", "")], is_section=True))
    for g, text in (
        ("G35", "Vendor sub-rows use Credit − Debit netting on Account Transactions, never raw Credit."),
        ("G36", "No vendor sub-rows under Revenue parents — Shopify per-order IDs are not vendors."),
        ("G39", "Monthly revenue comes from Shopify ×FX, not Xero monthly columns (Xero posts date ≠ sale date)."),
        ("G39b", "Monthly COGS also comes from Shopify per-sale product cost ×FX. Xero COGS depends on stock-write-off bookkeeping that's often incomplete. Freight, Warehouse and Fulfilment stay under Operating Expenses from Xero."),
        ("G40", "Accountant-reconciled P&L supersedes Xero for matching periods (out of v1 scope)."),
    ):
        tree.rows.append(make_row([
            text_cell(f"dl.{g}.a", g, bold=True),
            text_cell(f"dl.{g}.b", text),
            text_cell(f"dl.{g}.c", ""),
        ]))
    return tree
