"""Runtime dependency gate — standard-library only, no heavy imports.

Run BEFORE the main pipeline (which imports pandas/openpyxl at module load and
would otherwise fail cryptically if a dependency is missing).

    python3 -m scripts.check_deps          # human-readable
    python3 -m scripts.check_deps --json   # machine-readable for the skill

Exit codes: 0 = all good, 3 = something missing.
"""
from __future__ import annotations

import importlib.util
import json
import sys

MIN_PYTHON = (3, 11)
REQUIRED = [
    ("openpyxl", "openpyxl>=3.1", "Reading Xero .xlsx exports and writing the .xlsx report."),
    ("pandas", "pandas>=2.1", "All tabular transforms (rollups, netting, period windows)."),
]


def check() -> dict:
    py_ok = sys.version_info[:2] >= MIN_PYTHON
    py_version = ".".join(str(v) for v in sys.version_info[:3])

    modules = []
    for mod, pip_name, why in REQUIRED:
        found = importlib.util.find_spec(mod) is not None
        version = None
        if found:
            try:
                version = __import__(mod).__version__
            except Exception:
                version = "unknown"
        modules.append({
            "module": mod,
            "pip_name": pip_name,
            "why": why,
            "installed": found,
            "version": version,
        })

    missing = [m["pip_name"] for m in modules if not m["installed"]]
    ready = py_ok and not missing
    return {
        "ready": ready,
        "python": {
            "version": py_version,
            "min_required": ".".join(str(v) for v in MIN_PYTHON),
            "ok": py_ok,
            "executable": sys.executable,
        },
        "modules": modules,
        "missing_pip_names": missing,
        "install_command": ("pip install " + " ".join(missing)) if missing else None,
    }


def render_text(report: dict) -> str:
    lines = ["Dependency check:"]
    p = report["python"]
    mark = "✓" if p["ok"] else "✗"
    lines.append(f"  {mark} Python {p['version']} (need ≥ {p['min_required']})  [{p['executable']}]")
    for m in report["modules"]:
        mark = "✓" if m["installed"] else "✗"
        ver = f" {m['version']}" if m["version"] else ""
        lines.append(f"  {mark} {m['module']}{ver}" + ("" if m["installed"] else f"  — MISSING ({m['why']})"))
    lines.append("")
    if report["ready"]:
        lines.append("READY ✓ — all dependencies satisfied.")
    else:
        if not p["ok"]:
            lines.append(f"Python {p['min_required']}+ is required. Install a newer Python and re-run.")
        if report["missing_pip_names"]:
            lines.append("Install the missing packages:")
            lines.append(f"    {report['install_command']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    report = check()
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        print(render_text(report))
    return 0 if report["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
