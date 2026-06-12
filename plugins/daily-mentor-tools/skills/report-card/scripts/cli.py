"""Report Card entry point. Usage: python3 -m scripts.cli [inputs_dir] [output_dir]"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# Stdlib-only modules — always safe to import.
from .check_deps import check as check_deps
from .check_deps import render_text as render_deps_text
from .preflight import emit_json as emit_preflight_json
from .preflight import preflight, render_text_summary

# Heavy third-party imports (pandas, openpyxl). Guarded so a missing dependency
# produces a clean, actionable message instead of an ImportError traceback.
_DEPS_IMPORT_ERROR: ImportError | None = None
try:
    from .audit import add_format_audit, add_xlsx_audit_result, run_ingest_audit
    from .compute import (
        final_report_card, financial_position, homepage, ltv,
        monthly_pl, nccm,
    )
    from .ingest import ingest
    from .render_html import render as render_html
    from .render_xlsx import render as render_xlsx
    from .transform import transform
except ImportError as _e:  # pragma: no cover - exercised only when deps absent
    _DEPS_IMPORT_ERROR = _e


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Report Card.")
    parser.add_argument("inputs_dir", nargs="?", default="./inputs",
                        help="Directory containing the standardised input pack.")
    parser.add_argument("--check-deps", action="store_true",
                        help="Verify Python version + required packages (openpyxl, pandas) and exit.")
    parser.add_argument("--check-deps-json", action="store_true",
                        help="Like --check-deps but emit machine-readable JSON for skill consumption.")
    parser.add_argument("--preflight", action="store_true",
                        help="Run the pre-flight checklist only — report what's present/missing and exit without building.")
    parser.add_argument("--preflight-json", action="store_true",
                        help="Like --preflight but emit machine-readable JSON for skill consumption.")
    parser.add_argument("--force", action="store_true",
                        help="Build even if pre-flight reports missing required files.")
    parser.add_argument("output_dir", nargs="?", default=".",
                        help="Directory to write report-card-{date}.{html,xlsx} into.")
    parser.add_argument("--run-date", default=None,
                        help="Override the report run date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--reporting-currency", default="AUD",
                        help="Reporting currency (default AUD).")
    args = parser.parse_args(argv)

    # ---- Dependency gate (stdlib-only; runs before anything heavy) ----
    deps = check_deps()
    if args.check_deps_json:
        import json
        print(json.dumps(deps, indent=2))
        return 0 if deps["ready"] else 3
    if args.check_deps:
        print(render_deps_text(deps))
        return 0 if deps["ready"] else 3
    if not deps["ready"] or _DEPS_IMPORT_ERROR is not None:
        print(render_deps_text(deps), flush=True)
        if deps["install_command"]:
            print(f"\nRun this to install, then re-run the report:\n    {deps['install_command']}")
        return 3

    inputs_dir = Path(args.inputs_dir).resolve()

    # ---- Pre-flight (always run; --preflight / --preflight-json exit here) ----
    pf = preflight(inputs_dir)
    if args.preflight_json:
        print(emit_preflight_json(pf))
        return 0 if pf.is_ready else 2
    if args.preflight:
        print(render_text_summary(pf))
        return 0 if pf.is_ready else 2
    if not pf.is_ready and not args.force:
        print(render_text_summary(pf), flush=True)
        print("\nRefusing to build — add the missing required files and re-run, or pass --force to proceed anyway.")
        return 2
    if pf.is_ready:
        print(f"[preflight] {sum(1 for r in pf.requirements if r.found)}/{len(pf.requirements)} inputs present — ready.")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_date = date.fromisoformat(args.run_date) if args.run_date else date.today()

    print(f"[ingest] reading inputs from {inputs_dir}")
    bundle = ingest(inputs_dir, run_date=run_date)
    bundle.meta.reporting_currency = args.reporting_currency
    print(f"[ingest] client: {bundle.meta.client_name}; files found: {list(bundle.meta.files_found.keys())}; missing: {bundle.meta.files_missing}")

    print("[transform] normalising frames")
    bundle = transform(bundle)

    print("[compute] building 6 tab trees")
    trees = [
        homepage.compute(bundle),
        monthly_pl.compute(bundle),
        financial_position.compute(bundle),
        nccm.compute(bundle),
        ltv.compute(bundle),
        final_report_card.compute(bundle),
    ]

    print("[audit] running ingest assertions")
    audit_report = run_ingest_audit(bundle, trees)

    # --- Render HTML ---
    html_path = output_dir / f"report-card-{run_date}.html"
    print(f"[render] writing HTML → {html_path}")
    html_str = render_html(trees, audit_report, client=bundle.meta.client_name, run_date=run_date)
    html_path.write_text(html_str)
    print(f"[render] HTML size: {len(html_str):,} bytes")

    # --- Render xlsx ---
    xlsx_path = output_dir / f"report-card-{run_date}.xlsx"
    print(f"[render] writing xlsx → {xlsx_path}")
    xlsx_info = render_xlsx(trees, audit_report, xlsx_path, client=bundle.meta.client_name, run_date=run_date)

    add_format_audit(audit_report, "PASS",
        "openpyxl number_format set immediately after value (G1 compliant).")
    if xlsx_info["zip_valid"]:
        add_xlsx_audit_result(audit_report, "PASS",
            f"xlsx zip integrity verified ({xlsx_info['sheet_count']} sheets).", check_id="A8")
    else:
        add_xlsx_audit_result(audit_report, "HALT",
            "xlsx zip integrity check failed.", check_id="A8")
    # 6 report tabs + the audit sheet
    if xlsx_info["sheet_count"] >= 7:
        add_xlsx_audit_result(audit_report, "PASS",
            f"Sheet count = {xlsx_info['sheet_count']} (expected ≥ 7).", check_id="A9")
    else:
        add_xlsx_audit_result(audit_report, "HALT",
            f"Sheet count = {xlsx_info['sheet_count']} (expected ≥ 7).", check_id="A9")

    # Write audit JSON for traceability
    import json
    audit_dir = output_dir / "audit"
    audit_dir.mkdir(exist_ok=True)
    audit_json = {
        "run_id": audit_report.run_id,
        "timestamp": audit_report.timestamp.isoformat(),
        "client": bundle.meta.client_name,
        "run_date": str(run_date),
        "results": [
            {"check_id": r.check_id, "name": r.name, "status": r.status, "message": r.message, "details": r.details}
            for r in audit_report.results
        ],
    }
    (audit_dir / f"{audit_report.run_id}.json").write_text(json.dumps(audit_json, indent=2))

    # Re-render HTML so the post-render audit checks appear in the Audit Report tab
    html_str = render_html(trees, audit_report, client=bundle.meta.client_name, run_date=run_date)
    html_path.write_text(html_str)

    # Summary
    passes = sum(1 for r in audit_report.results if r.status == "PASS")
    fails = sum(1 for r in audit_report.results if r.status == "FAIL")
    skips = sum(1 for r in audit_report.results if r.status == "SKIP")
    halts = sum(1 for r in audit_report.results if r.status == "HALT")
    print(f"[done] audit: {passes} PASS · {fails} FAIL · {skips} SKIP · {halts} HALT")
    print(f"[done] HTML: {html_path}")
    print(f"[done] xlsx: {xlsx_path} ({xlsx_info['sheet_count']} sheets)")

    return 1 if audit_report.has_halts else 0


if __name__ == "__main__":
    sys.exit(main())
