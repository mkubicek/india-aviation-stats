"""Tests for the clean stage (table-driven resolution + cadence-split helpers)."""

import pandas as pd

from process import (
    _finalize,
    build_yearly,
    resolve_airport,
    source_csv,
)


def test_resolve_airport_uses_table_and_aliases():
    # City name resolves via the entity table; alternate spellings via airport_aliases.
    assert resolve_airport("Bengaluru", 2024, 6) == "BLR"
    assert resolve_airport("BOMBAY", 2024, 6) == "BOM"
    assert resolve_airport("TRIVANDRUM", 2024, 6) == "TRV"


def test_resolve_airport_is_period_aware_for_goa():
    assert resolve_airport("GOA", 2017, 6) == "GOI"   # Dabolim era
    assert resolve_airport("GOA", 2024, 6) == "GOX"   # Mopa era


def test_resolve_airport_returns_none_for_foreign_city():
    # Foreign counterpart cities are unmapped and dropped by Layer 2.
    assert resolve_airport("DUBAI", 2024, 6) is None


def test_source_csv_points_to_direct_aviation_aggregate():
    path = source_csv("domestic/city.csv")
    assert path.as_posix().endswith("data/raw/aviation/aggregated/domestic/city.csv")


def test_finalize_dedups_and_keeps_integer_conservation():
    rows = pd.DataFrame(
        [
            {"year": 2025, "month": 1, "airport": "COK", "departures": 6.0, "arrivals": 4.0},
            {"year": 2025, "month": 1, "airport": "COK", "departures": 7.0, "arrivals": 13.0},
        ]
    )
    result = _finalize(rows, ["year", "month", "airport"])
    assert len(result) == 1
    row = result.iloc[0]
    assert row["departures"] == 13 and row["arrivals"] == 17
    assert row["passengers"] == 30                       # recomputed as dep + arr
    assert result["passengers"].dtype == "int64"
    assert (result["passengers"] == result["departures"] + result["arrivals"]).all()


def test_build_yearly_keeps_only_complete_years():
    # 2024 has all 12 months (complete); 2025 has only 1 month (dropped).
    monthly = pd.concat(
        [
            pd.DataFrame(
                {"year": 2024, "month": list(range(1, 13)), "airport": "DEL",
                 "passengers": 100, "departures": 50, "arrivals": 50}
            ),
            pd.DataFrame(
                [{"year": 2025, "month": 1, "airport": "DEL",
                  "passengers": 100, "departures": 50, "arrivals": 50}]
            ),
        ],
        ignore_index=True,
    )
    yearly = build_yearly(monthly, None)
    assert set(yearly["year"]) == {2024}
    assert yearly.iloc[0]["passengers"] == 1200
    assert yearly.iloc[0]["category"] == "domestic"
    assert "tier" not in yearly.columns
