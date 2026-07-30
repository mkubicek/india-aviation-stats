"""Route-market, dual-airport, and network-structure metric tests."""

import math

import pandas as pd

from network import (
    annual_network_metrics,
    bidirectional_segments,
    comparison_windows,
    dual_airport_monthly_development,
    dual_airport_metrics,
    effective_destinations,
    eligible_route_markets,
    pareto_frontier,
    route_acquisition_sequence,
    route_market_frontier,
    structural_two_leg_opportunities,
    triangle_closures,
    window_segment_metrics,
)
from routes import airport_monthly_from_routes


def _route_rows(start: str, months: int, markets: dict[tuple[str, str], int]):
    rows = []
    for period in pd.period_range(start, periods=months, freq="M"):
        for (origin, destination), passengers in markets.items():
            rows.append(
                {
                    "year": period.year,
                    "month": period.month,
                    "origin": origin,
                    "destination": destination,
                    "passengers": passengers,
                }
            )
    return rows


def test_comparison_windows_are_complete_disjoint_and_explicit():
    routes = pd.DataFrame(
        _route_rows("2024-01", 24, {("AAA", "BBB"): 10})
    )

    windows = comparison_windows(routes)

    assert str(windows.latest[0]) == "2025-01"
    assert str(windows.latest[-1]) == "2025-12"
    assert str(windows.previous[0]) == "2024-01"
    assert not set(windows.latest) & set(windows.previous)


def test_bidirectional_segments_sum_both_directions():
    routes = pd.DataFrame(
        [
            {
                "year": 2025,
                "month": 1,
                "origin": "AAA",
                "destination": "BBB",
                "passengers": 100,
            },
            {
                "year": 2025,
                "month": 1,
                "origin": "BBB",
                "destination": "AAA",
                "passengers": 80,
            },
        ]
    )

    segment = bidirectional_segments(routes).iloc[0]

    assert segment["airport_a"] == "AAA"
    assert segment["airport_b"] == "BBB"
    assert segment["passengers"] == 180


def test_effective_destinations_matches_equal_weight_case():
    assert math.isclose(effective_destinations([100, 100, 100]), 3.0)
    assert effective_destinations([0, 0]) == 0


def test_route_market_frontier_uses_observed_volume_growth_and_persistence():
    rows = []
    # Prior T12: AAA-BBB = 200 bidirectional passengers/month.
    rows += _route_rows(
        "2024-01",
        12,
        {("AAA", "BBB"): 100, ("BBB", "AAA"): 100},
    )
    # Latest T12: 300/month, present in every month.
    rows += _route_rows(
        "2025-01",
        12,
        {("AAA", "BBB"): 150, ("BBB", "AAA"): 150},
    )
    routes = pd.DataFrame(rows)
    airport = airport_monthly_from_routes(routes)

    frontier = route_market_frontier(
        routes, airport, focal_airport="AAA"
    )

    assert frontier.loc["BBB", "latest_t12_passengers"] == 3600
    assert frontier.loc["BBB", "previous_t12_passengers"] == 2400
    assert frontier.loc["BBB", "latest_persistence_months"] == 12
    assert frontier.loc["BBB", "yoy_change_pct"] == 50


def test_eligible_markets_and_pareto_selection_are_deterministic():
    frame = pd.DataFrame(
        {
            "latest_t12_passengers": [1000, 800, 500],
            "previous_t12_passengers": [900, 500, 500],
            "latest_persistence_months": [12, 12, 12],
            "yoy_change_pct": [10, 60, 0],
        },
        index=["ANCHOR", "GROWTH", "DOMINATED"],
    )
    eligible = eligible_route_markets(
        frame, min_t12_passengers=100, min_persistence_months=9
    )

    selected = pareto_frontier(
        eligible,
        {"latest_t12_passengers": True, "yoy_change_pct": True},
    )

    assert selected == ["ANCHOR", "GROWTH"]


def test_dual_airport_metrics_apply_volume_and_persistence_floor():
    rows = []
    rows += _route_rows(
        "2024-01",
        12,
        {("INC", "AAA"): 100},
    )
    rows += _route_rows(
        "2025-01",
        12,
        {
            ("INC", "AAA"): 100,
            ("NEW", "AAA"): 20,
            ("NEW", "BBB"): 20,
        },
    )
    routes = pd.DataFrame(rows)
    airport = airport_monthly_from_routes(routes)

    result = dual_airport_metrics(
        routes,
        airport,
        incumbent="INC",
        newcomer="NEW",
        min_market_passengers=100,
        persistence_fraction=0.5,
    )

    assert result["comparison_months"] == 12
    assert result["shared_destinations"] == ["AAA"]
    assert result["newcomer_unique_destinations"] == ["BBB"]
    assert result["newcomer_share_pct"] > 0
    assert result["combined_vs_baseline_throughput_change_pct"] > 0
    assert result["combined_vs_baseline_destination_change"] == 1


def test_dual_airport_monthly_development_discloses_pre_entry_and_components():
    rows = []
    rows += _route_rows(
        "2024-12",
        3,
        {
            ("INC", "AAA"): 100,
            ("AAA", "INC"): 100,
        },
    )
    rows += _route_rows(
        "2025-01",
        2,
        {
            ("NEW", "AAA"): 20,
            ("AAA", "NEW"): 20,
        },
    )
    routes = pd.DataFrame(rows)
    airport = airport_monthly_from_routes(routes)

    development = dual_airport_monthly_development(
        airport,
        incumbent="INC",
        newcomer="NEW",
        pre_entry_months=1,
    )

    assert [str(period) for period in development.index] == [
        "2024-12",
        "2025-01",
        "2025-02",
    ]
    assert development.loc[pd.Period("2024-12"), "months_from_entry"] == -1
    assert development.loc[pd.Period("2025-01"), "months_from_entry"] == 0
    assert (
        development["combined_throughput"]
        == development["incumbent_throughput"]
        + development["newcomer_throughput"]
    ).all()
    assert development.loc[pd.Period("2025-01"), "newcomer_share_pct"] > 0


def test_route_acquisition_sequence_uses_first_positive_month():
    routes = pd.DataFrame(
        _route_rows("2025-01", 2, {("NEW", "AAA"): 10})
        + _route_rows("2025-02", 1, {("NEW", "BBB"): 5})
    )

    acquired = route_acquisition_sequence(routes, "NEW")

    assert acquired.set_index("destination").loc["AAA", "ramp_month"] == 1
    assert acquired.set_index("destination").loc["BBB", "ramp_month"] == 2


def test_annual_network_metrics_report_concentration_and_route_survival():
    rows = []
    rows += _route_rows(
        "2024-01",
        12,
        {("AAA", "BBB"): 100, ("BBB", "AAA"): 100},
    )
    rows += _route_rows(
        "2025-01",
        12,
        {
            ("AAA", "BBB"): 100,
            ("BBB", "AAA"): 100,
            ("AAA", "CCC"): 50,
            ("CCC", "AAA"): 50,
        },
    )
    routes = pd.DataFrame(rows)
    airport = airport_monthly_from_routes(routes)

    annual = annual_network_metrics(
        routes, airport, start_year=2024, end_year=2025
    )

    assert list(annual.index) == [2024, 2025]
    assert annual.loc[2025, "active_airports"] == 3
    assert annual.loc[2025, "active_routes"] == 2
    assert annual.loc[2025, "route_births"] == 1


def test_structural_two_leg_opportunity_excludes_persistent_direct_route():
    rows = []
    rows += _route_rows(
        "2024-01",
        12,
        {
            ("AAA", "HUB"): 100,
            ("HUB", "AAA"): 100,
            ("BBB", "HUB"): 100,
            ("HUB", "BBB"): 100,
        },
    )
    rows += _route_rows(
        "2025-01",
        12,
        {
            ("AAA", "HUB"): 110,
            ("HUB", "AAA"): 110,
            ("BBB", "HUB"): 110,
            ("HUB", "BBB"): 110,
            # Only BBB -> AAA is already direct; AAA -> BBB remains a
            # directional two-leg candidate.
            ("BBB", "AAA"): 5,
        },
    )
    routes = pd.DataFrame(rows)
    windows = comparison_windows(routes)

    result = structural_two_leg_opportunities(
        routes,
        hub="HUB",
        periods=windows.latest,
        previous_periods=windows.previous,
        min_leg_passengers=1000,
        min_leg_persistence_months=6,
    )

    assert len(result) == 1
    assert result.iloc[0]["origin"] == "AAA"
    assert result.iloc[0]["destination"] == "BBB"
    assert result.iloc[0]["balanced_leg_passengers"] == 1320


def test_structural_two_leg_opportunity_requires_non_declining_legs_by_default():
    rows = []
    rows += _route_rows(
        "2024-01",
        12,
        {
            ("AAA", "HUB"): 100,
            ("HUB", "BBB"): 100,
        },
    )
    rows += _route_rows(
        "2025-01",
        12,
        {
            ("AAA", "HUB"): 90,
            ("HUB", "BBB"): 110,
        },
    )
    routes = pd.DataFrame(rows)
    windows = comparison_windows(routes)

    result = structural_two_leg_opportunities(
        routes,
        hub="HUB",
        periods=windows.latest,
        previous_periods=windows.previous,
        min_leg_passengers=1_000,
        min_leg_persistence_months=6,
    )

    assert result.empty


def test_structural_two_leg_opportunity_applies_known_geographic_detour():
    rows = []
    for start, value in (("2024-01", 100), ("2025-01", 110)):
        rows += _route_rows(
            start,
            12,
            {
                ("AAA", "HUB"): value,
                ("HUB", "BBB"): value,
            },
        )
    routes = pd.DataFrame(rows)
    windows = comparison_windows(routes)

    result = structural_two_leg_opportunities(
        routes,
        hub="HUB",
        periods=windows.latest,
        previous_periods=windows.previous,
        min_leg_passengers=1000,
        min_leg_persistence_months=6,
        coordinates={
            "AAA": (0.0, 0.0),
            "BBB": (0.0, 1.0),
            "HUB": (0.0, 10.0),
        },
        max_detour_ratio=1.5,
    )

    assert result.empty


def test_triangle_closure_means_previously_two_edge_only():
    rows = []
    rows += _route_rows(
        "2024-01",
        12,
        {
            ("AAA", "HUB"): 100,
            ("HUB", "AAA"): 100,
            ("BBB", "HUB"): 100,
            ("HUB", "BBB"): 100,
        },
    )
    rows += _route_rows(
        "2025-01",
        12,
        {
            ("AAA", "BBB"): 100,
            ("BBB", "AAA"): 100,
        },
    )
    routes = pd.DataFrame(rows)
    windows = comparison_windows(routes)

    result = triangle_closures(
        routes,
        current_periods=windows.latest,
        previous_periods=windows.previous,
        min_direct_passengers=1000,
        min_direct_persistence_months=6,
    )

    assert len(result) == 1
    assert result.iloc[0]["prior_two_edge_hubs"] == ["HUB"]
