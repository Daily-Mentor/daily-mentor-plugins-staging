"""Homepage / Benchmark Scorecard.

Sources:
- NC/RC CSV (90-day snapshot block — but degrades to whatever period the CSV covers)
- Sessions CSV (last-90 weighted)
- Shopify daily ×FX (cumulative window match)
- Ad CSVs ×FX
- Xero P&L (OPEX average)
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..models import Banner, RenderTree, Row, Tooltip
from .helpers import int_cell, make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


_BENCHMARKS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "benchmarks.json"


def _benchmarks() -> dict:
    with _BENCHMARKS_PATH.open() as f:
        return json.load(f)


def compute(bundle) -> RenderTree:  # IngestBundle (with .derived)
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc
    sessions = bundle.sessions
    bm = _benchmarks()

    tree = RenderTree(tab_id="homepage", title="Homepage", subtitle="Company Performance Report Card")

    # --- Period label ---
    tree.subtitle = "12-Month Company Snapshot"

    # ---- NC / RC block ----
    # Aggregate ALL quarters in the NC/RC file (full 12 months). The file is grouped
    # by quarter, so taking a single row (.iloc[0]) would silently report just one
    # quarter; we sum every quarter for each segment instead.
    def _agg_segment(seg: str):
        if nc_rc is None or nc_rc.empty:
            return None
        rows = nc_rc[nc_rc["segment"].str.lower() == seg]
        if rows.empty:
            return None
        cols = ("gross", "discounts", "returns", "shipping", "taxes", "orders", "cogs")
        return {c: float(rows[c].sum()) if c in rows.columns else 0.0 for c in cols}

    new_row = _agg_segment("new")
    ret_row = _agg_segment("returning")

    tree.columns = ["Metric", "New Customer", "Returning Customer"]
    tree.rows.append(make_row([section_cell("hp.s1", "Customer Performance"), text_cell("hp.s1.b", ""), text_cell("hp.s1.c", "")], is_section=True))

    def nccm_cell(coord, value, label, sources):
        return money_cell(coord, value, tooltip=Tooltip(
            formula=label, inputs=[("Source", sources)], result_expr=f"{value:,.2f}" if value is not None else "—",
            sources=sources if isinstance(sources, list) else [sources],
            confidence_note="Provisional — NC/RC aggregated across the 12-month window.",
        ))

    nc_rc_source = Path(meta.files_found.get("nc_rc", "")).name
    for key, label in (
        ("gross", "Total Gross Sales"),
        ("discounts", "Discounts"),
        ("returns", "Returns"),
        ("shipping", "Shipping charges"),
        ("taxes", "Taxes"),
    ):
        nv = float(new_row[key]) if new_row is not None else None
        rv = float(ret_row[key]) if ret_row is not None else None
        tree.rows.append(make_row([
            text_cell(f"hp.{key}.a", label, indent=1),
            money_cell(f"hp.{key}.nc", nv, tooltip=Tooltip(
                formula=f"NC {label}", result_expr=f"{nv:,.2f}" if nv is not None else "—",
                sources=[nc_rc_source], confidence_note="Provisional — 12-month aggregate.")),
            money_cell(f"hp.{key}.rc", rv, tooltip=Tooltip(
                formula=f"RC {label}", result_expr=f"{rv:,.2f}" if rv is not None else "—",
                sources=[nc_rc_source], confidence_note="Provisional — 12-month aggregate.")),
        ]))

    # Performance Sales (Gross + Discounts + Shipping + Tax) — inclusive of tax per spec
    nc_perf = (float(new_row["gross"]) + float(new_row["discounts"]) + float(new_row["shipping"]) + float(new_row["taxes"])) if new_row is not None else None
    rc_perf = (float(ret_row["gross"]) + float(ret_row["discounts"]) + float(ret_row["shipping"]) + float(ret_row["taxes"])) if ret_row is not None else None
    tree.rows.append(make_row([
        text_cell("hp.perf.a", "Performance Sales (gross + discounts + shipping + tax)", bold=True, indent=1),
        money_cell("hp.perf.nc", nc_perf, tooltip=Tooltip(
            formula="NC Performance Sales = Gross + Discounts + Shipping + Tax",
            inputs=[("Gross", float(new_row["gross"])), ("Discounts", float(new_row["discounts"])),
                    ("Shipping", float(new_row["shipping"])), ("Tax", float(new_row["taxes"]))],
            result_expr=f"= {nc_perf:,.2f}" if nc_perf is not None else "—",
            sources=[nc_rc_source], gotcha_refs=["G36"],
            confidence_note="Inclusive of tax (intentional — matches Daily Mentor NCCM convention).",
        ), is_total=True),
        money_cell("hp.perf.rc", rc_perf, tooltip=Tooltip(
            formula="RC Performance Sales = Gross + Discounts + Shipping + Tax",
            sources=[nc_rc_source], confidence_note="Provisional.",
        ), is_total=True),
    ]))

    # Orders + AOV
    nc_orders = int(new_row["orders"]) if new_row is not None else None
    rc_orders = int(ret_row["orders"]) if ret_row is not None else None
    nc_aov = safe_div(nc_perf, nc_orders)
    rc_aov = safe_div(rc_perf, rc_orders)
    tree.rows.append(make_row([
        text_cell("hp.orders.a", "Orders", indent=1),
        int_cell("hp.orders.nc", nc_orders, tooltip=Tooltip(formula="NC Orders", sources=[nc_rc_source])),
        int_cell("hp.orders.rc", rc_orders, tooltip=Tooltip(formula="RC Orders", sources=[nc_rc_source])),
    ]))
    tree.rows.append(make_row([
        text_cell("hp.aov.a", "AOV (performance / orders)", indent=1),
        money_cell("hp.aov.nc", nc_aov, tooltip=Tooltip(
            formula="NC AOV = NC Performance Sales / NC Orders",
            inputs=[("Performance", nc_perf), ("Orders", nc_orders)],
            result_expr=f"{nc_perf:,.2f} / {nc_orders} = {nc_aov:,.2f}" if nc_aov else "—",
            sources=[nc_rc_source], confidence_note="Provisional — inclusive of tax.",
        ), decimals=2),
        money_cell("hp.aov.rc", rc_aov, tooltip=Tooltip(
            formula="RC AOV = RC Performance Sales / RC Orders",
            result_expr=f"{rc_perf:,.2f} / {rc_orders} = {rc_aov:,.2f}" if rc_aov else "—",
            sources=[nc_rc_source],
        ), decimals=2),
    ]))

    # COGS row
    nc_cogs = float(new_row["cogs"]) if new_row is not None else None
    rc_cogs = float(ret_row["cogs"]) if ret_row is not None else None
    tree.rows.append(make_row([
        text_cell("hp.cogs.a", "Cost of Goods Sold (Shopify product only)", indent=1),
        money_cell("hp.cogs.nc", nc_cogs, tooltip=Tooltip(
            formula="Shopify COGS (product cost only — does not include landed freight/warehouse)",
            sources=[nc_rc_source], gotcha_refs=["G39"],
            confidence_note="Shopify product-COGS — landed COGS comes from Xero (Freight & Warehouse), see Monthly P&L.",
        )),
        money_cell("hp.cogs.rc", rc_cogs, tooltip=Tooltip(
            formula="Shopify COGS (product cost only)", sources=[nc_rc_source])),
    ]))

    # ---- Site Metrics block ----
    tree.rows.append(make_row([section_cell("hp.s2", "Site Metrics"), text_cell("hp.s2.b", ""), text_cell("hp.s2.c", "")], is_section=True))
    if sessions is not None and not sessions.empty:
        total_sessions_90 = float(sessions.tail(12)["sessions"].sum())
        total_visitors_90 = float(sessions.tail(12)["visitors"].sum())
        sessions_src = Path(meta.files_found.get("sessions", "")).name
    else:
        total_sessions_90 = total_visitors_90 = None
        sessions_src = "—"

    cr = safe_div((nc_orders or 0) + (rc_orders or 0), total_sessions_90) if total_sessions_90 else None
    tree.rows.append(make_row([
        text_cell("hp.sessions.a", "Sessions (12 months)", indent=1),
        int_cell("hp.sessions.v", total_sessions_90, tooltip=Tooltip(
            formula="Sum of Sessions over the 12-month window",
            sources=[sessions_src], confidence_note="Provisional.",
        )),
        text_cell("hp.sessions.c", ""),
    ]))
    tree.rows.append(make_row([
        text_cell("hp.cr.a", "Conversion Rate (Orders / Sessions)", indent=1),
        pct_cell("hp.cr.v", cr, tooltip=Tooltip(
            formula="(NC Orders + RC Orders) / Sessions, both over the 12-month window",
            inputs=[("NC Orders", nc_orders), ("RC Orders", rc_orders), ("Sessions", total_sessions_90)],
            result_expr=f"({nc_orders} + {rc_orders}) / {total_sessions_90:,.0f} = {cr*100:.2f}%" if cr else "—",
            sources=[nc_rc_source, sessions_src],
        )),
        text_cell("hp.cr.c", ""),
    ]))

    # ---- Ad spend block (per-platform breakdown) ----
    tree.rows.append(make_row([section_cell("hp.s3", "Marketing Spend"), text_cell("hp.s3.b", ""), text_cell("hp.s3.c", "")], is_section=True))
    # Full 12-month window so ad spend lines up with the 12-month revenue above.
    snapshot_start = meta.lookback_start or (d.snapshot_window[0] if d.snapshot_window else None)
    snapshot_end = meta.lookback_end or (d.snapshot_window[1] if d.snapshot_window else None)
    ad_spend_90 = None
    fx_note = None
    ad_src_list = []
    platform_spend: dict[str, float] = {}
    if not d.daily_ad_spend.empty and snapshot_start and snapshot_end:
        ads_window = d.daily_ad_spend[
            (d.daily_ad_spend["day"] >= snapshot_start) & (d.daily_ad_spend["day"] <= snapshot_end)
        ]
        ad_spend_90 = float(ads_window["amount"].sum())
        for platform, sub in ads_window.groupby("platform"):
            platform_spend[platform] = float(sub["amount"].sum())
        for platform, ccy in meta.ad_platform_currency.items():
            ad_src_list.append(Path(meta.files_found.get(f"ad_spend_{platform}", "")).name)
            if ccy.code != meta.reporting_currency:
                rate = d.fx.rate(snapshot_end, ccy.code, meta.reporting_currency)
                fx_note = f"{ccy.code}→{meta.reporting_currency} ≈ {rate:.4f} (monthly cached rate, {snapshot_end.strftime('%Y-%m')})"

    # Per-platform rows
    platform_labels = {"meta": "Facebook / Meta Spend", "google": "Google Spend", "tiktok": "TikTok Spend"}
    for platform in ("meta", "google", "tiktok"):
        if platform in platform_spend:
            tree.rows.append(make_row([
                text_cell(f"hp.adspend.{platform}.a", platform_labels[platform], indent=1),
                money_cell(f"hp.adspend.{platform}.v", platform_spend[platform], tooltip=Tooltip(
                    formula=f"Sum of {platform_labels[platform]} over the 12-month window ×FX.",
                    sources=[Path(meta.files_found.get(f"ad_spend_{platform}", "")).name],
                    fx_note=fx_note if meta.ad_platform_currency.get(platform) and meta.ad_platform_currency[platform].code != meta.reporting_currency else None,
                    gotcha_refs=["G39"],
                )),
                text_cell(f"hp.adspend.{platform}.c", ""),
            ]))
    # "Other Spend" row (catch-all for any spend in derived.daily_ad_spend not in known platforms)
    other = sum(v for k, v in platform_spend.items() if k not in {"meta", "google", "tiktok"})
    if other:
        tree.rows.append(make_row([
            text_cell("hp.adspend.other.a", "Other Spend", indent=1),
            money_cell("hp.adspend.other.v", other, tooltip=Tooltip(
                formula="Spend from any other platforms in the inputs directory.",
                sources=ad_src_list,
            )),
            text_cell("hp.adspend.other.c", ""),
        ]))

    total_gross_period = (nc_perf or 0) + (rc_perf or 0)
    mer = safe_div(ad_spend_90, total_gross_period)

    tree.rows.append(make_row([
        text_cell("hp.adspend.a", "Total Ad Spend (12 months)", indent=1, bold=True),
        money_cell("hp.adspend.v", ad_spend_90, tooltip=Tooltip(
            formula="Sum of platform-level daily ad spend over the 12-month window, in reporting currency.",
            inputs=[("Window", f"{snapshot_start} → {snapshot_end}")],
            sources=ad_src_list, fx_note=fx_note,
            confidence_note="Provisional — sourced from ad platform exports (G39: not from Xero).",
        ), is_total=True),
        text_cell("hp.adspend.c", ""),
    ]))

    tree.rows.append(make_row([
        text_cell("hp.mer.a", "MER (Ad Spend / Gross Sales)", indent=1, bold=True),
        pct_cell("hp.mer.v", mer, tooltip=Tooltip(
            formula="MER = Total Ad Spend / (NC Gross + RC Gross + Shipping + Tax)",
            inputs=[("Ad Spend", ad_spend_90), ("Gross+Ship+Tax", total_gross_period)],
            result_expr=f"{ad_spend_90:,.0f} / {total_gross_period:,.0f} = {mer*100:.1f}%" if mer else "—",
            sources=ad_src_list + [nc_rc_source], gotcha_refs=["G39"],
        )),
        text_cell("hp.mer.c", ""),
    ]))

    # ---- OPEX Summary (snapshot period) ----
    tree.rows.append(make_row([section_cell("hp.s_opex", "OPEX Summary (12 months)"),
                                text_cell("hp.s_opex.b", ""), text_cell("hp.s_opex.c", "")], is_section=True))
    # Aggregate posted Xero OPEX over the 12-month window. If posted months are sparse, use posted-month average × ratio of window.
    opex_period = {"Marketing": 0.0, "Wages + Super": 0.0, "Subscriptions (Software)": 0.0,
                   "Other OPEX (freight/admin/travel/etc.)": 0.0}
    if not d.monthly_expenses.empty:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        # bucket per section
        if "bucket_section" in non_cogs.columns:
            by_section = non_cogs.groupby("bucket_section")["value"].apply(lambda s: float(s.abs().sum()))
            if "Marketing" in by_section: opex_period["Marketing"] = by_section["Marketing"]
            if "People" in by_section: opex_period["Wages + Super"] = by_section["People"]
            if "Software" in by_section: opex_period["Subscriptions (Software)"] = by_section["Software"]
            if "Other Operating Expenses" in by_section: opex_period["Other OPEX (freight/admin/travel/etc.)"] = by_section["Other Operating Expenses"]
    # If Marketing is empty in Xero but we have ad spend, use the snapshot-window ad spend instead
    if opex_period["Marketing"] == 0 and ad_spend_90:
        opex_period["Marketing"] = ad_spend_90

    total_opex_period = sum(opex_period.values())
    for label, val in opex_period.items():
        tree.rows.append(make_row([
            text_cell(f"hp.opex.{label}.a", label, indent=1),
            money_cell(f"hp.opex.{label}.v", val if val else None, tooltip=Tooltip(
                formula=f"Sum of Xero {label.split(' (')[0]} rows over posted months" + (" + ad-platform CSVs" if label == "Marketing" else ""),
                sources=[Path(meta.files_found.get("xero_pl", "")).name] + (ad_src_list if label == "Marketing" else []),
                gotcha_refs=["G39"] if label == "Marketing" else [],
                confidence_note=("Marketing pulls from ad-platform CSVs because Xero has no marketing accounts." if label == "Marketing" and ad_spend_90 else "Posted-month sum from Xero. Partial periods may understate."),
            )),
            text_cell(f"hp.opex.{label}.c", ""),
        ]))
    tree.rows.append(make_row([
        text_cell("hp.opex.tot.a", "Total OPEX (12 months)", indent=1, bold=True),
        money_cell("hp.opex.tot.v", total_opex_period if total_opex_period else None, tooltip=Tooltip(
            formula="Sum of the four OPEX buckets above.",
            sources=[Path(meta.files_found.get("xero_pl", "")).name, *ad_src_list],
        ), is_total=True),
        text_cell("hp.opex.tot.c", ""),
    ], is_total=True))

    # ---- Benchmark Scorecard ----
    tree.rows.append(make_row([section_cell("hp.s4", "Benchmark Scorecard"), text_cell("hp.s4.b", "Actual"), text_cell("hp.s4.c", "Target")], is_section=True))

    def bench_row(name, actual, target_str, target_ok: bool | None, tooltip: Tooltip, fmt="pct"):
        actual_cell = pct_cell(f"hp.bm.{name}.v", actual, tooltip=tooltip) if fmt == "pct" else money_cell(f"hp.bm.{name}.v", actual, tooltip=tooltip, decimals=2)
        status = "✓" if target_ok else ("✗" if target_ok is False else "—")
        return make_row([
            text_cell(f"hp.bm.{name}.a", name, indent=1),
            actual_cell,
            text_cell(f"hp.bm.{name}.t", f"{target_str}   {status}"),
        ])

    # MER
    tree.rows.append(bench_row(
        "MER (< 30%)", mer,
        f"< {bm['growth']['mer_max']*100:.0f}%",
        (mer is not None and mer < bm['growth']['mer_max']),
        Tooltip(formula="MER target <30% per Daily Mentor benchmarks", sources=ad_src_list, gotcha_refs=["G39"]),
    ))
    # CR
    cr_min = bm['growth']['conversion_rate_min']
    tree.rows.append(bench_row(
        "Conversion Rate", cr,
        f"> {cr_min*100:.1f}%",
        (cr is not None and cr > cr_min),
        Tooltip(formula="CR target >2.5%", sources=[nc_rc_source, sessions_src]),
    ))
    # Blended AOV
    blended_aov = safe_div(((nc_perf or 0) + (rc_perf or 0)), (nc_orders or 0) + (rc_orders or 0))
    tree.rows.append(bench_row(
        "Blended AOV", blended_aov,
        f"> ${bm['growth']['aov_min_aud']}",
        (blended_aov is not None and blended_aov > bm['growth']['aov_min_aud']),
        Tooltip(formula="(NC Performance + RC Performance) / (NC Orders + RC Orders)",
                inputs=[("NC perf", nc_perf), ("RC perf", rc_perf), ("Orders", (nc_orders or 0) + (rc_orders or 0))],
                sources=[nc_rc_source]),
        fmt="money",
    ))
    # Returns %
    returns_pct = safe_div(abs(float(new_row["returns"]) + float(ret_row["returns"])) if (new_row is not None and ret_row is not None) else None,
                           ((nc_perf or 0) + (rc_perf or 0)) or None)
    tree.rows.append(bench_row(
        "Returns %", returns_pct,
        f"< {bm['growth']['returns_pct_max']*100:.0f}%",
        (returns_pct is not None and returns_pct < bm['growth']['returns_pct_max']),
        Tooltip(formula="abs(NC Returns + RC Returns) / Performance Sales", sources=[nc_rc_source]),
    ))
    # NC order share
    total_orders = (nc_orders or 0) + (rc_orders or 0)
    nc_share = safe_div(nc_orders, total_orders) if total_orders else None
    nc_share_ok = None
    if nc_share is not None:
        nc_share_ok = bm['growth']['nc_order_share_min'] <= nc_share <= bm['growth']['nc_order_share_max']
    tree.rows.append(bench_row(
        "NC Order Share", nc_share,
        f"{int(bm['growth']['nc_order_share_min']*100)}–{int(bm['growth']['nc_order_share_max']*100)}%",
        nc_share_ok,
        Tooltip(formula="NC Orders / (NC + RC Orders)", sources=[nc_rc_source]),
    ))

    # ---- Banners ----
    tree.banners.append(Banner(severity="info",
        text="All figures are full 12-month: NC/RC aggregated across every quarter, ad spend and sessions summed over the lookback. (Per-quarter detail lives on the NCCM tab.)"))
    if meta.files_missing:
        tree.banners.append(Banner(severity="error",
            text="Missing input files: " + ", ".join(meta.files_missing)))
    if fx_note:
        tree.banners.append(Banner(severity="info",
            text=f"Ad spend converted to {meta.reporting_currency}. {fx_note}"))

    return tree
