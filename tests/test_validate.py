"""Tests for scripts/validate.py — focus on check_milestone_stability."""

import json

import pytest

from validate import check_milestone_stability


@pytest.fixture(autouse=True)
def isolate_dirs(tmp_path, monkeypatch):
    """Redirect PROCESSED_DIR and SNAPSHOTS_DIR to a tmp tree so tests don't
    touch real repo data."""
    import validate

    processed = tmp_path / "processed"
    processed.mkdir()
    snapshots = processed / "snapshots"
    snapshots.mkdir()
    (snapshots / "releases").mkdir()

    monkeypatch.setattr(validate, "PROCESSED_DIR", processed)
    monkeypatch.setattr(validate, "SNAPSHOTS_DIR", snapshots)
    return processed, snapshots


def _write(path, obj):
    path.write_text(json.dumps(obj))


def test_no_milestones_file_silent(isolate_dirs):
    """No milestones.json → no warnings, no crash."""
    assert check_milestone_stability() == []


def test_no_prior_snapshot_silent(isolate_dirs):
    """milestones.json present but snapshots/releases/ empty → silent."""
    processed, _ = isolate_dirs
    _write(
        processed / "milestones.json",
        {"projected": {"india_500m": {"p50_year": 2031}}},
    )
    assert check_milestone_stability() == []


def test_drift_within_threshold_silent(isolate_dirs):
    """p50 drift of 1 year → silent (threshold is >1)."""
    processed, snapshots = isolate_dirs
    _write(processed / "milestones.json", {"projected": {"m1": {"p50_year": 2032}}})
    _write(snapshots / "releases" / "2026-04.json", {"projected": {"m1": {"p50_year": 2031}}})
    assert check_milestone_stability() == []


def test_drift_beyond_threshold_warns(isolate_dirs):
    """p50 drift of 2 years → warning line."""
    processed, snapshots = isolate_dirs
    _write(processed / "milestones.json", {"projected": {"m1": {"p50_year": 2033}}})
    _write(snapshots / "releases" / "2026-04.json", {"projected": {"m1": {"p50_year": 2031}}})
    warnings = check_milestone_stability()
    assert len(warnings) == 1
    assert "m1" in warnings[0]
    assert "2031" in warnings[0]
    assert "2033" in warnings[0]


def test_drift_earlier_direction_labeled(isolate_dirs):
    """Drift where current < prior is labeled 'earlier'."""
    processed, snapshots = isolate_dirs
    _write(processed / "milestones.json", {"projected": {"m1": {"p50_year": 2029}}})
    _write(snapshots / "releases" / "2026-04.json", {"projected": {"m1": {"p50_year": 2032}}})
    warnings = check_milestone_stability()
    assert len(warnings) == 1
    assert "earlier" in warnings[0]


def test_new_milestone_not_in_prior_is_silent(isolate_dirs):
    """A milestone added after the prior snapshot → no warning, just skipped."""
    processed, snapshots = isolate_dirs
    _write(
        processed / "milestones.json",
        {"projected": {"m1": {"p50_year": 2031}, "m2_new": {"p50_year": 2035}}},
    )
    _write(snapshots / "releases" / "2026-04.json", {"projected": {"m1": {"p50_year": 2031}}})
    assert check_milestone_stability() == []


def test_null_p50_skipped(isolate_dirs):
    """beyond_horizon milestones (p50_year=null) don't raise and don't warn."""
    processed, snapshots = isolate_dirs
    _write(
        processed / "milestones.json",
        {"projected": {"m1": {"p50_year": None, "status": "beyond_horizon"}}},
    )
    _write(snapshots / "releases" / "2026-04.json", {"projected": {"m1": {"p50_year": 2031}}})
    assert check_milestone_stability() == []


def test_corrupt_snapshot_warns_no_crash(isolate_dirs):
    """A truncated snapshot file logs a warning, does not crash pipeline."""
    processed, snapshots = isolate_dirs
    _write(processed / "milestones.json", {"projected": {"m1": {"p50_year": 2031}}})
    (snapshots / "releases" / "2026-04.json").write_text('{"projected": {')  # truncated
    warnings = check_milestone_stability()
    assert len(warnings) == 1
    assert "unreadable" in warnings[0]


def test_uses_most_recent_snapshot(isolate_dirs):
    """With multiple release snapshots, the most recent (lexical sort) is used."""
    processed, snapshots = isolate_dirs
    releases = snapshots / "releases"
    _write(processed / "milestones.json", {"projected": {"m1": {"p50_year": 2033}}})
    _write(releases / "2025-10.json", {"projected": {"m1": {"p50_year": 2033}}})  # matches
    _write(releases / "2026-04.json", {"projected": {"m1": {"p50_year": 2031}}})  # drifts
    # 2026-04 sorts after 2025-10 and is the "most recent"; drift=2 should warn
    warnings = check_milestone_stability()
    assert len(warnings) == 1
    assert "2026-04.json" in warnings[0]
