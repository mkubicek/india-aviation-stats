"""Tests for chart generation helpers."""

import pandas as pd

from chart import (
    DISCLAIMER,
    _domestic_trailing_airport_passengers,
    find_risers,
)


def test_disclaimer_matches_project_required_text():
    assert DISCLAIMER == (
        "This is a personal open-source project. Views and analysis are my own "
        "and do not represent Flughafen Zürich AG, Noida International Airport, "
        "or any affiliated entity."
    )


def test_domestic_trailing_airport_passengers_requires_complete_windows():
    # Layer 1 is domestic-only (no category column).
    rows = []
    for month in range(1, 14):
        year = 2025 if month <= 12 else 2026
        real_month = month if month <= 12 else 1
        rows.extend([
            {"year": year, "month": real_month, "airport": "DEL", "passengers": 10},
            {"year": year, "month": real_month, "airport": "BOM", "passengers": 5},
        ])
    trailing = _domestic_trailing_airport_passengers(pd.DataFrame(rows))
    assert list(trailing.index.astype(str)) == ["2025-12", "2026-01"]
    assert trailing.loc[pd.Period("2025-12", freq="M"), "DEL"] == 120
    assert trailing.loc[pd.Period("2026-01", freq="M"), "BOM"] == 60


def test_find_risers_excludes_old_airports_and_renames():
    # DEL has data since 2015 (established) -> not a riser even though it is huge.
    # NEW first appears 2024 with strong recent volume -> a genuine newcomer.
    rows = []
    for y in range(2015, 2027):
        rows.append({"year": y, "month": 1, "airport": "DEL", "passengers": 1_000_000})
    for ym in [(2024, 6), (2025, 6), (2026, 1), (2026, 5)]:
        rows.append({"year": ym[0], "month": ym[1], "airport": "NEW", "passengers": 80_000})
    risers = find_risers(pd.DataFrame(rows))
    assert "NEW" in risers
    assert "DEL" not in risers


def test_find_risers_drops_tiny_newcomers():
    rows = [{"year": 2025, "month": m, "airport": "TINY", "passengers": 100} for m in range(1, 13)]
    assert "TINY" not in find_risers(pd.DataFrame(rows))
