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

    # COGS and OPEX come from Account Transactions (the atxn-derived P&L), per month:
    #   • COGS = Xero 'Cost of Sales' lines, allocated to each day in proportion to that
    #            day's share of the month's gross sales (cost follows revenue).
    #   • OPEX = Xero operating expenses EXCLUDING Cost of Sales and Marketing (ad spend is
    #            counted separately from the platform CSVs), spread evenly across the month's days.
    me = d.monthly_expenses if d.monthly_expenses is not None else None
    month_cogs: dict[date, float] = {}
    month_opex: dict[date, float] = {}
    if me is not None and not me.empty and "bucket_section" in me.columns:
        oi = me["is_other_income"].fillna(False) if "is_other_income" in me.columns else False
        cos = me[me["bucket_section"] == "Cost of Sales"]
        month_cogs = cos.groupby("month")["value"].apply(lambda s: float(s.abs().sum())).to_dict()
        opex_rows = me[(~me["bucket_section"].isin(["Cost of Sales", "Marketing"])) & (~oi)]
        month_opex = opex_rows.groupby("month")["value"].apply(lambda s: float(s.abs().sum())).to_dict()
    has_cogs = bool(month_cogs)
    atxn_src = Path(meta.files_found.get("xero_atxn", "")).name or "Xero Account Transactions"

    profit_label = "Profit" if has_cogs else "Pre-COGS Contribution"
    tree.columns = ["Date", "Orders", "Units", "Gross Sales", "After Fees", "Ad Spend",
                    ("COGS" if has_cogs else "COGS (n/a)"), "Refunds", "Op Cost",
                    "AOV", "CPA", "ROAS", profit_label, profit_label + " %"]
    if has_cogs:
        tree.banners.append(Banner(severity="info",
            text=("Daily P&L: COGS and OPEX both come from Account Transactions (Xero). COGS = each month's "
                  "Cost of Sales allocated by the day's share of gross sales; OPEX = each month's operating "
                  "expenses (excl. Cost of Sales and Marketing — ad spend is counted separately) spread evenly "
                  "across the month's days. Monthly totals tie back to the Monthly P&L.")))
    else:
        tree.banners.append(Banner(severity="warning",
            text=("No Cost-of-Sales lines in Account Transactions, so daily COGS can't be built — the bottom line "
                  "is a Pre-COGS Contribution (After Fees − Ad − Refunds − Op Cost).")))

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
        tot_cogs = month_cogs.get(month_key, 0.0)
        tot_refunds = float(group["returns_aud"].sum()) if "returns_aud" in group.columns else 0
        tot_op = month_opex.get(month_key, 0.0)
        n_days = len(group)
        daily_opex = (tot_op / n_days) if n_days else 0.0
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
            (money_cell(f"dt.{month_key}.tot.cogs", tot_cogs, tooltip=Tooltip(formula="Month's Cost of Sales from Account Transactions (Xero)", sources=[atxn_src], confidence_note="Xero Cost of Sales (product COGS + freight/packaging/fees)."))
             if has_cogs else text_cell(f"dt.{month_key}.tot.cogs", "—")),
            money_cell(f"dt.{month_key}.tot.refunds", abs(tot_refunds), tooltip=Tooltip(formula="abs sum of Returns ×FX", sources=[shopify_src])),
            money_cell(f"dt.{month_key}.tot.op", tot_op, tooltip=Tooltip(formula="Month's operating expenses (excl. Cost of Sales & Marketing) from Account Transactions", sources=[atxn_src], confidence_note="Marketing excluded — ad spend is counted separately.")),
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
            # COGS follows revenue: the day's share of the month's gross sales × month COGS.
            cogs = (tot_cogs * (gross / tot_gross)) if (has_cogs and tot_gross > 0) else 0.0
            refunds = float(day_row["returns_aud"]) if "returns_aud" in day_row else 0
            op = daily_opex
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
                    formula="Month's Cost of Sales (Account Transactions) × this day's share of monthly gross sales",
                    sources=[atxn_src], confidence_note="Allocated by sales share; monthly total ties to the Monthly P&L."))
                 if has_cogs else text_cell(f"dt.{day}.cogs", "—")),
                money_cell(f"dt.{day}.refunds", abs(refunds), decimals=2, tooltip=Tooltip(
                    formula="abs(Returns) for this day ×FX", sources=[shopify_src])),
                money_cell(f"dt.{day}.op", op, decimals=2, tooltip=Tooltip(
                    formula="Month's OPEX (Account Transactions, excl. Cost of Sales & Marketing) ÷ days in month",
                    sources=[atxn_src],
                    confidence_note="Even daily allocation of the month's operating expenses.")),
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
