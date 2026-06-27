"""Tests for advisory data validation helpers."""

import pandas as pd

from validate import (
    check_duplicate_airport_periods,
    check_domestic_month_coverage,
    check_international_quarter_coverage,
    check_negative_passengers,
)


def test_domestic_month_coverage_detects_missing_month():
    monthly = pd.DataFrame(
        [
            {"year": 2025, "month": 1, "category": "domestic", "passengers": 1},
            {"year": 2025, "month": 3, "category": "domestic", "passengers": 1},
        ]
    )

    warnings = check_domestic_month_coverage(monthly)

    assert warnings == ["coverage:domestic: missing 1 month(s): 2025-02"]


def test_domestic_month_coverage_accepts_continuous_months():
    monthly = pd.DataFrame(
        [
            {"year": 2025, "month": 1, "category": "domestic", "passengers": 1},
            {"year": 2025, "month": 2, "category": "domestic", "passengers": 1},
            {"year": 2025, "month": 3, "category": "domestic", "passengers": 1},
        ]
    )

    assert check_domestic_month_coverage(monthly) == []


def test_international_quarter_coverage_detects_missing_quarter():
    monthly = pd.DataFrame(
        [
            {"year": 2025, "month": 2, "category": "international", "passengers": 1},
            {"year": 2025, "month": 8, "category": "international", "passengers": 1},
        ]
    )

    warnings = check_international_quarter_coverage(monthly)

    assert warnings == ["coverage:international: missing 1 quarter(s): 2025-05"]


def test_negative_passengers_warns():
    monthly = pd.DataFrame(
        [
            {"year": 2025, "month": 1, "category": "domestic", "passengers": 1},
            {"year": 2025, "month": 2, "category": "domestic", "passengers": -1},
        ]
    )

    assert check_negative_passengers(monthly) == [
        "values:passengers: 1 negative passenger row(s)"
    ]


def test_duplicate_airport_periods_warns():
    monthly = pd.DataFrame(
        [
            {
                "year": 2025,
                "month": 1,
                "airport": "DEL",
                "category": "domestic",
                "passengers": 1,
            },
            {
                "year": 2025,
                "month": 1,
                "airport": "DEL",
                "category": "domestic",
                "passengers": 2,
            },
        ]
    )

    assert check_duplicate_airport_periods(monthly) == [
        "grain:airport_monthly: "
        "1 duplicate airport-period-category row(s): 2025-01:DEL:domestic"
    ]
