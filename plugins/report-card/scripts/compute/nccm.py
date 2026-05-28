"""NCCM Calculator — per-order contribution margin for new customers.

Four columns: Item | Per Order | % of AOV | Notes.
Notes column surfaces the derivation on-page (where the value comes from) instead of
relying on hover-only tooltips — useful when the workbook is printed or used offline.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


_DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "defaults.json"


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc
    with _DEFAULTS_PATH.open() as f:
        defaults = json.load(f)["nccm"]

    tree = RenderTree(tab_id="nccm", title="NCCM Calculator",
                      subtitle="New Customer Contribution Margin — per order. Run this by region if selling in multiple.")

    nc_src = Path(meta.files_found.get("nc_rc", "")).name
    ads_src = Path(meta.files_found.get("ad_spend_meta", "")).name
    xero_src = Path(meta.files_found.get("xero_pl", "")).name

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC report missing — cannot compute NCCM."))
        return tree

    nc = nc_rc[nc_rc["segment"].str.lower() == "new"].iloc[0]
    nc_orders = int(nc["orders"])
    nc_gross = float(nc["gross"])
    nc_disc = float(nc["discounts"])
    nc_ship = float(nc["shipping"])
    nc_tax = float(nc["taxes"])
    nc_cogs = float(nc["cogs"])

    nc_perf = nc_gross + nc_disc + nc_ship + nc_tax
    nc_aov = safe_div(nc_perf, nc_orders)
    tax_dollars = safe_div(nc_tax, nc_orders)
    tax_rate = safe_div(nc_tax, nc_perf - nc_tax) if (nc_perf - nc_tax) else None

    # Per-order COGS (product only from Shopify)
    cogs_per_order_product = safe_div(nc_cogs, nc_orders)
    cogs_pct_of_aov = safe_div(cogs_per_order_product, nc_aov)

    # Defaults
    pp_pct = defaults["payment_processing_pct"]
    smarkets_pct = defaults["shopify_markets_fee_pct"]
    txn_fee = defaults["transaction_fee_per_order_aud"]
    packaging = defaults["packaging_per_order_aud"]
    fulfillment = defaults["fulfillment_per_order_aud"]

    # Try to derive from Xero where possible
    # Shipping per order: prefer Xero Freight (posted-month sum) / total orders in that window
    shipping_per_order = None
    shipping_note = "Default — Xero Freight data not available."
    freight_q = 0.0
    if not d.monthly_expenses.empty and d.posted_months:
        freight_rows = d.monthly_expenses[
            d.monthly_expenses["account_lower"].str.contains("freight|courier|warehouse|fulfilment|fulfillment", regex=True, na=False)
        ]
        if not freight_rows.empty:
            freight_q = float(freight_rows["value"].abs().sum())
            posted_months_ct = len(d.posted_months)
            if posted_months_ct > 0:
                # estimate per-order over the same window: use NC orders pro-rated; if 30d NC/RC, scale to posted months
                # Easier: freight per month / orders per month (from Shopify daily)
                if not d.monthly_revenue_components.empty and "orders" in d.monthly_revenue_components.columns:
                    monthly_orders = d.monthly_revenue_components[
                        d.monthly_revenue_components["month"].isin(d.posted_months)
                    ]["orders"].sum()
                    if monthly_orders > 0:
                        shipping_per_order = freight_q / monthly_orders
                        shipping_note = f"Derived: Xero Freight {freight_q:,.0f} / {int(monthly_orders)} orders over posted months."

    if shipping_per_order is None:
        shipping_per_order = 0.0
        shipping_note = "Default 0 — request Xero Freight & Courier data."

    pp_dollar = nc_aov * pp_pct if nc_aov else None
    smarkets_dollar = nc_aov * smarkets_pct if nc_aov else None
    total_op_cost = sum(filter(None, [cogs_per_order_product, pp_dollar, smarkets_dollar, txn_fee, shipping_per_order, packaging, fulfillment]))
    total_pct = safe_div(total_op_cost, nc_aov)

    # CAC
    ad_total_window = 0.0
    if not d.daily_ad_spend.empty and d.snapshot_window:
        mask = (d.daily_ad_spend["day"] >= d.snapshot_window[0]) & (d.daily_ad_spend["day"] <= d.snapshot_window[1])
        ad_total_window = float(d.daily_ad_spend.loc[mask, "amount"].sum())
    cac = safe_div(ad_total_window, nc_orders) if nc_orders else None
    cac_pct = safe_div(cac, nc_aov)

    gp_per_order = (nc_aov - total_op_cost) if (nc_aov is not None and total_op_cost is not None) else None
    gp_pct = safe_div(gp_per_order, nc_aov)
    fcm = (gp_per_order - cac) if (gp_per_order is not None and cac is not None) else None
    fcm_pct = safe_div(fcm, nc_aov)

    tree.columns = ["Item", "Per Order", "% of AOV", "Notes"]

    def line(name, dollar, pct, tooltip, note, *, indent=1, bold=False, is_total=False):
        return make_row([
            text_cell(f"nccm.{name}.lbl", name, indent=indent, bold=bold),
            money_cell(f"nccm.{name}.v", dollar, tooltip=tooltip, decimals=2, is_total=is_total),
            pct_cell(f"nccm.{name}.p", pct, tooltip=tooltip),
            text_cell(f"nccm.{name}.n", note),
        ])

    # ---- Inputs ----
    tree.rows.append(make_row([section_cell("nccm.s1", "INPUTS"), text_cell("nccm.s1.b", ""), text_cell("nccm.s1.c", ""), text_cell("nccm.s1.d", "")], is_section=True))
    tree.rows.append(line("NC AOV", nc_aov, None,
        Tooltip(formula="(Gross + Discounts + Shipping + Tax) / Orders",
                inputs=[("Gross", nc_gross), ("Disc", nc_disc), ("Ship", nc_ship), ("Tax", nc_tax), ("Orders", nc_orders)],
                result_expr=f"= {nc_aov:,.2f}" if nc_aov else "—",
                sources=[nc_src], gotcha_refs=["G36"]),
        "Inclusive of tax — per Daily Mentor NCCM convention.",
        bold=True))
    tree.rows.append(line("  Tax per order", tax_dollars, tax_rate,
        Tooltip(formula="Tax / Orders", sources=[nc_src]),
        f"Effective tax rate {tax_rate*100:.1f}% on post-tax AOV." if tax_rate else "—",
        indent=2))

    # ---- Operational Cost per Order ----
    tree.rows.append(make_row([section_cell("nccm.s2", "OPERATIONAL COST PER ORDER"), text_cell("nccm.s2.b", ""), text_cell("nccm.s2.c", ""), text_cell("nccm.s2.d", "")], is_section=True))
    tree.rows.append(line("Product COGS (Shopify per-sale)", cogs_per_order_product, cogs_pct_of_aov,
        Tooltip(formula="NC COGS / NC Orders",
                inputs=[("NC COGS", nc_cogs), ("NC Orders", nc_orders)],
                result_expr=f"{nc_cogs:,.2f} / {nc_orders} = {cogs_per_order_product:,.2f}" if cogs_per_order_product else "—",
                sources=[nc_src], gotcha_refs=["G39"]),
        f"Shopify per-sale product cost. Landed COGS (Freight, Warehouse) charged below."))
    tree.rows.append(line("Payment Processing", pp_dollar, pp_pct,
        Tooltip(formula="AOV × Payment Processing %", sources=["defaults.json"]),
        f"Default {pp_pct*100:.1f}%. Override per client when known."))
    tree.rows.append(line("Shopify Markets Fee", smarkets_dollar, smarkets_pct,
        Tooltip(formula="AOV × Shopify Markets %", sources=["defaults.json"]),
        f"Default {smarkets_pct*100:.1f}%. 0% if not selling cross-border."))
    tree.rows.append(line("Transaction Fees", txn_fee, safe_div(txn_fee, nc_aov),
        Tooltip(formula="Per-order flat fee", sources=["defaults.json"]),
        f"Default ${txn_fee:.2f}/order. Replace with Xero 'Shopify & PayPal fees' / orders when available."))
    tree.rows.append(line("Shipping per order (landed)", shipping_per_order, safe_div(shipping_per_order, nc_aov),
        Tooltip(formula="Xero Freight & Courier (posted months) / orders over same window",
                inputs=[("Freight (posted)", freight_q)],
                sources=[xero_src], gotcha_refs=["G39"]),
        shipping_note))
    tree.rows.append(line("Packaging + supplies", packaging, safe_div(packaging, nc_aov),
        Tooltip(formula="Per-order flat", sources=["defaults.json"]),
        f"Default ${packaging:.2f}/order. Avg cost of box, tape, inserts."))
    tree.rows.append(line("Fulfilment (3PL)", fulfillment, safe_div(fulfillment, nc_aov),
        Tooltip(formula="Per-order flat (3PL)", sources=["defaults.json"]),
        f"Default ${fulfillment:.2f}/order. Replace with Xero 'Warehouse' or 3PL invoice / orders when available."))
    tree.rows.append(line("Total Operational Cost", total_op_cost, total_pct,
        Tooltip(formula="Sum of all operational cost lines above.",
                result_expr=f"= {total_op_cost:,.2f} ({total_pct*100:.1f}%)" if total_op_cost else "—"),
        "Sum of the lines above.",
        bold=True, is_total=True))

    # ---- Margin ----
    tree.rows.append(make_row([section_cell("nccm.s3", "MARGIN"), text_cell("nccm.s3.b", ""), text_cell("nccm.s3.c", ""), text_cell("nccm.s3.d", "")], is_section=True))
    tree.rows.append(line("Gross Profit per Order", gp_per_order, gp_pct,
        Tooltip(formula="AOV − Total Operational Cost",
                inputs=[("AOV", nc_aov), ("OpCost", total_op_cost)],
                result_expr=f"{nc_aov:,.2f} − {total_op_cost:,.2f} = {gp_per_order:,.2f}" if gp_per_order else "—"),
        "AOV minus all operational lines.",
        bold=True))
    tree.rows.append(line("CAC", cac, cac_pct,
        Tooltip(formula="Ad Spend (window) / NC Orders",
                inputs=[("Ad Spend", ad_total_window), ("NC Orders", nc_orders)],
                result_expr=f"{ad_total_window:,.2f} / {nc_orders} = {cac:,.2f}" if cac else "—",
                sources=[ads_src], gotcha_refs=["G39"]),
        f"Snapshot-period ad spend / NC orders."))
    tree.rows.append(line("First-Order Contribution Margin", fcm, fcm_pct,
        Tooltip(formula="Gross Profit per Order − CAC",
                result_expr=f"{gp_per_order:,.2f} − {cac:,.2f} = {fcm:,.2f}" if fcm else "—"),
        "Money kept per new customer after their first purchase.",
        bold=True, is_total=True))

    # Banners
    if d.snapshot_window:
        period_days = (d.snapshot_window[1] - d.snapshot_window[0]).days + 1
        if period_days < 85:
            tree.banners.append(Banner(severity="warning",
                text=f"NCCM based on a {period_days}-day NC/RC period (spec is 90 days). Numbers will move as more months accumulate."))
    tree.banners.append(Banner(severity="info",
        text="Operational lines marked 'default' should be replaced with client-specific data: Xero 'Shopify & PayPal fees', 'Freight & Courier', 'Warehouse' / 3PL invoices, packaging supplier rate card."))

    tree.notes = [
        "Per-region: if the brand sells AU + NZ + US, build a separate NCCM per region — unit economics differ markedly.",
        "AOV here is inclusive of tax — Daily Mentor convention. Operational cost ratios are expressed against this gross-of-tax AOV.",
        "First-Order CM is the money kept per new customer on their first purchase. Positive = customer acquisition is profitable on transaction one; negative = repeat-purchase economics must carry the brand.",
    ]
    return tree
