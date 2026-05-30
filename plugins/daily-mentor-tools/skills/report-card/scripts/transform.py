"""Normalisation pass: FX conversion, G35 Credit−Debit netting, monthly rollups,
chart-of-accounts bucketing, period-window derivation. Idempotent.

Consumers (compute/*.py) read from the transformed bundle.meta.* and the
extra attributes attached here (e.g. monthly_revenue, monthly_expenses,
vendor_breakdown, daily_ad_spend_aud).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from .fx import FxFetchError, FxResolver
from .models import IngestBundle


_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_coa() -> dict:
    with (_DATA_DIR / "chart_of_accounts.json").open() as f:
        return json.load(f)


def _bucket_account(account_lower: str, coa: dict) -> dict:
    """Return bucket descriptor for an account name (case-insensitive)."""
    if account_lower in coa.get("exact", {}):
        return coa["exact"][account_lower]
    for needle, descriptor in coa.get("contains", {}).items():
        if needle in account_lower:
            return descriptor
    return coa.get("default", {"bucket": "other", "section": "Operating Expenses", "sort": 900, "is_revenue": False})


def _month_first(d: date) -> date:
    return date(d.year, d.month, 1)


def _derive_pl_from_atxn(atxn: pd.DataFrame, coa: dict) -> pd.DataFrame:
    """Reconstruct a long-form P&L (account, account_lower, section, month, value)
    from raw Account Transactions. Uses Credit−Debit netting per (account, month)
    and applies the chart-of-accounts bucketing to assign section/is_revenue/etc.

    Excludes balance-sheet accounts (Inventory, GST liability, Intercompany Loan,
    Bank, Wise, On Call Savings, Retained Earnings) that don't belong in a P&L.
    """
    if atxn is None or atxn.empty:
        return pd.DataFrame(columns=["account", "account_lower", "section", "month", "value"])

    # Skip balance-sheet / equity-side accounts when building P&L from transactions
    bs_skip = {
        "inventory", "intercompany loan", "retained earnings", "current year earnings",
        "wise", "on call savings account", "business account", "business current account",
        "bank", "credit card", "accounts payable", "accounts receivable", "gst",
        "owner a funds introduced", "owner drawings", "net assets",
    }

    a = atxn.copy()
    a["month"] = a["date"].apply(_month_first)
    a["account_lower"] = a["account"].str.lower().str.strip()
    # Drop balance-sheet accounts
    keep_mask = ~a["account_lower"].apply(lambda al: any(skip in al for skip in bs_skip))
    a = a[keep_mask]
    if a.empty:
        return pd.DataFrame(columns=["account", "account_lower", "section", "month", "value"])

    # Net per (account, month). For Revenue accounts: net = Credit − Debit (positive = revenue).
    # For expense accounts: net = Debit − Credit (positive = expense).
    # Easier: aggregate both sides, and let the bucket logic choose later.
    agg = a.groupby(["account", "account_lower", "month"], as_index=False).agg(
        credit=("credit", "sum"),
        debit=("debit", "sum"),
    )
    descriptors = agg["account_lower"].map(lambda al: _bucket_account(al, coa))
    is_rev = descriptors.map(lambda d: d["is_revenue"])
    # Revenue value = Credit − Debit; expense value = Debit − Credit.
    agg["value"] = (
        is_rev.astype(int) * (agg["credit"] - agg["debit"])
        + (1 - is_rev.astype(int)) * (agg["debit"] - agg["credit"])
    )
    agg["section"] = descriptors.map(lambda d: d["section"])
    return agg[["account", "account_lower", "section", "month", "value"]]


def transform(bundle: IngestBundle) -> IngestBundle:
    """Mutates bundle in place — adds .derived namespace with normalised frames."""
    reporting = (bundle.meta.reporting_currency or "AUD").upper()
    fx = FxResolver(reporting_currency=reporting)
    coa = _load_coa()

    derived = SimpleNamespace(
        fx=fx,
        coa=coa,
        monthly_revenue=pd.DataFrame(),
        monthly_revenue_components=pd.DataFrame(),
        monthly_expenses=pd.DataFrame(),
        vendor_breakdown=pd.DataFrame(),
        daily_ad_spend=pd.DataFrame(),
        monthly_ad_spend=pd.DataFrame(),
        balance_sheet_snapshot=pd.DataFrame(),
        snapshot_as_at=None,
        posted_months=[],
        latest_full_quarter=None,
        snapshot_window=None,
        pl_source="xero_pl_file",  # or "atxn_derived"
        fx_unavailable=set(),  # currencies we couldn't fetch a rate for
    )

    def _safe_convert(value: float, on, from_ccy: str) -> tuple[float, float]:
        """FX convert with graceful fallback — if the rate can't be fetched (network
        down, unknown currency), fall back to 1.0 and record the currency so the
        audit/banners can flag it. A deployable skill must not hard-crash on FX."""
        if from_ccy == reporting:
            return value, 1.0
        try:
            return fx.convert(value, on, from_ccy, reporting)
        except FxFetchError:
            derived.fx_unavailable.add(from_ccy)
            return value, 1.0

    # ---- Ad spend: convert each daily row to reporting ccy ----
    ad_frames = []
    for platform, df in bundle.ad_spend.items():
        if df is None or df.empty:
            continue
        df = df.copy()
        ccy = bundle.meta.ad_platform_currency.get(platform).code if bundle.meta.ad_platform_currency.get(platform) else reporting
        rates, amount_conv = [], []
        for _, row in df.iterrows():
            val_conv, r = _safe_convert(float(row["amount_orig"]), row["day"], ccy)
            amount_conv.append(val_conv)
            rates.append(r)
        df["fx_rate"] = rates
        df["amount"] = amount_conv
        df["platform"] = platform
        ad_frames.append(df)
    if ad_frames:
        derived.daily_ad_spend = pd.concat(ad_frames, ignore_index=True).sort_values("day").reset_index(drop=True)
        d = derived.daily_ad_spend.copy()
        d["month"] = d["day"].apply(_month_first)
        derived.monthly_ad_spend = (
            d.groupby(["month", "platform"], as_index=False)["amount"]
            .sum()
            .sort_values(["month", "platform"])
            .reset_index(drop=True)
        )

    # ---- Shopify daily → monthly revenue (G39): Net Sales × FX ----
    if bundle.shopify_daily is not None and not bundle.shopify_daily.empty:
        sd = bundle.shopify_daily.copy()
        shop_ccy = bundle.meta.shopify_currency.code if bundle.meta.shopify_currency else reporting
        if shop_ccy != reporting:
            rates = sd["day"].apply(lambda d: _safe_convert(1.0, d, shop_ccy)[1])
            for col in ("gross", "discounts", "returns", "net", "shipping", "taxes", "total", "cogs"):
                if col in sd.columns:
                    sd[f"{col}_aud"] = sd[col] * rates
            sd["fx_rate"] = rates
        else:
            for col in ("gross", "discounts", "returns", "net", "shipping", "taxes", "total", "cogs"):
                if col in sd.columns:
                    sd[f"{col}_aud"] = sd[col]
            sd["fx_rate"] = 1.0
        bundle.shopify_daily = sd
        sd_m = sd.copy()
        sd_m["month"] = sd_m["day"].apply(_month_first)
        agg = {f"{c}_aud": "sum" for c in ("gross", "discounts", "returns", "net", "shipping", "taxes", "total", "cogs") if f"{c}_aud" in sd_m.columns}
        agg.update({"orders": "sum", "units": "sum"} if "units" in sd_m.columns else {"orders": "sum"})
        derived.monthly_revenue_components = (
            sd_m.groupby("month", as_index=False).agg(agg).sort_values("month").reset_index(drop=True)
        )
        if "net_aud" in derived.monthly_revenue_components.columns:
            derived.monthly_revenue = derived.monthly_revenue_components[["month", "net_aud"]].rename(columns={"net_aud": "revenue"})

    # ---- Xero P&L: bucket each row + identify posted months ----
    if bundle.xero_pl is not None and not bundle.xero_pl.empty:
        pl = bundle.xero_pl.copy()
        descriptors = pl["account_lower"].map(lambda al: _bucket_account(al, coa))
        pl["bucket"] = descriptors.map(lambda d: d["bucket"])
        pl["bucket_section"] = descriptors.map(lambda d: d["section"])
        pl["is_revenue"] = descriptors.map(lambda d: d["is_revenue"])
        pl["is_other_income"] = descriptors.map(lambda d: d.get("is_other_income", False))
        pl["sort"] = descriptors.map(lambda d: d["sort"])
        bundle.xero_pl = pl
        derived.monthly_expenses = pl[~pl["is_revenue"]].copy()
        if not derived.monthly_expenses.empty:
            month_totals = derived.monthly_expenses.groupby("month")["value"].apply(lambda s: float(s.abs().sum()))
            posted = sorted([m for m, v in month_totals.items() if v > 0])
            derived.posted_months = posted

    # ---- Fallback: derive P&L from Atxn when the file-based P&L is thin ----
    # If the Atxn covers materially more months than the loaded P&L, use Atxn as
    # the source of truth for expense rows. Happens when the input pack has the
    # NZ entity's Atxn but only the AU entity's (mostly empty) P&L.
    if bundle.xero_atxn is not None and not bundle.xero_atxn.empty:
        atxn_pl = _derive_pl_from_atxn(bundle.xero_atxn, coa)
        if not atxn_pl.empty:
            atxn_posted = sorted(set(atxn_pl[atxn_pl["value"].abs() > 0]["month"].tolist()))
            current_posted_ct = len(derived.posted_months)
            if len(atxn_posted) >= max(current_posted_ct + 2, 6):
                # Atxn is much richer — swap it in
                descriptors = atxn_pl["account_lower"].map(lambda al: _bucket_account(al, coa))
                atxn_pl["bucket"] = descriptors.map(lambda d: d["bucket"])
                atxn_pl["bucket_section"] = descriptors.map(lambda d: d["section"])
                atxn_pl["is_revenue"] = descriptors.map(lambda d: d["is_revenue"])
                atxn_pl["is_other_income"] = descriptors.map(lambda d: d.get("is_other_income", False))
                atxn_pl["sort"] = descriptors.map(lambda d: d["sort"])
                bundle.xero_pl = atxn_pl
                derived.monthly_expenses = atxn_pl[~atxn_pl["is_revenue"]].copy()
                derived.posted_months = atxn_posted
                derived.pl_source = "atxn_derived"

    # ---- G35: Credit − Debit netting on Account Transactions ----
    if bundle.xero_atxn is not None and not bundle.xero_atxn.empty:
        a = bundle.xero_atxn.copy()
        a["month"] = a["date"].apply(_month_first)
        # G35: net = Credit − Debit per (account, contact, month).
        # In Xero exports, for bank-account-mode transactions, Credit = outflow (expense),
        # Debit = inflow (refund). Net positive = net spend by that contact.
        net = (
            a.groupby(["account", "contact", "month"], as_index=False)
            .agg(credit=("credit", "sum"), debit=("debit", "sum"), n=("date", "count"))
        )
        net["net"] = net["credit"] - net["debit"]
        net = net[net["net"] != 0].sort_values(["account", "month", "net"], ascending=[True, True, False]).reset_index(drop=True)
        derived.vendor_breakdown = net

    # ---- Balance Sheet snapshot (most recent as-at) ----
    if bundle.xero_bs is not None and not bundle.xero_bs.empty:
        bs = bundle.xero_bs.copy()
        derived.snapshot_as_at = bs["as_at"].max()
        derived.balance_sheet_snapshot = bs[bs["as_at"] == derived.snapshot_as_at].copy()

    # ---- Snapshot windows ----
    if bundle.meta.lookback_end:
        end = bundle.meta.lookback_end
        # 90-day window for Homepage; clamp to available data
        start = end - pd.Timedelta(days=89)
        derived.snapshot_window = (start.date() if hasattr(start, "date") else start, end)

    bundle.derived = derived  # attach
    return bundle
