"""Passenger metric semantics: helpers, cross-layer conservation, label guards.

These tests lock the distinction the dashboard once got wrong: national domestic
demand is *passengers carried* (carrier table, counted once per journey), while
the airport table is *endpoint throughput* (arrivals + departures), which is
~2× the carried figure when summed nationally.
"""

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import chart
import metrics

ROOT = Path(__file__).resolve().parents[1]
AIRPORT_CSV = ROOT / "data/processed/airport_monthly.csv"
CARRIER_CSV = ROOT / "data/processed/carrier_monthly.csv"


# ── helper unit tests ────────────────────────────────────────


def test_domestic_airline_passengers_carried_filters_scheduled_domestic():
    carrier = pd.DataFrame(
        [
            {"airline": "X", "service_type": "scheduled_domestic",
             "year": 2026, "month": 5, "passengers": 1000},
            {"airline": "Y", "service_type": "scheduled_domestic",
             "year": 2026, "month": 5, "passengers": 500},
            # These must be excluded from the national domestic-demand metric.
            {"airline": "X", "service_type": "nonscheduled_domestic",
             "year": 2026, "month": 5, "passengers": 7},
            {"airline": "X", "service_type": "scheduled_international",
             "year": 2026, "month": 5, "passengers": 9},
        ]
    )
    carried = metrics.domestic_airline_passengers_carried(carrier)
    assert carried.loc[pd.Period("2026-05", freq="M")] == 1500


def test_domestic_airport_throughput_sums_endpoints_across_airports():
    monthly = pd.DataFrame(
        [
            {"year": 2026, "month": 5, "airport": "DEL", "passengers": 800},
            {"year": 2026, "month": 5, "airport": "BOM", "passengers": 700},
            {"year": 2026, "month": 4, "airport": "DEL", "passengers": 600},
        ]
    )
    throughput = metrics.domestic_airport_throughput(monthly)
    assert throughput.loc[pd.Period("2026-05", freq="M")] == 1500
    assert throughput.loc[pd.Period("2026-04", freq="M")] == 600


def test_international_gateway_throughput_sums_by_quarter():
    quarterly = pd.DataFrame(
        [
            {"year": 2026, "quarter": 1, "airport": "DEL", "passengers": 300},
            {"year": 2026, "quarter": 1, "airport": "BOM", "passengers": 200},
        ]
    )
    gateway = metrics.international_gateway_throughput(quarterly)
    assert gateway.loc[pd.Period("2026Q1", freq="Q")] == 500


def test_domestic_airport_matrix_is_airport_by_month():
    monthly = pd.DataFrame(
        [
            {"year": 2026, "month": 5, "airport": "DEL", "passengers": 10},
            {"year": 2026, "month": 5, "airport": "BOM", "passengers": 20},
            {"year": 2026, "month": 6, "airport": "DEL", "passengers": 30},
        ]
    )
    matrix = metrics.domestic_airport_matrix(monthly)
    assert matrix.loc[pd.Period("2026-05", freq="M"), "DEL"] == 10
    assert matrix.loc[pd.Period("2026-06", freq="M"), "BOM"] == 0  # filled, not NaN


def test_domestic_demand_series_fills_calendar_gaps_with_zero():
    """Positional rolling()/shift() are only calendar-correct on a gap-free index.

    Carrier scheduled-domestic is missing 2020-04 (COVID lockdown); the series
    must reindex it to 0, not skip it (which would slide the trailing window).
    """
    rows = [
        {"airline": "X", "service_type": "scheduled_domestic",
         "year": p.year, "month": p.month, "passengers": 1000}
        for p in pd.period_range("2020-01", "2021-12", freq="M")
        if p != pd.Period("2020-04", freq="M")  # the gap
    ]
    demand = metrics.domestic_demand_series(pd.DataFrame(rows))
    full = pd.period_range("2020-01", "2021-12", freq="M")
    assert list(demand.national.index) == list(full)  # contiguous, gap filled
    assert demand.national.loc[pd.Period("2020-04", freq="M")] == 0
    # First complete T12 lands at 2020-12: 11 months × 1000 + the zero gap = 11000.
    assert demand.trailing_12m.loc[pd.Period("2020-12", freq="M")] == 11000
    # YoY at 2021-05 compares to 2020-05 (same value) → 0.0, proving alignment.
    assert demand.monthly_yoy.loc[pd.Period("2021-05", freq="M")] == 0.0
    # YoY against the zero-filled month (2021-04 vs 2020-04 == 0) is undefined →
    # NaN, never inf (an inf would serialize as an invalid `Infinity` JSON token).
    yoy_2021_04 = demand.monthly_yoy.loc[pd.Period("2021-04", freq="M")]
    assert pd.isna(yoy_2021_04)
    assert not np.isinf(yoy_2021_04)


def test_domestic_demand_series_rejects_empty_carrier():
    """No scheduled-domestic rows is a broken pipeline → fail clearly, not NaT."""
    empty = pd.DataFrame(
        [{"airline": "X", "service_type": "scheduled_international",
          "year": 2026, "month": 5, "passengers": 100}]
    )
    with pytest.raises(ValueError, match="scheduled_domestic"):
        metrics.domestic_demand_series(empty)


# ── cross-layer conservation (real data) ─────────────────────


@pytest.mark.skipif(
    not (AIRPORT_CSV.exists() and CARRIER_CSV.exists()),
    reason="published CSVs not present",
)
def test_domestic_airport_throughput_tracks_twice_carrier_passengers():
    """National airport throughput ≈ 2× scheduled-domestic passengers carried.

    Every domestic journey is one carrier passenger and two airport endpoints, so
    national airport throughput should be ~2× passengers carried. The DGCA
    city-pair and carrier workbooks are compiled independently, so a few historic
    months diverge — most visibly 2017, where the city-pair totals run ~3-5% above
    2× the carrier totals, and early 2025 (~0.6%). The relationship still holds
    within a small tolerance, which is what guards against the layer confusion this
    test exists for: reusing airport throughput as passengers carried (a ~2× error)
    or vice versa (a ~0.5× error). Exact equality does NOT hold across all history,
    so we assert a band rather than equality.
    """
    airport = pd.read_csv(AIRPORT_CSV)
    carrier = pd.read_csv(CARRIER_CSV)
    throughput = metrics.domestic_airport_throughput(airport)
    carried = metrics.domestic_airline_passengers_carried(carrier)

    common = throughput.index.intersection(carried.index)
    assert len(common) >= 100  # the two layers really do overlap

    low, high = metrics.CONSERVATION_RATIO_BAND
    ratio = throughput.loc[common] / carried.loc[common]
    # Every overlapping month is within the conservation band around 2×.
    assert ratio.between(low, high).all(), ratio[~ratio.between(low, high)]


# ── dashboard summary uses the carrier layer ─────────────────


def test_dashboard_summary_domestic_uses_carrier_passengers_carried():
    """A fixture where throughput is exactly 2× carried proves the wiring."""
    month = {"year": 2026, "month": 5}
    # Airport endpoint throughput sums to 2000 for the month.
    monthly = pd.DataFrame(
        [
            {**month, "airport": "DEL", "passengers": 1200},
            {**month, "airport": "BOM", "passengers": 800},
        ]
    )
    # Scheduled-domestic passengers carried sum to 1000 (exactly half).
    carrier = pd.DataFrame(
        [
            {"airline": "X", "service_type": "scheduled_domestic", **month,
             "passengers": 600},
            {"airline": "Y", "service_type": "scheduled_domestic", **month,
             "passengers": 400},
            {"airline": "X", "service_type": "scheduled_international", **month,
             "passengers": 999},  # must be ignored
        ]
    )
    quarterly = pd.DataFrame(
        [{"year": 2026, "quarter": 1, "airport": "DEL", "passengers": 50}]
    )

    summary = chart.generate_dashboard_summary(
        monthly, quarterly, carrier, fingerprint="sha256:test"
    )
    dom = summary["domestic"]
    assert dom["latest_month_passengers_carried"] == 1000
    assert dom["airport_throughput_latest_month"] == 2000
    assert dom["latest_month_passengers_carried"] * 2 == dom["airport_throughput_latest_month"]
    assert dom["passengers_metric"] == "scheduled_domestic_passengers_carried"


def test_dashboard_summary_nulls_airport_context_when_layers_misalign():
    """Carrier can publish a month ahead of the airport layer; don't fabricate.

    The headline month follows the carrier layer. If the airport layer hasn't
    caught up, the airport-context fields must be null, not a silently-quoted
    different month (or a misleading 0 airports).
    """
    monthly = pd.DataFrame(
        [{"year": 2026, "month": 5, "airport": "DEL", "passengers": 1000}]
    )  # airport layer stops at 2026-05
    carrier = pd.DataFrame(
        [{"airline": "X", "service_type": "scheduled_domestic",
          "year": 2026, "month": 6, "passengers": 700}]
    )  # carrier is one month ahead
    quarterly = pd.DataFrame(
        [{"year": 2026, "quarter": 1, "airport": "DEL", "passengers": 50}]
    )

    dom = chart.generate_dashboard_summary(
        monthly, quarterly, carrier, fingerprint="sha256:test"
    )["domestic"]
    assert dom["latest_month"] == "2026-06"
    assert dom["latest_month_passengers_carried"] == 700
    assert dom["airport_throughput_latest_month"] is None
    assert dom["airports_latest_month"] is None


# ── static guards on chart label/source semantics ────────────


def test_demand_pulse_is_built_from_carrier_not_airport_layer():
    """The national headline must come from the carrier helper, never an airport sum."""
    src = inspect.getsource(chart.chart_india_domestic_demand_pulse)
    # domestic_demand_series wraps the carrier passengers-carried helper.
    assert "domestic_demand_series" in src
    assert "passengers carried" in src
    # And the dashboard summary builds the domestic headline the same way.
    summary_src = inspect.getsource(chart.generate_dashboard_summary)
    assert "domestic_demand_series" in summary_src
    # domestic_demand_series is itself carrier-sourced, with the gap-fill fix.
    helper_src = inspect.getsource(metrics.domestic_demand_series)
    assert "domestic_airline_passengers_carried" in helper_src


@pytest.mark.parametrize(
    "func, must_contain",
    [
        (chart.chart_top_airport_traffic_trends, "airport passenger movements"),
        (chart.chart_newcomer_airport_rampup, "airport passenger movements"),
        (chart.chart_domestic_market_share_gainers, "domestic airport throughput"),
        (chart.chart_international_gateway_share_gainers, "gateway"),
        (chart.chart_airport_seasonality_fingerprint, "airport-throughput index"),
    ],
)
def test_airport_charts_label_throughput_not_passengers_carried(func, must_contain):
    src = inspect.getsource(func)
    assert must_contain in src
    # An airport-level chart must never claim airline "passengers carried".
    assert "passengers carried" not in src
