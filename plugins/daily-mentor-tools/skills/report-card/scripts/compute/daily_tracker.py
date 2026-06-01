"""Daily Tracker — one row per day, with per-month sub-views.

HTML: single tab with month filter pills.
xlsx: 13 separate sheets (handled by renderer).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from ..models import Banner, Cell, RenderTree, Row, Tooltip
from .helpers import int_cell, make_row, money_cell, month_label, pct_cell, safe_div, section_cell, text_cell


_DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "defaults.json"


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    with _DEFAULTS_PATH.open() as f:
        defaults = json.load(f)
    after_fees_factor = defaults["daily_tracker"]["after_fees_factor"]

    tree = RenderTree(tab_id="daily_tracker", title="Daily Tracker",
                      subtitle="Day-by-day Orders, Sales, Ad Spend, Profit. Switch month using the pills.")

    if bundle.shopify_daily is None or bundle.shopify_daily.empty:
        tree.banners.append(Banner(severity="error", text="Shopify daily file missing — Daily Tracker cannot render."))
        return tree

    # The Shopify 'Total Sales Over Time' export usually carries no per-day COGS column.
    # When it's absent we can't deduct product cost daily, so the COGS column shows '—'
    # and the bottom line is a Pre-COGS Contribution (After Fees − Ad − Refunds − Op Cost).
    has_daily_cogs = ("cogs_aud" in bundle.shopify_daily.columns
                      and float(bundle.shopify_daily["cogs_aud"].abs().sum()) > 0)
    profit_label = "Profit" if has_daily_cogs else "Pre-COGS Contribution"
    tree.columns = ["Date", "Orders", "Units", "Gross Sales", "After Fees", "Ad Spend",
                    ("COGS" if has_daily_cogs else "COGS (n/a)"), "Refunds", "Op Cost",
                    "AOV", "CPA", "ROAS", profit_label, profit_label + " %"]
    if not has_daily_cogs:
        tree.banners.append(Banner(severity="warning",
            text=("Daily product COGS isn't in the Shopify 'Total Sales Over Time' export, so the COGS column "
                  "shows '—' and the bottom line is a Pre-COGS Contribution (After Fees − Ad − Refunds − Op Cost). "
                  "Full-period COGS is on the Monthly P&L (from Xero).")))

    # Op cost per day: avg posted OPEX × (days posted total) — but simpler: avg per-month / days-in-month.
    daily_op_cost = None
    if not d.monthly_expenses.empty and d.posted_months:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        per_month_opex = non_cogs.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
        # Estimate avg daily opex via the months posted
        posted_opex_total = float(per_month_opex[per_month_opex > 0].sum())
        posted_days = sum((date(m.year + (m.month // 12), (m.month % 12) + 1, 1) - m).days for m in d.posted_months)
        if posted_days > 0:
            daily_op_cost = posted_opex_total / posted_days

    # Daily ad spend lookup
    ad_by_day = {}
    if not d.daily_ad_spend.empty:
        ad_by_day = d.daily_ad_spend.groupby("day", as_index=True)["amount"].sum().to_dict()

    sd = bundle.shopify_daily.copy()
    sd["month"] = sd["day"].apply(lambda x: date(x.year, x.month, 1))

    shopify_src = Path(meta.files_found.get("shopify_daily", "")).name
    ad_src = Path(meta.files_found.get("ad_spend_meta", "")).name

    for month_key, group in sd.groupby("month"):
        month_rows: list[Row] = []
        # MONTH TOTAL row first
        tot_orders = float(group["orders"].sum()) if "orders" in group.columns else 0
        tot_units = float(group["units"].sum()) if "units" in group.columns else 0
        tot_gross = float(group["gross_aud"].sum())
        tot_after = tot_gross * after_fees_factor
        tot_ad = float(sum(ad_by_day.get(day, 0) for day in group["day"]))
        tot_cogs = float(group["cogs_aud"].sum()) if "cogs_aud" in group.columns else 0
        tot_refunds = float(group["returns_aud"].sum()) if "returns_aud" in group.columns else 0
        tot_op = (daily_op_cost or 0) * len(group)
        tot_profit = tot_after - tot_cogs - tot_ad - abs(tot_refunds) - tot_op
        tot_aov = safe_div(tot_gross, tot_orders)
        tot_cpa = safe_div(tot_ad, tot_orders)
        tot_roas = safe_div(tot_gross, tot_ad)
        tot_profit_pct = safe_div(tot_profit, tot_gross)

        total_cells = [
            text_cell(f"dt.{month_key}.tot.date", f"{month_label(month_key)} TOTAL", bold=True),
            int_cell(f"dt.{month_key}.tot.orders", tot_orders, tooltip=Tooltip(formula="Sum of daily orders", sources=[shopify_src])),
            int_cell(f"dt.{month_key}.tot.units", tot_units, tooltip=Tooltip(formula="Sum of daily units", sources=[shopify_src])),
            money_cell(f"dt.{month_key}.tot.gross", tot_gross, tooltip=Tooltip(formula="Sum of daily gross ×FX", sources=[shopify_src], gotcha_refs=["G39"])),
            money_cell(f"dt.{month_key}.tot.after", tot_after, tooltip=Tooltip(formula=f"Gross × {after_fees_factor}", confidence_note="After-fees factor is a mentor default; tune per client.")),
            money_cell(f"dt.{month_key}.tot.ad", tot_ad, tooltip=Tooltip(formula="Sum of platform daily ad spend ×FX", sources=[ad_src], gotcha_refs=["G39"])),
            (money_cell(f"dt.{month_key}.tot.cogs", tot_cogs, tooltip=Tooltip(formula="Sum of Shopify daily COGS ×FX", sources=[shopify_src], confidence_note="Shopify product-COGS only."))
             if has_daily_cogs else text_cell(f"dt.{month_key}.tot.cogs", "—")),
            money_cell(f"dt.{month_key}.tot.refunds", abs(tot_refunds), tooltip=Tooltip(formula="abs sum of Returns ×FX", sources=[shopify_src])),
            money_cell(f"dt.{month_key}.tot.op", tot_op, tooltip=Tooltip(formula="Avg daily OPEX × days in month", inputs=[("Avg daily", daily_op_cost), ("Days", len(group))], confidence_note="Derived from posted-OPEX average.")),
            money_cell(f"dt.{month_key}.tot.aov", tot_aov, decimals=2, tooltip=Tooltip(formula="Gross / Orders")),
            money_cell(f"dt.{month_key}.tot.cpa", tot_cpa, decimals=2, tooltip=Tooltip(formula="Ad Spend / Orders")),
            money_cell(f"dt.{month_key}.tot.roas", tot_roas, decimals=2, tooltip=Tooltip(formula="Gross / Ad Spend")),
            money_cell(f"dt.{month_key}.tot.profit", tot_profit, tooltip=Tooltip(formula="After Fees − COGS − Ad − abs(Refunds) − Op Cost"), is_total=True),
            pct_cell(f"dt.{month_key}.tot.profitp", tot_profit_pct, tooltip=Tooltip(formula="Profit / Gross")),
        ]
        month_rows.append(make_row(total_cells, is_total=True))

        for _, day_row in group.iterrows():
            day = day_row["day"]
            gross = float(day_row["gross_aud"]) if "gross_aud" in day_row else 0
            orders = int(day_row["orders"]) if "orders" in day_row else 0
            units = int(day_row["units"]) if "units" in day_row else 0
            after = gross * after_fees_factor
            ad = float(ad_by_day.get(day, 0))
            cogs = float(day_row["cogs_aud"]) if "cogs_aud" in day_row else 0
            refunds = float(day_row["returns_aud"]) if "returns_aud" in day_row else 0
            op = daily_op_cost or 0
            profit = after - cogs - ad - abs(refunds) - op
            aov = safe_div(gross, orders)
            cpa = safe_div(ad, orders)
            roas = safe_div(gross, ad)
            profit_pct = safe_div(profit, gross)

            cells = [
                text_cell(f"dt.{day}.date", str(day)),
                int_cell(f"dt.{day}.orders", orders),
                int_cell(f"dt.{day}.units", units),
                money_cell(f"dt.{day}.gross", gross, decimals=2, tooltip=Tooltip(
                    formula=f"Shopify daily gross ×FX for {day}", sources=[shopify_src], gotcha_refs=["G39"])),
                money_cell(f"dt.{day}.after", after, decimals=2, tooltip=Tooltip(
                    formula=f"Gross × {after_fees_factor}")),
                money_cell(f"dt.{day}.ad", ad, decimals=2, tooltip=Tooltip(
                    formula="Sum of platform spend for this day ×FX", sources=[ad_src], gotcha_refs=["G39"])),
                (money_cell(f"dt.{day}.cogs", cogs, decimals=2, tooltip=Tooltip(
                    formula="Shopify product COGS for this day ×FX", sources=[shopify_src]))
                 if has_daily_cogs else text_cell(f"dt.{day}.cogs", "—")),
                money_cell(f"dt.{day}.refunds", abs(refunds), decimals=2, tooltip=Tooltip(
                    formula="abs(Returns) for this day ×FX", sources=[shopify_src])),
                money_cell(f"dt.{day}.op", op, decimals=2, tooltip=Tooltip(
                    formula="Posted-OPEX total / posted days (flat allocation)",
                    inputs=[("Per day", daily_op_cost)],
                    confidence_note="Provisional — daily allocation of average monthly OPEX.")),
                money_cell(f"dt.{day}.aov", aov, decimals=2, tooltip=Tooltip(formula="Gross / Orders")),
                money_cell(f"dt.{day}.cpa", cpa, decimals=2, tooltip=Tooltip(formula="Ad / Orders")),
                money_cell(f"dt.{day}.roas", roas, decimals=2, tooltip=Tooltip(formula="Gross / Ad")),
                money_cell(f"dt.{day}.profit", profit, decimals=2, tooltip=Tooltip(
                    formula="After Fees − COGS − Ad − abs(Refunds) − Op Cost",
                    result_expr=f"{after:.2f} − {cogs:.2f} − {ad:.2f} − {abs(refunds):.2f} − {op:.2f} = {profit:.2f}",
                )),
                pct_cell(f"dt.{day}.profitp", profit_pct, tooltip=Tooltip(formula="Profit / Gross")),
            ]
            month_rows.append(make_row(cells))

        tree.sub_views[month_label(month_key)] = month_rows

    # Default rows = the latest month
    if tree.sub_views:
        last = list(tree.sub_views.keys())[-1]
        tree.rows = tree.sub_views[last]
    return tree
