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
    d = bundle.derived
    cohort = bundle.cohort
    src = Path(meta.files_found.get("cohort", "")).name or "Shopify Cohort Analysis"
    nc_src = Path(meta.files_found.get("nc_rc", "")).name or "NC/RC export"
    ad_src = Path(meta.files_found.get("ad_spend_meta", "")).name or "ad-platform CSVs"

    kind = str(cohort["kind"].iloc[0]) if "kind" in cohort.columns else "value"

    # ---- Economic inputs (full 12-month) ----
    nc_rc = bundle.nc_rc

    def _seg_perf_aov(seg: str):
        if nc_rc is None or nc_rc.empty:
            return 0.0, 0
        r = nc_rc[nc_rc["segment"].str.lower() == seg]
        if r.empty:
            return 0.0, 0
        orders = float(r["orders"].sum())
        perf = float((r["gross"] + r["discounts"] + r["shipping"] + r["taxes"]).sum())
        return (perf / orders if orders else 0.0), int(orders)

    nc_aov, nc_orders = _seg_perf_aov("new")     # incl tax
    rc_aov, _ = _seg_perf_aov("returning")        # incl tax

    mrc = d.monthly_revenue_components
    net = float(mrc["net_aud"].sum()) if (mrc is not None and not mrc.empty and "net_aud" in mrc.columns) else 0.0
    tax = float(mrc["taxes_aud"].sum()) if (mrc is not None and not mrc.empty and "taxes_aud" in mrc.columns) else 0.0
    gross = float(mrc["gross_aud"].sum()) if (mrc is not None and not mrc.empty and "gross_aud" in mrc.columns) else 0.0
    returns = abs(float(mrc["returns_aud"].sum())) if (mrc is not None and not mrc.empty and "returns_aud" in mrc.columns) else 0.0
    tax_rate = (tax / net) if net else 0.0
    me = d.monthly_expenses
    cogs = float(me[me["bucket_section"] == "Cost of Sales"]["value"].abs().sum()) if (me is not None and not me.empty and "bucket_section" in me.columns) else 0.0
    cogs_rate = (cogs / net) if net else 0.0
    returns_rate = (returns / gross) if gross else 0.0
    gmpo = cogs_rate + returns_rate  # cost-to-fulfill fraction (COGS% + Returns%)
    ad_spend = float(d.daily_ad_spend["amount"].sum()) if (d.daily_ad_spend is not None and not d.daily_ad_spend.empty) else 0.0
    cac = (ad_spend / nc_orders) if nc_orders else 0.0
    amer = (nc_aov / cac) if cac else 0.0

    if not nc_aov:
        tree.banners.append(Banner(severity="error",
            text="NC/RC export missing New-customer rows — cannot build the LTV economics."))
        tree.subtitle = "LTV Analysis"
        return tree

    # ---- Cumulative customer value (incl tax) curve: First Order + Month 0..5 ----
    # Retention cohort → value(N) = NC AOV + Σ retention(0..N) × RC AOV (repeats are valued
    # at the returning-customer AOV, which is what they actually spend). Value cohort → use
    # the supplied cumulative customer value directly.
    max_off = 5
    rp = cohort.pivot_table(index="cohort", columns="month_offset", values="value", aggfunc="mean")
    if kind == "retention":
        ret = {o: float(rp[o].mean()) for o in rp.columns if rp[o].notna().any()}
        first_order = nc_aov
        cv = []  # Month 0..5 cumulative customer value (incl tax)
        cum = nc_aov
        for o in range(0, max_off + 1):
            cum += ret.get(o, 0.0) * rc_aov
            cv.append(cum)
        repeat_basis = "retention"
    else:
        first_order = float(rp[0].mean()) if 0 in rp.columns else nc_aov
        cv = [float(rp[o].mean()) if o in rp.columns and rp[o].notna().any() else None for o in range(0, max_off + 1)]
        repeat_basis = "value"

    col_vals = [first_order] + cv                              # 7 entries
    col_labels = ["First Order"] + [f"Month {o}" for o in range(0, max_off + 1)]
    ncols = len(col_vals)
    tree.columns = ["Metric"] + col_labels
    tree.subtitle = "Customer lifetime value, contribution margin and return on acquisition spend (full 12-month basis)."

    def vrow(key, label, values, fmt="money", *, bold=False, is_total=False, indent=1, formula=""):
        cells = [text_cell(f"ltv.{key}.lbl", label, indent=indent, bold=bold)]
        for i, v in enumerate(values):
            tip = Tooltip(formula=formula or label, sources=[src, nc_src])
            if fmt == "money":
                cells.append(money_cell(f"ltv.{key}.{i}", v, decimals=2, tooltip=tip, is_total=is_total))
            elif fmt == "pct":
                cells.append(pct_cell(f"ltv.{key}.{i}", v, tooltip=tip))
            else:
                cells.append(text_cell(f"ltv.{key}.{i}", str(v)))
        return make_row(cells, is_total=is_total)

    def section(key, title):
        return make_row([section_cell(f"ltv.{key}", title)] + [text_cell(f"ltv.{key}.{i}", "") for i in range(ncols)], is_section=True)

    # ---- §1 LTV Cohort by Customer (per customer) ----
    ex_tax = [v / (1 + tax_rate) if v is not None else None for v in col_vals]
    gm_dollar = [(1 - gmpo) * v if v is not None else None for v in col_vals]
    cac_target = (first_order / amer) if amer else None
    cac_row = [cac_target] * ncols
    cm_time = [(gm_dollar[i] - cac_target) if (gm_dollar[i] is not None and cac_target is not None) else None for i in range(ncols)]

    tree.rows.append(section("s1", "LTV COHORT BY CUSTOMER (per customer)"))
    tree.rows.append(vrow("cv", "Customer Value (incl. tax)", col_vals, bold=True,
                          formula="NC AOV + Σ repeat-retention × RC AOV (returning-customer AOV)." if repeat_basis == "retention" else "Cumulative customer value from the cohort export."))
    tree.rows.append(vrow(" extax", "Customer Value (ex-tax)", ex_tax, formula="Customer Value ÷ (1 + tax rate)."))
    tree.rows.append(vrow("gm", "Gross Margin per Order $", gm_dollar, formula=f"(1 − GMPO) × Customer Value.  GMPO = COGS% + Returns% = {gmpo*100:.1f}%."))
    tree.rows.append(vrow("cac", "CAC Target", cac_row, formula=f"First-order value ÷ aMER ({amer:.2f})."))
    tree.rows.append(vrow("cmt", "Contribution Margin over Time", cm_time, bold=True, is_total=True,
                          formula="Gross Margin per Order − CAC Target."))

    # ---- §2 LTV of Cohort by Revenue (scaled to the acquired cohort) ----
    customers = (ad_spend / cac_target) if cac_target else 0.0
    cv_wt_co = [c * customers if c is not None else None for c in col_vals]
    cv_ex_co = [g * customers if g is not None else None for g in ex_tax]
    cogs_co = [v * gmpo if v is not None else None for v in cv_ex_co]
    ad_row = [ad_spend] * ncols
    cm_co = [(cv_ex_co[i] - (cogs_co[i] or 0) - ad_spend) if cv_ex_co[i] is not None else None for i in range(ncols)]

    tree.rows.append(section("s2", "LTV OF COHORT BY REVENUE"))
    tree.rows.append(vrow("co_cv", "Customer Value (incl. tax)", cv_wt_co, formula=f"Implied customers ({customers:,.0f} = ad spend ÷ CAC) × per-customer value."))
    tree.rows.append(vrow("co_ex", "Customer Value (ex-tax)", cv_ex_co, formula="Implied customers × per-customer ex-tax value."))
    tree.rows.append(vrow("co_cogs", "Product Cost to Fulfil (COGS)", cogs_co, formula=f"Ex-tax cohort value × GMPO ({gmpo*100:.1f}%)."))
    tree.rows.append(vrow("co_ad", "Ad Spend (12-month)", ad_row, formula="Acquisition spend that built the cohort (platform CSVs)."))
    tree.rows.append(vrow("co_cm", "Contribution Margin", cm_co, bold=True, is_total=True,
                          formula="Ex-tax cohort value − COGS − Ad Spend."))

    # ---- §3 Return on Spend Metrics ----
    inc_cv_d = [(cm_time[i] - cm_time[0]) if (cm_time[i] is not None and cm_time[0] is not None) else None for i in range(ncols)]
    inc_cv_p = [safe_div((col_vals[i] - col_vals[0]) if col_vals[i] is not None else None, col_vals[0]) for i in range(ncols)]
    inc_cm_d = [(cm_co[i] - cm_co[0]) if (cm_co[i] is not None and cm_co[0] is not None) else None for i in range(ncols)]
    inc_cm_p = [safe_div((cm_co[i] - cm_co[0]) if (cm_co[i] is not None and cm_co[0] is not None) else None, cm_co[0]) for i in range(ncols)]

    tree.rows.append(section("s3", "RETURN ON SPEND METRICS"))
    tree.rows.append(vrow("inc_cvd", "$ Increase of Customer Value", inc_cv_d, formula="Contribution Margin over Time vs First Order."))
    tree.rows.append(vrow("inc_cvp", "% Increase of Customer Value", inc_cv_p, fmt="pct", formula="(Customer Value − First Order) ÷ First Order."))
    tree.rows.append(vrow("inc_cmd", "$ Increase of Cohort Contribution Margin", inc_cm_d, formula="Cohort Contribution Margin vs First Order."))
    tree.rows.append(vrow("inc_cmp", "% Increase of Cohort Contribution Margin", inc_cm_p, fmt="pct", formula="(Cohort CM − First Order CM) ÷ First Order CM."))

    # ---- Banner / notes ----
    if repeat_basis == "retention":
        tree.banners.append(Banner(severity="info",
            text=(f"Derived from the retention cohort in {src}. The customer-value curve is NC AOV "
                  f"({nc_aov:,.2f}) plus cumulative repeat-retention valued at the returning-customer AOV "
                  f"({rc_aov:,.2f}) — repeats are valued at what returning customers actually spend, not the "
                  f"acquisition AOV. The % increase row feeds the Final Report Card M2/M5 benchmarks.")))
    else:
        tree.banners.append(Banner(severity="info",
            text=f"Customer-value cohort from {src}. The % increase row feeds the Final Report Card M2/M5 benchmarks."))
    tree.notes = [
        "§1 is per acquired customer; §2 scales it to the whole cohort using implied customers = 12-month ad spend ÷ CAC.",
        "GMPO (cost to fulfil) = COGS% + Returns%; aMER = NC AOV ÷ CAC. Both from the 12-month figures.",
        "Returning customers spend materially less than new ones, so repeat orders lift cumulative value only modestly — the % increase row reflects that.",
    ]

    # Stash % customer-value growth (by month offset) for the Final Report Card M2/M5 rows.
    # Column index: 0 = First Order, 1 = Month 0, … so Month N sits at index N+1.
    bundle.derived.ltv_growth = {o: (float(inc_cv_p[o + 1]) if inc_cv_p[o + 1] is not None else None) for o in range(0, max_off + 1)}
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
