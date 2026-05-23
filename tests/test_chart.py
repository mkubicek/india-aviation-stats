"""Tests for chart data selection helpers."""

import pandas as pd

from chart import _complete_airport_years, _domestic_trailing_airport_passengers


def test_complete_airport_years_requires_domestic_months_and_international_quarters():
    rows = []
    for month in range(1, 13):
        rows.append(
            {
                "year": 2025,
                "month": month,
                "category": "domestic",
            }
        )
    for month in [2, 5, 8, 11]:
        rows.append(
            {
                "year": 2025,
                "month": month,
                "category": "international",
            }
        )
    for month in range(1, 12):
        rows.append(
            {
                "year": 2026,
                "month": month,
                "category": "domestic",
            }
        )
    for month in [2, 5, 8, 11]:
        rows.append(
            {
                "year": 2026,
                "month": month,
                "category": "international",
            }
        )

    assert _complete_airport_years(pd.DataFrame(rows)) == [2025]


def test_domestic_trailing_airport_passengers_requires_complete_windows():
    rows = []
    for month in range(1, 14):
        year = 2025 if month <= 12 else 2026
        real_month = month if month <= 12 else 1
        rows.extend(
            [
                {
                    "year": year,
                    "month": real_month,
                    "airport": "DEL",
                    "category": "domestic",
                    "passengers": 10,
                },
                {
                    "year": year,
                    "month": real_month,
                    "airport": "BOM",
                    "category": "domestic",
                    "passengers": 5,
                },
            ]
        )

    trailing = _domestic_trailing_airport_passengers(pd.DataFrame(rows))

    assert list(trailing.index.astype(str)) == ["2025-12", "2026-01"]
    assert trailing.loc[pd.Period("2025-12", freq="M"), "DEL"] == 120
    assert trailing.loc[pd.Period("2026-01", freq="M"), "BOM"] == 60
