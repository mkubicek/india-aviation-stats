#!/usr/bin/env python3
"""Passenger metric semantics for the canonical aviation tables.

The same column name - ``passengers`` - means different things in different
published tables, and conflating them is a real reporting bug. This module is the
single home for that distinction so chart/dashboard code cannot accidentally sum
the wrong layer.

Two passenger layers matter for national totals:

* **Carrier passengers carried** (``carrier_monthly.csv``) - each journey is
  counted once, by the operating airline. This is the correct national
  domestic-demand metric.
* **Airport endpoint throughput** (``airport_monthly.csv``) - each domestic
  journey is counted twice, once at the origin airport (a departure) and once at
  the destination airport (an arrival). Correct for airport-level analysis; it is
  roughly ``2 × passengers carried`` when summed nationally.

A third layer, the international quarterly table, is **Indian gateway throughput**:
endpoint traffic at Indian airports only (foreign counterpart cities are dropped).

See ``METHODOLOGY.md`` → "Passenger metric semantics" and ``docs/data-dictionary.md``.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd

SCHEDULED_DOMESTIC = "scheduled_domestic"

# Months with no published carrier rows that are documented REAL zeros, not
# data gaps: 2020-04 is India's COVID lockdown (scheduled domestic grounded;
# airport_monthly carries the same month as 0). Every other unpublished month
# is treated as missing - filling it with 0 would fabricate a demand collapse
# in every trailing window that spans it.
KNOWN_ZERO_MONTHS = (pd.Period("2020-04", freq="M"),)

# Conservation tolerance: national airport throughput should be ~2× scheduled-
# domestic passengers carried. The DGCA city-pair and carrier workbooks are
# compiled independently, so a few historic months diverge a few percent (most
# visibly 2017, ~4.6% → ratio ~2.09; real-data range is ~[1.99, 2.09]). This
# ±10% band around 2× leaves headroom over that divergence - so a benign monthly
# DGCA revision can't red CI - while still decisively catching the layer-confusion
# class of bug (reusing throughput as carried ≈ 1.0× ratio; halving ≈ 0.5×).
# Shared by the validation check and the regression tests so they can't drift.
CONSERVATION_RATIO_BAND = (1.8, 2.2)


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
    must use - never a national sum of airport endpoint throughput.
    """
    c = add_month_period(carrier)
    scheduled_domestic = c[c["service_type"] == SCHEDULED_DOMESTIC]
    return scheduled_domestic.groupby("period")["passengers"].sum().sort_index()


class DomesticDemand(NamedTuple):
    """National scheduled-domestic passengers carried plus derived series."""

    national: pd.Series          # monthly passengers carried (gap-free index)
    trailing_12m: pd.Series      # trailing-12-month total
    monthly_yoy: pd.Series       # month vs same month last year (fraction)
    trailing_12m_yoy: pd.Series  # T12 vs prior T12 (fraction)


def _yoy(series: pd.Series, periods: int) -> pd.Series:
    """Year-over-year change as a fraction; a zero prior base yields NaN.

    Growth against a zero base is undefined, not infinite - and the gap-fill
    below creates a real zero month (2020-04). Mapping the zero denominator to
    NaN keeps a stray ``inf`` out of the series (an ``inf`` would serialize as a
    non-standard ``Infinity`` JSON token that browsers reject).
    """
    prior = series.shift(periods)
    return series / prior.where(prior != 0) - 1


def domestic_demand_series(carrier: pd.DataFrame) -> DomesticDemand:
    """National domestic demand (passengers carried) and its trailing/YoY series.

    The trailing-12 and YoY series use positional ``rolling(12)``/``shift(12)``,
    which are only calendar-correct on a gap-free monthly index, so the series
    is reindexed onto a contiguous ``PeriodIndex``. Only the documented
    ``KNOWN_ZERO_MONTHS`` (2020-04, grounded fleet) become real zeros; any
    other unpublished month stays NaN so every window spanning it reads n/a
    instead of fabricating a collapse.

    Raises ``ValueError`` on an empty/all-filtered carrier frame rather than
    emitting a ``NaT`` latest month and a downstream ``KeyError``: an absent
    scheduled-domestic series means the upstream pipeline is broken, and the
    chart/summary callers all require a populated headline.
    """
    national = domestic_airline_passengers_carried(carrier)
    if national.empty:
        raise ValueError(
            "no scheduled_domestic carrier rows - cannot build domestic demand series"
        )
    full = pd.period_range(national.index.min(), national.index.max(), freq="M")
    national = national.reindex(full)
    for period in KNOWN_ZERO_MONTHS:
        if period in national.index and pd.isna(national.loc[period]):
            national.loc[period] = 0
    # Any remaining NaN is an unpublished month: it voids (NaN) every trailing
    # window and YoY that spans it rather than being silently read as zero.
    t12 = national.rolling(12, min_periods=12).sum()
    return DomesticDemand(national, t12, _yoy(national, 12), _yoy(t12, 12))


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

    Endpoint traffic at Indian airports only - foreign counterpart cities are
    dropped upstream, so this is Indian gateway traffic, not foreign-airport
    totals and not airline-carried passengers.
    """
    q = add_quarter_period(quarterly)
    return q.groupby("period")["passengers"].sum().sort_index()
