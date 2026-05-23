"""Tests for source processing helpers."""

import pandas as pd

from process import aggregate_carrier_yearly_passengers


def test_aggregate_carrier_yearly_prefers_total_rows():
    rows = []
    for month in range(1, 13):
        rows.extend(
            [
                {
                    "Year": 2025,
                    "Month": month,
                    "Type": "ScheduledDomestic",
                    "Airline": "IndiGo",
                    "Passenger Number": 60,
                },
                {
                    "Year": 2025,
                    "Month": month,
                    "Type": "ScheduledDomestic",
                    "Airline": "Air India",
                    "Passenger Number": 40,
                },
                {
                    "Year": 2025,
                    "Month": month,
                    "Type": "ScheduledDomestic",
                    "Airline": "Total Domestic",
                    "Passenger Number": 100,
                },
            ]
        )
    df = pd.DataFrame(rows)

    yearly = aggregate_carrier_yearly_passengers(df)

    assert yearly.to_dict("records") == [{"year": 2025, "carrier_pax": 1200}]


def test_aggregate_carrier_yearly_falls_back_without_total_rows():
    rows = []
    for month in range(1, 13):
        rows.extend(
            [
                {
                    "Year": 2025,
                    "Month": month,
                    "Type": "ScheduledDomestic",
                    "Airline": "IndiGo",
                    "Passenger Number": 60,
                },
                {
                    "Year": 2025,
                    "Month": month,
                    "Type": "ScheduledDomestic",
                    "Airline": "Air India",
                    "Passenger Number": 40,
                },
            ]
        )
    df = pd.DataFrame(rows)

    yearly = aggregate_carrier_yearly_passengers(df)

    assert yearly.to_dict("records") == [{"year": 2025, "carrier_pax": 1200}]
