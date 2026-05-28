---
description: Generate a 12-tab e-commerce Report Card (HTML + xlsx) from a standardised input pack.
allowed-tools: ["Bash", "Read", "Write", "AskUserQuestion"]
argument-hint: "[inputs_dir] [output_dir]"
---

# /report-card

Build a Report Card for an e-commerce brand from a standardised input pack.

## Usage

```
/report-card ./inputs ./out
/report-card                       # defaults to ./inputs and cwd
```

## How the skill should behave

1. **Pre-flight first.** Before building, run `python3 -m scripts.cli --preflight <inputs_dir>` to scan what's present. Read the JSON report.
2. **If required files are missing**, ask the user to provide them. Use AskUserQuestion or plain conversation — list each missing file by name and explain where it comes from (Shopify export, Xero export, ad platform).
3. **If optional files are missing**, note them and continue — the build will degrade gracefully (e.g. LTV tab shows a red banner if cohort data is absent).
4. **Run the build** once all required inputs are accounted for: `python3 -m scripts.cli <inputs_dir> <output_dir>`.
5. **Report results** to the user: which files were used, audit pass/fail summary, output paths.

## What the build does

1. Auto-detects ad-platform currency from CSV headers. If currencies conflict with the reporting currency, fetches daily FX rates at runtime (cached per-run).
2. Computes 12 tabs of derived KPIs:
   - Revenue from Shopify daily × FX (G39).
   - COGS from Xero CoGS Recognition journals (preferred) or Shopify per-sale (fallback).
   - Vendor sub-rows via Account Transactions, Credit−Debit netted (G35).
   - No vendor sub-rows under Revenue parents (G36).
3. Renders `report-card-{YYYY-MM-DD}.html` (founder-facing, tooltips on every calculated cell) and `report-card-{YYYY-MM-DD}.xlsx` (mentor weekly-call) in `<output_dir>`.
4. Writes audit results to `<output_dir>/audit/{run_id}.json`.

## Behaviour

- **Brand-neutral**: client name inferred from input filenames.
- **Missing inputs**: red banner + audit FAIL, build continues.
- **No user gates** in v1 — single pass after preflight.
- **Tooltips** on every calculated cell (HTML) / cell comments stripped from xlsx.
- **Halts only** on xlsx zip-validity failure or sheet-count mismatch.
