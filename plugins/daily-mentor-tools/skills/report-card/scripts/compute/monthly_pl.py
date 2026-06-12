"""Monthly P&L tab.

Sections rendered in this order:

    REVENUE                  ← Shopify ×FX (G39)
    COST OF DELIVERY (COD)   ← all-in cost to deliver: product cost + freight/packaging/fees
    GROSS PROFIT             ← Net Sales − Product COGS
    OTHER INCOME             ← Xero rows tagged is_other_income
    MARKETING                ← Xero (or ad-platform CSV fallback)
    PEOPLE                   ← Xero
    SOFTWARE                 ← Xero
    OTHER OPERATING EXPENSES ← Xero
    TOTAL OPERATING EXPENSES
    NET PROFIT               ← Gross Profit + Other Income − Total Operating Expenses

Each non-revenue section emits TOTAL <section> subtotal rows. Final monthly
columns are followed by a 12-month Total column.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from ..models import Banner, Cell, RenderTree, Row, Tooltip
from .helpers import (
    make_row, money_cell, month_label, pct_cell, section_cell, text_cell,
)


_SKU_RECOG_RE = re.compile(r"^(?:Incorrect\s+)?[A-Za-z]+\s*\d{0,4}\s*_(.+?)_CoGS Recognition$", re.IGNORECASE)
_GEN_RECOG_RE = re.compile(r"^(?:Incorrect\s+)?[A-Za-z]+(?:\s+\d{2,4})?\s+CoGS Recognition$", re.IGNORECASE)

# Bookkeeper-abbreviation aliases — collapse codes back to canonical SKU names.
_SKU_ALIASES = {
    "ctb": "Classic Trimmer Blade",
    "fb": "Foil Blade",
}


def _clean_cogs_label(raw: str) -> str:
    """Normalise Xero CoGS-recognition journal contacts into useful labels.

    Reversal pairs ('Incorrect X CoGS Recognition' + 'X CoGS Recognition') are
    folded to the same label so Credit−Debit netting collapses them to the net
    correction. Bookkeeper SKU abbreviations (CTB, FB) are mapped back to full
    product names.

        'Jun 25_Product Name_CoGS Recognition'            → 'Product Name'
        'Apr 26_CTB_CoGS Recognition'                     → 'Classic Trimmer Blade'
        'July CoGS Recognition'                           → 'General CoGS'
        'Incorrect July CoGS Recognition'                 → 'General CoGS'  (nets vs above)
        'Adjustment for landed costs allocation only'     → 'Landed cost adjustments'
        'Shantou City Yicai Packaging Co., Ltd.'          → unchanged (real supplier)
    """
    if not isinstance(raw, str):
        return str(raw or "")
    s = raw.strip()
    if not s:
        return s
    low = s.lower()
    if "adjustment" in low and ("landed" in low or "cost" in low):
        return "Landed cost adjustments"
    m = _SKU_RECOG_RE.match(s)
    if m:
        sku = m.group(1).strip()
        return _SKU_ALIASES.get(sku.lower(), sku)
    if _GEN_RECOG_RE.match(s):
        return "General CoGS"
    return s


_EXPENSE_SECTION_ORDER = [
    "Marketing",
    "People",
    "Software",
    "Other Operating Expenses",
]

# Cost-of-Sales bucket display order (after the Shopify Product COGS line).
# Each tuple: (bucket id from chart_of_accounts.json, display label).
_COGS_BUCKETS = [
    ("cogs_packaging", "Packaging"),
    ("cogs_freight", "Shipping & Courier"),
    ("cogs_merchant", "Merchant / Platform Fees"),
    ("cogs_warehouse", "Warehouse / 3PL Fulfilment"),
    ("cogs_customer_service", "Customer Service"),
    ("cogs_customs", "Customs / Import Duties"),
    ("cogs_wise", "Wise / FX Transfer Fees"),
    ("cogs_materials", "Materials"),
]


def _last_12_months(end: date) -> list[date]:
    months: list[date] = []
    y, m = end.year, end.month
    for _ in range(12):
        months.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return list(reversed(months))


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta

    tree = RenderTree(tab_id="monthly_pl", title="Monthly P&L",
                      subtitle="12-month trailing — Shopify is the source of truth for monthly revenue and product COGS; Xero for expenses (G39).")

    if not meta.lookback_end:
        tree.banners.append(Banner(severity="error", text="No Shopify daily data — cannot compute Monthly P&L."))
        return tree

    months = _last_12_months(meta.lookback_end)
    tree.columns = ["Account"] + [month_label(m) for m in months] + ["12mo Total"]

    shopify_src = Path(meta.files_found.get("shopify_daily", "")).name
    xero_src = Path(meta.files_found.get("xero_pl", "")).name
    atxn_src = Path(meta.files_found.get("xero_atxn", "")).name
    ad_src = Path(meta.files_found.get("ad_spend_meta", "")).name

    n_cols = len(months)

    revenue_components = d.monthly_revenue_components.set_index("month") if not d.monthly_revenue_components.empty else None

    # ---- REVENUE section (Shopify, G39) ----
    rev_cells = [section_cell("pl.rev.h", "REVENUE")] + [text_cell(f"pl.rev.h.{i}", "") for i in range(n_cols + 1)]
    tree.rows.append(make_row(rev_cells, is_section=True))

    def shopify_row(label: str, col: str, indent: int = 1, bold: bool = False, formula_desc: str = ""):
        cells: list[Cell] = [text_cell(f"pl.{col}.lbl", label, indent=indent, bold=bold)]
        running_total = 0.0
        any_value = False
        for i, m in enumerate(months):
            v = None
            if revenue_components is not None and m in revenue_components.index and col in revenue_components.columns:
                v = float(revenue_components.loc[m, col])
                running_total += v
                any_value = True
            tooltip = Tooltip(
                formula=formula_desc or f"Sum of Shopify daily `{col}` for {month_label(m)} ×FX.",
                inputs=[("Month", month_label(m))],
                result_expr=f"{v:,.2f}" if v is not None else "—",
                sources=[shopify_src], gotcha_refs=["G39"],
                confidence_note="Provisional — Shopify CSV converted to reporting currency at daily FX.",
            )
            cells.append(money_cell(f"pl.{col}.{i}", v, tooltip=tooltip))
        # 12mo total
        cells.append(money_cell(f"pl.{col}.tot", running_total if any_value else None, tooltip=Tooltip(
            formula=f"Sum of 12 monthly `{col}` values.",
            sources=[shopify_src], gotcha_refs=["G39"],
        ), is_total=True))
        return make_row(cells)

    tree.rows.append(shopify_row("Gross Sales", "gross_aud", formula_desc="Sum of Shopify daily Gross sales ×FX."))
    tree.rows.append(shopify_row("Discounts", "discounts_aud", formula_desc="Sum of Shopify daily Discounts ×FX (negative)."))
    tree.rows.append(shopify_row("Returns", "returns_aud", formula_desc="Sum of Shopify daily Returns ×FX (negative)."))
    tree.rows.append(shopify_row("Shipping", "shipping_aud", formula_desc="Sum of Shopify daily Shipping ×FX."))
    tree.rows.append(shopify_row("Net Sales", "net_aud", indent=0, bold=True, formula_desc="Net Sales = Gross + Discounts + Returns. From Shopify daily ×FX. Excludes Tax (G39)."))

    # TOTAL REVENUE row mirrors Net Sales
    revenue_monthly: dict[date, float] = {}
    total_cells = [text_cell("pl.totrev.lbl", "TOTAL REVENUE", bold=True)]
    rev_total_12mo = 0.0
    for i, m in enumerate(months):
        v = None
        if revenue_components is not None and m in revenue_components.index and "net_aud" in revenue_components.columns:
            v = float(revenue_components.loc[m, "net_aud"])
            revenue_monthly[m] = v
            rev_total_12mo += v
        total_cells.append(money_cell(f"pl.totrev.{i}", v, tooltip=Tooltip(
            formula="Total Revenue = Shopify Net Sales ×FX (excludes tax, G39).",
            sources=[shopify_src], gotcha_refs=["G39"],
        ), is_total=True))
    total_cells.append(money_cell("pl.totrev.tot", rev_total_12mo if rev_total_12mo else None, tooltip=Tooltip(
        formula="12-month sum of Net Sales.", sources=[shopify_src], gotcha_refs=["G39"],
    ), is_total=True))
    tree.rows.append(make_row(total_cells, is_total=True))

    tree.rows.append(make_row([text_cell("pl.spacer1", "")] + [text_cell(f"pl.spacer1.{i}", "") for i in range(n_cols + 1)]))

    # ---- COST OF DELIVERY (componentised; contribution-margin shape) ----
    tree.rows.append(make_row(
        [section_cell("pl.cogs.h", "COST OF DELIVERY (COD)")] + [text_cell(f"pl.cogs.h.{i}", "") for i in range(n_cols + 1)],
        is_section=True,
    ))

    # Track per-month component dollars for the TOTAL COGS row.
    cogs_component_monthly: dict[str, dict[date, float]] = {}

    # 1. Product COGS — prefer Xero (CoGS Recognition journals) when posted; fall back to Shopify per-sale.
    pl_raw_early = d.monthly_expenses if d.monthly_expenses is not None else pd.DataFrame()
    xero_cogs_rows = pl_raw_early[pl_raw_early["bucket"] == "cogs_product_xero"] if not pl_raw_early.empty else pd.DataFrame()
    xero_cogs_monthly = (
        xero_cogs_rows.groupby("month")["value"].apply(lambda s: float(s.abs().sum())).to_dict()
        if not xero_cogs_rows.empty else {}
    )
    use_xero_cogs = bool(xero_cogs_monthly) and any(v > 0 for v in xero_cogs_monthly.values())

    product_cogs_monthly: dict[date, float] = {}
    if use_xero_cogs:
        label = "Product COGS (Xero CoGS Recognition)"
        for i, m in enumerate(months):
            v = xero_cogs_monthly.get(m)
            if v:
                product_cogs_monthly[m] = v
        product_cogs_row = [text_cell("pl.cogs_xero.lbl", label, indent=1)]
        prod_12mo = 0.0
        for i, m in enumerate(months):
            v = product_cogs_monthly.get(m)
            if v:
                prod_12mo += v
            product_cogs_row.append(money_cell(f"pl.cogs_xero.{i}", v, tooltip=Tooltip(
                formula=f"Sum of Xero `Cost of Goods Sold` journal lines for {month_label(m)} (Credit − Debit).",
                result_expr=f"{v:,.2f}" if v is not None else "—",
                sources=[xero_src, atxn_src], gotcha_refs=["G35"],
                confidence_note="Accrual-basis Product COGS via the bookkeeper's monthly CoGS Recognition journals.",
            )))
        product_cogs_row.append(money_cell("pl.cogs_xero.tot", prod_12mo or None, tooltip=Tooltip(
            formula="12-month sum of Xero Product COGS journals.", sources=[xero_src, atxn_src], gotcha_refs=["G35"],
        ), is_total=True))
        # SKU sub-rows from Atxn vendor breakdown filtered to the COGS account.
        sku_sub_rows: list[Row] = []
        if d.vendor_breakdown is not None and not d.vendor_breakdown.empty:
            cogs_vendor = d.vendor_breakdown[d.vendor_breakdown["account"].str.lower().isin(["cost of goods sold", "cost of sales"])].copy()
            if not cogs_vendor.empty:
                cogs_vendor["sku"] = cogs_vendor["contact"].apply(_clean_cogs_label)
                # Aggregate by cleaned SKU label
                sku_grouped = cogs_vendor.groupby(["sku", "month"], as_index=False)["net"].sum()
                sku_totals = sku_grouped.groupby("sku")["net"].apply(lambda s: float(s.abs().sum())).sort_values(ascending=False)
                for sku in sku_totals.index:
                    sub_cells = [text_cell(f"pl.cogs_xero.{sku}.lbl", f"• {sku}", indent=2)]
                    sku_12mo = 0.0
                    for i, m in enumerate(months):
                        match = sku_grouped[(sku_grouped["sku"] == sku) & (sku_grouped["month"] == m)]
                        v = None
                        if not match.empty:
                            raw = float(match.iloc[0]["net"])
                            v = abs(raw) if raw else None
                        if v:
                            sku_12mo += v
                        sub_cells.append(money_cell(f"pl.cogs_xero.{sku}.{i}", v, tooltip=Tooltip(
                            formula=f"Net Xero COGS for `{sku}` in {month_label(m)} (Credit − Debit).",
                            sources=[atxn_src], gotcha_refs=["G35"],
                            confidence_note="SKU label normalised from the bookkeeper's recognition journal description.",
                        )))
                    sub_cells.append(money_cell(f"pl.cogs_xero.{sku}.tot", sku_12mo or None, tooltip=Tooltip(
                        formula="12-month sum.", sources=[atxn_src], gotcha_refs=["G35"],
                    ), is_total=True))
                    sku_sub_rows.append(make_row(sub_cells, sub_of="vendor::cogs_product_xero"))
        expandable_key = "vendor::cogs_product_xero" if sku_sub_rows else None
        tree.rows.append(make_row(product_cogs_row, expandable_key=expandable_key))
        tree.rows.extend(sku_sub_rows)
    else:
        label = "Product COGS (Shopify per-sale — Xero CoGS account empty)"
        product_cogs_row = [text_cell("pl.shop_cogs.lbl", label, indent=1)]
        prod_12mo = 0.0
        for i, m in enumerate(months):
            v = None
            if revenue_components is not None and m in revenue_components.index and "cogs_aud" in revenue_components.columns:
                raw = float(revenue_components.loc[m, "cogs_aud"])
                v = raw if raw else None
            if v is not None:
                product_cogs_monthly[m] = v
                prod_12mo += v
            product_cogs_row.append(money_cell(f"pl.shop_cogs.{i}", v, tooltip=Tooltip(
                formula=f"Sum of Shopify daily `Cost of goods sold` ×FX for {month_label(m)}.",
                result_expr=f"{v:,.2f}" if v is not None else "—",
                sources=[shopify_src], gotcha_refs=["G39"],
                confidence_note="Shopify per-sale product cost. Xero has no CoGS Recognition journals to use as a primary source.",
            )))
        product_cogs_row.append(money_cell("pl.shop_cogs.tot", prod_12mo or None, tooltip=Tooltip(
            formula="12-month sum of Shopify product COGS ×FX.", sources=[shopify_src], gotcha_refs=["G39"],
        ), is_total=True))
        tree.rows.append(make_row(product_cogs_row))
    cogs_component_monthly["product"] = product_cogs_monthly

    # 2. Each Cost-of-Sales bucket from Xero — render one row per bucket that has any data.
    pl_raw = d.monthly_expenses if d.monthly_expenses is not None else pd.DataFrame()
    cogs_rows_in_xero = pl_raw[pl_raw["bucket_section"] == "Cost of Sales"] if (not pl_raw.empty and "bucket_section" in pl_raw.columns) else pd.DataFrame()
    vendor_df_for_cogs = d.vendor_breakdown if d.vendor_breakdown is not None else pd.DataFrame()

    for bucket_id, label in _COGS_BUCKETS:
        bucket_rows = cogs_rows_in_xero[cogs_rows_in_xero["bucket"] == bucket_id] if not cogs_rows_in_xero.empty else pd.DataFrame()
        # Skip the Xero Cost of Goods Sold account itself — Shopify is the canonical product cost (avoids double-count).
        if bucket_id == "cogs_product_xero":
            continue
        if bucket_rows.empty:
            continue
        per_month = bucket_rows.groupby("month")["value"].apply(lambda s: float(s.abs().sum())).to_dict()
        cogs_component_monthly[bucket_id] = per_month

        component_row = [text_cell(f"pl.cogs.{bucket_id}.lbl", label, indent=1)]
        comp_12mo = 0.0
        for i, m in enumerate(months):
            v = per_month.get(m)
            if v:
                comp_12mo += v
            component_row.append(money_cell(f"pl.cogs.{bucket_id}.{i}", v, tooltip=Tooltip(
                formula=f"Sum of Xero `{label}` accounts for {month_label(m)} (Contribution-margin classification — variable cost per unit sold).",
                sources=[xero_src],
                confidence_note=("Posted in Xero." if v else "No posting this month."),
            )))
        component_row.append(money_cell(f"pl.cogs.{bucket_id}.tot", comp_12mo or None, tooltip=Tooltip(
            formula=f"12-month sum of {label}.", sources=[xero_src],
        ), is_total=True))
        # Vendor expansion if Atxn has matching accounts
        expandable_cogs = None
        if not vendor_df_for_cogs.empty:
            account_names = bucket_rows["account_lower"].unique().tolist()
            vmatch = vendor_df_for_cogs[vendor_df_for_cogs["account"].str.lower().isin(account_names)]
            if not vmatch.empty:
                expandable_cogs = f"vendor::{bucket_id}"
        tree.rows.append(make_row(component_row, expandable_key=expandable_cogs))

        # Vendor sub-rows under this COGS component
        if expandable_cogs:
            for contact in sorted(vmatch["contact"].dropna().unique().tolist()):
                sub_cells = [text_cell(f"pl.cogs.{bucket_id}.{contact}.lbl", f"• {contact}", indent=2)]
                contact_12mo = 0.0
                for i, m in enumerate(months):
                    v_match = vmatch[(vmatch["contact"] == contact) & (vmatch["month"] == m)]
                    cv = None
                    if not v_match.empty:
                        raw = float(v_match.iloc[0]["net"])
                        cv = abs(raw) if raw else None
                    if cv:
                        contact_12mo += cv
                    sub_cells.append(money_cell(f"pl.cogs.{bucket_id}.{contact}.{i}", cv, tooltip=Tooltip(
                        formula=f"Net spend with `{contact}` under {label} for {month_label(m)} (Credit−Debit per G35).",
                        sources=[atxn_src], gotcha_refs=["G35"],
                    )))
                sub_cells.append(money_cell(f"pl.cogs.{bucket_id}.{contact}.tot", contact_12mo or None, tooltip=Tooltip(
                    formula="12-month sum.", sources=[atxn_src], gotcha_refs=["G35"],
                ), is_total=True))
                tree.rows.append(make_row(sub_cells, sub_of=expandable_cogs))

    # 3. Returns Shipping & Processing — derived line (per-return cost × return count).
    # Skip if we can't derive (would mostly be 0 for now).

    # 4. TOTAL COST OF DELIVERY
    total_cogs_monthly: dict[date, float] = {}
    tot_cogs_cells = [text_cell("pl.totcogs.lbl", "TOTAL COST OF DELIVERY", bold=True)]
    tot_cogs_12mo = 0.0
    for i, m in enumerate(months):
        components = [cm.get(m, 0) for cm in cogs_component_monthly.values()]
        v = sum(components) if any(components) else None
        if v is not None:
            total_cogs_monthly[m] = v
            tot_cogs_12mo += v
        tot_cogs_cells.append(money_cell(f"pl.totcogs.{i}", v, tooltip=Tooltip(
            formula="Sum of all Cost of Goods Sold lines for the month.",
            sources=[shopify_src, xero_src],
        ), is_total=True))
    tot_cogs_cells.append(money_cell("pl.totcogs.tot", tot_cogs_12mo or None, tooltip=Tooltip(
        formula="12-month sum of all COGS lines.", sources=[shopify_src, xero_src],
    ), is_total=True))
    tree.rows.append(make_row(tot_cogs_cells, is_total=True))

    # ---- Inventory Suppliers — cash-basis info row (NOT in COGS totals) ----
    if bundle.xero_atxn is not None and not bundle.xero_atxn.empty:
        inv_rows = bundle.xero_atxn[bundle.xero_atxn["account"].str.lower() == "inventory"].copy()
        # Keep only true supplier rows — exclude CoGS Recognition journal lines that also touch Inventory.
        inv_rows = inv_rows[~inv_rows["contact"].astype(str).str.contains("CoGS Recognition|Incorrect|Adjustment", case=False, na=False)]
        if not inv_rows.empty:
            inv_rows["month"] = inv_rows["date"].apply(lambda dd: date(dd.year, dd.month, 1))
            # Cash outflow = Debit (purchases capitalise on the asset side)
            supplier_monthly = inv_rows.groupby(["contact", "month"], as_index=False)["debit"].sum()
            supplier_totals = (
                supplier_monthly.groupby("contact")["debit"].sum().sort_values(ascending=False)
            )
            non_zero_suppliers = [s for s in supplier_totals.index if supplier_totals[s] > 0]
            if non_zero_suppliers:
                memo_header = [section_cell("pl.invsup.h", "INVENTORY PURCHASES BY SUPPLIER  (memo — cash-basis, not in COGS totals)")] + [text_cell(f"pl.invsup.h.{i}", "") for i in range(n_cols + 1)]
                tree.rows.append(make_row(memo_header, is_section=True))
                grand_12mo = 0.0
                for supplier in non_zero_suppliers:
                    sub_cells = [text_cell(f"pl.invsup.{supplier}.lbl", supplier, indent=1)]
                    sup_12mo = 0.0
                    for i, m in enumerate(months):
                        match = supplier_monthly[(supplier_monthly["contact"] == supplier) & (supplier_monthly["month"] == m)]
                        v = float(match.iloc[0]["debit"]) if not match.empty and match.iloc[0]["debit"] else None
                        if v:
                            sup_12mo += v
                        sub_cells.append(money_cell(f"pl.invsup.{supplier}.{i}", v, tooltip=Tooltip(
                            formula=f"Inventory purchase from `{supplier}` in {month_label(m)} (Debit side of Inventory account).",
                            sources=[atxn_src],
                            confidence_note="Cash-out timing — purchase orders capitalised to Inventory, released to COGS later by recognition journals.",
                        )))
                    sub_cells.append(money_cell(f"pl.invsup.{supplier}.tot", sup_12mo or None, tooltip=Tooltip(
                        formula="12-month total of inventory purchases from this supplier.", sources=[atxn_src],
                    ), is_total=True))
                    tree.rows.append(make_row(sub_cells))
                    grand_12mo += sup_12mo
                total_cells = [text_cell("pl.invsup.tot.lbl", "Total Inventory Purchases (memo)", bold=True)]
                for i, m in enumerate(months):
                    monthly = supplier_monthly[supplier_monthly["month"] == m]["debit"].sum()
                    total_cells.append(money_cell(f"pl.invsup.tot.{i}", float(monthly) if monthly else None, is_total=True, tooltip=Tooltip(
                        formula="Sum of inventory purchases (all suppliers) for the month.", sources=[atxn_src],
                    )))
                total_cells.append(money_cell("pl.invsup.tot.tot", grand_12mo or None, is_total=True, tooltip=Tooltip(
                    formula="12-month inventory purchases.", sources=[atxn_src],
                )))
                tree.rows.append(make_row(total_cells, is_total=True))
                tree.rows.append(make_row([text_cell("pl.invsup.spacer", "")] + [text_cell(f"pl.invsup.spacer.{i}", "") for i in range(n_cols + 1)]))

    # ---- GROSS PROFIT ----
    gp_monthly: dict[date, float | None] = {}
    gp_cells = [text_cell("pl.gp.lbl", "GROSS PROFIT", bold=True)]
    gp_total_12mo = 0.0
    for i, m in enumerate(months):
        rev = revenue_monthly.get(m)
        c = total_cogs_monthly.get(m)
        if rev is not None and c is not None:
            gp = rev - c
        elif rev is not None:
            gp = rev
        else:
            gp = None
        gp_monthly[m] = gp
        if gp is not None:
            gp_total_12mo += gp
        gp_cells.append(money_cell(f"pl.gp.{i}", gp, tooltip=Tooltip(
            formula="Net Sales − Total COGS",
            inputs=[("Net Sales", rev), ("Total COGS", c)],
            result_expr=f"{rev:,.0f} − {c:,.0f} = {gp:,.0f}" if (rev is not None and c is not None) else "—",
            sources=[shopify_src, xero_src], gotcha_refs=["G39"],
            confidence_note="Contribution-margin Gross Profit — all variable costs deducted.",
        ), is_total=True))
    gp_cells.append(money_cell("pl.gp.tot", gp_total_12mo or None, tooltip=Tooltip(
        formula="12-month Gross Profit.", sources=[shopify_src, xero_src],
    ), is_total=True))
    tree.rows.append(make_row(gp_cells, is_total=True))

    # ---- GROSS MARGIN % ----
    gm_cells = [text_cell("pl.gm.lbl", "Gross Margin %", indent=1)]
    for i, m in enumerate(months):
        rev = revenue_monthly.get(m)
        gp = gp_monthly.get(m)
        gm = (gp / rev) if (rev and gp is not None and rev > 0) else None
        gm_cells.append(pct_cell(f"pl.gm.{i}", gm, tooltip=Tooltip(
            formula="Gross Profit / Net Sales",
            inputs=[("GP", gp), ("Net Sales", rev)],
            result_expr=f"{gp:,.0f} / {rev:,.0f} = {gm*100:.1f}%" if gm is not None else "—",
            sources=[shopify_src, xero_src],
        )))
    # 12mo margin
    gm_12mo = (gp_total_12mo / rev_total_12mo) if rev_total_12mo > 0 else None
    gm_cells.append(pct_cell("pl.gm.tot", gm_12mo, tooltip=Tooltip(
        formula="12-month GP / 12-month Net Sales.", sources=[shopify_src, xero_src],
    )))
    tree.rows.append(make_row(gm_cells))

    tree.rows.append(make_row([text_cell("pl.spacer2", "")] + [text_cell(f"pl.spacer2.{i}", "") for i in range(n_cols + 1)]))

    # ---- Operating Expense sections from Xero ----
    pl_raw = d.monthly_expenses if d.monthly_expenses is not None else pd.DataFrame()
    if pl_raw.empty:
        tree.banners.append(Banner(severity="warning",
            text="Xero P&L has no expense rows posted — Operating Expense sections will be empty."))
        pl_raw = pd.DataFrame(columns=["account", "account_lower", "bucket", "bucket_section", "is_revenue", "is_other_income", "value", "month", "sort"])

    # Inject Marketing row sourced from ad-platform CSVs if Xero has no marketing accounts
    marketing_in_xero = pl_raw[pl_raw["bucket_section"] == "Marketing"] if not pl_raw.empty else pd.DataFrame()
    inject_marketing_from_ads = marketing_in_xero.empty and not d.monthly_ad_spend.empty
    ad_marketing_monthly: dict[date, float] = {}
    if inject_marketing_from_ads:
        ad_monthly = d.monthly_ad_spend.groupby("month", as_index=False)["amount"].sum()
        ad_marketing_monthly = {row["month"]: float(row["amount"]) for _, row in ad_monthly.iterrows()}

    # ---- OTHER INCOME ----
    other_income = pl_raw[pl_raw.get("is_other_income") == True] if "is_other_income" in pl_raw.columns else pd.DataFrame()
    other_income_monthly: dict[date, float] = {}
    if not other_income.empty:
        tree.rows.append(make_row(
            [section_cell("pl.oi.h", "OTHER INCOME")] + [text_cell(f"pl.oi.h.{i}", "") for i in range(n_cols + 1)],
            is_section=True,
        ))
        for account in sorted(other_income["account"].unique()):
            acc_rows = other_income[other_income["account"] == account]
            cells = [text_cell(f"pl.oi.{account}.lbl", account, indent=1)]
            account_12mo = 0.0
            for i, m in enumerate(months):
                match = acc_rows[acc_rows["month"] == m]
                v = float(match.iloc[0]["value"]) if not match.empty and match.iloc[0]["value"] else None
                if v is not None:
                    account_12mo += v
                    other_income_monthly[m] = other_income_monthly.get(m, 0) + v
                cells.append(money_cell(f"pl.oi.{account}.{i}", v, tooltip=Tooltip(
                    formula=f"Xero row '{account}' for {month_label(m)}", sources=[xero_src],
                )))
            cells.append(money_cell(f"pl.oi.{account}.tot", account_12mo or None, tooltip=Tooltip(
                formula="12-month sum.", sources=[xero_src],
            ), is_total=True))
            tree.rows.append(make_row(cells))
        # TOTAL OTHER INCOME
        toi_cells = [text_cell("pl.toi.lbl", "TOTAL OTHER INCOME", bold=True)]
        toi_12mo = 0.0
        for i, m in enumerate(months):
            v = other_income_monthly.get(m)
            if v:
                toi_12mo += v
            toi_cells.append(money_cell(f"pl.toi.{i}", v, is_total=True, tooltip=Tooltip(formula="Sum of Other Income rows for the month.", sources=[xero_src])))
        toi_cells.append(money_cell("pl.toi.tot", toi_12mo or None, is_total=True, tooltip=Tooltip(formula="12-mo sum.", sources=[xero_src])))
        tree.rows.append(make_row(toi_cells, is_total=True))
        tree.rows.append(make_row([text_cell("pl.spacer_oi", "")] + [text_cell(f"pl.spacer_oi.{i}", "") for i in range(n_cols + 1)]))

    # ---- OPEX sections (Marketing / People / Software / Other Operating Expenses) ----
    opex_section_monthly: dict[str, dict[date, float]] = {s: {} for s in _EXPENSE_SECTION_ORDER}

    for section in _EXPENSE_SECTION_ORDER:
        section_rows = pl_raw[(pl_raw["bucket_section"] == section)] if not pl_raw.empty else pd.DataFrame()

        if section == "Marketing" and inject_marketing_from_ads:
            tree.rows.append(make_row(
                [section_cell(f"pl.sec.{section}", section.upper())] + [text_cell(f"pl.sec.{section}.h.{i}", "") for i in range(n_cols + 1)],
                is_section=True,
            ))
            cells = [text_cell("pl.marketing_ads.lbl", "Ad Platform Spend (from CSVs)", indent=1)]
            section_12mo = 0.0
            for i, m in enumerate(months):
                v = ad_marketing_monthly.get(m)
                if v:
                    section_12mo += v
                    opex_section_monthly[section][m] = opex_section_monthly[section].get(m, 0) + v
                cells.append(money_cell(f"pl.marketing_ads.{i}", v, tooltip=Tooltip(
                    formula=f"Sum of platform daily ad spend ×FX for {month_label(m)}",
                    sources=[ad_src], gotcha_refs=["G39"],
                    confidence_note="Sourced from ad-platform CSVs — Xero has no Marketing/Advertising accounts. Convertible via daily FX where applicable.",
                )))
            cells.append(money_cell("pl.marketing_ads.tot", section_12mo or None, tooltip=Tooltip(
                formula="12-month sum from ad-platform CSVs.", sources=[ad_src],
            ), is_total=True))
            tree.rows.append(make_row(cells))
            # TOTAL row for the section
            tot_cells = [text_cell(f"pl.tot.{section}.lbl", f"TOTAL {section.upper()}", bold=True)]
            sec_12mo = 0.0
            for i, m in enumerate(months):
                v = opex_section_monthly[section].get(m)
                if v: sec_12mo += v
                tot_cells.append(money_cell(f"pl.tot.{section}.{i}", v, is_total=True))
            tot_cells.append(money_cell(f"pl.tot.{section}.tot", sec_12mo or None, is_total=True))
            tree.rows.append(make_row(tot_cells, is_total=True))
            tree.rows.append(make_row([text_cell(f"pl.spacer.{section}", "")] + [text_cell(f"pl.spacer.{section}.{i}", "") for i in range(n_cols + 1)]))
            continue

        if section_rows.empty:
            continue

        tree.rows.append(make_row(
            [section_cell(f"pl.sec.{section}", section.upper())] + [text_cell(f"pl.sec.{section}.h.{i}", "") for i in range(n_cols + 1)],
            is_section=True,
        ))

        sorted_accounts = section_rows[["account", "sort"]].drop_duplicates().sort_values(["sort", "account"])
        vendor_df = d.vendor_breakdown if d.vendor_breakdown is not None else pd.DataFrame()

        for _, srow in sorted_accounts.iterrows():
            account = srow["account"]
            account_lower = account.lower()
            account_rows = section_rows[section_rows["account"] == account]
            cells = [text_cell(f"pl.{account_lower}.lbl", account, indent=1, bold=True)]
            account_12mo = 0.0
            for i, m in enumerate(months):
                match = account_rows[account_rows["month"] == m]
                v = None
                if not match.empty:
                    raw = float(match.iloc[0]["value"])
                    v = abs(raw) if raw else None
                if v is not None:
                    account_12mo += v
                    opex_section_monthly[section][m] = opex_section_monthly[section].get(m, 0) + v
                cells.append(money_cell(f"pl.{account_lower}.{i}", v, tooltip=Tooltip(
                    formula=f"Xero P&L row '{account}' for {month_label(m)}",
                    sources=[xero_src],
                    confidence_note=("Provisional — posting-date, may include catch-up entries." if v else "No posting this month."),
                )))
            cells.append(money_cell(f"pl.{account_lower}.tot", account_12mo or None, tooltip=Tooltip(
                formula="12-month sum.", sources=[xero_src],
            ), is_total=True))
            # Vendor expandability key
            expandable = None
            if not vendor_df.empty:
                vendor_match = vendor_df[vendor_df["account"].str.lower().str.contains(account_lower) | (vendor_df["account"].str.lower() == account_lower)]
                if not vendor_match.empty:
                    expandable = f"vendor::{account_lower}"
            tree.rows.append(make_row(cells, expandable_key=expandable))

            if expandable:
                contacts = sorted(vendor_match["contact"].dropna().unique().tolist())
                for contact in contacts:
                    sub_cells = [text_cell(f"pl.{account_lower}.{contact}.lbl", f"• {contact}", indent=2)]
                    contact_12mo = 0.0
                    for i, m in enumerate(months):
                        cv = None
                        v_match = vendor_match[(vendor_match["contact"] == contact) & (vendor_match["month"] == m)]
                        if not v_match.empty:
                            cv = float(v_match.iloc[0]["net"])
                            cv = abs(cv) if cv else cv
                        if cv:
                            contact_12mo += cv
                        sub_cells.append(money_cell(f"pl.{account_lower}.{contact}.{i}", cv, tooltip=Tooltip(
                            formula=f"Net spend with `{contact}` under `{account}` for {month_label(m)} (Credit − Debit per G35).",
                            sources=[atxn_src], gotcha_refs=["G35"],
                            confidence_note="Vendor-net via Credit − Debit; absolute value displayed.",
                        )))
                    sub_cells.append(money_cell(f"pl.{account_lower}.{contact}.tot", contact_12mo or None, tooltip=Tooltip(
                        formula="12-month sum.", sources=[atxn_src], gotcha_refs=["G35"],
                    ), is_total=True))
                    tree.rows.append(make_row(sub_cells, sub_of=expandable))

        # TOTAL <section>
        tot_cells = [text_cell(f"pl.tot.{section}.lbl", f"TOTAL {section.upper()}", bold=True)]
        sec_12mo = 0.0
        for i, m in enumerate(months):
            v = opex_section_monthly[section].get(m)
            if v: sec_12mo += v
            tot_cells.append(money_cell(f"pl.tot.{section}.{i}", v, is_total=True, tooltip=Tooltip(formula=f"Sum of {section} rows for the month.", sources=[xero_src])))
        tot_cells.append(money_cell(f"pl.tot.{section}.tot", sec_12mo or None, is_total=True, tooltip=Tooltip(formula=f"12-month sum of {section}.", sources=[xero_src])))
        tree.rows.append(make_row(tot_cells, is_total=True))
        tree.rows.append(make_row([text_cell(f"pl.spacer.{section}", "")] + [text_cell(f"pl.spacer.{section}.{i}", "") for i in range(n_cols + 1)]))

    # ---- TOTAL OPERATING EXPENSES ----
    opex_monthly: dict[date, float] = {}
    for section_monthly in opex_section_monthly.values():
        for m, v in section_monthly.items():
            opex_monthly[m] = opex_monthly.get(m, 0) + v
    total_opex_cells = [text_cell("pl.totopex.lbl", "TOTAL OPERATING EXPENSES", bold=True)]
    total_opex_12mo = 0.0
    for i, m in enumerate(months):
        v = opex_monthly.get(m)
        if v: total_opex_12mo += v
        total_opex_cells.append(money_cell(f"pl.totopex.{i}", v, is_total=True, tooltip=Tooltip(
            formula="Sum of Marketing + People + Software + Other Operating Expenses.",
            sources=[xero_src, ad_src],
        )))
    total_opex_cells.append(money_cell("pl.totopex.tot", total_opex_12mo or None, is_total=True, tooltip=Tooltip(
        formula="12-month sum of all Operating Expenses.", sources=[xero_src, ad_src],
    )))
    tree.rows.append(make_row(total_opex_cells, is_total=True))

    # ---- NET PROFIT ----
    np_cells = [text_cell("pl.np.lbl", "NET PROFIT", bold=True)]
    np_12mo = 0.0
    for i, m in enumerate(months):
        gp = gp_monthly.get(m)
        oi = other_income_monthly.get(m, 0)
        opex = opex_monthly.get(m, 0)
        if gp is None and not oi and not opex:
            np = None
        else:
            np = (gp or 0) + oi - opex
            np_12mo += np
        np_cells.append(money_cell(f"pl.np.{i}", np, is_total=True, tooltip=Tooltip(
            formula="Gross Profit + Other Income − Total Operating Expenses",
            inputs=[("GP", gp), ("Other Income", oi), ("OPEX", opex)],
            result_expr=f"{gp or 0:,.0f} + {oi:,.0f} − {opex:,.0f} = {np:,.0f}" if np is not None else "—",
            sources=[shopify_src, xero_src, ad_src], gotcha_refs=["G39"],
            confidence_note="Provisional — degrades to '—' when no GP, Other Income, or OPEX is available.",
        )))
    np_cells.append(money_cell("pl.np.tot", np_12mo or None, is_total=True, tooltip=Tooltip(
        formula="12-month Net Profit.", sources=[shopify_src, xero_src, ad_src],
    )))
    tree.rows.append(make_row(np_cells, is_total=True))

    # ---- Banners ----
    if use_xero_cogs:
        tree.banners.append(Banner(severity="info",
            text="Product COGS uses Xero CoGS Recognition journals (accrual basis). SKU sub-rows are normalised from the bookkeeper's journal descriptions (e.g. 'Jun 25_<SKU>_CoGS Recognition' → '<SKU>'). Inventory suppliers appear as a memo block below Total COGS — cash-out timing, separate from accrual COGS."))
    else:
        tree.banners.append(Banner(severity="info",
            text="Cost of Sales uses contribution-margin classification: Product COGS comes from Shopify per-sale (×FX), variable costs (Freight, Packaging, Merchant Fees, Fulfilment, Customs) come from Xero. Gross Profit is the landed contribution margin."))
    if getattr(d, "pl_source", "xero_pl_file") == "atxn_derived":
        tree.banners.append(Banner(severity="info",
            text="The supplied Xero P&L file was thinner than the Account Transactions export — P&L lines have been reconstructed from Account Transactions (Credit − Debit per account-month). Vendor breakdown comes from the same source."))
    elif meta.files_found.get("xero_pl"):
        tree.banners.append(Banner(severity="warning",
            text="Using the supplied Xero P&L file — it overrides the Account-Transactions reconstruction and takes precedence for these expense lines. Verify the bookkeeper's categorisation, since any mis-mapped account flows straight into these figures."))
    if inject_marketing_from_ads:
        tree.banners.append(Banner(severity="info",
            text="No Marketing/Advertising account found in Xero — the Marketing section is sourced from the ad-platform CSVs instead (Meta + Google + TikTok where present)."))
    posted = d.posted_months or []
    if posted:
        first, last = posted[0], posted[-1]
        gap_months = 12 - len(posted)
        sev = "warning" if gap_months >= 6 else "info"
        tree.banners.append(Banner(severity=sev,
            text=f"Xero Operating Expenses coverage: {month_label(first)} – {month_label(last)} ({len(posted)} months posted, {gap_months} months missing). Empty months render '—'."))
    else:
        tree.banners.append(Banner(severity="warning",
            text="Xero P&L shows no posted activity — Operating Expense rows render '—'."))

    if not d.vendor_breakdown.empty and d.vendor_breakdown["account"].nunique() == 1:
        only_account = d.vendor_breakdown["account"].iloc[0]
        tree.banners.append(Banner(severity="info",
            text=f"Account Transactions export is bank-account-mode ('{only_account}' only). Vendor sub-rows aggregate by contact at the bank level; cannot attribute to specific expense accounts. Request an expense-grouped Atxn export for richer breakdown."))

    # ---- % of Net Sales column (each line's 12-mo total ÷ 12-mo Net Sales) ----
    tree.columns.append("% of Net Sales")
    for row in tree.rows:
        if not row.cells:
            continue
        last = row.cells[-1]
        base = last.coord or (row.cells[0].coord or "row")
        if (not row.is_section and rev_total_12mo > 0
                and last.fmt in ("currency", "currency_dec") and isinstance(last.value, (int, float))):
            row.cells.append(pct_cell(f"{base}.pctnet", float(last.value) / rev_total_12mo, tooltip=Tooltip(
                formula="This line's 12-month total ÷ 12-month Net Sales.",
                sources=[shopify_src],
            )))
        else:
            row.cells.append(text_cell(f"{base}.pctnet", ""))

    # ---- Notes section at bottom ----
    tree.notes = [
        "Click a section header to collapse/expand the group; click ▸ on an account row to expand vendor detail (where Account Transactions is grouped by expense account).",
        "% of Net Sales = the line's 12-month total as a share of 12-month Net Sales.",
        "Vendor net = Credit − Debit per (account, contact, month). G35.",
        "Account totals are SUM formulas — adjust an underlying number and the rollup follows.",
        "Months with no Xero posting render as '—' rather than 0 — silent zeros would be misleading (G39).",
    ]

    return tree
