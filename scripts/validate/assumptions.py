"""The assumptions-ledger engine + reverse gate.

Reads the static OKF files in ``assumptions/`` as **read-only** input and writes a
*fresh* verdict each run (verdicts live in the report + DATA_QUALITY.md, never
written back into the files, so the knowledge base stays diff-clean). Two jobs:

1. Re-run each file's named ``falsification`` test against current data →
   ``HOLDS`` / ``TRIGGERED`` (new evidence contradicts → BLOCKING) /
   ``STALE`` (recheck date passed → advisory) / ``ORPHANED`` (the quirk vanished
   → advisory).
2. **Reverse gate (completeness by construction):** any anomaly the mechanical
   checks surface — a concurrent same-canonical merge, a high-volume unmapped
   name — that has *no* covering assumption file is an undocumented quirk →
   BLOCKING. Nothing weird stays silent.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from entities import build_airport_resolver

from .checks import Finding, _fail, _ok, _warn
from .overlap import _read_domestic_rows

ROOT = Path(__file__).resolve().parent.parent.parent
ASSUMPTIONS_DIR = ROOT / "assumptions"
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
DATA_QUALITY_PATH = PROCESSED_DIR / "DATA_QUALITY.md"
INDEX_PATH = ASSUMPTIONS_DIR / "index.md"


# ── OKF parsing ──────────────────────────────────────────────


def parse_okf(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---"):
        return {"id": path.stem, "frontmatter": {}, "body": text}
    _, fm, body = text.split("---", 2)
    return {"id": path.stem, "frontmatter": yaml.safe_load(fm) or {}, "body": body.strip()}


def load_assumptions() -> list[dict]:
    return [parse_okf(p) for p in sorted(ASSUMPTIONS_DIR.glob("*.md")) if p.name != "index.md"]


# ── data accessors ───────────────────────────────────────────


def _layer1() -> pd.DataFrame:
    path = PROCESSED_DIR / "airport_monthly.csv"
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _carrier_airlines() -> set[str]:
    """Distinct airline entities present in carrier_monthly (the carrier table)."""
    path = PROCESSED_DIR / "carrier_monthly.csv"
    if not path.exists():
        return set()
    return set(pd.read_csv(path)["airline"].astype(str).unique())


def _label_months() -> dict[str, set]:
    """raw domestic source label (upper) -> set of (year, month) it appears in."""
    out: dict[str, set] = defaultdict(set)
    if RAW_DOMESTIC.exists():
        for label, year, month, _ in _read_domestic_rows(RAW_DOMESTIC):
            if label:
                out[label.upper()].add((year, month))
    return out


# ── named falsification-test library (prose + named test, never embedded code) ──


def _t_size_ordering(params, ctx) -> tuple[str, str]:
    totals = ctx["totals"]
    big, small = params["bigger"], params["smaller"]
    if big not in totals or small not in totals:
        return "TRIGGERED", f"{big} or {small} absent from the domestic-monthly table (possible erase/merge)"
    if totals[big] >= totals[small]:
        return "HOLDS", f"{big} ({totals[big]:,}) >= {small} ({totals[small]:,})"
    return "TRIGGERED", f"size ordering broke: {small} ({totals[small]:,}) > {big} ({totals[big]:,})"


def _t_distinct(params, ctx) -> tuple[str, str]:
    totals = ctx["totals"]
    missing = [a for a in params["airports"] if a not in totals]
    if missing:
        return "TRIGGERED", f"airports merged/erased: {missing} absent from the domestic-monthly table"
    return "HOLDS", f"{params['airports']} all present and distinct"


def _t_month_disjoint(params, ctx) -> tuple[str, str]:
    lm = ctx["label_months"]
    labels = [str(x).upper() for x in params["labels"]]
    present = [l for l in labels if lm.get(l)]
    # pairwise month-overlap
    for i in range(len(present)):
        for j in range(i + 1, len(present)):
            shared = lm[present[i]] & lm[present[j]]
            if shared:
                ex = sorted(shared)[0]
                return "TRIGGERED", (f"{present[i]} and {present[j]} co-occur in "
                                     f"{ex[0]}-{ex[1]:02d} — not a clean disjoint rename")
    if not present:
        return "ORPHANED", f"none of {labels} present in the data"
    return "HOLDS", f"{present} are month-disjoint"


def _t_concurrent_declared(params, ctx) -> tuple[str, str]:
    lm = ctx["label_months"]
    labels = [str(x).upper() for x in params["labels"]]
    declared = ctx["declared_concurrent"].get(params["airport"], set())
    # do the labels still co-occur?
    co = False
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            if lm.get(labels[i], set()) & lm.get(labels[j], set()):
                co = True
    if not co:
        return "ORPHANED", f"{labels} no longer co-occur for {params['airport']}"
    if set(labels) <= declared:
        return "HOLDS", f"{labels} declared as one airport ({params['airport']})"
    return "TRIGGERED", f"{labels} co-occur for {params['airport']} but are not declared"


def _t_airlines_distinct(params, ctx) -> tuple[str, str]:
    present = ctx["airlines"]
    names = [str(x) for x in params["airlines"]]
    if not present:
        return "ORPHANED", "carrier_monthly absent — cannot check airline identity"
    missing = [a for a in names if a not in present]
    if missing:
        return "TRIGGERED", f"airline(s) collapsed/erased: {missing} absent from carrier_monthly"
    return "HOLDS", f"{names} all present as distinct airlines"


TESTS = {
    "size-ordering-holds": _t_size_ordering,
    "distinct-airports-not-merged": _t_distinct,
    "month-disjoint-rename": _t_month_disjoint,
    "concurrent-merge-declared": _t_concurrent_declared,
    "airlines-linked-not-collapsed": _t_airlines_distinct,
}


# ── engine ───────────────────────────────────────────────────


def _context(mappings: dict) -> dict:
    l1 = _layer1()
    totals = {} if l1.empty else l1.groupby("airport")["passengers"].sum().to_dict()
    declared = {e["airport"]: set(x.upper() for x in e["labels"])
                for e in (mappings.get("concurrent_labels") or [])}
    return {
        "totals": totals,
        "label_months": _label_months(),
        "declared_concurrent": declared,
        "airlines": _carrier_airlines(),
    }


def evaluate(assumptions: list[dict], mappings: dict) -> list[dict]:
    ctx = _context(mappings)
    results = []
    for a in assumptions:
        fm = a["frontmatter"]
        name = fm.get("falsification")
        params = fm.get("params", {}) or {}
        recheck_by = fm.get("recheck_by")
        verdict, detail = "HOLDS", ""
        if name not in TESTS:
            verdict, detail = "TRIGGERED", f"unknown falsification test {name!r}"
        else:
            verdict, detail = TESTS[name](params, ctx)
        # staleness overlay (advisory) only if currently holding
        if verdict == "HOLDS" and recheck_by and str(recheck_by) < date.today().strftime("%Y-%m"):
            verdict, detail = "STALE", f"recheck_by {recheck_by} passed"
        results.append({
            "id": a["id"],
            "title": fm.get("title", a["id"]),
            "category": fm.get("category", ""),
            "test": name,
            "verdict": verdict,
            "detail": detail,
            "covers": fm.get("covers", []),
        })
    return results


def reverse_gate(assumptions: list[dict], mappings: dict) -> list[Finding]:
    """Every anomaly the mechanical checks surface must have a covering file."""
    covered = set()
    for a in assumptions:
        covered |= set(a["frontmatter"].get("covers", []))

    findings = []
    # concurrent merges (from the overlap gate's perspective)
    resolver = build_airport_resolver(mappings, extra_aliases=mappings.get("airport_aliases"))
    per_month = defaultdict(lambda: defaultdict(set))
    if RAW_DOMESTIC.exists():
        for label, year, month, _ in _read_domestic_rows(RAW_DOMESTIC):
            if not label:
                continue
            k = resolver.resolve(label, year, month)
            if k:
                per_month[k][(year, month)].add(label.upper())
    for canon, months in sorted(per_month.items()):
        if any(len(ls) > 1 for ls in months.values()):
            if canon not in covered:
                findings.append(_fail(f"reverse_gate.undocumented.{canon}", "BLOCKING",
                                      f"{canon} has a concurrent same-canonical merge with no "
                                      f"covering assumptions/ file — document it or clean it"))
    if not findings:
        findings.append(_ok("reverse_gate", "BLOCKING",
                            "every concurrent merge has a covering assumption file"))
    return findings


def generate_index(results: list[dict]) -> None:
    lines = ["# Assumptions index", "",
             "Routing table for the cleanup knowledge base (OKF bundle). Verdicts are",
             "recomputed by `validate --assumptions` and shown in `data/processed/DATA_QUALITY.md`;",
             "they are not written back into these files.", "",
             "| id | title | category | → file |", "| --- | --- | --- | --- |"]
    for r in sorted(results, key=lambda x: x["id"]):
        lines.append(f"| {r['id']} | {r['title']} | {r['category']} | [{r['id']}.md]({r['id']}.md) |")
    INDEX_PATH.write_text("\n".join(lines) + "\n")


def generate_data_quality(results: list[dict], reverse: list[Finding]) -> None:
    today = date.today().isoformat()
    lines = ["# Data quality", "",
             f"Auto-generated by `validate --assumptions` on {today}. Each cleanup",
             "assumption is re-tested against the current data on every refresh.", "",
             "| id | verdict | title | detail |", "| --- | --- | --- | --- |"]
    badge = {"HOLDS": "✅ HOLDS", "TRIGGERED": "🛑 TRIGGERED",
             "STALE": "🟡 STALE", "ORPHANED": "⚪ ORPHANED"}
    for r in sorted(results, key=lambda x: x["id"]):
        lines.append(f"| {r['id']} | {badge.get(r['verdict'], r['verdict'])} | {r['title']} | {r['detail']} |")
    rg_fail = [f for f in reverse if f.status == "fail"]
    lines += ["", "## Reverse gate", "",
              ("🛑 " + str(len(rg_fail)) + " undocumented quirk(s): "
               + "; ".join(f.message for f in rg_fail)) if rg_fail
              else "✅ No undocumented quirks — every anomaly has a covering assumption file."]
    DATA_QUALITY_PATH.write_text("\n".join(lines) + "\n")


def run_assumptions(write: bool = True) -> int:
    print("\n=== Assumptions ledger ===\n", flush=True)
    mappings = yaml.safe_load((ROOT / "mappings.yaml").read_text())
    assumptions = load_assumptions()
    results = evaluate(assumptions, mappings)
    reverse = reverse_gate(assumptions, mappings)

    if write:
        generate_index(results)
        generate_data_quality(results, reverse)
        report_path = PROCESSED_DIR / "validation_report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        report["assumptions"] = results
        report["reverse_gate"] = [f.as_dict() for f in reverse]
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    for r in results:
        if r["verdict"] != "HOLDS":
            print(f"  [{r['verdict']}] {r['id']}: {r['detail']}", flush=True)
    triggered = [r for r in results if r["verdict"] == "TRIGGERED"]
    rg_fail = [f for f in reverse if f.status == "fail"]
    for f in rg_fail:
        print(f"  [FAIL/BLOCKING] {f.check}: {f.message}", flush=True)

    print(f"\n  {len(results)} assumption(s): "
          f"{sum(1 for r in results if r['verdict']=='HOLDS')} hold, "
          f"{len(triggered)} triggered, "
          f"{sum(1 for r in results if r['verdict']=='STALE')} stale, "
          f"{sum(1 for r in results if r['verdict']=='ORPHANED')} orphaned; "
          f"reverse gate: {len(rg_fail)} undocumented quirk(s)")
    return 1 if (triggered or rg_fail) else 0
