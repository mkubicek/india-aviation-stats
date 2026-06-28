"""Tests for the validation engine (validate/ package)."""

from pathlib import Path

import pandas as pd
import yaml

from validate.checks import (
    check_cadence,
    check_carrier,
    check_conservation_tripwire,
    check_definitional,
    check_schema,
)
from validate.overlap import check_unmapped_names, overlap_gate

ROOT = Path(__file__).resolve().parent.parent
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())


def _failed(findings):
    return [f for f in findings if f.status == "fail"]


# ── cadence ──

def test_cadence_flags_duplicate_layer1_rows():
    dup = pd.DataFrame(
        [{"year": 2024, "month": 1, "airport": "DEL",
          "passengers": 100, "departures": 50, "arrivals": 50}] * 2
    )
    assert any(f.check == "cadence.layer1_unique" for f in _failed(check_cadence(dup, None)))


def test_cadence_flags_bad_quarter_domain():
    q = pd.DataFrame(
        [{"year": 2024, "quarter": 7, "airport": "DEL",
          "passengers": 100, "departures": 50, "arrivals": 50}]
    )
    monthly = pd.DataFrame([{"year": 2024, "month": 1, "airport": "DEL",
                             "passengers": 100, "departures": 50, "arrivals": 50}])
    assert any(f.check == "cadence.layer2_quarter_domain" for f in _failed(check_cadence(monthly, q)))


# ── definitional ──

def test_definitional_flags_sum_break():
    bad = pd.DataFrame(
        [{"year": 2024, "month": 1, "airport": "DEL",
          "passengers": 99, "departures": 50, "arrivals": 50}]
    )
    assert any("sum" in f.check for f in _failed(check_definitional(bad, "l1")))


def test_definitional_flags_non_integer():
    flo = pd.DataFrame(
        [{"year": 2024, "month": 1, "airport": "DEL",
          "passengers": 100.0, "departures": 50.0, "arrivals": 50.0}]
    )
    assert any("int" in f.check for f in _failed(check_definitional(flo, "l1")))


# ── conservation tripwire ──

def test_conservation_tripwire_holds_by_construction():
    m = pd.DataFrame(
        [
            {"year": 2024, "month": 1, "airport": "DEL", "passengers": 10, "departures": 6, "arrivals": 4},
            {"year": 2024, "month": 1, "airport": "BOM", "passengers": 10, "departures": 4, "arrivals": 6},
        ]
    )
    assert not _failed(check_conservation_tripwire(m))


# ── overlap gate (the load-bearing check) ──

def test_overlap_gate_passes_with_declared_merge():
    assert not _failed(overlap_gate(MAPPINGS, RAW_DOMESTIC))


def test_overlap_gate_blocks_undeclared_concurrent_merge():
    stripped = dict(MAPPINGS)
    stripped["concurrent_labels"] = []
    fails = _failed(overlap_gate(stripped, RAW_DOMESTIC))
    assert fails, "removing the COCHIN/KOCHI declaration must red the gate"
    assert any("COK" in f.check for f in fails)


# ── advisory: high-volume unmapped names ──

def test_no_high_volume_unmapped_domestic_labels():
    assert not _failed(check_unmapped_names(MAPPINGS, RAW_DOMESTIC))


# ── Layer 4 carrier ──

def test_carrier_flags_load_factor_out_of_range():
    df = pd.DataFrame([
        {"airline": "IndiGo", "service_type": "scheduled_domestic", "year": 2024, "month": 1,
         "passenger_load_factor": 150.0, "weight_load_factor": 80.0},
    ])
    warns = [f for f in check_carrier(df) if f.status == "warn"]
    assert any("load_factor" in f.check for f in warns)


def test_carrier_flags_duplicate_key():
    df = pd.DataFrame([
        {"airline": "IndiGo", "service_type": "scheduled_domestic", "year": 2024, "month": 1,
         "passenger_load_factor": 80.0, "weight_load_factor": 70.0},
    ] * 2)
    assert any(f.check == "carrier.unique" for f in check_carrier(df) if f.status == "fail")


def test_published_carrier_is_tidy_and_links_not_collapses():
    df = pd.read_csv(ROOT / "data" / "processed" / "carrier_monthly.csv")
    assert list(df.columns)[:4] == ["airline", "service_type", "year", "month"]
    assert not df["airline"].isin(["Total Domestic", "Total International"]).any()
    assert "Airheritage" not in set(df["airline"])     # spelling canonicalized
    assert "Vistara" in set(df["airline"])             # merger linked, not collapsed
    assert int(df.duplicated(["airline", "service_type", "year", "month"]).sum()) == 0


# ── schema conformance against the real published layers ──

def test_published_layers_conform_to_schema():
    import json
    proc = ROOT / "data" / "processed"
    layers = {
        n: pd.read_csv(proc / f"{n}.csv")
        for n in ("airport_monthly", "airport_international_quarterly", "airport_yearly")
        if (proc / f"{n}.csv").exists()
    }
    meta = json.loads((proc / "metadata.json").read_text())
    assert not _failed(check_schema(layers, meta))
