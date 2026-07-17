"""Pre-flight checklist — scan inputs dir, return what's present / missing.

The skill calls this BEFORE the build. If anything required is missing,
the skill prompts the user to upload the file, then re-runs preflight.

Output is plain JSON-serialisable for easy consumption by the skill agent.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


Status = Literal["present", "missing", "optional_missing"]


@dataclass
class FileRequirement:
    role: str
    label: str
    required: bool
    description: str
    source_system: str
    export_path_hint: str
    accepted_patterns: list[str]  # Substrings that should appear in the filename (lowercase)
    accepted_extensions: list[str]
    found: bool = False
    matched_path: str | None = None
    matched_size_bytes: int | None = None


@dataclass
class PreflightReport:
    inputs_dir: str
    inputs_dir_exists: bool
    files_scanned: int
    requirements: list[FileRequirement] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)  # Files in the dir that don't map to any requirement

    # Ad-platform roles form an "at least one of" group rather than each being required.
    _AD_ROLES = ("ad_spend_meta", "ad_spend_google", "ad_spend_tiktok")

    @property
    def missing_required(self) -> list[FileRequirement]:
        return [r for r in self.requirements if r.required and not r.found]

    @property
    def missing_optional(self) -> list[FileRequirement]:
        return [r for r in self.requirements
                if not r.required and not r.found and r.role not in self._AD_ROLES]

    @property
    def ad_platform_present(self) -> bool:
        return any(r.found for r in self.requirements if r.role in self._AD_ROLES)

    @property
    def is_ready(self) -> bool:
        return self.inputs_dir_exists and not self.missing_required and self.ad_platform_present

    def to_dict(self) -> dict:
        return {
            "inputs_dir": self.inputs_dir,
            "inputs_dir_exists": self.inputs_dir_exists,
            "files_scanned": self.files_scanned,
            "is_ready": self.is_ready,
            "ad_platform_present": self.ad_platform_present,
            "summary": {
                "present": sum(1 for r in self.requirements if r.found),
                "missing_required": len(self.missing_required),
                "missing_optional": len(self.missing_optional),
                "ad_platform_present": self.ad_platform_present,
            },
            "requirements": [asdict(r) for r in self.requirements],
            "extras": self.extras,
        }


def _spec() -> list[FileRequirement]:
    """The canonical input pack specification. Brand-neutral."""
    return [
        FileRequirement(
            role="shopify_daily",
            label="Total Sales Over Time (daily, last 365 days)",
            required=True,
            description="Daily orders / gross sales / discounts / returns / tax / COGS for the 12-month lookback. Source of truth for monthly revenue and quarterly order counts.",
            source_system="Shopify Admin",
            export_path_hint="Analytics → Reports → Total Sales Over Time → time period = Last 365 Days → remove comparison → export CSV → save as 'Daily Mentor - Total Sales Over Time'.",
            accepted_patterns=["total sales over time", "shopify_daily", "total_sales"],
            accepted_extensions=[".csv"],
        ),
        FileRequirement(
            role="nc_rc",
            label="NC vs RC, last 365 days (per quarter)",
            required=True,
            description="New vs returning split of gross sales, discounts, returns, shipping, tax, orders, AOV and COGS — broken out by quarter for the quarter-over-quarter NCCM.",
            source_system="Shopify Admin",
            export_path_hint=("Analytics → custom report → New exploration → time period = Last 365 Days → "
                              "Sidekick prompt: 'New exploration report for L365 days, New Customers vs Returning "
                              "Customers, grouped by quarter, include gross sales, discounts, returns, shipping, tax, "
                              "orders, average order value and COGS' → export CSV → save as 'Daily Mentor - NC v RC L365'."),
            accepted_patterns=["nc v rc", "nc vs rc", "new or returning", "new vs returning"],
            accepted_extensions=[".csv"],
        ),
        FileRequirement(
            role="sessions",
            label="Sessions by Month",
            required=True,
            description="Online store visitors, sessions, conversion rate per month for the last 13 months.",
            source_system="Shopify Admin",
            export_path_hint="Analytics → Reports → Sessions → group by month → export CSV → save as 'Sessions by month'.",
            accepted_patterns=["sessions by month", "sessions_by_month", "sessions"],
            accepted_extensions=[".csv"],
        ),
        FileRequirement(
            role="xero_bs",
            label="Xero Balance Sheet (12-month columns)",
            required=True,
            description="Balance sheet snapshot for the As-At date plus prior months for trend.",
            source_system="Xero",
            export_path_hint=("Reports → Balance Sheet → time period = This Month → Compare with → "
                              "'Enter a Different Number' = 12 → Update → export Excel → save as 'Daily Mentor - Balance Sheet'."),
            accepted_patterns=["balance_sheet", "balance sheet"],
            accepted_extensions=[".xlsx"],
        ),
        FileRequirement(
            role="xero_atxn",
            label="Xero Account Transactions (last 365 days, all accounts)",
            required=True,
            description="Every transaction by account for the 12-month lookback. Sole source for expense rows, COGS reconstruction, and vendor sub-rows (Credit−Debit netted).",
            source_system="Xero",
            export_path_hint=("Reports → Account Transactions → Accounts = Select All → time period = Custom, Last 365 Days → "
                              "columns = Date, Contact, Description, Debit (AUD), Credit (AUD) → Update → export Excel → "
                              "save as 'Daily Mentor - Account Transactions'."),
            accepted_patterns=["account_transactions", "account transactions"],
            accepted_extensions=[".xlsx"],
        ),
        FileRequirement(
            role="xero_pl",
            label="Xero Profit & Loss (optional — Account Transactions is the primary source)",
            required=False,
            description="Not needed when the full Account Transactions export is supplied — the P&L is reconstructed from transactions. If a clean bookkeeper-categorised P&L is provided, it takes precedence over the reconstruction.",
            source_system="Xero",
            export_path_hint="Reports → Profit & Loss → date range = 'Last 12 months', columns = 'Months' → export XLSX.",
            accepted_patterns=["profit_and_loss", "profit and loss"],
            accepted_extensions=[".xlsx"],
        ),
        FileRequirement(
            role="ad_spend_meta",
            label="Meta (Facebook) Ad Spend (12 months) — at least one ad platform required",
            required=False,
            description="Daily spend per campaign for the 12-month lookback. Currency must appear in the column header (e.g. `Amount spent (AUD)`). At minimum one of Meta / Google / TikTok is required.",
            source_system="Meta Ads Manager",
            export_path_hint="Ads Manager → Reports → Customise → columns = Day, Campaign name, Amount spent → date range last 12 months → export CSV.",
            accepted_patterns=["facebook_spend", "facebook spend", "meta_spend", "meta spend"],
            accepted_extensions=[".csv", ".xlsx"],
        ),
        FileRequirement(
            role="ad_spend_google",
            label="Google Ads Spend (optional)",
            required=False,
            description="Daily spend if Google Ads is in the marketing mix. Same format as Meta export — Day, Campaign, Amount spent (CCY).",
            source_system="Google Ads",
            export_path_hint="Google Ads → Reports → Predefined reports → Time → Day → export CSV.",
            accepted_patterns=["google_spend", "google spend", "google_ads"],
            accepted_extensions=[".csv", ".xlsx"],
        ),
        FileRequirement(
            role="ad_spend_tiktok",
            label="TikTok Ads Spend (optional)",
            required=False,
            description="Daily spend if TikTok Ads is in the marketing mix.",
            source_system="TikTok Ads Manager",
            export_path_hint="TikTok Ads → Reports → custom report → daily breakdown → export CSV.",
            accepted_patterns=["tiktok_spend", "tiktok spend"],
            accepted_extensions=[".csv", ".xlsx"],
        ),
        FileRequirement(
            role="cohort",
            label="Shopify Cohort Analysis",
            required=True,
            description="Customer Value by cohort month. Drives the LTV tab (true cohort matrix) and Final Report Card M2/M5 growth rows.",
            source_system="Shopify Admin",
            export_path_hint="Analytics → Reports → Customers → 'Cohort Analysis' → 'Customer value by month, last 6 months' → export CSV.",
            accepted_patterns=["cohort"],
            accepted_extensions=[".csv"],
        ),
    ]


def _match(req: FileRequirement, name_lower: str, ext_lower: str) -> bool:
    if ext_lower not in req.accepted_extensions:
        return False
    return any(p in name_lower for p in req.accepted_patterns)


def preflight(inputs_dir: Path) -> PreflightReport:
    """Scan the inputs directory and return a structured checklist."""
    inputs_dir = Path(inputs_dir)
    report = PreflightReport(
        inputs_dir=str(inputs_dir),
        inputs_dir_exists=inputs_dir.exists() and inputs_dir.is_dir(),
        files_scanned=0,
        requirements=_spec(),
    )
    if not report.inputs_dir_exists:
        return report

    # Collect all files in the dir (non-recursive)
    files = sorted([p for p in inputs_dir.iterdir() if p.is_file() and not p.name.startswith(".")])
    report.files_scanned = len(files)

    matched_paths: set[str] = set()
    for req in report.requirements:
        # For roles where multiple files could match (e.g. multiple Atxn from two entities),
        # pick the largest file.
        candidates = [p for p in files if _match(req, p.name.lower(), p.suffix.lower())]
        if candidates:
            best = max(candidates, key=lambda p: p.stat().st_size)
            req.found = True
            req.matched_path = str(best)
            req.matched_size_bytes = best.stat().st_size
            matched_paths.add(str(best))

    report.extras = [p.name for p in files if str(p) not in matched_paths]
    return report


def render_text_summary(report: PreflightReport) -> str:
    """Human-readable summary for stdout / chat."""
    lines: list[str] = []
    lines.append(f"Inputs directory: {report.inputs_dir}")
    if not report.inputs_dir_exists:
        lines.append("  ✗ Directory does not exist.")
        return "\n".join(lines)
    lines.append(f"  Files scanned: {report.files_scanned}")
    lines.append("")
    lines.append("REQUIRED INPUTS")
    for r in report.requirements:
        if not r.required:
            continue
        if r.found:
            size_kb = (r.matched_size_bytes or 0) / 1024
            lines.append(f"  ✓ {r.label}")
            lines.append(f"      {Path(r.matched_path).name}  ({size_kb:,.0f} KB)")
        else:
            lines.append(f"  ✗ {r.label}  — MISSING")
            lines.append(f"      Source: {r.source_system}")
            lines.append(f"      How to export: {r.export_path_hint}")
    lines.append("")
    mark = "✓" if report.ad_platform_present else "✗"
    lines.append(f"AD SPEND ({mark} at least one platform required)")
    for r in report.requirements:
        if r.role not in PreflightReport._AD_ROLES:
            continue
        if r.found:
            size_kb = (r.matched_size_bytes or 0) / 1024
            lines.append(f"  ✓ {r.label.split(' —')[0]}")
            lines.append(f"      {Path(r.matched_path).name}  ({size_kb:,.0f} KB)")
        else:
            lines.append(f"  · {r.label.split(' —')[0].split(' (optional')[0]}  — not provided")
    if not report.ad_platform_present:
        lines.append("      Provide at least one: Meta, Google, or TikTok daily spend (12 months).")
    lines.append("")
    lines.append("OPTIONAL INPUTS")
    for r in report.requirements:
        if r.required or r.role in PreflightReport._AD_ROLES:
            continue
        if r.found:
            size_kb = (r.matched_size_bytes or 0) / 1024
            lines.append(f"  ✓ {r.label}")
            lines.append(f"      {Path(r.matched_path).name}  ({size_kb:,.0f} KB)")
        else:
            lines.append(f"  · {r.label}  — not provided")
            lines.append(f"      Source: {r.source_system}")
            lines.append(f"      How to export: {r.export_path_hint}")
    if report.extras:
        lines.append("")
        lines.append("EXTRA FILES IN DIR (not used)")
        for name in report.extras:
            lines.append(f"  – {name}")
    lines.append("")
    if report.is_ready:
        lines.append("READY TO BUILD ✓")
    else:
        problems = []
        n = len(report.missing_required)
        if n:
            problems.append(f"{n} required file{'s' if n != 1 else ''} missing")
        if not report.ad_platform_present:
            problems.append("no ad-platform spend file")
        lines.append("NOT READY — " + "; ".join(problems) + ".")
    return "\n".join(lines)


def emit_json(report: PreflightReport) -> str:
    return json.dumps(report.to_dict(), indent=2)
