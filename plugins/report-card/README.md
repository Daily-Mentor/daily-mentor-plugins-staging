# Report Card

Generate a 12-tab e-commerce diagnostic for any ecommerce founder from a standardised input pack (Shopify CSVs + Xero exports + ad-platform CSVs). Brand-neutral — works across businesses and reporting currencies.

Source-of-truth rules: Shopify is authoritative for monthly revenue (G39), Xero for expense accounts, Account Transactions netted Credit−Debit per (account, contact, month) for vendor breakdown (G35), no vendor sub-rows under revenue parents (G36).

## Outputs

- `report-card-{YYYY-MM-DD}.html` — founder-facing, dynamic, tooltips on every calculated cell explaining sources + formula + gotcha refs. Single self-contained file, Daily Mentor brand styling.
- `report-card-{YYYY-MM-DD}.xlsx` — mentor weekly-call use. 24 sheets (12 logical tabs, with the Daily Tracker expanded to one sheet per month). No cell comments — tooltips live in the HTML.

## Quick start

```bash
# from this plugin directory
python3 -m scripts.cli --preflight ./inputs          # 1. check what's present/missing
python3 -m scripts.cli ./inputs ./out                # 2. build (defaults to AUD)
python3 -m scripts.cli ./inputs ./out --reporting-currency GBP   # any reporting currency
```

Or via slash command (once installed):

```
/report-card ./inputs ./out
```

The skill runs the pre-flight checklist first and prompts for any missing required files before building.

## Architecture

```
scripts/
  cli.py          # entry — preflight gate, then orchestrates the pipeline
  preflight.py    # input-pack checklist (present / missing / optional)
  ingest.py       # file discovery + parsing (no business logic)
  transform.py    # runtime FX, G35 netting, Atxn-derived P&L, period windows
  fx.py           # on-demand FX (Frankfurter/ECB), fetched only when currencies differ
  compute/        # per-tab math; each emits a RenderTree
  render_html.py  # single self-contained HTML (f-strings + inlined CSS/JS)
  render_xlsx.py  # openpyxl, built fresh each run, comment-free
  audit.py        # 12 PASS/FAIL/SKIP assertions
  models.py       # Cell, Tooltip, RenderTree, IngestBundle dataclasses

templates/static/ # report.css (brand kit) + report.js (tabs, month filter)
data/             # benchmarks, mentor defaults, chart-of-accounts (no FX dictionary)
tests/            # pytest; synthetic-brand fixtures generated at runtime (no client data)
```

## Currency

FX is resolved **at runtime** — there is no baked-in rate dictionary. When a source currency (e.g. ad-platform spend) differs from the reporting currency, daily rates are fetched from Frankfurter (ECB reference rates) and cached to `.fx-cache/` for the run. If every source is already in the reporting currency, no network call is made. If the API is unreachable, the build degrades gracefully (conversion falls back to 1.0 and the audit flags it) rather than crashing.

## Tab inventory

1. Homepage / Benchmark Scorecard
2. Monthly P&L (8 sections, vendor sub-rows, 12-month total)
3. Financial Position
4. NCCM Calculator (quarter-over-quarter; needs the NC/RC export grouped by quarter)
5. LTV Analysis (degrades when Cohort CSV absent)
6. Final Report Card (Bleed/Fix + Ops benchmarks)
7. Brand Profit Simulator
8. Daily Tracker (1 tab in HTML with month filter; per-month sheets in xlsx)
9. Notes & Reconciliation
10. Audit Report
11. Change Log
12. Design Legend

## Dependencies

Python 3.11+, openpyxl, pandas. (FX uses the standard library; no `requests`/`jinja2`.)

```bash
pip install openpyxl pandas pytest
```

## Tests

```bash
python3 -m pytest tests/test_gates.py -v
```

Three acceptance gates: (1) evergreen across brand + currency, (2) pre-flight blocks on missing inputs, (3) produces both HTML + xlsx. Network-resilient — runs offline.

## Gotchas defended

- **G35** Credit−Debit netting on Account Transactions
- **G36** No vendor sub-rows under Revenue parents
- **G39** Shopify is monthly-revenue source; Xero is expense source
- **G1–G7** openpyxl quirks (number formats, merged cells, conditional formatting, zip integrity)

Out of scope: **G40** (accountant P&L override / Provisional→Reconciled tag flip).
