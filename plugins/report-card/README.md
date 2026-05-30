# Report Card

The **Report Card** skill (one tool in the Daily Mentor plugin marketplace) turns a standardised pack of Shopify, Xero and ad-platform exports into a 12-tab e-commerce diagnostic for a founder: a founder-facing HTML report (tooltips on every calculated cell) plus a mentor xlsx. Brand- and currency-neutral — it works across businesses and reporting currencies, with quarter-over-quarter unit economics (NCCM) and cohort-based LTV.

Source-of-truth rules: Shopify is authoritative for monthly revenue (G39), Xero for expense accounts, Account Transactions netted Credit−Debit per (account, contact, month) for vendor breakdown (G35), no vendor sub-rows under revenue parents (G36).

## Required inputs & how to obtain them

All exports cover the **last 365 days**. Drop them into one folder and point the skill at it (`/report-card <folder>`). The client name is inferred from the Xero filenames. File detection is fuzzy — the save-as names below are recommended but variants are matched.

### Shopify

**1. Sessions by Month** → `Sessions by month - YYYY-MM-DD.csv`
- Shopify Analytics → Reports → **Sessions**
- Group by month → Export as CSV

**2. Total Sales (daily)** → save as `Daily Mentor - Total Sales Over Time`
- Shopify Analytics → Reports → **Total Sales** (over time)
- Change time period: Last → **365 Days**
- Remove comparison
- Export as CSV
- Save Report as `Daily Mentor - Total Sales Over Time`

**3. New vs Returning, per quarter** → save as `Daily Mentor - NC v RC L365 CalQoQ`
- Shopify Analytics → **custom report** → New exploration
- Change time period: Last → **365 Days**
- Paste into the Shopify Sidekick box: *"New exploration report for L365 days summarised per calendar quarter, New Customers vs Returning Customers, include filters gross sales, discounts, returns, shipping, tax, orders, Average order value and COGS"*
- Save Report as `Daily Mentor - NC v RC L365 CalQoQ`
- The **per-calendar-quarter** grouping is what drives the quarter-over-quarter NCCM. Without it, NCCM falls back to a single blended period (and says so).

### Xero

**4. Balance Sheet** → `{CLIENT}_-_Balance_Sheet.xlsx`
- Xero → Reports → **Balance Sheet**
- Change time period: default → **This Month**
- Hit **Compare with** → set to *Enter a Different Number* → enter **12**
- Hit Update
- Export as **Excel** file
- Save Report as `Daily Mentor - Balance Sheet`

**5. Account Transactions** → `{CLIENT}_-_Account_Transactions.xlsx`
- Xero → Reports → **Account Transactions**
- Accounts → **Select All**
- Change time period: default → **Custom Date Range, Last 365 Days**
- Update columns to show **Date, Contact, Description, Debit (AUD), Credit (AUD)**
- Hit Update
- Export as **Excel** file
- Save Report as `Daily Mentor - Account Transactions`
- This is the **primary expense source** — the P&L is reconstructed from it (Credit−Debit netted per account/contact/month). A separate Xero P&L export is *optional* and only used if you want the bookkeeper's own categorisation to override the reconstruction.

### Ad platforms — at least one required

**6. Daily ad spend** (Meta / Google / TikTok) → e.g. `facebook_spend.csv`
- Export daily spend by campaign for the last 12 months. The currency must appear in the column header (e.g. `Amount spent (AUD)`).
- Provide at least one platform; all supplied platforms are summed. More is better.

### Optional — unlocks the LTV tab

**7. Cohort Analysis** → e.g. `Daily Mentor - Cohort Analysis customer value by month.csv`
- Shopify Analytics → **Customers → Cohort Analysis** → *'Customer value by month'* (last 6 months) → Export as CSV
- With it, the LTV tab renders the true cohort retention matrix and the Final Report Card Month-2 / Month-5 growth benchmarks populate. Without it, the LTV tab degrades to a repeat-economics proxy from the NC/RC split.

| Role | Required | Saved-as name |
|---|---|---|
| Sessions by month | yes | `Sessions by month - YYYY-MM-DD.csv` |
| Total Sales (daily) | yes | `Daily Mentor - Total Sales Over Time` |
| NC vs RC (per quarter) | yes | `Daily Mentor - NC v RC L365 CalQoQ` |
| Balance Sheet | yes | `{CLIENT}_-_Balance_Sheet.xlsx` |
| Account Transactions | yes | `{CLIENT}_-_Account_Transactions.xlsx` |
| Ad spend (Meta/Google/TikTok) | at least one | `*facebook*spend*` / `*google*spend*` / `*tiktok*spend*` |
| Cohort Analysis | optional | `*cohort*.csv` |
| Xero Profit & Loss | optional | `{CLIENT}_-_Profit_and_Loss.xlsx` |

Run `python3 -m scripts.cli --preflight <folder>` (or just invoke the skill) to see exactly what's present, missing, or optional before building.

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
5. LTV Analysis (Mode A cohort matrix with Cohort CSV; Mode B repeat-economics proxy without)
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

Acceptance gates cover: evergreen across brand + currency, dependency + pre-flight gates block on missing tools/inputs, P&L-optional and ad-platform-one-of input rules, quarter-over-quarter NCCM, two-mode LTV (cohort matrix vs proxy), and dual HTML + xlsx output. Network-resilient — runs offline.

## Gotchas defended

- **G35** Credit−Debit netting on Account Transactions
- **G36** No vendor sub-rows under Revenue parents
- **G39** Shopify is monthly-revenue source; Xero is expense source
- **G1–G7** openpyxl quirks (number formats, merged cells, conditional formatting, zip integrity)

Out of scope: **G40** (accountant P&L override / Provisional→Reconciled tag flip).
