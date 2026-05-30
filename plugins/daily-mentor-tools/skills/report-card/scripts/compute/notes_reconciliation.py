"""Notes & Reconciliation — auto-generated metadata, source manifest, mentor flags."""
from __future__ import annotations

from pathlib import Path

from ..models import RenderTree, Tooltip
from .helpers import make_row, money_cell, section_cell, text_cell


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    tree = RenderTree(tab_id="notes_reconciliation", title="Notes & Reconciliation",
                      subtitle=f"Generated {meta.run_date} for {meta.client_name}")
    tree.columns = ["Item", "Value"]

    def kv(name, value, indent=1):
        tree.rows.append(make_row([
            text_cell(f"nr.{name}.lbl", name, indent=indent),
            text_cell(f"nr.{name}.v", value),
        ]))

    tree.rows.append(make_row([section_cell("nr.s1", "Period & Currency"), text_cell("nr.s1.v", "")], is_section=True))
    kv("Run date", str(meta.run_date))
    kv("Client", meta.client_name)
    kv("Reporting currency", meta.reporting_currency)
    if meta.lookback_start and meta.lookback_end:
        kv("Lookback window", f"{meta.lookback_start} → {meta.lookback_end} ({(meta.lookback_end - meta.lookback_start).days + 1} days)")
    if d.snapshot_window:
        kv("Snapshot window (Homepage / Benchmark)", f"{d.snapshot_window[0]} → {d.snapshot_window[1]}")
    if d.snapshot_as_at:
        kv("Balance sheet as at", str(d.snapshot_as_at))

    tree.rows.append(make_row([section_cell("nr.s2", "FX Rates Used"), text_cell("nr.s2.v", "")], is_section=True))
    for platform, ccy in meta.ad_platform_currency.items():
        if ccy.code != meta.reporting_currency and d.snapshot_window:
            rate = d.fx.rate(d.snapshot_window[1], ccy.code, meta.reporting_currency)
            kv(f"{platform} ({ccy.code} → {meta.reporting_currency})", f"{rate:.4f} (monthly cached for {d.snapshot_window[1].strftime('%Y-%m')})")
    if meta.shopify_currency and meta.shopify_currency.code != meta.reporting_currency:
        kv(f"Shopify ({meta.shopify_currency.code} → {meta.reporting_currency})", "Daily rates applied per shopify_daily.day")
    elif meta.shopify_currency:
        kv("Shopify currency", f"{meta.shopify_currency.code} ({meta.shopify_currency.confidence})")

    tree.rows.append(make_row([section_cell("nr.s3", "Source Files"), text_cell("nr.s3.v", "")], is_section=True))
    for role, path in meta.files_found.items():
        kv(role, Path(path).name)
    if meta.files_missing:
        for role in meta.files_missing:
            kv(role + " (MISSING)", "Not found in inputs directory")

    tree.rows.append(make_row([section_cell("nr.s4", "Posted Periods (Xero)"), text_cell("nr.s4.v", "")], is_section=True))
    if d.posted_months:
        kv("Posted months", ", ".join(m.strftime("%b %Y") for m in d.posted_months))
        kv("Months not yet posted", "All other months in the 12-month window — bookkeeping may be behind.")
    else:
        kv("Posted months", "None — Xero P&L shows no posted activity.")

    tree.rows.append(make_row([section_cell("nr.s_cogs", "COGS Source"), text_cell("nr.s_cogs.v", "")], is_section=True))
    if bundle.shopify_daily is not None and not bundle.shopify_daily.empty and "cogs_aud" in bundle.shopify_daily.columns:
        shop_cogs_total = float(bundle.shopify_daily["cogs_aud"].sum())
        kv("Shopify product COGS (12-mo)", f"{shop_cogs_total:,.0f} {meta.reporting_currency} — used as the COGS source.")
    if bundle.xero_pl is not None and not bundle.xero_pl.empty:
        xero_cogs = bundle.xero_pl[bundle.xero_pl["bucket"] == "cogs"]["value"].sum()
        xero_cogs = float(abs(xero_cogs))
        kv("Xero COGS (12-mo, informational)", f"{xero_cogs:,.0f} {meta.reporting_currency} — not used in Monthly P&L; depends on stock-write-off bookkeeping.")
    kv("Why Shopify over Xero for COGS", "Shopify posts product cost at sale time; Xero requires the bookkeeper to reclassify Inventory→COGS via journals. Freight, Warehouse and Fulfilment are still sourced from Xero under Operating Expenses.")

    tree.rows.append(make_row([section_cell("nr.s5", "Recommended Actions"), text_cell("nr.s5.v", "")], is_section=True))
    recs = []
    if bundle.cohort is None:
        recs.append("Request Shopify Cohort Analysis CSV (Customers → Cohort Analysis → 'Customer value by month, last 6 months') to unlock LTV tab.")
    if not d.vendor_breakdown.empty and d.vendor_breakdown["account"].nunique() == 1:
        recs.append("Request Xero Account Transactions export grouped by expense account (not bank-account only) for richer vendor breakdown.")
    if len(d.posted_months) < 3:
        recs.append("Request 12-month Xero P&L export — fewer than 3 months currently posted.")
    if not recs:
        recs.append("None — all standard inputs supplied.")
    for i, r in enumerate(recs):
        tree.rows.append(make_row([text_cell(f"nr.rec.{i}", "• " + r, indent=1), text_cell(f"nr.rec.{i}.v", "")]))

    return tree
