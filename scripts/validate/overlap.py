"""The month-grain overlap-classification gate (the load-bearing check).

Two genuinely different airports can hide behind name-similar source labels
(Goa: Dabolim vs Mopa), and the same airport can hide behind two spellings
(Kochi/Cochin). Only a human can tell which. So this gate never merges on a
heuristic: it surfaces every case where **two distinct source labels feed one
canonical airport in the same month** and BLOCKS unless that merge is declared in
``mappings.yaml: concurrent_labels``. A future DGCA refresh that lands a new label
on an existing airport reds CI until a human classifies it.

It also emits the advisory "high-volume unmapped name" check — a real Indian
airport we failed to map would be silent passenger loss.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from entities import build_airport_resolver

from .checks import Finding, _fail, _ok, _warn

UNMAPPED_PAX_THRESHOLD = 100_000  # per-year, advisory


def _read_domestic_rows(raw_domestic: Path):
    with raw_domestic.open() as f:
        rd = csv.reader(f)
        next(rd, None)
        for r in rd:
            if len(r) < 6:
                continue
            year = 2000 + int(r[0]) if len(r[0]) == 2 else int(r[0])
            month = int(r[1])
            try:
                pax = float(r[4]) + float(r[5])
            except ValueError:
                pax = 0.0
            for label in (r[2], r[3]):
                yield label.strip(), year, month, pax


def overlap_gate(mappings: dict, raw_domestic: Path) -> list[Finding]:
    """BLOCKING: every concurrent same-canonical merge must be declared."""
    resolver = build_airport_resolver(mappings, extra_aliases=mappings.get("airport_aliases"))

    # canonical -> {(year, month) -> set(labels)}
    per_month: dict[str, dict[tuple, set]] = defaultdict(lambda: defaultdict(set))
    for label, year, month, _pax in _read_domestic_rows(raw_domestic):
        if not label:
            continue
        key = resolver.resolve(label, year, month)
        if key:
            per_month[key][(year, month)].add(label.upper())

    # concurrent same-canonical label sets
    concurrent: dict[str, set] = {}
    for canon, months in per_month.items():
        labels = set()
        for _, ls in months.items():
            if len(ls) > 1:
                labels |= ls
        if labels:
            concurrent[canon] = labels

    # declared allowlist
    declared = {}
    for entry in mappings.get("concurrent_labels", []) or []:
        declared[entry["airport"]] = set(l.upper() for l in entry["labels"])

    findings = []
    for canon, labels in sorted(concurrent.items()):
        allow = declared.get(canon, set())
        undeclared = labels - allow
        if undeclared:
            findings.append(_fail(
                f"overlap.concurrent.{canon}", "BLOCKING",
                f"{canon} sums concurrent labels {sorted(labels)} in the same month(s) "
                f"but {sorted(undeclared)} are not declared in concurrent_labels — "
                "classify (same airport? distinct airports?) before merging"))
        else:
            findings.append(_ok(
                f"overlap.concurrent.{canon}", "BLOCKING",
                f"{canon}: concurrent labels {sorted(labels)} declared as one airport"))
    if not concurrent:
        findings.append(_ok("overlap.concurrent", "BLOCKING",
                            "no concurrent same-canonical merges in the data"))
    return findings


def check_unmapped_names(mappings: dict, raw_domestic: Path) -> list[Finding]:
    """ADVISORY: flag any unmapped domestic label above the volume threshold."""
    resolver = build_airport_resolver(mappings, extra_aliases=mappings.get("airport_aliases"))
    pax_by_label: dict[str, float] = defaultdict(float)
    years: dict[str, set] = defaultdict(set)
    for label, year, month, pax in _read_domestic_rows(raw_domestic):
        if label and resolver.resolve(label, year, month) is None:
            pax_by_label[label.upper()] += pax
            years[label.upper()].add(year)

    flagged = []
    for label, total in pax_by_label.items():
        per_year = total / max(1, len(years[label]))
        if per_year >= UNMAPPED_PAX_THRESHOLD:
            flagged.append((label, int(per_year)))
    if flagged:
        flagged.sort(key=lambda x: -x[1])
        return [_warn("unmapped.high_volume",
                      f"{len(flagged)} unmapped domestic label(s) >{UNMAPPED_PAX_THRESHOLD:,}/yr: "
                      + ", ".join(f"{l} (~{p:,}/yr)" for l, p in flagged[:5]))]
    return [_ok("unmapped.high_volume", "ADVISORY",
               "no high-volume unmapped domestic labels")]
