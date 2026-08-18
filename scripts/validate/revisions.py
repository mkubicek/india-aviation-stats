"""Revision log: which published values moved since the last data commit.

Git *is* the snapshot store - the processed CSVs are committed, so we diff the
freshly-regenerated working-tree CSV against the version in the last commit
(``git show HEAD:<path>``) keyed on the table's natural key. A restated past value
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

# Every published table is diffed. Covering only the airport layers once left the
# carrier and route tables free to be restated in silence: a July 2026 refresh
# rewrote 2,721 published load-factor values (86.66 -> 86.66023056391617) through
# an upstream dtype accident, and this log would have reported "no changes".
# ``entity`` names the row; the remaining key columns form the period label.
LAYERS = {
    "airport_monthly": {"key": ["year", "month", "airport"], "entity": ["airport"]},
    "airport_international_quarterly": {
        "key": ["year", "quarter", "airport"], "entity": ["airport"],
    },
    "carrier_monthly": {
        "key": ["airline", "service_type", "year", "month"],
        "entity": ["airline", "service_type"],
    },
    "domestic_route_monthly": {
        "key": ["year", "month", "origin", "destination"],
        "entity": ["origin", "destination"],
    },
    # Derived, so a movement here with no movement above is a derivation bug.
    # Keyed with `category`: (year, airport) alone is NOT unique here.
    "airport_yearly": {"key": ["year", "airport", "category"], "entity": ["airport"]},
}
MATERIAL_PCT = 1.0  # surface deltas above this percent prominently
MAX_ROWS_PER_LAYER = 200  # the rest are counted, never silently dropped


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


def compute_changes(
    old: pd.DataFrame, new: pd.DataFrame, key: list[str], entity: list[str] | None = None
) -> list[tuple]:
    """Pure diff of passenger values keyed on ``key``: (period, entity, old, new, kind)."""
    entity = list(entity or ["airport"])
    merged = old.merge(new, on=key, how="outer", suffixes=("_old", "_new"), indicator=True)
    merged = merged.rename(columns={"_merge": "merge_ind"})
    changes = []
    for row in merged.itertuples(index=False):
        d = row._asdict()
        old_p, new_p, ind = d.get("passengers_old"), d.get("passengers_new"), d["merge_ind"]
        period = "-".join(str(d[k]) for k in key)
        label = " · ".join(str(d[k]) for k in entity)
        if ind == "left_only":
            changes.append((period, label, int(old_p), None, "removed"))
        elif ind == "right_only":
            changes.append((period, label, None, int(new_p), "added"))
        elif old_p != new_p:
            changes.append((period, label, int(old_p), int(new_p), "restated"))
    return changes


def count_other_column_changes(old: pd.DataFrame, new: pd.DataFrame, key: list[str]) -> int:
    """Rows present in both versions whose non-key, non-passenger values moved.

    ``compute_changes`` itemises passengers only, so a table can be rewritten
    wholesale in another column (load factors, tonne-kilometres) and show as
    "no changes". This counts those rows so the log states they exist.
    """
    shared = [
        c for c in old.columns
        if c in new.columns and c not in key and c != "passengers"
    ]
    if not shared:
        return 0
    merged = old.merge(new, on=key, how="inner", suffixes=("_old", "_new"))
    if merged.empty:
        return 0
    moved = pd.Series(False, index=merged.index)
    for column in shared:
        a, b = merged[f"{column}_old"], merged[f"{column}_new"]
        moved |= ~((a == b) | (a.isna() & b.isna()))
    return int(moved.sum())


def diff_layer(name: str, spec: dict) -> dict:
    key, entity = spec["key"], spec["entity"]
    path = PROCESSED_DIR / f"{name}.csv"
    if not path.exists():
        return {"layer": name, "status": "absent"}
    new = pd.read_csv(path)
    # A key that is not unique turns the outer merge into a cartesian product and
    # invents changes in an unchanged file, so refuse rather than report fiction.
    dup = int(new.duplicated(key).sum())
    if dup:
        raise ValueError(f"{name}: {dup} row(s) share the diff key {key}; "
                         "the layer's key in LAYERS is wrong")
    old = _committed_version(f"data/processed/{name}.csv")
    if old is None:
        return {"layer": name, "status": "baseline", "rows": len(new)}
    return {
        "layer": name,
        "status": "diffed",
        "changes": compute_changes(old, new, key, entity),
        "other_column_changes": count_other_column_changes(old, new, key),
    }


def _fmt_pct(old, new) -> str:
    if not old:
        return " - "
    return f"{(new - old) / old * 100:+.1f}%"


def run_revisions(write: bool = True) -> dict:
    print("\n=== Revision log ===\n", flush=True)
    results = [diff_layer(name, spec) for name, spec in LAYERS.items()]

    lines = ["# Revisions", "",
             "Published values that moved since the previous data commit "
             "(diff of the regenerated CSVs against `git HEAD`). Period · entity · "
             "old → new. Every published table is covered; passenger changes are "
             "itemised and movements in other columns are counted. Empty between "
             "refreshes that change nothing.", ""]
    total_changes = 0
    for r in results:
        lines.append(f"## {r['layer']}")
        if r["status"] == "baseline":
            lines.append(f"\nBaseline - first committed version ({r['rows']:,} rows).\n")
            continue
        if r["status"] == "absent":
            lines.append("\n(not generated)\n")
            continue
        changes = r["changes"]
        other = r.get("other_column_changes", 0)
        total_changes += len(changes)
        if not changes:
            lines.append("\nNo passenger changes.\n" if other else "\nNo changes.\n")
        else:
            lines += ["", "| period | entity | old | new | Δ | kind |",
                      "| --- | --- | --- | --- | --- | --- |"]
            for period, label, old_p, new_p, kind in changes[:MAX_ROWS_PER_LAYER]:
                op = "" if old_p is None else f"{old_p:,}"
                np_ = "" if new_p is None else f"{new_p:,}"
                pct = _fmt_pct(old_p, new_p) if (old_p and new_p) else " - "
                lines.append(f"| {period} | {label} | {op} | {np_} | {pct} | {kind} |")
            if len(changes) > MAX_ROWS_PER_LAYER:
                lines.append(f"\n…and {len(changes) - MAX_ROWS_PER_LAYER:,} more of the same kinds.")
            lines.append("")
        if other:
            lines += [f"{other:,} row(s) present in both versions changed in a column "
                      "other than passengers.", ""]

    if write:
        REVISIONS_PATH.write_text("\n".join(lines) + "\n")
    print(f"  {total_changes} changed value(s) across {len(results)} table(s)")
    return {"total_changes": total_changes, "layers": results}


if __name__ == "__main__":
    run_revisions()
