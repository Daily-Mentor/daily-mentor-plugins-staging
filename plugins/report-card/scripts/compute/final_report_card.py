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
                      subtitle="Bleed / Fix diagnostic vs Daily Mentor targets. Based on the snapshot period.")

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC missing — cannot derive Final Report Card."))
        return tree

    nc = nc_rc[nc_rc["segment"].str.lower() == "new"].iloc[0]
    rc = nc_rc[nc_rc["segment"].str.lower() == "returning"].iloc[0]

    nc_gross = float(nc["gross"]); rc_gross = float(rc["gross"])
    nc_disc = float(nc["discounts"]); rc_disc = float(rc["discounts"])
    nc_ret = float(nc["returns"]); rc_ret = float(rc["returns"])
    nc_ship = float(nc["shipping"]); rc_ship = float(rc["shipping"])
    nc_tax = float(nc["taxes"]); rc_tax = float(rc["taxes"])
    nc_orders = int(nc["orders"]); rc_orders = int(rc["orders"])
    nc_cogs = float(nc["cogs"]); rc_cogs = float(rc["cogs"])

    gross_rev = nc_gross + rc_gross
    disc = nc_disc + rc_disc
    ret = nc_ret + rc_ret
    ship = nc_ship + rc_ship
    tax = nc_tax + rc_tax
    total_rev = gross_rev + disc + ret + ship + tax  # "Performance Sales" sum
    total_cogs = nc_cogs + rc_cogs
    total_orders = nc_orders + rc_orders

    ad_spend = 0.0
    if not d.daily_ad_spend.empty and d.snapshot_window:
        mask = (d.daily_ad_spend["day"] >= d.snapshot_window[0]) & (d.daily_ad_spend["day"] <= d.snapshot_window[1])
        ad_spend = float(d.daily_ad_spend.loc[mask, "amount"].sum())

    avg_opex = None
    if not d.monthly_expenses.empty and d.posted_months:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        per_month = non_cogs.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
        non_zero = per_month[per_month > 0]
        avg_opex = float(non_zero.mean()) if not non_zero.empty else None
    opex_period = (avg_opex * 3) if avg_opex else None

    profit = total_rev - total_cogs - ad_spend - (opex_period or 0)
    profit_pct = safe_div(profit, total_rev)
    cogs_pct = safe_div(total_cogs, total_rev)
    marketing_pct = safe_div(ad_spend, total_rev)
    opex_pct = safe_div(opex_period, total_rev)
    cm = safe_div(total_rev - total_cogs - ad_spend, total_rev)
    returns_pct = safe_div(abs(ret), total_rev)
    blended_aov = safe_div(total_rev, total_orders)
    nc_share = safe_div(nc_orders, total_orders)
    nc_aov = safe_div(nc_gross + nc_disc + nc_ship + nc_tax, nc_orders)
    rc_aov = safe_div(rc_gross + rc_disc + rc_ship + rc_tax, rc_orders) if rc_orders else None
    rc_lift = safe_div((rc_aov - nc_aov) if (rc_aov and nc_aov) else None, nc_aov) if nc_aov else None

    cr = None
    if bundle.sessions is not None and not bundle.sessions.empty:
        sessions_total = float(bundle.sessions.tail(3)["sessions"].sum())
        cr = safe_div(total_orders, sessions_total)

    src_nc_rc = Path(meta.files_found.get("nc_rc", "")).name
    src_ads = Path(meta.files_found.get("ad_spend_meta", "")).name
    src_xero = Path(meta.files_found.get("xero_pl", "")).name

    # ===== Block 1: Revenue Breakdown =====
    tree.columns = ["Metric", "Actual", "Target", "Status", "Bleed", "Fix"]
    tree.rows.append(make_row(
        [section_cell("frc.s0", "REVENUE BREAKDOWN (snapshot period)")] + [text_cell(f"frc.s0.{c}", "") for c in "abcd"],
        is_section=True,
    ))

    def revrow(name, value, source, gotcha=None):
        return make_row([
            text_cell(f"frc.r.{name}.lbl", name, indent=1),
            money_cell(f"frc.r.{name}.v", value, tooltip=Tooltip(
                formula=f"NC + RC {name} for the snapshot window.",
                inputs=[("NC", value if name == "Total Revenue" else None)],
                sources=[source], gotcha_refs=gotcha or [],
            )),
            text_cell(f"frc.r.{name}.t", ""),
            text_cell(f"frc.r.{name}.s", ""),
            text_cell(f"frc.r.{name}.b", ""),
            text_cell(f"frc.r.{name}.f", ""),
        ])
    tree.rows.append(revrow("Gross Revenue", gross_rev, src_nc_rc))
    tree.rows.append(revrow("Discounts", disc, src_nc_rc))
    tree.rows.append(revrow("Refunds", ret, src_nc_rc))
    tree.rows.append(revrow("Shipping Charges", ship, src_nc_rc))
    tree.rows.append(revrow("Tax", tax, src_nc_rc))
    tree.rows.append(make_row([
        text_cell("frc.r.tot.lbl", "Total Revenue (Performance Sales)", bold=True),
        money_cell("frc.r.tot.v", total_rev, tooltip=Tooltip(
            formula="Gross + Discounts + Refunds + Shipping + Tax",
            inputs=[("Gross", gross_rev), ("Disc", disc), ("Ref", ret), ("Ship", ship), ("Tax", tax)],
            result_expr=f"= {total_rev:,.0f}",
            sources=[src_nc_rc],
        ), is_total=True),
        text_cell("frc.r.tot.t", ""),
        text_cell("frc.r.tot.s", ""),
        text_cell("frc.r.tot.b", ""),
        text_cell("frc.r.tot.f", ""),
    ], is_total=True))

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
        target_label = target_str or (
            f"< {target_pct*100:.0f}%" if max_target else f"> {target_pct*100:.0f}%"
        )
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

    # ===== Block 2: Financial Benchmarks =====
    tree.rows.append(make_row(
        [section_cell("frc.s1", "FINANCIAL BENCHMARKS")] + [text_cell(f"frc.s1.{c}", "") for c in "abcd"],
        is_section=True,
    ))
    tree.rows.append(benchrow("Profit %", profit_pct, bm['financial']['profit_pct_min'], max_target=False,
        tooltip=Tooltip(formula="Profit / Total Revenue", inputs=[("Profit", profit), ("Revenue", total_rev)], sources=[src_nc_rc, src_ads, src_xero])))
    tree.rows.append(benchrow("COGS %", cogs_pct, bm['financial']['cogs_pct_max'], max_target=True,
        tooltip=Tooltip(formula="COGS / Total Revenue", inputs=[("COGS", total_cogs)], sources=[src_nc_rc], gotcha_refs=["G39"])))
    tree.rows.append(benchrow("Marketing %", marketing_pct, bm['financial']['marketing_pct_max'], max_target=True,
        tooltip=Tooltip(formula="Ad Spend / Total Revenue", inputs=[("Ad", ad_spend)], sources=[src_ads], gotcha_refs=["G39"])))
    tree.rows.append(benchrow("OPEX %", opex_pct, bm['financial']['opex_pct_max'], max_target=True,
        tooltip=Tooltip(formula="(Avg posted OPEX × 3) / Total Revenue", inputs=[("Avg OPEX", avg_opex), ("OPEX period", opex_period)], sources=[src_xero])))

    # ===== Block 3: Growth Benchmarks =====
    tree.rows.append(make_row(
        [section_cell("frc.s2", "GROWTH BENCHMARKS")] + [text_cell(f"frc.s2.{c}", "") for c in "abcd"],
        is_section=True,
    ))
    tree.rows.append(benchrow("MER (Ad / Rev)", marketing_pct, bm['growth']['mer_max'], max_target=True,
        tooltip=Tooltip(formula="Ad Spend / Total Revenue (same as Marketing % — both forms shown for clarity)",
                        sources=[src_ads, src_nc_rc])))
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
    if inv_balance and monthly_rev_avg:
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
        money_cell("frc.o.invdays.v", inv_days, decimals=0, tooltip=Tooltip(
            formula="Inventory balance / (avg monthly revenue × COGS% / 30)",
            inputs=[("Inventory", inv_balance), ("Avg monthly revenue", monthly_rev_avg)],
            sources=["Xero Balance Sheet", "Shopify daily"],
            confidence_note="Derived. A stock-take revision could shift this meaningfully.",
        )),
        text_cell("frc.o.invdays.t", "30–60 days typical"),
        text_cell("frc.o.invdays.s", "—"),
        text_cell("frc.o.invdays.b", "—"),
        text_cell("frc.o.invdays.f", "Discuss with operations"),
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
