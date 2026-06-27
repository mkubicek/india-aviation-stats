"""Tests for source processing helpers."""

import pandas as pd

from process import aggregate_airport_periods, city_to_iata, source_csv


def test_city_to_iata_aliases_common_city_names():
    assert city_to_iata("Bengaluru") == "BLR"
    assert city_to_iata("Bombay") == "BOM"
    assert city_to_iata("Trivandrum") == "TRV"


def test_city_to_iata_keeps_unknown_as_uppercase_source_name():
    assert city_to_iata("Unknown Field") == "UNKNOWN FIELD"


def test_source_csv_points_to_direct_aviation_aggregate():
    path = source_csv("domestic/city.csv")
    assert path.as_posix().endswith("data/raw/aviation/aggregated/domestic/city.csv")


def test_aggregate_airport_periods_merges_duplicate_mapped_airports():
    rows = pd.DataFrame(
        [
            {
                "year": 2025,
                "month": 1,
                "airport": "COK",
                "category": "domestic",
                "passengers": 10,
                "departures": 6,
                "arrivals": 4,
            },
            {
                "year": 2025,
                "month": 1,
                "airport": "COK",
                "category": "domestic",
                "passengers": 20,
                "departures": 7,
                "arrivals": 13,
            },
        ]
    )

    result = aggregate_airport_periods(rows)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["passengers"] == 30
    assert row["departures"] == 13
    assert row["arrivals"] == 17
