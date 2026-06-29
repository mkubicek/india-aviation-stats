#!/usr/bin/env python3
"""Passenger metric semantics for the canonical aviation tables.

The same column name — ``passengers`` — means different things in different
published tables, and conflating them is a real reporting bug. This module is the
single home for that distinction so chart/dashboard code cannot accidentally sum
the wrong layer.

Two passenger layers matter for national totals:

* **Carrier passengers carried** (``carrier_monthly.csv``) — each journey is
  counted once, by the operating airline. This is the correct national
  domestic-demand metric.
* **Airport endpoint throughput** (``airport_monthly.csv``) — each domestic
  journey is counted twice, once at the origin airport (a departure) and once at
  the destination airport (an arrival). Correct for airport-level analysis; it is
  roughly ``2 × passengers carried`` when summed nationally.

A third layer, the international quarterly table, is **Indian gateway throughput**:
endpoint traffic at Indian airports only (foreign counterpart cities are dropped).

See ``METHODOLOGY.md`` → "Passenger metric semantics" and ``docs/data-dictionary.md``.
"""

from __future__ import annotations

import pandas as pd

SCHEDULED_DOMESTIC = "scheduled_domestic"


def add_month_period(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a monthly ``period`` column from integer ``year``/``month``."""
    out = df.copy()
    out["period"] = pd.to_datetime(
        {
            "year": out["year"].astype(int),
            "month": out["month"].astype(int),
            "day": 1,
        }
    ).dt.to_period("M")
    return out


def add_quarter_period(df: pd.DataFrame) -> pd.DataFrame:
    """Attach a quarterly ``period`` column from integer ``year``/``quarter``."""
    out = df.copy()
    out["period"] = pd.PeriodIndex(
        out["year"].astype(int).astype(str) + "Q" + out["quarter"].astype(int).astype(str),
        freq="Q",
    )
    return out


def domestic_airline_passengers_carried(carrier: pd.DataFrame) -> pd.Series:
    """Monthly scheduled-domestic passengers carried by airlines.

    Returns one value per month, indexed by a monthly ``PeriodIndex``. Each
    passenger journey is counted once. **This is the correct national
    domestic-demand metric** and is what national passenger-carried charts/KPIs
    must use — never a national sum of airport endpoint throughput.
    """
    c = add_month_period(carrier)
    scheduled_domestic = c[c["service_type"] == SCHEDULED_DOMESTIC]
    return scheduled_domestic.groupby("period")["passengers"].sum().sort_index()


def domestic_airport_matrix(monthly: pd.DataFrame) -> pd.DataFrame:
    """Airport-by-month endpoint-throughput matrix for airport-level charts.

    Rows are months, columns are airports, values are endpoint throughput
    (``departures + arrivals``). Missing cells are filled with 0.
    """
    m = add_month_period(monthly)
    grouped = m.groupby(["period", "airport"], as_index=False)["passengers"].sum()
    return (
        grouped.pivot(index="period", columns="airport", values="passengers")
        .fillna(0)
        .sort_index()
    )


def domestic_airport_throughput(monthly: pd.DataFrame) -> pd.Series:
    """Monthly domestic airport passenger movements (arrivals + departures).

    Returns one value per month across all Indian airport endpoints. This is
    endpoint throughput, **not** passengers carried: summed nationally it
    double-counts each domestic journey. Do not label it as passengers carried.
    """
    m = add_month_period(monthly)
    return m.groupby("period")["passengers"].sum().sort_index()


def international_gateway_matrix(quarterly: pd.DataFrame) -> pd.DataFrame:
    """Gateway-by-quarter endpoint-throughput matrix for Indian gateways."""
    q = add_quarter_period(quarterly)
    grouped = q.groupby(["period", "airport"], as_index=False)["passengers"].sum()
    return (
        grouped.pivot(index="period", columns="airport", values="passengers")
        .fillna(0)
        .sort_index()
    )


def international_gateway_throughput(quarterly: pd.DataFrame) -> pd.Series:
    """Quarterly Indian international gateway passenger throughput.

    Endpoint traffic at Indian airports only — foreign counterpart cities are
    dropped upstream, so this is Indian gateway traffic, not foreign-airport
    totals and not airline-carried passengers.
    """
    q = add_quarter_period(quarterly)
    return q.groupby("period")["passengers"].sum().sort_index()
