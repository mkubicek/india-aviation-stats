"""Tests for the git-diff revision log."""

import pandas as pd

from validate.revisions import compute_changes

KEY = ["year", "month", "airport"]


def _row(airport, pax, month=1):
    return {"year": 2026, "month": month, "airport": airport,
            "passengers": pax, "departures": pax // 2, "arrivals": pax - pax // 2}


def test_detects_restated_added_removed():
    old = pd.DataFrame([_row("DEL", 100), _row("BOM", 200), _row("OLD", 50)])
    new = pd.DataFrame([_row("DEL", 100), _row("BOM", 250), _row("NEW", 70)])
    changes = {c[1]: c for c in compute_changes(old, new, KEY)}

    assert "DEL" not in changes                      # unchanged -> not reported
    assert changes["BOM"][2:5] == (200, 250, "restated")
    assert changes["NEW"][2:5] == (None, 70, "added")
    assert changes["OLD"][2:5] == (50, None, "removed")


def test_identical_frames_have_no_changes():
    df = pd.DataFrame([_row("DEL", 100), _row("BOM", 200)])
    assert compute_changes(df, df.copy(), KEY) == []
