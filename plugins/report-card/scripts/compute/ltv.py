"""LTV Analysis — degrades to an 'input missing' banner when the Shopify Cohort Analysis CSV isn't supplied."""
from __future__ import annotations

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, section_cell, text_cell


def compute(bundle) -> RenderTree:
    tree = RenderTree(tab_id="ltv", title="LTV Analysis", subtitle="Customer value by cohort month")

    if bundle.cohort is None:
        tree.banners.append(Banner(severity="error",
            text=("Input missing — Shopify Cohort Analysis report needed. "
                  "Export from Shopify Analytics → Customers → Cohort Analysis → "
                  "'Customer value by month' (last 6 months), save as CSV in inputs folder, re-run /report-card.")))
        # Empty cohort scaffold
        tree.columns = ["Cohort Metric", "Month 0", "Month 1", "Month 2", "Month 3", "Month 4", "Month 5+"]
        for label in ("Customer Value (incl. tax)", "Gross Profit per Order", "Net Profit (after returns)", "% Increase vs Month 0"):
            cells = [text_cell(f"ltv.{label}.lbl", label, indent=1)]
            for i in range(6):
                cells.append(money_cell(f"ltv.{label}.{i}", None, tooltip=Tooltip(
                    formula="Cohort value — Shopify Cohort Analysis report not provided.",
                    confidence_note="Missing — see banner above.",
                )))
            tree.rows.append(make_row(cells))
        return tree

    # If cohort is present, render real values (placeholder for v2 if cohort CSV present)
    tree.banners.append(Banner(severity="info", text="Cohort data present — full LTV rendering not implemented in v1."))
    return tree
