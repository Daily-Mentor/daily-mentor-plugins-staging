"""LTV Analysis — two modes.

Mode A (cohort CSV present): the true cohort retention matrix. Rows = acquisition
cohort, columns = months since first purchase, cells = cumulative customer value,
plus a blended %-growth-vs-Month-0 row that feeds the Final Report Card M2/M5
benchmarks (≥30% / ≥50%).

Mode B (cohort CSV absent — common): a quarter-over-quarter repeat-economics proxy
derived from the NC/RC split + quarterly ad spend. These are directional estimates,
NOT a true cohort curve — flagged plainly. The genuine retention curve requires the
Shopify Cohort Analysis export.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell

_BENCHMARKS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "benchmarks.json"


def _quarter_sort_key(label: str) -> tuple[int, int]:
    try:
        q, y = label.split()
        return (int(y), int(q.lstrip("Qq")))
    except Exception:
        return (9999, 9)


def _quarter_window(label: str) -> tuple[date, date] | None:
    try:
        from datetime import timedelta
        q, y = label.split()
        qi = int(q.lstrip("Qq")); yr = int(y)
        sm = (qi - 1) * 3 + 1
        start = date(yr, sm, 1)
        end = (date(yr, 12, 31) if sm + 2 == 12
               else date(yr, sm + 3, 1) - timedelta(days=1))
        return start, end
    except Exception:
        return None


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    tree = RenderTree(tab_id="ltv", title="LTV Analysis", subtitle="Customer lifetime value")

    if bundle.cohort is not None and not bundle.cohort.empty:
        return _mode_a_cohort(bundle, tree)
    return _mode_b_proxy(bundle, tree)


# ---------------------------------------------------------------------------
# Mode A — true cohort matrix
# ---------------------------------------------------------------------------

def _mode_a_cohort(bundle, tree: RenderTree) -> RenderTree:
    meta = bundle.meta
    cohort = bundle.cohort
    src = Path(meta.files_found.get("cohort", "")).name or "Shopify Cohort Analysis"
    with _BENCHMARKS_PATH.open() as f:
        bm = json.load(f).get("growth", {})

    kind = str(cohort["kind"].iloc[0]) if "kind" in cohort.columns else "value"

    offsets = sorted(cohort["month_offset"].unique().tolist())
    max_off = min(max(offsets), 5) if offsets else 0
    shown = [o for o in offsets if o <= max_off]
    cohorts = sorted(cohort["cohort"].unique().tolist())

    tree.columns = ["Cohort"] + [f"Month {o}" for o in shown]

    if kind == "retention":
        # Retention cohort (repeat-purchase rate by months since first order). Convert it
        # to a cumulative customer-value curve: orders per acquired customer through Month N
        # = 1 (the acquisition order) + Σ repeat-rate over Months 1..N; value = orders × AOV.
        # The growth-vs-Month-0 ratio is AOV-independent (it's just the cumulative repeat rate).
        d = bundle.derived
        aov = 1.0
        mrc = d.monthly_revenue_components
        if mrc is not None and not mrc.empty and "net_aud" in mrc.columns and "orders" in mrc.columns:
            tot_orders = float(mrc["orders"].sum())
            if tot_orders > 0:
                aov = float(mrc["net_aud"].sum()) / tot_orders
        rpivot = cohort.pivot_table(index="cohort", columns="month_offset", values="value", aggfunc="mean")
        all_offsets = sorted(cohort["month_offset"].unique().tolist())
        data = {}
        for c in cohorts:
            cum_orders = 1.0
            prev = None
            for o in all_offsets:
                if o == 0:
                    val = 1.0  # acquisition order only
                else:
                    r = rpivot.loc[c, o] if (c in rpivot.index and o in rpivot.columns) else None
                    if r is not None and r == r:  # not NaN
                        cum_orders += float(r)
                        prev = cum_orders
                    val = prev if prev is not None else cum_orders
                data.setdefault(o, {})[c] = val * aov
        # pd.DataFrame({offset: {cohort: val}}) → index = cohort, columns = offset.
        pivot = pd.DataFrame(data)
        tree.subtitle = "Cumulative customer value by acquisition cohort — derived from repeat-retention × blended AOV."
    else:
        pivot = cohort.pivot_table(index="cohort", columns="month_offset", values="value", aggfunc="mean")
        tree.subtitle = "Cumulative customer value by acquisition cohort (Shopify Cohort Analysis)."

    for c in cohorts:
        cells = [text_cell(f"ltv.{c}.lbl", str(c), indent=1)]
        for o in shown:
            v = float(pivot.loc[c, o]) if (c in pivot.index and o in pivot.columns and pivot.loc[c, o] == pivot.loc[c, o]) else None
            m0 = float(pivot.loc[c, 0]) if (c in pivot.index and 0 in pivot.columns and pivot.loc[c, 0] == pivot.loc[c, 0]) else None
            growth = safe_div((v - m0) if (v is not None and m0 is not None) else None, m0) if m0 else None
            cells.append(money_cell(f"ltv.{c}.{o}", v, decimals=2, tooltip=Tooltip(
                formula=f"Cumulative customer value at Month {o} for the {c} cohort.",
                result_expr=(f"+{growth*100:.0f}% vs Month 0" if growth is not None and o > 0 else None),
                sources=[src],
            )))
        tree.rows.append(make_row(cells))

    # Blended %-growth-vs-Month-0 row (averaged across cohorts deep enough to have each offset)
    growth_cells = [text_cell("ltv.growth.lbl", "Blended % increase vs Month 0", bold=True)]
    blended_growth: dict[int, float | None] = {}
    for o in shown:
        if o == 0:
            blended_growth[o] = 0.0
            growth_cells.append(pct_cell("ltv.growth.0", 0.0, tooltip=Tooltip(formula="Baseline.")))
            continue
        ratios = []
        for c in cohorts:
            if c in pivot.index and 0 in pivot.columns and o in pivot.columns:
                m0 = pivot.loc[c, 0]; mo = pivot.loc[c, o]
                if m0 == m0 and mo == mo and m0:
                    ratios.append((mo - m0) / m0)
        g = (sum(ratios) / len(ratios)) if ratios else None
        blended_growth[o] = g
        growth_cells.append(pct_cell(f"ltv.growth.{o}", g, tooltip=Tooltip(
            formula=f"Mean (Month {o} − Month 0) / Month 0 across cohorts with ≥{o} months of history.",
            sources=[src])))
    tree.rows.append(make_row(growth_cells, is_total=True))

    # Benchmark check rows (M2 / M5)
    m2 = blended_growth.get(2)
    m5 = blended_growth.get(5)
    tree.rows.append(make_row([section_cell("ltv.bm", "BENCHMARKS")] + [text_cell(f"ltv.bm.{i}", "") for i in range(len(shown))], is_section=True))
    if 2 in shown:
        ok = (m2 is not None and m2 >= bm.get("month_2_ltv_growth_min", 0.3))
        row = [text_cell("ltv.m2.lbl", f"Month 2 growth (target ≥ {bm.get('month_2_ltv_growth_min', 0.3)*100:.0f}%)", indent=1)]
        row.append(pct_cell("ltv.m2.v", m2, tooltip=Tooltip(formula="Blended Month-2 cumulative value vs Month 0.", sources=[src])))
        row += [text_cell(f"ltv.m2.pad{i}", "✓" if ok else "✗" if m2 is not None else "—") if i == 0 else text_cell(f"ltv.m2.pad{i}", "") for i in range(len(shown) - 1)]
        tree.rows.append(make_row(row))
    if 5 in shown:
        ok = (m5 is not None and m5 >= bm.get("month_5_ltv_growth_min", 0.5))
        row = [text_cell("ltv.m5.lbl", f"Month 5 growth (target ≥ {bm.get('month_5_ltv_growth_min', 0.5)*100:.0f}%)", indent=1)]
        row.append(pct_cell("ltv.m5.v", m5, tooltip=Tooltip(formula="Blended Month-5 cumulative value vs Month 0.", sources=[src])))
        row += [text_cell(f"ltv.m5.pad{i}", "✓" if ok else "✗" if m5 is not None else "—") if i == 0 else text_cell(f"ltv.m5.pad{i}", "") for i in range(len(shown) - 1)]
        tree.rows.append(make_row(row))

    if kind == "retention":
        tree.banners.append(Banner(severity="info",
            text=(f"Derived from the retention cohort in {src}: each customer's cumulative value = "
                  f"(1 acquisition order + cumulative repeat-purchase rate) × blended AOV. The growth-vs-Month-0 "
                  f"row is the cumulative repeat rate (AOV-independent) and feeds the Final Report Card M2/M5 benchmarks.")))
        tree.notes = [
            "Source export reports repeat-purchase retention by months since first order, not dollar value — value is reconstructed using the blended AOV.",
            "Month-0 = the acquisition order (index 1.0 × AOV). Later months add the cohort's cumulative repeat rate.",
            "Growth vs Month 0 (and the M2/M5 benchmarks) depends only on retention, so it holds regardless of the AOV assumption.",
            "Recent cohorts have fewer months of history, so later-month cells are blank — the blended row only averages cohorts deep enough to have each offset.",
        ]
    else:
        tree.banners.append(Banner(severity="info",
            text=f"True cohort value from {src}. Each cell is cumulative customer value at that month since first purchase. The blended growth row feeds the Final Report Card M2/M5 benchmarks."))
        tree.notes = [
            "Cohort = the month a customer first purchased. Columns track that group's cumulative spend over their lifetime.",
            "Recent cohorts have fewer months of history, so later-month cells are blank — the blended row only averages cohorts deep enough to have each offset.",
        ]
    # Stash blended growth so the Final Report Card can read it (plain floats, not np types).
    bundle.derived.ltv_growth = {k: (float(v) if v is not None else None) for k, v in blended_growth.items()}
    return tree


# ---------------------------------------------------------------------------
# Mode B — quarter-over-quarter proxy from NC/RC + ad spend
# ---------------------------------------------------------------------------

def _mode_b_proxy(bundle, tree: RenderTree) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc
    with _BENCHMARKS_PATH.open() as f:
        bm = json.load(f).get("growth", {})
    nc_src = Path(meta.files_found.get("nc_rc", "")).name or "NC/RC export"

    tree.subtitle = "Repeat-economics proxy (NC/RC split) — true cohort curve needs the Shopify Cohort Analysis export."

    if nc_rc is None or nc_rc.empty or "quarter" not in nc_rc.columns:
        tree.banners.append(Banner(severity="error",
            text=("LTV unavailable — provide the Shopify Cohort Analysis export "
                  "(Analytics → Customers → Cohort Analysis → 'Customer value by month', last 6 months) "
                  "for true cohort LTV, or the quarterly NC v RC export for repeat-economics proxies.")))
        return tree

    quarters = sorted([q for q in nc_rc["quarter"].astype(str).unique() if q != "All"], key=_quarter_sort_key)
    if not quarters:
        quarters = ["All"]

    def seg(qlabel, segment):
        rows = nc_rc[(nc_rc["quarter"].astype(str) == qlabel) & (nc_rc["segment"].str.lower() == segment)]
        return rows.iloc[0] if not rows.empty else None

    def perf(row):
        if row is None:
            return None
        return float(row.get("gross", 0) or 0) + float(row.get("discounts", 0) or 0) + \
               float(row.get("shipping", 0) or 0) + float(row.get("taxes", 0) or 0)

    tree.columns = ["Metric"] + quarters + ["Notes"]
    ncol = len(quarters)

    def row(key, label, getter, fmt, note, *, bold=False, is_total=False):
        cells = [text_cell(f"ltv.{key}.lbl", label, bold=bold)]
        for i, q in enumerate(quarters):
            v = getter(q)
            tip = Tooltip(formula=label, sources=[nc_src])
            if fmt == "pct":
                cells.append(pct_cell(f"ltv.{key}.{i}", v, tooltip=tip))
            elif fmt == "money":
                cells.append(money_cell(f"ltv.{key}.{i}", v, decimals=2, tooltip=tip))
            else:
                cells.append(text_cell(f"ltv.{key}.{i}", f"{v:.2f}x" if isinstance(v, (int, float)) and v is not None else "—"))
        cells.append(text_cell(f"ltv.{key}.note", note))
        return make_row(cells, is_total=is_total)

    def repeat_rate(q):
        nc, rc = seg(q, "new"), seg(q, "returning")
        nco = float(nc.get("orders", 0)) if nc is not None else 0
        rco = float(rc.get("orders", 0)) if rc is not None else 0
        return safe_div(rco, nco + rco) if (nco + rco) else None

    def nc_aov(q):
        nc = seg(q, "new"); return safe_div(perf(nc), float(nc.get("orders", 0))) if nc is not None and nc.get("orders", 0) else None

    def rc_aov(q):
        rc = seg(q, "returning"); return safe_div(perf(rc), float(rc.get("orders", 0))) if rc is not None and rc.get("orders", 0) else None

    def rc_lift(q):
        n, r = nc_aov(q), rc_aov(q)
        return safe_div((r - n) if (n and r) else None, n) if n else None

    tree.rows.append(make_row([section_cell("ltv.s1", "REPEAT ECONOMICS (proxy)")] + [text_cell(f"ltv.s1.{i}", "") for i in range(ncol + 1)], is_section=True))
    tree.rows.append(row("repeat", "Repeat purchase rate", repeat_rate, "pct", "RC orders / (NC + RC orders) in the quarter."))
    tree.rows.append(row("ncaov", "NC AOV", nc_aov, "money", "New-customer AOV (incl. tax)."))
    tree.rows.append(row("rcaov", "RC AOV", rc_aov, "money", "Returning-customer AOV (incl. tax)."))
    tree.rows.append(row("lift", f"RC AOV lift vs NC (target ≥ {bm.get('rc_aov_lift_min', 0.2)*100:.0f}%)", rc_lift, "pct",
                         "(RC AOV − NC AOV) / NC AOV. Returning customers should spend more."))

    # Realised returning-margin per new customer acquired (12-month window)
    tot_nc_orders = sum(float(seg(q, "new").get("orders", 0)) for q in quarters if seg(q, "new") is not None)
    tot_rc_perf = sum(perf(seg(q, "returning")) or 0 for q in quarters)
    tot_rc_cogs = sum(float(seg(q, "returning").get("cogs", 0) or 0) for q in quarters if seg(q, "returning") is not None)
    rc_gp = tot_rc_perf - tot_rc_cogs
    realised = safe_div(rc_gp, tot_nc_orders) if tot_nc_orders else None

    tree.rows.append(make_row([section_cell("ltv.s2", "REALISED VALUE PROXY (12-month)")] + [text_cell(f"ltv.s2.{i}", "") for i in range(ncol + 1)], is_section=True))
    realised_cells = [text_cell("ltv.realised.lbl", "Returning margin per new customer", bold=True)]
    for i in range(ncol):
        if i == 0:
            realised_cells.append(money_cell("ltv.realised.v", realised, decimals=2, tooltip=Tooltip(
                formula="Σ returning gross profit over 12 months ÷ Σ new-customer orders over 12 months.",
                inputs=[("RC gross profit", rc_gp), ("NC orders", tot_nc_orders)],
                result_expr=f"{rc_gp:,.0f} / {tot_nc_orders:,.0f} = {realised:,.2f}" if realised else "—",
                sources=[nc_src],
                confidence_note="Directional proxy — conflates acquisition cohorts. Not a true cohort curve.")))
        else:
            realised_cells.append(text_cell(f"ltv.realised.pad{i}", ""))
    realised_cells.append(text_cell("ltv.realised.note", "12-month realised, all quarters combined."))
    tree.rows.append(make_row(realised_cells, is_total=True))

    tree.banners.append(Banner(severity="warning",
        text="No Shopify Cohort Analysis export supplied — this tab shows directional repeat-economics proxies from the NC/RC split, not a true cohort retention curve. Add the cohort CSV to unlock the real Month 0→5 matrix and the Final Report Card M2/M5 benchmarks."))
    tree.banners.append(Banner(severity="info",
        text="To upgrade: Shopify → Analytics → Customers → Cohort Analysis → 'Customer value by month' (last 6 months) → export CSV into the inputs folder, re-run."))
    tree.notes = [
        "These proxies use the New vs Returning split, which shows the period mix — not which acquisition cohort a returning order belongs to. They trend correctly but are not cohort-exact.",
        "'Returning margin per new customer' approximates how much repeat value each acquired customer generates within the 12-month window.",
    ]
    return tree
