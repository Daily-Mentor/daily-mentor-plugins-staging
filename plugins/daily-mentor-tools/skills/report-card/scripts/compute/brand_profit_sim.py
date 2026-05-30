"""Brand Profit Simulator — aMER scenario projection."""
from __future__ import annotations

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc

    tree = RenderTree(tab_id="brand_profit_sim", title="Brand Profit Simulator",
                      subtitle="What-if projection across aMER scenarios — based on the snapshot period.")

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC missing — simulator cannot run."))
        return tree

    nc = nc_rc[nc_rc["segment"].str.lower() == "new"].iloc[0]
    rc = nc_rc[nc_rc["segment"].str.lower() == "returning"].iloc[0]
    nc_orders = int(nc["orders"])
    nc_perf = float(nc["gross"]) + float(nc["discounts"]) + float(nc["shipping"]) + float(nc["taxes"])
    nc_aov = safe_div(nc_perf, nc_orders)
    nc_cogs = float(nc["cogs"])
    nc_cogs_per_order = safe_div(nc_cogs, nc_orders)

    ad_spend = 0.0
    if not d.daily_ad_spend.empty and d.snapshot_window:
        mask = (d.daily_ad_spend["day"] >= d.snapshot_window[0]) & (d.daily_ad_spend["day"] <= d.snapshot_window[1])
        ad_spend = float(d.daily_ad_spend.loc[mask, "amount"].sum())
    actual_amer = safe_div(nc_perf, ad_spend)

    # OPEX/period
    avg_opex = None
    if not d.monthly_expenses.empty and d.posted_months:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        per_month = non_cogs.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
        avg_opex = float(per_month[per_month > 0].mean()) if any(per_month > 0) else None
    opex_period = (avg_opex * 3) if avg_opex else None

    scenarios = [
        ("Actual", actual_amer, ad_spend, nc_perf),
        ("Target aMER 5.0", 5.0, nc_perf / 5.0 if nc_perf else None, nc_perf),
        ("Conservative aMER 3.0", 3.0, nc_perf / 3.0 if nc_perf else None, nc_perf),
        ("Bear aMER 2.0", 2.0, nc_perf / 2.0 if nc_perf else None, nc_perf),
    ]

    tree.columns = ["Metric"] + [s[0] for s in scenarios]

    def row(label, values, fmt="money", tooltip=None):
        cells = [text_cell(f"sim.{label}.lbl", label, indent=1)]
        for i, v in enumerate(values):
            coord = f"sim.{label}.{i}"
            if fmt == "money":
                cells.append(money_cell(coord, v, tooltip=tooltip))
            elif fmt == "pct":
                cells.append(pct_cell(coord, v, tooltip=tooltip))
            else:
                cells.append(text_cell(coord, str(v) if v is not None else "—"))
        return make_row(cells)

    tree.rows.append(row("aMER", [s[1] for s in scenarios], fmt="money", tooltip=Tooltip(formula="Revenue / Ad Spend")))
    tree.rows.append(row("Ad Spend (NC, period)", [s[2] for s in scenarios], fmt="money",
                         tooltip=Tooltip(formula="NC Revenue / aMER")))
    tree.rows.append(row("NC Revenue", [s[3] for s in scenarios], fmt="money",
                         tooltip=Tooltip(formula="Constant — fixed at actual NC revenue.", sources=["NC/RC"])))

    # COGS rows
    cogs_row = [nc_cogs for _ in scenarios]
    tree.rows.append(row("NC COGS (Shopify product)", cogs_row, fmt="money",
                         tooltip=Tooltip(formula="NC COGS, held constant.", gotcha_refs=["G39"])))

    # Profit
    profits = []
    for label, amer, ad, rev in scenarios:
        if rev is None or ad is None or opex_period is None:
            profits.append(None)
            continue
        profits.append(rev - nc_cogs - ad - opex_period)
    tree.rows.append(row("Period Profit", profits, fmt="money",
                         tooltip=Tooltip(formula="Revenue − COGS − Ad − OPEX(period)",
                                         inputs=[("OPEX", opex_period)],
                                         confidence_note="OPEX derived from avg posted month × 3.")))

    cmps = [safe_div(p, s[3]) if (p is not None and s[3]) else None for p, s in zip(profits, scenarios)]
    tree.rows.append(row("Profit %", cmps, fmt="pct",
                         tooltip=Tooltip(formula="Profit / Revenue")))

    if d.snapshot_window:
        period_days = (d.snapshot_window[1] - d.snapshot_window[0]).days + 1
        if period_days < 85:
            tree.banners.append(Banner(severity="warning",
                text=f"Projections built from a {period_days}-day NC/RC window — sample-thin."))
    return tree
