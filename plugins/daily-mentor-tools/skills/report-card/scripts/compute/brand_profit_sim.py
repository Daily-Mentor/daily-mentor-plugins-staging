"""Brand Profit Simulator — aMER scenario projection."""
from __future__ import annotations

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc

    tree = RenderTree(tab_id="brand_profit_sim", title="Brand Profit Simulator",
                      subtitle="What-if projection across aMER scenarios — full 12-month new-customer acquisition economics.")

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC missing — simulator cannot run."))
        return tree

    # Aggregate New-customer rows across ALL quarters (full 12 months) — never a single
    # quarter. aMER is an acquisition metric, so it is driven by new-customer revenue.
    nc_rows = nc_rc[nc_rc["segment"].str.lower() == "new"]
    if nc_rows.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC has no New-customer rows — simulator cannot run."))
        return tree

    def _s(col):
        return float(nc_rows[col].sum()) if col in nc_rows.columns else 0.0

    nc_orders = int(_s("orders"))
    nc_perf = _s("gross") + _s("discounts") + _s("shipping") + _s("taxes")
    nc_aov = safe_div(nc_perf, nc_orders)
    nc_cogs = _s("cogs")
    nc_cogs_per_order = safe_div(nc_cogs, nc_orders)

    # Full 12-month ad spend (platform CSVs).
    ad_spend = float(d.daily_ad_spend["amount"].sum()) if not d.daily_ad_spend.empty else 0.0
    actual_amer = safe_div(nc_perf, ad_spend)

    # Full 12-month OPEX, excluding Cost of Sales and Marketing — marketing is already
    # counted once via ad spend, so it must not be doubled from Xero's marketing accounts.
    opex_period = None
    me = d.monthly_expenses
    if me is not None and not me.empty and "bucket_section" in me.columns:
        oi = me["is_other_income"].fillna(False) if "is_other_income" in me.columns else False
        opex_rows = me[(~me["bucket_section"].isin(["Cost of Sales", "Marketing"])) & (~oi)]
        opex_period = float(opex_rows["value"].abs().sum())

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

    tree.rows.append(row("aMER", [f"{s[1]:.2f}x" if s[1] is not None else None for s in scenarios], fmt="text",
                         tooltip=Tooltip(formula="NC Revenue / Ad Spend (acquisition MER).")))
    tree.rows.append(row("Ad Spend (12-month)", [s[2] for s in scenarios], fmt="money",
                         tooltip=Tooltip(formula="Actual = 12-month platform spend; scenarios = NC Revenue / target aMER.")))
    tree.rows.append(row("NC Revenue (12-month)", [s[3] for s in scenarios], fmt="money",
                         tooltip=Tooltip(formula="Constant — fixed at 12-month new-customer revenue (incl. tax).", sources=["NC/RC"])))

    # COGS rows
    cogs_row = [nc_cogs for _ in scenarios]
    tree.rows.append(row("NC COGS (12-month)", cogs_row, fmt="money",
                         tooltip=Tooltip(formula="New-customer product COGS over 12 months, held constant.", gotcha_refs=["G39"])))

    # Profit
    profits = []
    for label, amer, ad, rev in scenarios:
        if rev is None or ad is None or opex_period is None:
            profits.append(None)
            continue
        profits.append(rev - nc_cogs - ad - opex_period)
    tree.rows.append(row("Period Profit (12-month)", profits, fmt="money",
                         tooltip=Tooltip(formula="NC Revenue − NC COGS − Ad Spend − OPEX",
                                         inputs=[("OPEX (12-mo, excl. mktg)", opex_period)],
                                         confidence_note="Full 12-month OPEX, excluding Cost of Sales and Marketing (ad spend counted separately). New-customer view — excludes returning-customer revenue.")))

    cmps = [safe_div(p, s[3]) if (p is not None and s[3]) else None for p, s in zip(profits, scenarios)]
    tree.rows.append(row("Profit %", cmps, fmt="pct",
                         tooltip=Tooltip(formula="Profit / Revenue")))

    tree.banners.append(Banner(severity="info",
        text=("New-customer acquisition view over the full 12 months: NC Revenue and NC COGS are held "
              "constant while ad spend flexes to each target aMER. Profit applies full-company OPEX "
              "(excl. marketing) against new-customer revenue, so it is a deliberately conservative floor — "
              "returning-customer revenue would add on top.")))
    return tree
