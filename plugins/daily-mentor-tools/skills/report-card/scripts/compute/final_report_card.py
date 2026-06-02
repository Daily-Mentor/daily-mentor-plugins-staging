"""Final Report Card — Bleed/Fix diagnostic dashboard vs Daily Mentor benchmarks.

Three blocks:
  1. Revenue breakdown (Gross / Discounts / Refunds / Shipping / Tax / Total Revenue)
  2. Financial Benchmarks (Profit %, COGS %, Marketing %, OPEX %) with $ bleed + % fix prescription
  3. Growth Benchmarks (MER, CM, Returns, AOV, NC share, RC AOV lift, LTV growth)
  4. Ops Benchmarks (COGS %, OPEX %, lead times, inventory days, ad-launch cadence)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


_BENCHMARKS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "benchmarks.json"


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc
    with _BENCHMARKS_PATH.open() as f:
        bm = json.load(f)

    tree = RenderTree(tab_id="final_report_card", title="Final Report Card",
                      subtitle="Bleed / Fix diagnostic vs Daily Mentor targets. Revenue & financials are full 12-month (Shopify daily + Xero); the New-vs-Returning split is from the NC/RC file.")

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC missing — cannot derive Final Report Card."))
        return tree

    # NC vs RC split — aggregate ALL quarters in the NC/RC file (full 12 months).
    # The daily sales file can't split New vs Returning, so the behavioural metrics
    # (NC share, RC AOV lift, NC/RC AOV) come from here. Revenue itself comes from the
    # daily file below. We .sum() across every quarter — never a single quarter.
    new_rows = nc_rc[nc_rc["segment"].str.lower() == "new"]
    ret_rows = nc_rc[nc_rc["segment"].str.lower() == "returning"]

    def _seg_sum(df, col):
        return float(df[col].sum()) if (not df.empty and col in df.columns) else 0.0

    nc_orders = int(_seg_sum(new_rows, "orders"))
    rc_orders = int(_seg_sum(ret_rows, "orders"))
    total_orders = nc_orders + rc_orders
    # Performance Sales (incl. tax) per segment — the AOV convention (Daily Mentor).
    nc_perf = (_seg_sum(new_rows, "gross") + _seg_sum(new_rows, "discounts")
               + _seg_sum(new_rows, "shipping") + _seg_sum(new_rows, "taxes"))
    rc_perf = (_seg_sum(ret_rows, "gross") + _seg_sum(ret_rows, "discounts")
               + _seg_sum(ret_rows, "shipping") + _seg_sum(ret_rows, "taxes"))

    # Average posted monthly OPEX — used only for the coverage banner below.
    avg_opex = None
    if not d.monthly_expenses.empty and d.posted_months:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        per_month = non_cogs.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
        non_zero = per_month[per_month > 0]
        avg_opex = float(non_zero.mean()) if not non_zero.empty else None
    opex_period = (avg_opex * 3) if avg_opex else None

    src_nc_rc = Path(meta.files_found.get("nc_rc", "")).name
    src_ads = Path(meta.files_found.get("ad_spend_meta", "")).name
    src_xero = Path(meta.files_found.get("xero_pl", "")).name
    src_shopify = Path(meta.files_found.get("shopify_daily", "")).name
    # COGS / OPEX come from Xero — the supplied P&L if present, otherwise the
    # Account-Transactions reconstruction it was derived from.
    src_xero_acc = Path(meta.files_found.get("xero_pl") or meta.files_found.get("xero_atxn", "")).name

    # ===== Full 12-month basis (drives Profit and the Financial Benchmarks) =====
    # Revenue is the Shopify daily-sales total (Net Sales ×FX, G39) across the whole
    # 12-month lookback. COGS comes only from Xero (Cost of Sales). Ad spend is the
    # full-period platform total. OPEX excludes Cost of Sales *and* Marketing —
    # marketing is already counted once via ad spend, never doubled from Xero.
    rev_12mo = None
    if not d.monthly_revenue_components.empty and "net_aud" in d.monthly_revenue_components.columns:
        rev_12mo = float(d.monthly_revenue_components["net_aud"].sum())
    me_full = d.monthly_expenses if d.monthly_expenses is not None else pd.DataFrame()
    cogs_12mo = None
    opex_12mo = None
    if not me_full.empty and "bucket_section" in me_full.columns:
        oi_mask = me_full["is_other_income"].fillna(False) if "is_other_income" in me_full.columns else False
        cogs_rows_12 = me_full[me_full["bucket_section"] == "Cost of Sales"]
        cogs_12mo = float(cogs_rows_12["value"].abs().sum())
        opex_rows_12 = me_full[(~me_full["bucket_section"].isin(["Cost of Sales", "Marketing"])) & (~oi_mask)]
        opex_12mo = float(opex_rows_12["value"].abs().sum())
    ad_spend_12mo = float(d.daily_ad_spend["amount"].sum()) if not d.daily_ad_spend.empty else 0.0

    profit_12mo = None
    if rev_12mo is not None:
        profit_12mo = rev_12mo - (cogs_12mo or 0) - ad_spend_12mo - (opex_12mo or 0)
    profit_pct_12 = safe_div(profit_12mo, rev_12mo)
    cogs_pct_12 = safe_div(cogs_12mo, rev_12mo)
    marketing_pct_12 = safe_div(ad_spend_12mo, rev_12mo)
    opex_pct_12 = safe_div(opex_12mo, rev_12mo)

    # Revenue Breakdown line items — all from the Shopify daily file (source of truth),
    # full 12 months ×FX. Net Sales (= Gross + Discounts + Returns, G39) is the revenue
    # base that the Financial Benchmarks divide by; Shipping and Tax are collected but
    # are not revenue, so they sit below the Net Sales subtotal.
    mrc = d.monthly_revenue_components

    def _rc12(col):
        return float(mrc[col].sum()) if (not mrc.empty and col in mrc.columns) else None
    rb_gross = _rc12("gross_aud")
    rb_disc = _rc12("discounts_aud")
    rb_ret = _rc12("returns_aud")
    rb_net = _rc12("net_aud")
    rb_ship = _rc12("shipping_aud")
    rb_tax = _rc12("taxes_aud")

    # ===== Growth metrics on the same full-12-month basis as the rest of the card =====
    # Revenue base = daily-file Net Sales (rev_12mo); COGS = Xero; Ad = full-period total.
    # The NC/RC file supplies only the New-vs-Returning split (orders & per-segment AOV).
    total_rev = rev_12mo
    total_cogs = cogs_12mo
    cm = safe_div((rev_12mo - (cogs_12mo or 0) - ad_spend_12mo) if rev_12mo is not None else None, rev_12mo)
    returns_pct = safe_div(abs(rb_ret) if rb_ret is not None else None, rev_12mo)
    blended_aov = safe_div(rev_12mo, total_orders)
    nc_share = safe_div(nc_orders, total_orders)
    nc_aov = safe_div(nc_perf, nc_orders)
    rc_aov = safe_div(rc_perf, rc_orders) if rc_orders else None
    rc_lift = safe_div((rc_aov - nc_aov) if (rc_aov and nc_aov) else None, nc_aov) if nc_aov else None
    cr = None
    if bundle.sessions is not None and not bundle.sessions.empty:
        sessions_12mo = float(bundle.sessions.tail(12)["sessions"].sum())
        cr = safe_div(total_orders, sessions_12mo)

    # ===== Block 1: Revenue Breakdown (Shopify daily, full 12-month) =====
    tree.columns = ["Metric", "Actual", "Target", "Status", "Bleed", "Fix"]
    tree.rows.append(make_row(
        [section_cell("frc.s0", "REVENUE BREAKDOWN (Shopify daily — full 12-month)")] + [text_cell(f"frc.s0.{c}", "") for c in "abcd"],
        is_section=True,
    ))

    def revrow(name, value, formula, *, gotcha=None):
        return make_row([
            text_cell(f"frc.r.{name}.lbl", name, indent=1),
            money_cell(f"frc.r.{name}.v", value, tooltip=Tooltip(
                formula=formula,
                sources=[src_shopify], gotcha_refs=gotcha or ["G39"],
            )),
            text_cell(f"frc.r.{name}.t", ""),
            text_cell(f"frc.r.{name}.s", ""),
            text_cell(f"frc.r.{name}.b", ""),
            text_cell(f"frc.r.{name}.f", ""),
        ])
    tree.rows.append(revrow("Gross Sales", rb_gross, "Sum of Shopify daily Gross sales ×FX (12 months)."))
    tree.rows.append(revrow("Discounts", rb_disc, "Sum of Shopify daily Discounts ×FX (12 months)."))
    tree.rows.append(revrow("Returns", rb_ret, "Sum of Shopify daily Returns ×FX (12 months)."))
    tree.rows.append(make_row([
        text_cell("frc.r.net.lbl", "Net Sales (revenue base)", bold=True),
        money_cell("frc.r.net.v", rb_net, tooltip=Tooltip(
            formula="Net Sales = Gross + Discounts + Returns (excludes Shipping & Tax, G39). The base for all benchmark percentages.",
            inputs=[("Gross", rb_gross), ("Disc", rb_disc), ("Returns", rb_ret)],
            result_expr=f"= {rb_net:,.0f}" if rb_net is not None else "—",
            sources=[src_shopify], gotcha_refs=["G39"],
        ), is_total=True),
        text_cell("frc.r.net.t", ""),
        text_cell("frc.r.net.s", ""),
        text_cell("frc.r.net.b", ""),
        text_cell("frc.r.net.f", ""),
    ], is_total=True))
    tree.rows.append(revrow("Shipping charges (collected)", rb_ship, "Sum of Shopify daily Shipping ×FX (12 months). Collected — not part of Net Sales."))
    tree.rows.append(revrow("Tax (collected)", rb_tax, "Sum of Shopify daily Taxes ×FX (12 months). Collected for the tax authority — not revenue."))

    # ===== Helper for benchmark rows =====
    def status_str(ok: bool | None) -> str:
        return "✓" if ok else ("✗" if ok is False else "—")

    def bleed_and_fix(actual_pct, target_pct, *, max_target: bool):
        """Return (bleed_dollars, fix_text). Bleed positive = $ over (max target) or $ under (min target)."""
        if actual_pct is None or target_pct is None or total_rev is None:
            return None, "—"
        if max_target:
            # Target is a ceiling (e.g. <30%); bleed = excess × rev (positive when over)
            bleed = (actual_pct - target_pct) * total_rev
            if bleed > 0:
                return bleed, f"Decrease by {(actual_pct - target_pct)*100:.1f} pts"
            return bleed, f"Headroom — {abs(actual_pct - target_pct)*100:.1f} pts under cap"
        else:
            # Target is a floor (e.g. ≥15%); bleed = shortfall × rev (positive when under)
            bleed = (target_pct - actual_pct) * total_rev
            if bleed > 0:
                return bleed, f"Increase by {(target_pct - actual_pct)*100:.1f} pts"
            return bleed, f"Above floor — {abs(actual_pct - target_pct)*100:.1f} pts above"

    def benchrow(name, actual, target_pct, *, max_target: bool, actual_fmt="pct", target_str: str | None = None, tooltip: Tooltip | None = None):
        ok = None
        if actual is not None and target_pct is not None:
            ok = (actual < target_pct) if max_target else (actual > target_pct)
        # Bleed/Fix only meaningful when actual is a %-of-revenue metric. For dollar-valued metrics
        # (AOV, etc.) or unit metrics (days), the bleed × rev calc is nonsensical.
        if actual_fmt == "pct":
            bleed, fix = bleed_and_fix(actual, target_pct, max_target=max_target)
        else:
            bleed = None
            if actual is not None and target_pct is not None:
                delta = actual - target_pct
                fix = (f"Decrease by {abs(delta):.1f}" if (max_target and delta > 0) else
                       f"Increase by {abs(delta):.1f}" if (not max_target and delta < 0) else
                       f"On target — {abs(delta):.1f} headroom")
            else:
                fix = "—"
        actual_cell = (
            pct_cell(f"frc.b.{name}.a", actual, tooltip=tooltip) if actual_fmt == "pct"
            else money_cell(f"frc.b.{name}.a", actual, tooltip=tooltip, decimals=2)
        )
        # Keep the target's decimal (e.g. 2.5%) — rounding it to a whole number made
        # a passing-looking number read as a fail (2.3% vs a "2%" label that was really 2.5%).
        if target_str:
            target_label = target_str
        elif target_pct is not None:
            _tp = f"{target_pct*100:.1f}".rstrip("0").rstrip(".")
            target_label = f"< {_tp}%" if max_target else f"> {_tp}%"
        else:
            target_label = "—"
        bleed_cell = (
            money_cell(f"frc.b.{name}.b", bleed, tooltip=Tooltip(
                formula=("Excess over cap × Revenue" if max_target else "Shortfall under floor × Revenue"),
                sources=[src_nc_rc],
            )) if bleed is not None else text_cell(f"frc.b.{name}.b", "—")
        )
        return make_row([
            text_cell(f"frc.b.{name}.lbl", name, indent=1),
            actual_cell,
            text_cell(f"frc.b.{name}.t", target_label),
            text_cell(f"frc.b.{name}.s", status_str(ok)),
            bleed_cell,
            text_cell(f"frc.b.{name}.f", fix),
        ])

    # ===== Block 2: Financial Benchmarks (full 12-month basis) =====
    tree.rows.append(make_row(
        [section_cell("frc.s1", "FINANCIAL BENCHMARKS (full 12-month)")] + [text_cell(f"frc.s1.{c}", "") for c in "abcd"],
        is_section=True,
    ))
    tree.rows.append(benchrow("Profit %", profit_pct_12, bm['financial']['profit_pct_min'], max_target=False,
        tooltip=Tooltip(formula="12-month Profit / 12-month Shopify Revenue. Profit = Revenue − COGS − Ad Spend − OPEX.",
                        inputs=[("Profit", profit_12mo), ("Revenue", rev_12mo)],
                        sources=[src_shopify, src_xero_acc, src_ads], gotcha_refs=["G39"])))
    tree.rows.append(benchrow("COGS %", cogs_pct_12, bm['financial']['cogs_pct_max'], max_target=True,
        tooltip=Tooltip(formula="12-month Xero Cost of Sales / 12-month Shopify Revenue.",
                        inputs=[("COGS", cogs_12mo), ("Revenue", rev_12mo)], sources=[src_xero_acc])))
    tree.rows.append(benchrow("Marketing %", marketing_pct_12, bm['financial']['marketing_pct_max'], max_target=True,
        tooltip=Tooltip(formula="12-month platform Ad Spend / 12-month Shopify Revenue.",
                        inputs=[("Ad", ad_spend_12mo), ("Revenue", rev_12mo)], sources=[src_ads], gotcha_refs=["G39"])))
    tree.rows.append(benchrow("OPEX %", opex_pct_12, bm['financial']['opex_pct_max'], max_target=True,
        tooltip=Tooltip(formula="12-month Xero OPEX (excl. Cost of Sales and Marketing) / 12-month Shopify Revenue.",
                        inputs=[("OPEX", opex_12mo), ("Revenue", rev_12mo)], sources=[src_xero_acc])))

    # ===== Block 3: Growth Benchmarks =====
    tree.rows.append(make_row(
        [section_cell("frc.s2", "GROWTH BENCHMARKS (snapshot — New vs Returning)")] + [text_cell(f"frc.s2.{c}", "") for c in "abcd"],
        is_section=True,
    ))
    tree.rows.append(benchrow("MER (Ad / Rev)", marketing_pct_12, bm['growth']['mer_max'], max_target=True,
        tooltip=Tooltip(formula="12-month platform Ad Spend / 12-month Shopify Net Sales (same ratio as Marketing %).",
                        inputs=[("Ad Spend", ad_spend_12mo), ("Net Sales", rev_12mo)],
                        sources=[src_ads, src_shopify], gotcha_refs=["G39"])))
    tree.rows.append(benchrow("Contribution Margin", cm, bm['growth']['contribution_margin_min'], max_target=False,
        tooltip=Tooltip(formula="(Revenue − COGS − Ad) / Revenue", sources=[src_nc_rc, src_ads])))
    tree.rows.append(benchrow("Returns %", returns_pct, bm['growth']['returns_pct_max'], max_target=True,
        tooltip=Tooltip(formula="abs(Refunds) / Revenue", sources=[src_nc_rc])))
    tree.rows.append(benchrow("Conversion Rate", cr, bm['growth']['conversion_rate_min'], max_target=False,
        tooltip=Tooltip(formula="Orders / Sessions (last 3 months)", sources=[src_nc_rc])))
    tree.rows.append(benchrow("Blended AOV", blended_aov, bm['growth']['aov_min_aud'], max_target=False, actual_fmt="money",
        target_str=f"> ${bm['growth']['aov_min_aud']}",
        tooltip=Tooltip(formula="Revenue / Orders", sources=[src_nc_rc])))
    tree.rows.append(benchrow("NC Order Share", nc_share, None, max_target=False,
        target_str=f"{int(bm['growth']['nc_order_share_min']*100)}–{int(bm['growth']['nc_order_share_max']*100)}%",
        tooltip=Tooltip(formula="NC Orders / Total Orders", sources=[src_nc_rc])))
    # NC share manual status
    if nc_share is not None:
        ok_share = bm['growth']['nc_order_share_min'] <= nc_share <= bm['growth']['nc_order_share_max']
        last_row = tree.rows[-1]
        last_row.cells[3] = text_cell("frc.b.NC Order Share.s", status_str(ok_share))
        # Bleed/Fix
        if nc_share < bm['growth']['nc_order_share_min']:
            last_row.cells[5] = text_cell("frc.b.NC Order Share.f", f"Increase NC share by {(bm['growth']['nc_order_share_min']-nc_share)*100:.0f} pts")
        elif nc_share > bm['growth']['nc_order_share_max']:
            last_row.cells[5] = text_cell("frc.b.NC Order Share.f", f"Re-engage RCs — NC share {(nc_share-bm['growth']['nc_order_share_max'])*100:.0f} pts above the band")
        else:
            last_row.cells[5] = text_cell("frc.b.NC Order Share.f", "Inside band")

    tree.rows.append(benchrow("RC AOV Lift vs NC", rc_lift, bm['growth']['rc_aov_lift_min'], max_target=False,
        tooltip=Tooltip(formula="(RC AOV − NC AOV) / NC AOV. Positive = RC spends more than NC.",
                        inputs=[("NC AOV", nc_aov), ("RC AOV", rc_aov)], sources=[src_nc_rc])))

    # LTV growth rows — populated from the cohort matrix (LTV tab stashes blended growth on derived).
    ltv_growth = getattr(d, "ltv_growth", None)
    m2_actual = ltv_growth.get(2) if ltv_growth else None
    m5_actual = ltv_growth.get(5) if ltv_growth else None
    _cohort_note = ("From Shopify Cohort Analysis — blended cumulative customer value vs Month 0."
                    if ltv_growth else "Missing — Cohort Analysis CSV not provided; supply it to populate.")
    tree.rows.append(benchrow("Month 2 Customer Value Growth", m2_actual, bm['growth']['month_2_ltv_growth_min'], max_target=False,
        tooltip=Tooltip(formula="Cohort Month-2 cumulative value / Month-0 − 1", confidence_note=_cohort_note)))
    tree.rows.append(benchrow("Month 5 Customer Value Growth", m5_actual, bm['growth']['month_5_ltv_growth_min'], max_target=False,
        tooltip=Tooltip(formula="Cohort Month-5 cumulative value / Month-0 − 1", confidence_note=_cohort_note)))

    # ===== Block 4: Ops Benchmarks =====
    tree.rows.append(make_row(
        [section_cell("frc.s3", "OPS BENCHMARKS (mentor-entered after build)")] + [text_cell(f"frc.s3.{c}", "") for c in "abcd"],
        is_section=True,
    ))

    # Inventory days
    inv_days = None
    inv_balance = None
    if not d.balance_sheet_snapshot.empty:
        inv_rows = d.balance_sheet_snapshot[d.balance_sheet_snapshot["account"].str.lower().str.contains("inventory|stock", na=False, regex=True)]
        if not inv_rows.empty:
            inv_balance = float(inv_rows["value"].sum())
    monthly_rev_avg = None
    if not d.monthly_revenue.empty:
        non_zero = d.monthly_revenue[d.monthly_revenue["revenue"] > 0]
        if not non_zero.empty:
            monthly_rev_avg = float(non_zero["revenue"].mean())
    # Only meaningful for a positive stock balance — a negative inventory asset is a
    # bookkeeping anomaly, not "negative days of cover".
    inv_negative = inv_balance is not None and inv_balance < 0
    if inv_balance and inv_balance > 0 and monthly_rev_avg:
        # Use overall COGS% from monthly revenue components
        cogs_ratio = 0.30
        if not d.monthly_revenue_components.empty and "cogs_aud" in d.monthly_revenue_components.columns and "net_aud" in d.monthly_revenue_components.columns:
            tc = float(d.monthly_revenue_components["cogs_aud"].sum())
            tr = float(d.monthly_revenue_components["net_aud"].sum())
            if tr > 0: cogs_ratio = tc / tr
        daily_cogs = (monthly_rev_avg * cogs_ratio) / 30
        if daily_cogs > 0:
            inv_days = inv_balance / daily_cogs

    tree.rows.append(make_row([
        text_cell("frc.o.invdays.lbl", "Blended Inventory Days on Hand", indent=1),
        (text_cell("frc.o.invdays.v", "—") if inv_negative else money_cell("frc.o.invdays.v", inv_days, decimals=0, tooltip=Tooltip(
            formula="Inventory balance / (avg monthly revenue × COGS% / 30)",
            inputs=[("Inventory", inv_balance), ("Avg monthly revenue", monthly_rev_avg)],
            sources=["Xero Balance Sheet", "Shopify daily"],
            confidence_note="Derived. A stock-take revision could shift this meaningfully.",
        ))),
        text_cell("frc.o.invdays.t", "30–60 days typical"),
        text_cell("frc.o.invdays.s", "—"),
        text_cell("frc.o.invdays.b", "—"),
        text_cell("frc.o.invdays.f",
                  f"Negative inventory balance ({inv_balance:,.0f}) — fix stock-take/COGS before reading days" if inv_negative else "Discuss with operations"),
    ]))

    tree.rows.append(make_row([
        text_cell("frc.o.leadtime.lbl", "Product lead times (PO → warehouse)", indent=1),
        text_cell("frc.o.leadtime.v", "—"),
        text_cell("frc.o.leadtime.t", "< 60 days"),
        text_cell("frc.o.leadtime.s", "—"),
        text_cell("frc.o.leadtime.b", "—"),
        text_cell("frc.o.leadtime.f", "Mentor-entered after build"),
    ]))
    tree.rows.append(make_row([
        text_cell("frc.o.adlaunch.lbl", "Monthly # of ads launched", indent=1),
        text_cell("frc.o.adlaunch.v", "—"),
        text_cell("frc.o.adlaunch.t", "> 20/mo"),
        text_cell("frc.o.adlaunch.s", "—"),
        text_cell("frc.o.adlaunch.b", "—"),
        text_cell("frc.o.adlaunch.f", "Mentor-entered after build"),
    ]))
    tree.rows.append(make_row([
        text_cell("frc.o.promos.lbl", "Marketing / Promo events per year", indent=1),
        text_cell("frc.o.promos.v", "—"),
        text_cell("frc.o.promos.t", "12 / year"),
        text_cell("frc.o.promos.s", "—"),
        text_cell("frc.o.promos.b", "—"),
        text_cell("frc.o.promos.f", "Mentor-entered after build"),
    ]))
    tree.rows.append(make_row([
        text_cell("frc.o.emails.lbl", "Emails sent per week", indent=1),
        text_cell("frc.o.emails.v", "—"),
        text_cell("frc.o.emails.t", "≥ 3 / week"),
        text_cell("frc.o.emails.s", "—"),
        text_cell("frc.o.emails.b", "—"),
        text_cell("frc.o.emails.f", "Mentor-entered after build"),
    ]))

    # Banners
    tree.banners.append(Banner(severity="info",
        text=("Revenue Breakdown and Financial Benchmarks use the full 12-month basis with the Shopify daily "
              "sales file as the source of truth for revenue: Net Sales (×FX, G39) is the revenue base; COGS = "
              "Xero Cost of Sales; Ad Spend = platform CSVs; OPEX = Xero operating expenses excluding Cost of "
              "Sales and Marketing (marketing is counted once, via ad spend). Growth Benchmarks below remain the "
              "snapshot-period New-vs-Returning view.")))
    if bundle.cohort is None:
        tree.banners.append(Banner(severity="info",
            text="LTV Month 2 / Month 5 growth rows show '—' — Shopify Cohort Analysis CSV not provided."))
    if avg_opex is None or opex_period is None:
        tree.banners.append(Banner(severity="warning",
            text="OPEX % derived from avg posted month × 3 — Xero coverage is partial. See Monthly P&L coverage banner."))

    tree.notes = [
        "Bleed = dollar amount above/below target (positive = costing you money).",
        "Fix = the percentage-point change required to hit target.",
        "Ops benchmarks below the line are placeholders — mentor edits after the call.",
    ]

    return tree
