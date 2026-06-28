"""Tests for the assumptions-ledger engine + reverse gate."""

from pathlib import Path

import pytest
import yaml

import validate.assumptions as A

ROOT = Path(__file__).resolve().parent.parent
RAW_DOMESTIC = ROOT / "data" / "raw" / "aviation" / "aggregated" / "domestic" / "city.csv"
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

# The ledger is re-tested against raw DGCA data (gitignored; cache-restored in CI).
requires_raw = pytest.mark.skipif(
    not RAW_DOMESTIC.exists(),
    reason="raw DGCA data not present (gitignored; restored from cache in CI)",
)


@requires_raw
def test_all_committed_assumptions_hold():
    results = A.evaluate(A.load_assumptions(), MAPPINGS)
    triggered = [r for r in results if r["verdict"] == "TRIGGERED"]
    assert not triggered, f"committed assumptions must hold, got: {triggered}"
    assert len(results) >= 5


def test_size_ordering_triggers_when_reversed():
    fake = [{"id": "X", "frontmatter": {
        "falsification": "size-ordering-holds",
        "params": {"bigger": "GOX", "smaller": "GOI"},  # deliberately wrong
        "covers": ["GOI", "GOX"]}}]
    assert A.evaluate(fake, MAPPINGS)[0]["verdict"] == "TRIGGERED"


@requires_raw
def test_reverse_gate_blocks_undocumented_concurrent_merge():
    # Drop the COK assumption file -> its concurrent merge becomes undocumented.
    without_cok = [a for a in A.load_assumptions() if a["id"] != "COK-001"]
    fails = [f for f in A.reverse_gate(without_cok, MAPPINGS) if f.status == "fail"]
    assert any("COK" in f.check for f in fails)


@requires_raw
def test_reverse_gate_passes_with_full_bundle():
    fails = [f for f in A.reverse_gate(A.load_assumptions(), MAPPINGS) if f.status == "fail"]
    assert not fails


def test_okf_files_have_required_frontmatter():
    for a in A.load_assumptions():
        fm = a["frontmatter"]
        assert fm.get("type") == "cleanup-assumption", a["id"]
        assert fm.get("falsification") in A.TESTS, a["id"]
        # `covers` lists the airport canonicals an assumption documents for the
        # reverse gate; it may be empty for non-airport policies (e.g. airlines).
        assert isinstance(fm.get("covers"), list), a["id"]


def test_airline_link_not_collapse_holds():
    results = {r["id"]: r for r in A.evaluate(A.load_assumptions(), MAPPINGS)}
    assert results["AIRLINE-001"]["verdict"] == "HOLDS"


def test_airline_assumption_triggers_if_a_brand_is_collapsed():
    fake = [{"id": "X", "frontmatter": {
        "falsification": "airlines-linked-not-collapsed",
        "params": {"airlines": ["Vistara", "Nonexistent Air"]},
        "covers": []}}]
    assert A.evaluate(fake, MAPPINGS)[0]["verdict"] == "TRIGGERED"
