"""Tests for the assumptions-ledger engine + reverse gate."""

from pathlib import Path

import yaml

import validate.assumptions as A

ROOT = Path(__file__).resolve().parent.parent
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())


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


def test_reverse_gate_blocks_undocumented_concurrent_merge():
    # Drop the COK assumption file -> its concurrent merge becomes undocumented.
    without_cok = [a for a in A.load_assumptions() if a["id"] != "COK-001"]
    fails = [f for f in A.reverse_gate(without_cok, MAPPINGS) if f.status == "fail"]
    assert any("COK" in f.check for f in fails)


def test_reverse_gate_passes_with_full_bundle():
    fails = [f for f in A.reverse_gate(A.load_assumptions(), MAPPINGS) if f.status == "fail"]
    assert not fails


def test_okf_files_have_required_frontmatter():
    for a in A.load_assumptions():
        fm = a["frontmatter"]
        assert fm.get("type") == "cleanup-assumption", a["id"]
        assert fm.get("falsification") in A.TESTS, a["id"]
        assert fm.get("covers"), a["id"]
