"""NCCM Calculator — New Customer Contribution Margin, quarter over quarter.

Layout: metrics run down the rows; each calendar quarter is a column, plus a
trailing Notes column explaining each metric's derivation.

Per-quarter inputs (NC AOV, orders, COGS) come from that quarter's New-customer
rows in the NC/RC export. CAC is genuinely quarterly: quarter ad spend (from the
daily ad-platform data, windowed to the calendar quarter) ÷ that quarter's NC
orders. Operational fee lines use mentor defaults applied to each quarter's AOV.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, pct_cell, safe_div, section_cell, text_cell


_DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "defaults.json"


def _quarter_sort_key(label: str) -> tuple[int, int]:
    """'Q1 2026' -> (2026, 1). 'All' sorts last."""
    try:
        q, y = label.split()
        return (int(y), int(q.lstrip("Qq")))
    except Exception:
        return (9999, 9)


def _quarter_window(label: str) -> tuple[date, date] | None:
    """Calendar-quarter date span for an ad-spend window. 'Q2 2026' -> (Apr 1, Jun 30)."""
    try:
        q, y = label.split()
        qi = int(q.lstrip("Qq")); yr = int(y)
        start_month = (qi - 1) * 3 + 1
        start = date(yr, start_month, 1)
        end_month = start_month + 2
        # last day of end_month
        if end_month == 12:
            end = date(yr, 12, 31)
        else:
            end = date(yr, end_month + 1, 1).replace(day=1)
            from datetime import timedelta
            end = end - timedelta(days=1)
        return start, end
    except Exception:
        return None


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    nc_rc = bundle.nc_rc
    with _DEFAULTS_PATH.open() as f:
        defaults = json.load(f)["nccm"]
    # First-order CM target for the Target ROAS row (mentor default, distinct from the
    # blended 35% CM growth benchmark on the Final Report Card).
    cm_min = defaults.get("target_cm_pct_first_order", 0.25)

    tree = RenderTree(tab_id="nccm", title="NCCM Calculator",
                      subtitle="New Customer Contribution Margin — quarter over quarter. Run by region if selling in multiple.")

    nc_src = Path(meta.files_found.get("nc_rc", "")).name
    ads_src = Path(meta.files_found.get("ad_spend_meta", "")).name or "ad-platform CSVs"

    if nc_rc is None or nc_rc.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC report missing — cannot compute NCCM."))
        return tree

    # Defaults (mentor)
    pp_pct = defaults["payment_processing_pct"]
    smarkets_pct = defaults["shopify_markets_fee_pct"]
    txn_fee = defaults["transaction_fee_per_order_aud"]
    packaging = defaults["packaging_per_order_aud"]
    fulfillment = defaults["fulfillment_per_order_aud"]

    # Which quarters do we have NC rows for?
    have_quarter_col = "quarter" in nc_rc.columns
    new_rows = nc_rc[nc_rc["segment"].str.lower() == "new"].copy()
    if new_rows.empty:
        tree.banners.append(Banner(severity="error", text="NC/RC export has no 'New' customer rows."))
        return tree

    quarters = sorted(new_rows["quarter"].astype(str).unique().tolist(), key=_quarter_sort_key)
    single_period = (quarters == ["All"]) or not have_quarter_col

    # ---- Per-quarter computation ----
    def compute_quarter(qlabel: str) -> dict:
        rows = new_rows[new_rows["quarter"].astype(str) == qlabel]
        if rows.empty:
            return {}
        nc = rows.iloc[0]
        nc_orders = int(nc.get("orders", 0) or 0)
        nc_gross = float(nc.get("gross", 0) or 0)
        nc_disc = float(nc.get("discounts", 0) or 0)
        nc_ship = float(nc.get("shipping", 0) or 0)
        nc_tax = float(nc.get("taxes", 0) or 0)
        nc_cogs = float(nc.get("cogs", 0) or 0)
        nc_perf = nc_gross + nc_disc + nc_ship + nc_tax
        aov = safe_div(nc_perf, nc_orders)

        cogs_po = safe_div(nc_cogs, nc_orders)
        pp_dollar = aov * pp_pct if aov else None
        sm_dollar = aov * smarkets_pct if aov else None
        op_cost = sum(filter(None, [cogs_po, pp_dollar, sm_dollar, txn_fee, packaging, fulfillment]))
        gp_po = (aov - op_cost) if (aov is not None) else None

        # Quarter ad spend → CAC
        ad_q = 0.0
        win = _quarter_window(qlabel) if not single_period else d.snapshot_window
        if not d.daily_ad_spend.empty and win:
            mask = (d.daily_ad_spend["day"] >= win[0]) & (d.daily_ad_spend["day"] <= win[1])
            ad_q = float(d.daily_ad_spend.loc[mask, "amount"].sum())
        cac = safe_div(ad_q, nc_orders) if nc_orders else None
        fcm = (gp_po - cac) if (gp_po is not None and cac is not None) else None
        # All ROAS rows are first-time-customer (acquisition) economics — repeat revenue excluded.
        # Actual ROAS: the quarter's NC revenue per ad dollar.
        act_roas = safe_div(nc_perf, ad_q) if ad_q else None
        # Breakeven ROAS: the ROAS at which first-order CM = 0 (spend per order = GP per order).
        be_roas = safe_div(aov, gp_po) if (aov and gp_po and gp_po > 0) else None
        # Target ROAS: the ROAS needed to bank the first-order CM target (ad/order = GP − cm_min × AOV).
        tgt_denom = (gp_po - cm_min * aov) if (aov and gp_po is not None) else None
        tgt_roas = (aov / tgt_denom) if (tgt_denom and tgt_denom > 0) else None

        return {
            "orders": nc_orders, "aov": aov, "tax_po": safe_div(nc_tax, nc_orders),
            "cogs_po": cogs_po, "pp": pp_dollar, "sm": sm_dollar, "txn": txn_fee,
            "pack": packaging, "ful": fulfillment, "op_cost": op_cost,
            "gp_po": gp_po, "ad_q": ad_q, "cac": cac, "fcm": fcm,
            "act_roas": act_roas, "be_roas": be_roas, "tgt_roas": tgt_roas,
            "nc_perf": nc_perf, "nc_cogs": nc_cogs,
        }

    qdata = {q: compute_quarter(q) for q in quarters}
    qdata = {q: v for q, v in qdata.items() if v}
    quarters = [q for q in quarters if q in qdata]
    if not quarters:
        tree.banners.append(Banner(severity="error", text="No quarters with NC data could be computed."))
        return tree

    col_labels = ["This period" if single_period else q for q in quarters]
    tree.columns = ["Metric"] + col_labels + ["Notes"]
    ncol = len(quarters)

    def metric_row(key, label, getter, fmt="money", note="", *, indent=1, bold=False, is_total=False, tip_formula=""):
        cells = [text_cell(f"nccm.{key}.lbl", label, indent=indent, bold=bold)]
        for i, q in enumerate(quarters):
            v = getter(qdata[q])
            tip = Tooltip(formula=tip_formula or label, sources=[nc_src], result_expr=(f"{v:,.2f}" if isinstance(v, (int, float)) and v is not None else "—"))
            if fmt == "money":
                cells.append(money_cell(f"nccm.{key}.{i}", v, tooltip=tip, decimals=2, is_total=is_total))
            elif fmt == "pct":
                cells.append(pct_cell(f"nccm.{key}.{i}", v, tooltip=tip))
            elif fmt == "ratio":
                cells.append(text_cell(f"nccm.{key}.{i}", f"{v:.2f}x" if v is not None else "—"))
            else:
                cells.append(text_cell(f"nccm.{key}.{i}", f"{int(v):,}" if v is not None else "—"))
        cells.append(text_cell(f"nccm.{key}.note", note))
        return make_row(cells, is_total=is_total)

    def section(key, title):
        return make_row([section_cell(f"nccm.{key}", title)]
                        + [text_cell(f"nccm.{key}.{i}", "") for i in range(ncol + 1)], is_section=True)

    # ---- INPUTS ----
    tree.rows.append(section("s1", "INPUTS"))
    tree.rows.append(metric_row("aov", "NC AOV", lambda v: v["aov"], "money",
        "Inclusive of tax (Daily Mentor convention). (Gross + Discounts + Shipping + Tax) / Orders.",
        bold=True, tip_formula="(Gross + Discounts + Shipping + Tax) / NC Orders"))
    tree.rows.append(metric_row("orders", "NC Orders", lambda v: v["orders"], "int",
        "New-customer orders in the quarter (from the NC/RC export)."))
    tree.rows.append(metric_row("tax", "Tax per order", lambda v: v["tax_po"], "money",
        "Tax collected / NC orders.", indent=2))

    # ---- BLENDED COGS PER ORDER ----
    tree.rows.append(section("s2", "BLENDED COGS PER ORDER"))
    tree.rows.append(metric_row("cogs", "Product COGS (Shopify per-sale)", lambda v: v["cogs_po"], "money",
        "NC COGS / NC orders. Landed costs (Freight, Warehouse) sit in the lines below."))
    tree.rows.append(metric_row("pp", "Payment Processing", lambda v: v["pp"], "money",
        f"Default {pp_pct*100:.1f}% of AOV. Override per client when known."))
    tree.rows.append(metric_row("sm", "Shopify Markets Fee", lambda v: v["sm"], "money",
        f"Default {smarkets_pct*100:.1f}% of AOV. 0% if not selling cross-border."))
    tree.rows.append(metric_row("txn", "Transaction Fees", lambda v: v["txn"], "money",
        f"Default ${txn_fee:.2f}/order. Replace with Xero 'Shopify & PayPal fees' / orders when available."))
    tree.rows.append(metric_row("pack", "Packaging + supplies", lambda v: v["pack"], "money",
        f"Default ${packaging:.2f}/order. Box, tape, inserts."))
    tree.rows.append(metric_row("ful", "Fulfilment (3PL)", lambda v: v["ful"], "money",
        f"Default ${fulfillment:.2f}/order. Replace with Xero 'Warehouse' / 3PL invoice / orders."))
    tree.rows.append(metric_row("opcost", "Total COGS per order", lambda v: v["op_cost"], "money",
        "", bold=True, is_total=True))

    # ---- MARGIN ----
    tree.rows.append(section("s3", "MARGIN"))
    tree.rows.append(metric_row("gp", "Gross Profit per Order", lambda v: v["gp_po"], "money",
        "AOV − Total COGS per order.", bold=True, tip_formula="AOV − Total COGS per order"))
    tree.rows.append(metric_row("adq", "Ad Spend (quarter)", lambda v: v["ad_q"], "money",
        "Total ad-platform spend in the calendar quarter (×FX).", indent=2))
    tree.rows.append(metric_row("cac", "CAC", lambda v: v["cac"], "money",
        "Quarter ad spend / NC orders for the same quarter.", tip_formula="Quarter Ad Spend / NC Orders"))
    tree.rows.append(metric_row("actroas", "Actual ROAS (first-time customers)", lambda v: v["act_roas"], "ratio",
        "Quarter NC revenue ÷ quarter ad spend. Acquisition ROAS — repeat-customer revenue excluded.",
        tip_formula="NC Performance Sales ÷ Quarter Ad Spend", bold=True))
    tree.rows.append(metric_row("beroas", "Breakeven ROAS (first-time customers)", lambda v: v["be_roas"], "ratio",
        "AOV ÷ Gross Profit per Order — the ROAS at which the first order breaks even. Below this, acquisition loses money on order one.",
        tip_formula="NC AOV ÷ Gross Profit per Order"))
    tree.rows.append(metric_row("tgtroas", f"Target ROAS (first-time customers, ≥ {cm_min*100:.0f}% CM)", lambda v: v["tgt_roas"], "ratio",
        f"AOV ÷ (GP per order − {cm_min*100:.0f}% × AOV) — the ROAS needed to bank a {cm_min*100:.0f}% first-order contribution margin. '—' = unreachable at current per-order costs.",
        tip_formula="NC AOV ÷ (GP per order − CM target × AOV)"))
    tree.rows.append(metric_row("fcm", "First-Order Contribution Margin", lambda v: v["fcm"], "money",
        "Gross Profit per Order − CAC. Positive = acquisition profitable on order one.",
        bold=True, is_total=True, tip_formula="Gross Profit per Order − CAC"))

    # ---- Banners ----
    if single_period:
        tree.banners.append(Banner(severity="warning",
            text="NC/RC export has no quarter dimension — NCCM shows a single blended period. Re-export 'NC v RC L365' grouped by quarter to unlock quarter-over-quarter."))
    else:
        tree.banners.append(Banner(severity="info",
            text=f"Quarter-over-quarter across {len(quarters)} calendar quarter(s). CAC uses each quarter's ad spend ÷ that quarter's NC orders; per-order fees use mentor defaults applied to each quarter's AOV."))
    tree.banners.append(Banner(severity="info",
        text="Operational lines marked 'default' should be replaced with client-specific data: Xero 'Shopify & PayPal fees', 'Freight & Courier', 'Warehouse' / 3PL invoices, packaging supplier rate card."))

    tree.notes = [
        "Per-region: if the brand sells across regions (AU + NZ + US), build a separate NCCM per region — unit economics differ markedly.",
        "AOV is inclusive of tax (Daily Mentor convention); operational cost ratios are expressed against this gross-of-tax AOV.",
        "First-Order CM is the money kept per new customer on their first purchase. Negative means repeat-purchase economics must carry the brand.",
        "Partial calendar quarters at the edges of the 12-month window will show fewer orders — read trend, not absolute level, on those.",
    ]
    return tree
