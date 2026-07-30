"""Canonical domestic route construction and route-to-airport aggregation.

DGCA domestic city-pair rows contain two directional passenger observations:

* ``City1 -> City2`` = ``PaxToCity2``
* ``City2 -> City1`` = ``PaxFromCity2``

This module resolves both endpoints through the same period-aware entity table
used by the airport layer, preserves explicit zero-direction observations, and
aggregates duplicate canonical routes deterministically. It never drops an
unresolved domestic endpoint: an unresolved label makes the build fail before a
partial route table can be published.
"""

from __future__ import annotations

import pandas as pd

ROUTE_KEY = ["year", "month", "origin", "destination"]
ROUTE_COLUMNS = ROUTE_KEY + ["passengers"]


class UnresolvedDomesticEndpointError(ValueError):
    """One or more domestic source labels did not resolve to an airport."""

    def __init__(self, labels: tuple[str, ...]):
        self.labels = labels
        super().__init__(self.__str__())

    def __str__(self) -> str:
        sample = ", ".join(self.labels[:10])
        suffix = "..." if len(self.labels) > 10 else ""
        return (
            f"{len(self.labels)} unresolved domestic endpoint label(s): "
            f"{sample}{suffix}"
        )


def _whole_passengers(values: pd.Series, column: str) -> pd.Series:
    """Parse source passenger cells without silently rounding or coercing text."""
    raw = values.copy()
    numeric = pd.to_numeric(raw, errors="coerce")
    text = raw.astype("string").str.strip()
    invalid = numeric.isna() & raw.notna() & ~text.isin(["", "-"])
    if invalid.any():
        examples = sorted(set(text[invalid].dropna().astype(str)))[:5]
        raise ValueError(f"{column} has non-numeric passenger values: {examples}")
    numeric = numeric.fillna(0)
    fractional = (numeric - numeric.round()).abs() > 1e-9
    if fractional.any():
        examples = sorted(set(numeric[fractional].astype(float)))[:5]
        raise ValueError(f"{column} has non-integer passenger values: {examples}")
    return numeric.round().astype("int64")


def build_domestic_routes(
    raw: pd.DataFrame,
    resolver,
    *,
    exclusions: list[dict] | None = None,
) -> pd.DataFrame:
    """Convert normalized city-pair rows into canonical directed routes.

    ``resolver`` must expose ``resolve(label, year, month)``. Duplicate
    canonical routes are summed, and the result is sorted by its full key.
    Blank direction cells are explicit zeros; malformed non-numeric values and
    unresolved endpoints raise rather than disappearing.
    """
    required = [
        "Year",
        "Month",
        "City1",
        "City2",
        "PaxToCity2",
        "PaxFromCity2",
    ]
    missing = sorted(set(required) - set(raw.columns))
    if missing:
        raise ValueError(f"domestic city-pair input missing columns: {missing}")

    source = raw[required].copy()
    source["year"] = pd.to_numeric(source["Year"], errors="raise").astype("int64")
    source["month"] = pd.to_numeric(source["Month"], errors="raise").astype("int64")
    bad_month = source[~source["month"].between(1, 12)]
    if not bad_month.empty:
        raise ValueError(
            f"domestic city-pair input has month outside 1..12: "
            f"{sorted(bad_month['month'].unique())}"
        )
    source["to_passengers"] = _whole_passengers(
        source["PaxToCity2"], "PaxToCity2"
    )
    source["from_passengers"] = _whole_passengers(
        source["PaxFromCity2"], "PaxFromCity2"
    )

    source["origin"] = [
        resolver.resolve(label, int(year), int(month))
        for label, year, month in source[["City1", "year", "month"]].itertuples(
            index=False, name=None
        )
    ]
    source["destination"] = [
        resolver.resolve(label, int(year), int(month))
        for label, year, month in source[["City2", "year", "month"]].itertuples(
            index=False, name=None
        )
    ]

    unresolved = set(
        source.loc[source["origin"].isna(), "City1"].astype(str)
    ) | set(source.loc[source["destination"].isna(), "City2"].astype(str))
    if unresolved:
        raise UnresolvedDomesticEndpointError(tuple(sorted(unresolved)))

    excluded_mask = pd.Series(False, index=source.index)
    for exclusion in exclusions or []:
        required_exclusion = {"year", "month", "city1", "city2", "airport"}
        missing_exclusion = required_exclusion - set(exclusion)
        if missing_exclusion:
            raise ValueError(
                f"domestic route exclusion missing fields: "
                f"{sorted(missing_exclusion)}"
            )
        match = (
            (source["year"] == int(exclusion["year"]))
            & (source["month"] == int(exclusion["month"]))
            & (
                source["City1"].astype(str).str.strip().str.upper()
                == str(exclusion["city1"]).strip().upper()
            )
            & (
                source["City2"].astype(str).str.strip().str.upper()
                == str(exclusion["city2"]).strip().upper()
            )
        )
        if not match.any():
            raise ValueError(
                "declared domestic route exclusion did not match a source row: "
                f"{exclusion['year']}-{int(exclusion['month']):02d} "
                f"{exclusion['city1']}->{exclusion['city2']}"
            )
        matched = source[match]
        expected_airport = str(exclusion["airport"])
        if not (
            (matched["origin"] == expected_airport)
            & (matched["destination"] == expected_airport)
        ).all():
            raise ValueError(
                "domestic route exclusion is not the declared canonical self-loop: "
                f"{exclusion['city1']}->{exclusion['city2']} != {expected_airport}"
            )
        excluded_mask |= match
    source = source[~excluded_mask].copy()

    forward = source[
        ["year", "month", "origin", "destination", "to_passengers"]
    ].rename(columns={"to_passengers": "passengers"})
    reverse = source[
        ["year", "month", "destination", "origin", "from_passengers"]
    ].rename(
        columns={
            "destination": "origin",
            "origin": "destination",
            "from_passengers": "passengers",
        }
    )
    directed = pd.concat([forward, reverse], ignore_index=True)
    routes = (
        directed.groupby(ROUTE_KEY, as_index=False, sort=True)["passengers"]
        .sum()
        .sort_values(ROUTE_KEY)
        .reset_index(drop=True)
    )
    routes["passengers"] = routes["passengers"].astype("int64")
    return routes[ROUTE_COLUMNS]


def airport_monthly_from_routes(routes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a directed route table to canonical airport endpoint traffic."""
    departures = (
        routes.groupby(["year", "month", "origin"], as_index=False)["passengers"]
        .sum()
        .rename(columns={"origin": "airport", "passengers": "departures"})
    )
    arrivals = (
        routes.groupby(["year", "month", "destination"], as_index=False)[
            "passengers"
        ]
        .sum()
        .rename(columns={"destination": "airport", "passengers": "arrivals"})
    )
    monthly = departures.merge(
        arrivals, on=["year", "month", "airport"], how="outer"
    ).fillna({"departures": 0, "arrivals": 0})
    monthly["departures"] = monthly["departures"].astype("int64")
    monthly["arrivals"] = monthly["arrivals"].astype("int64")
    monthly["passengers"] = monthly["departures"] + monthly["arrivals"]
    columns = [
        "year",
        "month",
        "airport",
        "passengers",
        "departures",
        "arrivals",
    ]
    return monthly[columns].sort_values(
        ["year", "month", "airport"]
    ).reset_index(drop=True)
