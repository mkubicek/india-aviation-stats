"""Directed domestic route construction and conservation tests."""

import pandas as pd
import pytest

from entities import build_airport_resolver
from routes import (
    UnresolvedDomesticEndpointError,
    airport_monthly_from_routes,
    build_domestic_routes,
)
from validate.checks import check_domestic_routes, check_route_history


MAPPINGS = {
    "airports": {
        "AAA": {"city": "Alpha"},
        "BBB": {"city": "Beta"},
        "CCC": {"city": "Gamma"},
    }
}


def _resolver():
    return build_airport_resolver(MAPPINGS)


def test_build_routes_splits_directions_aggregates_and_keeps_zero():
    raw = pd.DataFrame(
        [
            [2025, 1, "Alpha", "Beta", 100, 80],
            [2025, 1, "Alpha", "Beta", 7, 3],
            [2025, 1, "Alpha", "Gamma", 5, ""],
        ],
        columns=[
            "Year",
            "Month",
            "City1",
            "City2",
            "PaxToCity2",
            "PaxFromCity2",
        ],
    )

    routes = build_domestic_routes(raw, _resolver())

    assert list(routes.columns) == [
        "year",
        "month",
        "origin",
        "destination",
        "passengers",
    ]
    assert routes.passengers.dtype == "int64"
    values = routes.set_index(["origin", "destination"])["passengers"].to_dict()
    assert values == {
        ("AAA", "BBB"): 107,
        ("AAA", "CCC"): 5,
        ("BBB", "AAA"): 83,
        ("CCC", "AAA"): 0,
    }


def test_build_routes_refuses_unresolved_domestic_endpoint():
    raw = pd.DataFrame(
        [[2025, 1, "Alpha", "Unknown", 10, 9]],
        columns=[
            "Year",
            "Month",
            "City1",
            "City2",
            "PaxToCity2",
            "PaxFromCity2",
        ],
    )
    with pytest.raises(UnresolvedDomesticEndpointError, match="Unknown"):
        build_domestic_routes(raw, _resolver())


def test_build_routes_refuses_fractional_passengers():
    raw = pd.DataFrame(
        [[2025, 1, "Alpha", "Beta", 10.5, 9]],
        columns=[
            "Year",
            "Month",
            "City1",
            "City2",
            "PaxToCity2",
            "PaxFromCity2",
        ],
    )
    with pytest.raises(ValueError, match="non-integer"):
        build_domestic_routes(raw, _resolver())


def test_build_routes_applies_declared_canonical_self_loop_exclusion():
    raw = pd.DataFrame(
        [[2025, 1, "Alpha", "Alpha", 0, 2]],
        columns=[
            "Year",
            "Month",
            "City1",
            "City2",
            "PaxToCity2",
            "PaxFromCity2",
        ],
    )
    exclusions = [
        {
            "year": 2025,
            "month": 1,
            "city1": "ALPHA",
            "city2": "ALPHA",
            "airport": "AAA",
        }
    ]

    routes = build_domestic_routes(raw, _resolver(), exclusions=exclusions)

    assert routes.empty


def test_route_to_airport_reconciliation_is_exact():
    routes = pd.DataFrame(
        [
            [2025, 1, "AAA", "BBB", 100],
            [2025, 1, "BBB", "AAA", 80],
            [2025, 1, "AAA", "CCC", 5],
            [2025, 1, "CCC", "AAA", 0],
        ],
        columns=["year", "month", "origin", "destination", "passengers"],
    )

    monthly = airport_monthly_from_routes(routes).set_index("airport")

    assert monthly.loc["AAA", "departures"] == 105
    assert monthly.loc["AAA", "arrivals"] == 80
    assert monthly.loc["BBB", "departures"] == 80
    assert monthly.loc["BBB", "arrivals"] == 100
    assert monthly.loc["CCC", "departures"] == 0
    assert monthly.loc["CCC", "arrivals"] == 5
    assert monthly["departures"].sum() == routes["passengers"].sum()
    assert monthly["arrivals"].sum() == routes["passengers"].sum()

    findings = check_domestic_routes(
        routes, monthly.reset_index(), {"AAA", "BBB", "CCC"}
    )
    assert not [finding for finding in findings if finding.status == "fail"]


def test_route_validation_detects_airport_reconciliation_break():
    routes = pd.DataFrame(
        [[2025, 1, "AAA", "BBB", 100]],
        columns=["year", "month", "origin", "destination", "passengers"],
    )
    monthly = airport_monthly_from_routes(routes)
    monthly.loc[monthly["airport"] == "AAA", "departures"] += 1

    findings = check_domestic_routes(routes, monthly, {"AAA", "BBB"})

    assert any(
        finding.check == "routes.airport_reconciliation"
        and finding.status == "fail"
        for finding in findings
    )


def test_route_validation_reports_missing_airport_layer_without_crashing():
    routes = pd.DataFrame(
        [[2025, 1, "AAA", "BBB", 100]],
        columns=["year", "month", "origin", "destination", "passengers"],
    )

    findings = check_domestic_routes(routes, None, {"AAA", "BBB"})

    assert any(
        finding.check == "routes.airport_reconciliation"
        and finding.status == "fail"
        for finding in findings
    )


def test_route_history_blocks_disappearing_published_key():
    previous = pd.DataFrame(
        [
            [2025, 1, "AAA", "BBB", 100],
            [2025, 1, "BBB", "AAA", 80],
        ],
        columns=["year", "month", "origin", "destination", "passengers"],
    )
    current = previous.iloc[:1].copy()

    findings = check_route_history(current, previous)

    assert findings[0].status == "fail"
    assert "BBB->AAA" in findings[0].message
