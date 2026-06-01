"""Financial Position — balance sheet snapshot + narrative mentor flags."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..models import Banner, RenderTree, Tooltip
from .helpers import make_row, money_cell, section_cell, text_cell


_BANK_KEYWORDS = ["bank", "business account", "qantas", "credit card", "nab",
                  "australian dollar", "british pound", "euro", "us dollar", "new zealand dollar"]
_CC_KEYWORDS = ["credit card", "qantas credit"]
_UNDEPOSITED_KEYWORDS = ["undeposited"]
_INVENTORY_KEYWORDS = ["inventory", "stock on hand", "stock"]
_LOAN_KEYWORDS = ["shopify loan", "loan", "intercompany"]
_GST_KEYWORDS = ["gst"]
_PAYG_KEYWORDS = ["payg"]
_SUPER_KEYWORDS = ["super"]
_OWNER_KEYWORDS = ["owner", "drawings", "funds introduced"]


def _all_rows_matching(df: pd.DataFrame, keywords: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    pattern = "|".join(keywords)
    return df[df["account"].str.lower().str.contains(pattern, regex=True, na=False)]


def _sum_or_none(df: pd.DataFrame) -> float | None:
    if df.empty:
        return None
    return float(df["value"].sum())


def compute(bundle) -> RenderTree:
    d = bundle.derived
    meta = bundle.meta
    snapshot = d.balance_sheet_snapshot if not d.balance_sheet_snapshot.empty else pd.DataFrame()

    tree = RenderTree(tab_id="financial_position", title="Financial Position",
                      subtitle=f"As at {d.snapshot_as_at}  |  Source: Xero Balance Sheet  |  Currency: {meta.reporting_currency}"
                      if d.snapshot_as_at else "Balance Sheet")
    src = Path(meta.files_found.get("xero_bs", "")).name

    if snapshot.empty:
        tree.banners.append(Banner(severity="error", text="No balance sheet data found."))
        return tree

    tree.columns = ["Account", "Balance"]

    # ---- Pre-compute the key buckets ----
    # Cash on hand = the accounts Xero groups under the 'Bank' sub-heading. The
    # 'Total Bank' line is excluded at parse time because Xero often exports it as 0,
    # so we sum the child accounts directly. Fall back to keyword matching only when
    # the sub-section wasn't captured (older exports / unusual layouts).
    bank_rows = pd.DataFrame()
    if "subsection" in snapshot.columns:
        bank_rows = snapshot[snapshot["subsection"].astype(str).str.lower() == "bank"]
    if bank_rows.empty:
        bank_rows = _all_rows_matching(snapshot[snapshot["section"] == "Assets"], _BANK_KEYWORDS)
    cc_rows = _all_rows_matching(snapshot, _CC_KEYWORDS)
    # Exclude credit-card rows from the bank list
    bank_only = bank_rows[~bank_rows["account"].str.lower().str.contains("credit card", na=False)]
    undeposited_rows = _all_rows_matching(snapshot, _UNDEPOSITED_KEYWORDS)
    inventory_rows = _all_rows_matching(snapshot, _INVENTORY_KEYWORDS)
    loan_rows = _all_rows_matching(snapshot[snapshot["section"] == "Liabilities"], _LOAN_KEYWORDS)
    gst_rows = _all_rows_matching(snapshot[snapshot["section"] == "Liabilities"], _GST_KEYWORDS)
    payg_rows = _all_rows_matching(snapshot[snapshot["section"] == "Liabilities"], _PAYG_KEYWORDS)
    super_rows = _all_rows_matching(snapshot[snapshot["section"] == "Liabilities"], _SUPER_KEYWORDS)
    owner_rows = _all_rows_matching(snapshot, _OWNER_KEYWORDS)
    cy_earn_rows = _all_rows_matching(snapshot[snapshot["section"] == "Equity"], ["current year earnings"])
    retained_rows = _all_rows_matching(snapshot[snapshot["section"] == "Equity"], ["retained"])

    cash = _sum_or_none(bank_only) or 0
    cc = _sum_or_none(cc_rows) or 0  # may be negative or positive
    net_cash = cash - abs(cc)
    undeposited = _sum_or_none(undeposited_rows) or 0
    total_liquid = net_cash + undeposited
    inventory = _sum_or_none(inventory_rows) or 0
    shopify_loan = _sum_or_none(loan_rows) or 0

    gst_raw = _sum_or_none(gst_rows) or 0
    payg_raw = _sum_or_none(payg_rows) or 0
    super_raw = _sum_or_none(super_rows) or 0
    # Xero convention: liability accounts hold POSITIVE balances when owed; NEGATIVE = refund pending.
    gst_owed = gst_raw
    payg_owed = payg_raw
    super_owed = super_raw
    tax_payroll_total = max(gst_owed, 0) + max(payg_owed, 0) + max(super_owed, 0)

    cy_earn = _sum_or_none(cy_earn_rows) or 0
    retained = _sum_or_none(retained_rows) or 0
    owner_funds = _sum_or_none(owner_rows) or 0

    # ---- Key Metrics ----
    tree.rows.append(make_row([section_cell("fp.km.h", "KEY METRICS"), text_cell("fp.km.h.v", "")], is_section=True))

    def line(name: str, value: float | None, tooltip: Tooltip, *, indent: int = 1, bold: bool = False, is_total: bool = False):
        tree.rows.append(make_row([
            text_cell(f"fp.km.{name}.lbl", name, indent=indent, bold=bold),
            money_cell(f"fp.km.{name}.v", value, tooltip=tooltip, is_total=is_total),
        ]))

    # Cash by currency under "Cash in bank accounts" header
    line("Cash in bank accounts (all currencies)", cash, Tooltip(
        formula="Sum of all Bank accounts (excluding credit card).",
        sources=[src], confidence_note="Snapshot as at the BS date.",
    ), bold=True)
    if not bank_only.empty and len(bank_only) > 1:
        for _, r in bank_only.iterrows():
            line(f"  • {r['account']}", float(r["value"]), Tooltip(
                formula=f"Xero Bank row '{r['account']}' as at {r['as_at']}.",
                sources=[src],
            ), indent=2)
    if not cc_rows.empty:
        for _, r in cc_rows.iterrows():
            line(f"Less: {r['account']}", -abs(float(r["value"])), Tooltip(
                formula="Credit card balance (shown as negative — reduces net cash).",
                sources=[src],
            ))
    line("Net Cash", net_cash, Tooltip(
        formula="Bank − abs(Credit card)",
        inputs=[("Bank", cash), ("Credit card", abs(cc))],
        result_expr=f"{cash:,.2f} − {abs(cc):,.2f} = {net_cash:,.2f}",
        sources=[src],
    ), bold=True, is_total=True)
    if undeposited:
        line("Undeposited Funds (collected, not banked)", undeposited, Tooltip(
            formula="Sum of Undeposited Funds accounts.",
            sources=[src], confidence_note="Includes Shopify payouts in transit, Stripe pending, etc.",
        ))
        line("Total Liquid Position", total_liquid, Tooltip(
            formula="Net Cash + Undeposited Funds",
            inputs=[("Net Cash", net_cash), ("Undeposited", undeposited)],
            result_expr=f"{net_cash:,.2f} + {undeposited:,.2f} = {total_liquid:,.2f}",
            sources=[src],
        ), bold=True, is_total=True)

    if inventory:
        line("Stock / Inventory on hand", inventory, Tooltip(
            formula="Sum of Inventory / Stock balance sheet accounts.",
            sources=[src], confidence_note="If stock take is overdue this may understate true value.",
        ))
    if shopify_loan:
        line("Shopify Loan / Intercompany loan outstanding", abs(shopify_loan), Tooltip(
            formula="Sum of loan-type liability accounts.",
            sources=[src],
        ))

    # Tax stack
    if gst_owed or payg_owed or super_owed:
        if gst_owed > 0:
            line("GST Payable", gst_owed, Tooltip(
                formula="Positive Xero GST liability = owed to ATO.",
                sources=[src],
            ))
        elif gst_owed < 0:
            line("GST Refund Pending", abs(gst_owed), Tooltip(
                formula="Negative Xero GST liability = refund expected from ATO.",
                sources=[src], confidence_note="A refund-pending balance is an asset effectively, not a payable.",
            ))
        if payg_owed:
            line("PAYG Payable", payg_owed, Tooltip(
                formula="Xero PAYG liability.", sources=[src],
            ))
        if super_owed:
            line("Super Payable", super_owed, Tooltip(
                formula="Xero Superannuation liability.", sources=[src],
            ))
        if tax_payroll_total > 0:
            line("Total Tax/Payroll Owed", tax_payroll_total, Tooltip(
                formula="GST + PAYG + Super (only the owed sides).",
                sources=[src], confidence_note="Cash should be reserved before these fall due.",
            ), bold=True, is_total=True)

    if cy_earn:
        line("Current Year Earnings", cy_earn, Tooltip(
            formula="Xero YTD P&L position.",
            sources=[src], confidence_note="Negative = YTD loss.",
        ))
    if retained:
        line("Retained Earnings", retained, Tooltip(
            formula="Accumulated earnings from prior years.", sources=[src],
        ))
    if owner_funds:
        line("Owner Drawings / Funds Introduced", owner_funds, Tooltip(
            formula="Sum of Owner Drawings / Funds Introduced accounts.",
            sources=[src], confidence_note="Positive = owner has put money in; negative = owner has drawn.",
        ))

    # ---- Mentor Flags ----
    tree.rows.append(make_row([section_cell("fp.flags.h", "MENTOR FLAGS"), text_cell("fp.flags.h.v", "")], is_section=True))

    avg_monthly_opex = None
    if not d.monthly_expenses.empty and d.posted_months:
        non_cogs = d.monthly_expenses[~d.monthly_expenses["account_lower"].str.contains("cost of")]
        per_month = non_cogs.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
        non_zero = per_month[per_month > 0]
        if not non_zero.empty:
            avg_monthly_opex = float(non_zero.mean())

    monthly_revenue_avg = None
    if not d.monthly_revenue.empty:
        non_zero = d.monthly_revenue[d.monthly_revenue["revenue"] > 0]
        if not non_zero.empty:
            monthly_revenue_avg = float(non_zero["revenue"].mean())

    flags: list[tuple[str, str, str]] = []  # (severity, headline, narrative)

    # Cash runway
    if avg_monthly_opex and avg_monthly_opex > 0:
        runway = total_liquid / avg_monthly_opex if total_liquid else 0
        sev = "warning" if runway < 2 else "info"
        flags.append((sev,
            "Cash runway",
            f"At posted-OPEX run-rate ({avg_monthly_opex:,.0f}/mo), liquid position covers ~{runway:.1f} months."))

    # YTD loss / profit
    if cy_earn:
        if cy_earn < 0:
            flags.append(("warning",
                "YTD result negative",
                f"Current Year Earnings = {cy_earn:,.0f}. Reviewing OPEX vs revenue is the central conversation."))
        else:
            flags.append(("info",
                "YTD result positive",
                f"Current Year Earnings = {cy_earn:,.0f}."))

    # Inventory days of cover — only meaningful for a positive stock balance.
    if inventory < 0:
        flags.append(("warning",
            "Negative inventory balance",
            f"Inventory on the balance sheet is {inventory:,.0f} — a negative stock asset. This usually means COGS "
            f"recognition has outrun recorded purchases or a stock-take is overdue. Days-of-cover can't be computed "
            f"until the balance is corrected."))
    elif inventory and monthly_revenue_avg and monthly_revenue_avg > 0:
        cogs_pct = 0.30
        if not d.monthly_revenue_components.empty and "cogs_aud" in d.monthly_revenue_components.columns and "net_aud" in d.monthly_revenue_components.columns:
            tot_cogs = float(d.monthly_revenue_components["cogs_aud"].sum())
            tot_rev = float(d.monthly_revenue_components["net_aud"].sum())
            if tot_rev > 0:
                cogs_pct = tot_cogs / tot_rev
        daily_cogs = (monthly_revenue_avg * cogs_pct) / 30
        if daily_cogs > 0:
            days = inventory / daily_cogs
            flags.append(("info",
                "Inventory efficiency",
                f"{inventory:,.0f} stock on hand ≈ {days:.0f} days of cover at {cogs_pct*100:.0f}% COGS on average monthly revenue {monthly_revenue_avg:,.0f}."))

    # Tax stack
    if tax_payroll_total > 0:
        flags.append(("info",
            "Tax stack",
            f"{tax_payroll_total:,.0f} GST+PAYG+Super owed at snapshot. Ensure cash reserved before these fall due."))

    # Refundable GST
    if gst_owed < 0:
        flags.append(("info",
            "GST refund pending",
            f"GST balance is {gst_raw:,.0f} (refund expected from ATO of {abs(gst_owed):,.0f}). Verify pending refund is on track."))

    # Owner drawings
    if owner_funds and owner_funds < -5000:
        flags.append(("warning",
            "Owner drawings",
            f"Owner drawings YTD = {owner_funds:,.0f}. Worth a salary-vs-drawings conversation."))
    elif owner_funds and owner_funds > 0:
        flags.append(("info",
            "Owner funds introduced",
            f"Owner has injected {owner_funds:,.0f} YTD — flag for owner/group conversation."))

    # Intercompany loan
    intercompany = _sum_or_none(_all_rows_matching(snapshot, ["intercompany"]))
    if intercompany and abs(intercompany) > 5000:
        flags.append(("info",
            "Intercompany loan",
            f"Intercompany loan balance = {intercompany:,.0f}. Tied to NZ entity activity — review on group P&L."))

    for sev, headline, narrative in flags:
        icon = "⚠ " if sev == "warning" else "• "
        tree.rows.append(make_row([
            text_cell(f"fp.flag.{headline}.lbl", icon + headline, indent=1, bold=True),
            text_cell(f"fp.flag.{headline}.v", narrative),
        ]))

    if not flags:
        tree.rows.append(make_row([
            text_cell("fp.flags.none", "No flags raised — snapshot looks routine.", indent=1),
            text_cell("fp.flags.none.v", ""),
        ]))

    # ---- Full Balance Sheet detail ----
    tree.rows.append(make_row([section_cell("fp.full.h", "FULL BALANCE SHEET DETAIL"),
                                text_cell("fp.full.h.v", "")], is_section=True))

    section_order = ["Assets", "Liabilities", "Equity"]
    for section in section_order:
        sub = snapshot[snapshot["section"] == section]
        if sub.empty:
            continue
        tree.rows.append(make_row([
            text_cell(f"fp.full.sec.{section}", section, bold=True),
            text_cell(f"fp.full.sec.{section}.v", ""),
        ]))
        section_total = 0.0
        for _, r in sub.sort_values("account").iterrows():
            val = float(r["value"]) if r["value"] is not None else None
            section_total += (val or 0)
            tree.rows.append(make_row([
                text_cell(f"fp.full.{section}.{r['account']}.lbl", r["account"], indent=1),
                money_cell(f"fp.full.{section}.{r['account']}.v", val,
                           tooltip=Tooltip(formula=f"Xero balance for `{r['account']}` as at {r['as_at']}.",
                                           sources=[src])),
            ]))
        tree.rows.append(make_row([
            text_cell(f"fp.full.{section}.total.lbl", f"Total {section}", bold=True),
            money_cell(f"fp.full.{section}.total.v", section_total, is_total=True, tooltip=Tooltip(
                formula=f"Sum of {section} balances.", sources=[src],
            )),
        ], is_total=True))

    tree.notes = [
        "Liability accounts in Xero hold positive balances when owed. A negative GST liability indicates a refund pending (treated as effectively an asset).",
        "Mentor flags compare snapshot values against derived run-rates (avg posted OPEX, avg monthly revenue, COGS%).",
    ]

    return tree
