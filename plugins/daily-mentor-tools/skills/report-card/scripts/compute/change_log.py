"""Change Log — append-only per-run history."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..models import RenderTree
from .helpers import make_row, text_cell


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def compute(bundle, run_id: str | None = None, output_dir: Path | None = None) -> RenderTree:
    meta = bundle.meta
    output_dir = Path(output_dir) if output_dir else Path.cwd()
    log_path = output_dir / "audit" / "change_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    if log_path.exists():
        try:
            entries = json.loads(log_path.read_text())
        except Exception:
            entries = []

    file_hashes = {}
    for role, path in meta.files_found.items():
        try:
            file_hashes[role] = _hash_file(Path(path))
        except Exception:
            file_hashes[role] = "ERR"

    new_entry = {
        "run_id": run_id or datetime.now().strftime("%Y%m%dT%H%M%S"),
        "run_date": str(meta.run_date),
        "client": meta.client_name,
        "reporting_currency": meta.reporting_currency,
        "files_found": list(meta.files_found.keys()),
        "files_missing": meta.files_missing,
        "file_hashes": file_hashes,
        "lookback": [str(meta.lookback_start), str(meta.lookback_end)],
    }
    entries.append(new_entry)
    log_path.write_text(json.dumps(entries, indent=2))

    tree = RenderTree(tab_id="change_log", title="Change Log", subtitle="Per-run history of inputs and runs.")
    tree.columns = ["Run", "Date", "Client", "Files", "Hashes (short)"]
    for e in reversed(entries):
        files_str = ", ".join(e["files_found"])
        hashes_str = ", ".join(f"{k}={v}" for k, v in e["file_hashes"].items())
        tree.rows.append(make_row([
            text_cell(f"cl.{e['run_id']}.a", e["run_id"]),
            text_cell(f"cl.{e['run_id']}.b", e["run_date"]),
            text_cell(f"cl.{e['run_id']}.c", e["client"]),
            text_cell(f"cl.{e['run_id']}.d", files_str),
            text_cell(f"cl.{e['run_id']}.e", hashes_str),
        ]))
    return tree
