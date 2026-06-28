"""Tests for triage mode — the advisory research worklist.

Triage is deterministic (no network); it only DETECTS + scaffolds. These tests
pin that: the shipped dataset triages to nothing, an unmapped high-volume label
surfaces, and the emitted OKF skeleton is parseable and names a real test.
"""

from pathlib import Path

import pytest
import yaml

import validate.assumptions as A
from validate.triage import _okf_skeleton, build_worklist

ROOT = Path(__file__).resolve().parent.parent
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

requires_raw = pytest.mark.skipif(
    not RAW_DOMESTIC.exists(),
    reason="raw DGCA data not present (gitignored; restored from cache in CI)",
)


@requires_raw
def test_clean_dataset_has_empty_triage_queue():
    # Every label in the shipped mappings is classified, so triage finds nothing.
    # If a future edit leaves something unclassified, this test surfaces it.
    assert build_worklist(MAPPINGS, RAW_DOMESTIC) == []


def test_unmapped_high_volume_label_is_queued(tmp_path):
    raw = tmp_path / "city.csv"
    raw.write_text(
        "year,month,City1,City2,PaxToCity2,PaxFromCity2\n"
        "2025,1,NONEXISTENT TESTONLY AIRPORT,DELHI,90000,90000\n"
    )
    items = build_worklist(MAPPINGS, raw)
    hits = [it for it in items if "NONEXISTENT TESTONLY AIRPORT" in it["labels"]]
    assert len(hits) == 1
    assert hits[0]["kind"] == "unmapped_high_volume"
    assert hits[0]["approx_pax_per_year"] >= 100_000
    # DELHI resolves to a real canonical, so it is never queued.
    assert not any("DELHI" in it["labels"] for it in items)


def test_below_threshold_label_is_not_queued(tmp_path):
    raw = tmp_path / "city.csv"
    raw.write_text(
        "year,month,City1,City2,PaxToCity2,PaxFromCity2\n"
        "2025,1,NONEXISTENT TESTONLY AIRPORT,DELHI,10,10\n"
    )
    assert build_worklist(MAPPINGS, raw) == []


def test_skeleton_is_parseable_okf_naming_a_real_test():
    skel = _okf_skeleton(
        title="t", category="mapping", falsification="month-disjoint-rename",
        covers=["XXX"], labels=["PURNEA", "PURNIA AIRPORT"], question="q?")
    assert skel.startswith("---")
    _, fm_text, body = skel.split("---", 2)
    fm = yaml.safe_load(fm_text)
    assert fm["falsification"] in A.TESTS          # the draft points at a real test
    assert isinstance(fm["covers"], list)
    assert fm["params"]["labels"] == ["PURNEA", "PURNIA AIRPORT"]
    assert "NEEDS-HUMAN-REVIEW" in fm["tags"]       # a draft is visibly unfinished
    assert "TODO" in body
