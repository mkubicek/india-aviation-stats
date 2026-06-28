"""Triage mode: turn the gate's *unclassified* anomalies into a research worklist.

ADVISORY and on-demand — never part of the blocking path. The mechanical gate can
**detect** an anomaly (two source labels feeding one airport in the same month; a
high-volume label that maps to nothing) but it cannot **classify** it: deciding
whether two labels are one physical airport or two needs world knowledge. That is
the one judgement the data alone can't make.

So this module emits, per anomaly, a research question + a ready-to-fill OKF
assumption skeleton, so an agent *with web search* can hunt counter-evidence and
draft a cited ``assumptions/<id>.md`` for a **human to confirm**. It performs no
network or LLM calls itself — it stays deterministic; the searching lives in the
``validate-assumptions`` skill. Triage never blocks; the gate is the pass/fail.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from entities import build_airport_resolver

from .assumptions import load_assumptions
from .overlap import UNMAPPED_PAX_THRESHOLD, _read_domestic_rows

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
TRIAGE_PATH = PROCESSED_DIR / "triage_queue.json"


def _q(label: str) -> str:
    """Quote a label for a YAML flow sequence only when it needs it."""
    return f'"{label}"' if any(c in label for c in " ,:#") else label


def _okf_skeleton(*, title, category, falsification, covers, labels, question, airport=None) -> str:
    covers_yaml = "[" + ", ".join(covers) + "]" if covers else "[]"
    labels_yaml = ", ".join(_q(l) for l in labels)
    # concurrent-merge-declared reads params.airport; emit it so a drafted file is
    # complete and won't crash `validate --assumptions`.
    airport_line = f"  airport: {airport}\n" if airport else ""
    return f"""---
type: cleanup-assumption
title: {title}
category: {category}
falsification: {falsification}
covers: {covers_yaml}
params:
{airport_line}  labels: [{labels_yaml}]
tags: [airport, triage-draft, NEEDS-HUMAN-REVIEW]
---
# Observation

<!-- Auto-detected by triage. Confirm against the raw data, then describe it: -->
{question}

# Interpretation

<!-- TODO: your reading, backed by the Evidence below. -->

# Decision

<!-- TODO: the exact mapping you will encode in mappings.yaml. -->

# Evidence

<!-- TODO: cite 1-2 PRIMARY sources (IATA / airport authority / Wikipedia) and,
     ideally, note one search that tried to REFUTE this reading and failed. -->
- https://en.wikipedia.org/wiki/<airport> — IATA/ICAO code + physical location

# Falsification

`{falsification}`: re-open if the data later contradicts this.
"""


def build_worklist(mappings: dict, raw_domestic: Path) -> list[dict]:
    """Deterministic: scan raw labels, return the items that need world-knowledge.

    Two kinds, mirroring exactly what the gate detects but can't decide:
      - ``undeclared_concurrent`` — >1 source label feeds one canonical in the same
        month, not declared in ``concurrent_labels`` and not covered by an
        assumption (this reds the reverse gate).
      - ``unmapped_high_volume`` — a label resolves to nothing above the volume
        threshold (advisory in the gate; a real airport we failed to map).
    """
    if not raw_domestic.exists():
        return []
    resolver = build_airport_resolver(mappings, extra_aliases=mappings.get("airport_aliases"))

    covered: set[str] = set()
    for a in load_assumptions():
        covered |= set(a["frontmatter"].get("covers", []) or [])

    declared = {e["airport"]: set(l.upper() for l in e["labels"])
                for e in (mappings.get("concurrent_labels") or [])}

    per_month: dict[str, dict[tuple, set]] = defaultdict(lambda: defaultdict(set))
    unmapped_pax: dict[str, float] = defaultdict(float)
    unmapped_years: dict[str, set] = defaultdict(set)
    unmapped_months: dict[str, set] = defaultdict(set)

    for label, year, month, pax in _read_domestic_rows(raw_domestic):
        if not label:
            continue
        canon = resolver.resolve(label, year, month)
        if canon is None:
            up = label.upper()
            unmapped_pax[up] += pax
            unmapped_years[up].add(year)
            unmapped_months[up].add((year, month))
        else:
            per_month[canon][(year, month)].add(label.upper())

    items: list[dict] = []

    # Kind 1 — undeclared concurrent merges (mirrors overlap + reverse gate).
    for canon in sorted(per_month):
        labelset: set[str] = set()
        co_months: list[tuple] = []
        for ym, ls in per_month[canon].items():
            if len(ls) > 1:
                labelset |= ls
                co_months.append(ym)
        if not labelset:
            continue
        undeclared = labelset - declared.get(canon, set())
        if not undeclared or canon in covered:
            continue
        labels = sorted(labelset)
        q = (f"Source labels {labels} all resolve to {canon} and co-occur in the same "
             f"month(s). Are they ONE physical airport (declare in concurrent_labels + a "
             f"`concurrent-merge-declared` assumption) or DISTINCT airports wrongly merged "
             f"onto {canon} (split into separate canonical keys)? Search for evidence that "
             f"they are NOT the same place.")
        items.append({
            "kind": "undeclared_concurrent",
            "canonical": canon,
            "labels": labels,
            "months": sorted(f"{y}-{m:02d}" for y, m in co_months)[:6],
            "id_hint": f"{canon}-NNN",
            "research_question": q,
            "suggested_falsification": "concurrent-merge-declared",
            "draft_path": f"assumptions/{canon}-NNN.md",
            "draft": _okf_skeleton(
                title=f"TODO: are {labels} one airport ({canon}) or distinct?",
                category="deduplication", falsification="concurrent-merge-declared",
                covers=[canon], labels=labels, question=q, airport=canon),
        })

    # Kind 2 — high-volume unmapped labels (a real airport we failed to map).
    for label, total in unmapped_pax.items():
        per_year = total / max(1, len(unmapped_years[label]))
        if per_year < UNMAPPED_PAX_THRESHOLD:
            continue
        q = (f"Source label '{label}' (~{int(per_year):,} pax/yr) maps to no canonical "
             f"airport. What airport is it? Find its IATA code. Is it (a) a NEW airport, "
             f"(b) a spelling variant / rename of an existing canonical "
             f"(`month-disjoint-rename`), or (c) a distinct airport colliding with an "
             f"existing code (`distinct-airports-not-merged`)? Search for counter-evidence "
             f"to your first guess before mapping it.")
        items.append({
            "kind": "unmapped_high_volume",
            "canonical": None,
            "labels": [label],
            "months": sorted(f"{y}-{m:02d}" for y, m in unmapped_months[label])[:6],
            "approx_pax_per_year": int(per_year),
            "id_hint": "XXX-001",
            "research_question": q,
            "suggested_falsification": "month-disjoint-rename",
            "draft_path": "assumptions/XXX-001.md  # rename XXX to the IATA code once known",
            "draft": _okf_skeleton(
                title=f"TODO: identify '{label}' (rename the id to its IATA code)",
                category="mapping", falsification="month-disjoint-rename",
                covers=["XXX"], labels=[label], question=q),
        })

    items.sort(key=lambda it: (it["kind"], it.get("canonical") or it["labels"][0]))
    return items


def run_triage(write: bool = True) -> int:
    print("\n=== Triage (advisory: research worklist for unclassified labels) ===\n", flush=True)
    mappings = yaml.safe_load((ROOT / "mappings.yaml").read_text())
    items = build_worklist(mappings, RAW_DOMESTIC)

    if write:
        TRIAGE_PATH.write_text(json.dumps(
            {"generated": date.today().isoformat(), "count": len(items), "items": items},
            indent=2) + "\n")

    if not items:
        print("  Queue empty — every concurrent merge is declared/covered and no high-volume "
              "label is unmapped. Nothing to research.", flush=True)
    else:
        print(f"  {len(items)} label(s) need classification (the gate detects, you decide):\n",
              flush=True)
        for it in items:
            who = it["canonical"] or it["labels"][0]
            print(f"  • [{it['kind']}] {who}: {it['labels']}", flush=True)
            print(f"      → {it['research_question']}", flush=True)
            print(f"      draft: {it['draft_path']}", flush=True)
        print(f"\n  Worklist + ready-to-fill OKF skeletons: {TRIAGE_PATH.relative_to(ROOT)}",
              flush=True)
        print("  Research each (web), draft assumptions/<id>.md, get human sign-off, then "
              "edit mappings.yaml and re-run the gate.", flush=True)
    print("\n  (advisory — triage never blocks; the gate is the pass/fail.)", flush=True)
    return 0
