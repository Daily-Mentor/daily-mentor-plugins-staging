---
name: report-card
description: Use when the user invokes /report-card, asks to build a report card or e-commerce diagnostic, or refers to a standardised input pack (Shopify CSVs + Xero exports + ad-platform CSVs). Brand-neutral — works for any e-commerce client. Produces a 12-tab HTML (founder-facing, tooltips) plus xlsx fallback (mentor weekly-call use).
version: 0.2.0
---

# Report Card Builder

## When to use

The user has a folder of mentee data and wants the Report Card deliverable for an e-commerce founder. The plugin is brand-neutral — it works for any client whose data follows the input-pack spec.

## Step 0 — Dependency gate (run before everything)

The pipeline needs Python ≥ 3.11 plus `openpyxl` and `pandas`. Check this first, because a missing interpreter or package would otherwise fail cryptically.

1. **Is Python present?** Run `python3 --version` via Bash. If the command isn't found, tell the user Python 3.11+ must be installed (e.g. `brew install python` on macOS, python.org installer on Windows) and stop — you cannot proceed without it.
2. **Are the packages present?** Run `python3 -m scripts.check_deps --json` from the plugin directory. Parse the JSON:
   - `ready: true` → continue to pre-flight.
   - `ready: false` → look at `missing_pip_names` and `install_command`.
3. **Offer to install.** If packages are missing, do not silently install. Ask the user: "openpyxl/pandas aren't installed — shall I install them with `<install_command>`?" If they agree, run the `install_command` via Bash (prefer `python3 -m pip install --user <pkgs>`, or `pip install --break-system-packages <pkgs>` on externally-managed envs). Re-run `check_deps --json` to confirm `ready: true`, then continue. If they decline, stop and explain the build can't run without them.

## Mandatory pre-flight

**After deps are satisfied, always run the pre-flight check before any build.**

```bash
python3 -m scripts.cli --preflight-json <inputs_dir>
```

This returns JSON describing what's present, missing, and optional. Parse it:

- `is_ready: true` → all required files are present, proceed to build.
- `is_ready: false` → one or more required files missing. **Do not build.** Tell the user what's missing.

### Prompting the user for missing files

For each entry in `requirements` where `required: true` and `found: false`, surface to the user:

- The file's **label** (human-readable name)
- The **source system** (Shopify Admin, Xero, Meta Ads Manager, etc.)
- The **export_path_hint** (where in the source UI they need to go)
- The **accepted_patterns** (substrings their filename should contain)

Ask them to either:
1. Drop the file into `<inputs_dir>` and tell you they've done so, or
2. Upload it in this chat and tell you where they put it — you'll move it.

Once they've added files, re-run the pre-flight JSON command to confirm. Loop until `is_ready: true`.

### Optional inputs

For each entry where `required: false` and `found: false`, mention it briefly and note what tab degrades without it (LTV tab needs the Shopify Cohort Analysis CSV; Google/TikTok ad spend supplements the Meta CSV). Do not block — these are nice-to-have.

## The input pack (brand-neutral spec)

| Role | File pattern | Required | Source |
|---|---|---|---|
| `shopify_daily` | `shopify_daily_*.csv` | yes | Shopify → Analytics → Total Sales (daily) |
| `nc_rc` | `Gross sales by new or returning customer*.csv` | yes | Shopify → Analytics → NC/RC report |
| `sessions` | `Sessions by month*.csv` | yes | Shopify → Analytics → Sessions |
| `xero_pl` | `*_Profit_and_Loss.xlsx` | yes | Xero → Reports → P&L (12-month, monthly columns) |
| `xero_bs` | `*_Balance_Sheet.xlsx` | yes | Xero → Reports → Balance Sheet |
| `xero_atxn` | `*_Account_Transactions.xlsx` | yes | Xero → Reports → Account Transactions (12-month, all accounts) |
| `ad_spend_meta` | `*facebook*spend*.{csv,xlsx}` | yes | Meta Ads Manager → daily spend by campaign |
| `ad_spend_google` | `*google*spend*.{csv,xlsx}` | optional | Google Ads → daily report |
| `ad_spend_tiktok` | `*tiktok*spend*.{csv,xlsx}` | optional | TikTok Ads Manager → daily report |
| `cohort` | `*cohort*.csv` | optional | Shopify → Customer Cohort Analysis (unlocks LTV tab) |

## Pipeline (single pass after preflight clears)

```bash
python3 -m scripts.cli <inputs_dir> <output_dir> [--reporting-currency AUD|NZD|USD|...]
```

1. **Ingest** — parse all files; sniff currency from ad-platform CSV headers; build `IngestBundle`.
2. **Transform** — FX-convert to reporting currency **only if currencies differ** (Frankfurter ECB rates fetched at runtime, cached per-run); apply G35 Credit−Debit netting; parse section-banded Xero exports; derive period windows.
3. **Compute** — per-tab `RenderTree` with `Cell` objects carrying value + format + confidence + `Tooltip`.
4. **Render** — HTML (Jinja2 + inlined Alpine.js, single self-contained file, Daily Mentor brand styling) and xlsx (fresh openpyxl workbook, no comments).
5. **Audit** — A1–A12 PASS/FAIL/SKIP assertions; only A8 (zip-valid) and A9 (sheet-count) halt.

## Source-of-truth rules (load-bearing — do not relax)

- **Monthly revenue → Shopify ×FX** (G39). Never Xero monthly columns (they're posting-date, not sale-date).
- **COGS → Xero CoGS Recognition journals if posted; Shopify per-sale ×FX as fallback.** Cost of Sales components (Freight, Packaging, Merchant Fees, Fulfilment, Customs) come from Xero as separate lines.
- **Vendor sub-rows → Account Transactions, Credit−Debit netted** per (account, contact, month) (G35).
- **No vendor sub-rows under Revenue parents** (G36).
- **Ad spend → platform CSVs ×FX**, never Xero.
- **FX**: runtime only. If everything's in the reporting currency, NO network call is made.

## Behaviour notes

- **Brand-neutral**: client name is detected from input filenames; nothing about the brand is hardcoded.
- **FX is on-demand**: rates are fetched from Frankfurter only when source ≠ reporting currency. Cached to `.fx-cache/rates.json` for repeat runs.
- **Two-entity packs**: if multiple Xero files match a role (parent + subsidiary), the larger file wins.
- **Atxn-derived P&L fallback**: if the supplied P&L has <4 months of posted activity but Atxn covers more, the skill reconstructs the P&L from Atxn.

## Failure modes & next-steps recipes

- **Pre-flight blocks build** → ask user to provide missing required files; re-run preflight; do not skip.
- **A3 FX FAIL** → runtime fetch failed (network down, currency unknown). Suggest running with `--reporting-currency` matching the source data to skip FX entirely.
- **A4 SKIP** → Xero has no revenue accounts; reconciliation can't run. Informational.
- **LTV tab red banner** → ask client for Shopify Cohort Analysis CSV.
