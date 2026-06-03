"""Core dataclasses shared across ingest, transform, compute, render, audit."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


Confidence = Literal["reconciled", "provisional", "mentor_input", "missing", "derived"]
CellFormat = Literal[
    "currency",
    "currency_dec",
    "pct",
    "int",
    "text",
    "date",
    "ratio",
]


@dataclass
class Tooltip:
    formula: str = ""
    inputs: list[tuple[str, Any]] = field(default_factory=list)
    result_expr: str = ""
    sources: list[str] = field(default_factory=list)
    gotcha_refs: list[str] = field(default_factory=list)
    confidence_note: str = ""
    fx_note: str | None = None

    def to_text(self) -> str:
        """Plain-text rendering for xlsx cell comments."""
        lines = []
        if self.formula:
            lines.append(self.formula)
        if self.inputs:
            for label, value in self.inputs:
                lines.append(f"  • {label}: {value}")
        if self.result_expr:
            lines.append(f"= {self.result_expr}")
        if self.fx_note:
            lines.append(f"FX: {self.fx_note}")
        if self.sources:
            lines.append("Sources: " + ", ".join(self.sources))
        if self.gotcha_refs:
            lines.append("Refs: " + " · ".join(self.gotcha_refs))
        if self.confidence_note:
            lines.append(self.confidence_note)
        return "\n".join(lines)


@dataclass
class Cell:
    coord: str
    label: str | None = None
    value: float | int | str | None = None
    fmt: CellFormat = "text"
    confidence: Confidence = "provisional"
    tooltip: Tooltip | None = None
    # Optional styling hints
    bold: bool = False
    indent: int = 0
    section_header: bool = False
    is_total: bool = False
    is_missing: bool = False  # render as "—"
    # Mentor-editable inputs (Final Report Card ops benchmarks): the value cell becomes an
    # <input> in the HTML and its sibling status cell flips ✓/✗ against the target live.
    editable: bool = False
    target_value: float | None = None  # numeric benchmark for live comparison
    target_max: bool = False           # True = actual should be ≤ target (ceiling); False = ≥ (floor)
    unit: str = ""                     # display suffix on the input (e.g. "days", "/mo")
    mentor_status_key: str | None = None  # on a status cell: the coord of the input it mirrors


@dataclass
class Row:
    cells: list[Cell] = field(default_factory=list)
    is_section: bool = False
    is_total: bool = False
    expandable_key: str | None = None  # for HTML accordion / vendor sub-rows


@dataclass
class Banner:
    """Top-of-tab disclosure banner."""
    severity: Literal["info", "warning", "error"]
    text: str


@dataclass
class RenderTree:
    """The compute output for a single tab. Renderers consume this."""
    tab_id: str
    title: str
    subtitle: str = ""
    banners: list[Banner] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Optional pre-rendered HTML chunk (used by static/legend tabs)
    raw_html: str | None = None
    # For tabs that have multiple sub-views (Daily Tracker month filter)
    sub_views: dict[str, list[Row]] = field(default_factory=dict)


# ---------- Ingest dataclasses ----------


@dataclass
class CurrencyTag:
    code: str  # "AUD" / "NZD" / "USD"
    confidence: Literal["explicit", "assumed"]
    source: str  # description of where we learned this


@dataclass
class IngestMeta:
    inputs_dir: str
    run_date: date
    client_name: str
    reporting_currency: str = "AUD"
    shopify_currency: CurrencyTag | None = None
    ad_platform_currency: dict[str, CurrencyTag] = field(default_factory=dict)
    files_found: dict[str, str] = field(default_factory=dict)  # role → file path
    files_missing: list[str] = field(default_factory=list)
    lookback_start: date | None = None
    lookback_end: date | None = None


@dataclass
class IngestBundle:
    meta: IngestMeta
    # Raw frames keyed by role; values are pandas.DataFrame (typed Any to avoid hard pandas dependency at type-check time)
    shopify_daily: Any | None = None
    nc_rc: Any | None = None
    sessions: Any | None = None
    xero_pl: Any | None = None         # long-form: account, month, value, section, bucket
    xero_bs: Any | None = None         # long-form: account, as_at, value, section
    xero_atxn: Any | None = None       # long-form: date, account, contact, debit, credit, source, description
    ad_spend: dict[str, Any] = field(default_factory=dict)  # platform → DataFrame (day, campaign, amount_aud, amount_orig, ccy, fx_rate)
    cohort: Any | None = None          # optional Shopify Cohort CSV


# ---------- Audit dataclasses ----------


@dataclass
class AuditResult:
    check_id: str
    name: str
    status: Literal["PASS", "FAIL", "SKIP", "HALT"]
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    run_id: str
    timestamp: datetime
    results: list[AuditResult] = field(default_factory=list)

    @property
    def has_halts(self) -> bool:
        return any(r.status == "HALT" for r in self.results)
