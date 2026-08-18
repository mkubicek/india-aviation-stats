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


def test_counts_changes_outside_the_passenger_column():
    """A wholesale rewrite of a non-passenger column must not read as 'no changes'."""
    from validate.revisions import count_other_column_changes

    old = pd.DataFrame([
        {"airline": "IndiGo", "service_type": "scheduled_domestic", "year": 2026,
         "month": 7, "passengers": 100, "passenger_load_factor": 86.66},
        {"airline": "Akasa Air", "service_type": "scheduled_domestic", "year": 2026,
         "month": 7, "passengers": 50, "passenger_load_factor": 91.93},
    ])
    new = old.copy()
    new.loc[0, "passenger_load_factor"] = 86.66023056391617

    key = ["airline", "service_type", "year", "month"]
    assert compute_changes(old, new, key, ["airline", "service_type"]) == []
    assert count_other_column_changes(old, new, key) == 1
    assert count_other_column_changes(old, old.copy(), key) == 0


def test_entity_label_defaults_to_airport_and_joins_multi_column_entities():
    old = pd.DataFrame([{"year": 2026, "month": 7, "origin": "DXN",
                         "destination": "BOM", "passengers": 100}])
    new = pd.DataFrame([{"year": 2026, "month": 7, "origin": "DXN",
                         "destination": "BOM", "passengers": 120}])

    key = ["year", "month", "origin", "destination"]
    (period, label, old_p, new_p, kind), = compute_changes(old, new, key, ["origin", "destination"])
    assert label == "DXN · BOM"
    assert period == "2026-7-DXN-BOM"
    assert (old_p, new_p, kind) == (100, 120, "restated")


def test_diff_layer_refuses_a_non_unique_key():
    """(year, airport) is not unique in airport_yearly; a bad key would fabricate
    a cartesian product of changes in an unchanged file."""
    import pytest

    from validate.revisions import LAYERS, diff_layer

    assert LAYERS["airport_yearly"]["key"] == ["year", "airport", "category"]
    with pytest.raises(ValueError, match="share the diff key"):
        diff_layer("airport_yearly", {"key": ["year", "airport"], "entity": ["airport"]})
