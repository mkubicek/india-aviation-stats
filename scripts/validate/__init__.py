"""Validation engine for the canonical aviation tables.

``run()`` loads the published tables + entity tables, runs the mechanical checks
and the overlap-classification gate, writes a machine-readable
``validation_report.json`` and a human-readable ``warnings.log``, and returns a
process exit code (non-zero iff a BLOCKING check failed). The assumptions ledger
(``--assumptions``) and revision log are added in their own modules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from .checks import (
    Finding,
    check_cadence,
    check_carrier,
    check_conservation_tripwire,
    check_coverage,
    check_definitional,
    check_metric_semantics,
    check_schema,
)
from .overlap import check_unmapped_names, overlap_gate

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
WARNINGS_PATH = ROOT / "warnings.log"
REPORT_PATH = PROCESSED_DIR / "validation_report.json"

__all__ = [
    "Finding", "run", "collect_findings",
    "check_cadence", "check_definitional", "check_schema",
    "check_conservation_tripwire", "check_coverage", "check_carrier",
    "check_metric_semantics", "overlap_gate", "check_unmapped_names",
]


def _load_mappings() -> dict:
    return yaml.safe_load((ROOT / "mappings.yaml").read_text())


def _load_layer(name: str) -> pd.DataFrame | None:
    path = PROCESSED_DIR / f"{name}.csv"
    return pd.read_csv(path) if path.exists() else None


def collect_findings() -> list[Finding]:
    """Run every mechanical check + the overlap gate; return all findings."""
    mappings = _load_mappings()
    metadata = {}
    meta_path = PROCESSED_DIR / "metadata.json"
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text())

    monthly = _load_layer("airport_monthly")
    quarterly = _load_layer("airport_international_quarterly")
    yearly = _load_layer("airport_yearly")
    layers = {
        "airport_monthly": monthly,
        "airport_international_quarterly": quarterly,
        "airport_yearly": yearly,
    }

    findings: list[Finding] = []
    if monthly is None:
        findings.append(Finding("layers.present", "fail", "BLOCKING",
                                "airport_monthly.csv missing - run the clean stage"))
        return findings

    findings += check_cadence(monthly, quarterly)
    findings += check_definitional(monthly, "airport_monthly")
    if quarterly is not None:
        findings += check_definitional(quarterly, "airport_international_quarterly")
    findings += check_schema(layers, metadata)
    findings += check_conservation_tripwire(monthly)
    carrier = _load_layer("carrier_monthly")
    if carrier is not None:
        findings += check_carrier(carrier)
        findings += check_metric_semantics(monthly, carrier)
    if RAW_DOMESTIC.exists():
        findings += overlap_gate(mappings, RAW_DOMESTIC)
        findings += check_unmapped_names(mappings, RAW_DOMESTIC)
    findings += check_coverage(monthly, quarterly)
    return findings


def _summarize(findings: list[Finding]) -> dict:
    blocking = [f for f in findings if f.severity == "BLOCKING" and f.status == "fail"]
    tripwire = [f for f in findings if f.severity == "TRIPWIRE" and f.status == "fail"]
    advisories = [f for f in findings if f.status == "warn"]
    return {
        "blocking_failures": len(blocking),
        "tripwire_failures": len(tripwire),
        "advisories": len(advisories),
        "passed": sum(1 for f in findings if f.status == "pass"),
        "findings": [f.as_dict() for f in findings],
    }


def run(write: bool = True) -> int:
    print("=== Validating Data ===\n", flush=True)
    findings = collect_findings()
    report = _summarize(findings)

    if write:
        REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
        advisories = [f for f in findings if f.status == "warn"]
        WARNINGS_PATH.write_text(
            "\n".join(f"{f.check}: {f.message}" for f in advisories) + ("\n" if advisories else "")
        )

    for f in findings:
        if f.status != "pass":
            tag = "FAIL" if f.status == "fail" else "WARN"
            print(f"  [{tag}/{f.severity}] {f.check}: {f.message}", flush=True)

    print(f"\n  {report['passed']} passed, {report['blocking_failures']} blocking failure(s), "
          f"{report['tripwire_failures']} tripwire failure(s), {report['advisories']} advisory(ies)")
    blocking = report["blocking_failures"] + report["tripwire_failures"]
    print("\nDone." if blocking == 0 else f"\nFAILED: {blocking} blocking/tripwire failure(s).", flush=True)
    return 1 if blocking else 0
