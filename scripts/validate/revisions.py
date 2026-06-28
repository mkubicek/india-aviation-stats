"""Revision log: which published values moved since the last data commit.

Git *is* the snapshot store — the processed CSVs are committed, so we diff the
freshly-regenerated working-tree CSV against the version in the last commit
(``git show HEAD:<path>``) keyed on the layer's natural key. A restated past value
then reads as a disclosed restatement in ``REVISIONS.md``, not a silent edit.

Run this BEFORE committing the new data (regenerate → validate → revisions →
commit), so HEAD still holds the previous refresh.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
REVISIONS_PATH = PROCESSED_DIR / "REVISIONS.md"

LAYERS = {
    "airport_monthly": ["year", "month", "airport"],
    "airport_international_quarterly": ["year", "quarter", "airport"],
}
MATERIAL_PCT = 1.0  # surface deltas above this percent prominently


def _committed_version(rel_path: str) -> pd.DataFrame | None:
    try:
        blob = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    if not blob.strip():
        return None
    return pd.read_csv(io.StringIO(blob))


def compute_changes(old: pd.DataFrame, new: pd.DataFrame, key: list[str]) -> list[tuple]:
    """Pure diff of passenger values keyed on ``key``: (period, airport, old, new, kind)."""
    merged = old.merge(new, on=key, how="outer", suffixes=("_old", "_new"), indicator=True)
    merged = merged.rename(columns={"_merge": "merge_ind"})
    changes = []
    for row in merged.itertuples(index=False):
        d = row._asdict()
        old_p, new_p, ind = d.get("passengers_old"), d.get("passengers_new"), d["merge_ind"]
        period = "-".join(str(d[k]) for k in key)
        if ind == "left_only":
            changes.append((period, d["airport"], int(old_p), None, "removed"))
        elif ind == "right_only":
            changes.append((period, d["airport"], None, int(new_p), "added"))
        elif old_p != new_p:
            changes.append((period, d["airport"], int(old_p), int(new_p), "restated"))
    return changes


def diff_layer(name: str, key: list[str]) -> dict:
    path = PROCESSED_DIR / f"{name}.csv"
    if not path.exists():
        return {"layer": name, "status": "absent"}
    new = pd.read_csv(path)
    old = _committed_version(f"data/processed/{name}.csv")
    if old is None:
        return {"layer": name, "status": "baseline", "rows": len(new)}
    return {"layer": name, "status": "diffed", "changes": compute_changes(old, new, key)}


def _fmt_pct(old, new) -> str:
    if not old:
        return "—"
    return f"{(new - old) / old * 100:+.1f}%"


def run_revisions(write: bool = True) -> dict:
    print("\n=== Revision log ===\n", flush=True)
    results = [diff_layer(name, key) for name, key in LAYERS.items()]

    lines = ["# Revisions", "",
             "Published values that moved since the previous data commit "
             "(diff of the regenerated CSVs against `git HEAD`). Period · airport · "
             "old → new. Empty between refreshes that change nothing.", ""]
    total_changes = 0
    for r in results:
        lines.append(f"## {r['layer']}")
        if r["status"] == "baseline":
            lines.append(f"\nBaseline — first committed version ({r['rows']:,} rows).\n")
            continue
        if r["status"] == "absent":
            lines.append("\n(not generated)\n")
            continue
        changes = r["changes"]
        total_changes += len(changes)
        if not changes:
            lines.append("\nNo changes.\n")
            continue
        lines += ["", "| period | airport | old | new | Δ | kind |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for period, airport, old_p, new_p, kind in changes[:200]:
            op = "" if old_p is None else f"{old_p:,}"
            np_ = "" if new_p is None else f"{new_p:,}"
            pct = _fmt_pct(old_p, new_p) if (old_p and new_p) else "—"
            lines.append(f"| {period} | {airport} | {op} | {np_} | {pct} | {kind} |")
        if len(changes) > 200:
            lines.append(f"\n…and {len(changes) - 200} more.")
        lines.append("")

    if write:
        REVISIONS_PATH.write_text("\n".join(lines) + "\n")
    print(f"  {total_changes} changed value(s) across {len(results)} layer(s)")
    return {"total_changes": total_changes, "layers": results}


if __name__ == "__main__":
    run_revisions()
