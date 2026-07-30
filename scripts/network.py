"""Deterministic route-market and domestic network metrics.

The functions in this module operate only on observed DGCA segment passengers.
They do not infer passenger origin/final destination, transfers, itineraries,
capacity, fares, or route economics.
"""

from __future__ import annotations

import math
from typing import NamedTuple

import numpy as np
import pandas as pd


class ComparisonWindows(NamedTuple):
    latest: pd.PeriodIndex
    previous: pd.PeriodIndex


def add_month_period(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["period"] = pd.to_datetime(
        {
            "year": out["year"].astype(int),
            "month": out["month"].astype(int),
            "day": 1,
        }
    ).dt.to_period("M")
    return out


def comparison_windows(
    df: pd.DataFrame, *, window_months: int = 12
) -> ComparisonWindows:
    """Latest and immediately preceding complete, disjoint monthly windows."""
    dated = add_month_period(df)
    available = set(dated["period"])
    latest_end = dated["period"].max()
    latest = pd.period_range(
        latest_end - (window_months - 1), latest_end, freq="M"
    )
    previous = pd.period_range(
        latest_end - (2 * window_months - 1),
        latest_end - window_months,
        freq="M",
    )
    missing = [period for period in latest.append(previous) if period not in available]
    if missing:
        raise ValueError(
            "route data lacks months required for complete comparison windows: "
            + ", ".join(str(period) for period in missing[:6])
        )
    return ComparisonWindows(latest=latest, previous=previous)


def bidirectional_segments(routes: pd.DataFrame) -> pd.DataFrame:
    """Directed route rows -> unordered bidirectional segment-month totals."""
    dated = add_month_period(routes)
    dated["airport_a"] = dated[["origin", "destination"]].min(axis=1)
    dated["airport_b"] = dated[["origin", "destination"]].max(axis=1)
    return (
        dated.groupby(
            ["period", "airport_a", "airport_b"], as_index=False, sort=True
        )["passengers"]
        .sum()
        .sort_values(["period", "airport_a", "airport_b"])
        .reset_index(drop=True)
    )


def window_segment_metrics(
    segment_monthly: pd.DataFrame, periods: pd.PeriodIndex
) -> pd.DataFrame:
    """Volume, positive-month persistence, and volatility by segment."""
    selected = segment_monthly[segment_monthly["period"].isin(periods)]
    if selected.empty:
        index = pd.MultiIndex.from_arrays(
            [[], []], names=["airport_a", "airport_b"]
        )
        return pd.DataFrame(
            columns=["passengers", "persistence", "monthly_cv"], index=index
        )
    pivot = selected.pivot_table(
        index="period",
        columns=["airport_a", "airport_b"],
        values="passengers",
        aggfunc="sum",
        fill_value=0,
    ).reindex(periods, fill_value=0)
    totals = pivot.sum(axis=0).astype("int64")
    persistence = (pivot > 0).sum(axis=0).astype("int64")
    means = pivot.mean(axis=0).replace(0, np.nan)
    cv = pivot.std(axis=0, ddof=0) / means
    out = pd.DataFrame(
        {
            "passengers": totals,
            "persistence": persistence,
            "monthly_cv": cv,
        }
    )
    out.index.names = ["airport_a", "airport_b"]
    return out.sort_index()


def directed_window_metrics(
    routes: pd.DataFrame, periods: pd.PeriodIndex
) -> pd.DataFrame:
    """Volume, positive-month persistence, and volatility by directed route."""
    selected = add_month_period(routes)
    selected = selected[selected["period"].isin(periods)]
    if selected.empty:
        index = pd.MultiIndex.from_arrays(
            [[], []], names=["origin", "destination"]
        )
        return pd.DataFrame(
            columns=["passengers", "persistence", "monthly_cv"], index=index
        )
    pivot = selected.pivot_table(
        index="period",
        columns=["origin", "destination"],
        values="passengers",
        aggfunc="sum",
        fill_value=0,
    ).reindex(periods, fill_value=0)
    totals = pivot.sum(axis=0).astype("int64")
    persistence = (pivot > 0).sum(axis=0).astype("int64")
    means = pivot.mean(axis=0).replace(0, np.nan)
    cv = pivot.std(axis=0, ddof=0) / means
    out = pd.DataFrame(
        {
            "passengers": totals,
            "persistence": persistence,
            "monthly_cv": cv,
        }
    )
    out.index.names = ["origin", "destination"]
    return out.sort_index()


def effective_destinations(values: pd.Series | np.ndarray | list[float]) -> float:
    """Shannon effective number of destinations, exp(-sum(p * ln(p)))."""
    weights = np.asarray(values, dtype=float)
    weights = weights[weights > 0]
    if not len(weights):
        return 0.0
    shares = weights / weights.sum()
    return float(np.exp(-(shares * np.log(shares)).sum()))


def _counterpart(row: pd.Series, airport: str) -> str:
    return str(row["airport_b"] if row["airport_a"] == airport else row["airport_a"])


def airport_network_metrics(
    routes: pd.DataFrame,
    airport_monthly: pd.DataFrame,
    periods: pd.PeriodIndex,
    *,
    min_market_passengers: int = 0,
    min_persistence_months: int = 1,
    segment_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Traffic scale, direct breadth, HHI, and effective destinations by airport."""
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    segment_metrics = window_segment_metrics(segments, periods)
    active = segment_metrics[
        (segment_metrics["passengers"] >= min_market_passengers)
        & (segment_metrics["persistence"] >= min_persistence_months)
        & (segment_metrics["passengers"] > 0)
    ].reset_index()
    traffic = (
        add_month_period(airport_monthly)
        .loc[lambda d: d["period"].isin(periods)]
        .groupby("airport")["passengers"]
        .sum()
    )
    codes = sorted(set(active["airport_a"]) | set(active["airport_b"]))
    rows = []
    for airport in codes:
        links = active[
            (active["airport_a"] == airport) | (active["airport_b"] == airport)
        ]
        weights = links["passengers"].astype(float)
        shares = weights / weights.sum() if weights.sum() else weights
        rows.append(
            {
                "airport": airport,
                "throughput": int(traffic.get(airport, 0)),
                "direct_destinations": int(len(links)),
                "effective_destinations": effective_destinations(weights),
                "route_hhi": float((shares**2).sum()) if len(shares) else np.nan,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "throughput",
                "direct_destinations",
                "effective_destinations",
                "route_hhi",
            ]
        )
    return pd.DataFrame(rows).set_index("airport").sort_index()


def haversine_km(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    """Great-circle distance between two (latitude, longitude) points."""
    lat1, lon1 = map(math.radians, first)
    lat2, lon2 = map(math.radians, second)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def route_market_frontier(
    routes: pd.DataFrame,
    airport_monthly: pd.DataFrame,
    *,
    focal_airport: str,
    proxy_airport: str | None = None,
    distance_origin: str | None = None,
    coordinates: dict[str, tuple[float, float]] | None = None,
    window_months: int = 12,
    trend_years: int = 3,
    segment_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Observed bidirectional markets from one focal airport.

    Returns transparent dimensions rather than a composite score.
    """
    windows = comparison_windows(routes, window_months=window_months)
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    latest = window_segment_metrics(segments, windows.latest)
    previous = window_segment_metrics(segments, windows.previous)
    latest_end = windows.latest[-1]
    base_periods = pd.period_range(
        latest_end - (trend_years + 1) * window_months + 1,
        latest_end - trend_years * window_months,
        freq="M",
    )
    base = window_segment_metrics(segments, base_periods)

    latest_reset = latest.reset_index()
    focal = latest_reset[
        (latest_reset["airport_a"] == focal_airport)
        | (latest_reset["airport_b"] == focal_airport)
    ].copy()
    focal["destination"] = focal.apply(
        lambda row: _counterpart(row, focal_airport), axis=1
    )
    focal = focal.set_index("destination")
    out = focal[["passengers", "persistence", "monthly_cv"]].rename(
        columns={
            "passengers": "latest_t12_passengers",
            "persistence": "latest_persistence_months",
            "monthly_cv": "latest_monthly_cv",
        }
    )

    def focal_series(metrics: pd.DataFrame, column: str) -> pd.Series:
        reset = metrics.reset_index()
        selected = reset[
            (reset["airport_a"] == focal_airport)
            | (reset["airport_b"] == focal_airport)
        ].copy()
        if selected.empty:
            return pd.Series(dtype=float)
        selected["destination"] = selected.apply(
            lambda row: _counterpart(row, focal_airport), axis=1
        )
        return selected.set_index("destination")[column]

    out["previous_t12_passengers"] = focal_series(previous, "passengers")
    out["absolute_yoy_change"] = (
        out["latest_t12_passengers"] - out["previous_t12_passengers"].fillna(0)
    )
    prior_nonzero = out["previous_t12_passengers"].where(
        out["previous_t12_passengers"] > 0
    )
    out["yoy_change_pct"] = (
        out["latest_t12_passengers"] / prior_nonzero - 1
    ) * 100
    out["base_t12_passengers"] = focal_series(base, "passengers")
    base_nonzero = out["base_t12_passengers"].where(
        out["base_t12_passengers"] > 0
    )
    out[f"cagr_{trend_years}y_pct"] = (
        (out["latest_t12_passengers"] / base_nonzero) ** (1 / trend_years) - 1
    ) * 100

    destination_network = airport_network_metrics(
        routes,
        airport_monthly,
        windows.latest,
        segment_monthly=segments,
    )
    out["destination_t12_throughput"] = destination_network["throughput"]
    out["destination_direct_markets"] = destination_network[
        "direct_destinations"
    ]
    out["destination_effective_markets"] = destination_network[
        "effective_destinations"
    ]

    if proxy_airport:
        proxy_volume = {}
        proxy_persistence = {}
        for destination in out.index:
            key = tuple(sorted((proxy_airport, destination)))
            if key in latest.index:
                proxy_volume[destination] = int(latest.loc[key, "passengers"])
                proxy_persistence[destination] = int(
                    latest.loc[key, "persistence"]
                )
            else:
                proxy_volume[destination] = 0
                proxy_persistence[destination] = 0
        out[f"{proxy_airport.lower()}_t12_passengers"] = pd.Series(proxy_volume)
        out[f"{proxy_airport.lower()}_persistence_months"] = pd.Series(
            proxy_persistence
        )

    if coordinates and distance_origin:
        origin_coordinate = coordinates.get(distance_origin)
        out["distance_km"] = [
            (
                haversine_km(origin_coordinate, coordinates[destination])
                if origin_coordinate and destination in coordinates
                else np.nan
            )
            for destination in out.index
        ]
    return out.sort_values(
        ["latest_t12_passengers"], ascending=False
    )


def eligible_route_markets(
    frontier: pd.DataFrame,
    *,
    min_t12_passengers: int,
    min_persistence_months: int,
) -> pd.DataFrame:
    """Transparent evidence floor for a route-market frontier chart."""
    return frontier[
        (frontier["latest_t12_passengers"] >= min_t12_passengers)
        & (frontier["previous_t12_passengers"] >= min_t12_passengers)
        & (
            frontier["latest_persistence_months"]
            >= min_persistence_months
        )
        & frontier["yoy_change_pct"].notna()
    ].copy()


def pareto_frontier(
    frame: pd.DataFrame, dimensions: dict[str, bool]
) -> list[str]:
    """Return stable-index labels not dominated on all supplied dimensions.

    ``True`` means larger is better; ``False`` means smaller is better.
    """
    if frame.empty:
        return []
    columns = list(dimensions)
    clean = frame.dropna(subset=columns).sort_index()
    values = clean[columns].astype(float).to_numpy()
    maximize = [dimensions[column] for column in columns]
    selected = []
    for i, label in enumerate(clean.index):
        dominated = False
        for j in range(len(clean)):
            if i == j:
                continue
            at_least_as_good = [
                values[j, k] >= values[i, k]
                if maximize[k]
                else values[j, k] <= values[i, k]
                for k in range(len(columns))
            ]
            strictly_better = [
                values[j, k] > values[i, k]
                if maximize[k]
                else values[j, k] < values[i, k]
                for k in range(len(columns))
            ]
            if all(at_least_as_good) and any(strictly_better):
                dominated = True
                break
        if not dominated:
            selected.append(str(label))
    return selected


def _active_destination_set(
    segment_metrics: pd.DataFrame,
    airport: str,
    *,
    min_market_passengers: int,
    min_persistence_months: int,
) -> tuple[set[str], pd.DataFrame]:
    active = segment_metrics[
        (segment_metrics["passengers"] >= min_market_passengers)
        & (segment_metrics["persistence"] >= min_persistence_months)
    ].reset_index()
    links = active[
        (active["airport_a"] == airport) | (active["airport_b"] == airport)
    ].copy()
    destinations = {
        _counterpart(row, airport) for _, row in links.iterrows()
    }
    return destinations, links


def dual_airport_metrics(
    routes: pd.DataFrame,
    airport_monthly: pd.DataFrame,
    *,
    incumbent: str,
    newcomer: str,
    comparison_periods: pd.PeriodIndex | None = None,
    min_market_passengers: int = 10_000,
    persistence_fraction: float = 0.5,
    segment_monthly: pd.DataFrame | None = None,
) -> dict:
    """Observed traffic and network-role comparison for an airport pair."""
    airport = add_month_period(airport_monthly)
    newcomer_rows = airport[
        (airport["airport"] == newcomer) & (airport["passengers"] > 0)
    ]
    if newcomer_rows.empty:
        raise ValueError(f"{newcomer} has no observed positive passenger month")
    entry = newcomer_rows["period"].min()
    latest_end = airport["period"].max()
    if comparison_periods is None:
        available_months = latest_end.ordinal - entry.ordinal + 1
        length = min(12, available_months)
        comparison_periods = pd.period_range(
            latest_end - (length - 1), latest_end, freq="M"
        )
    baseline_periods = pd.period_range(
        entry - len(comparison_periods), entry - 1, freq="M"
    )
    required_months = max(
        1, math.ceil(len(comparison_periods) * persistence_fraction)
    )
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    comparison_segments = window_segment_metrics(segments, comparison_periods)
    baseline_segments = window_segment_metrics(segments, baseline_periods)
    incumbent_destinations, incumbent_links = _active_destination_set(
        comparison_segments,
        incumbent,
        min_market_passengers=min_market_passengers,
        min_persistence_months=required_months,
    )
    newcomer_destinations, newcomer_links = _active_destination_set(
        comparison_segments,
        newcomer,
        min_market_passengers=min_market_passengers,
        min_persistence_months=required_months,
    )
    baseline_required = max(
        1, math.ceil(len(baseline_periods) * persistence_fraction)
    )
    baseline_incumbent, _ = _active_destination_set(
        baseline_segments,
        incumbent,
        min_market_passengers=min_market_passengers,
        min_persistence_months=baseline_required,
    )

    traffic = airport.pivot_table(
        index="period",
        columns="airport",
        values="passengers",
        aggfunc="sum",
        fill_value=0,
    )

    def total(code: str, periods: pd.PeriodIndex) -> int:
        if code not in traffic:
            return 0
        return int(traffic.reindex(periods, fill_value=0)[code].sum())

    incumbent_traffic = total(incumbent, comparison_periods)
    newcomer_traffic = total(newcomer, comparison_periods)
    combined = incumbent_traffic + newcomer_traffic
    shared = incumbent_destinations & newcomer_destinations
    incumbent_unique = incumbent_destinations - newcomer_destinations
    newcomer_unique = newcomer_destinations - incumbent_destinations
    combined_destinations = incumbent_destinations | newcomer_destinations
    baseline_traffic = total(incumbent, baseline_periods)
    return {
        "incumbent": incumbent,
        "newcomer": newcomer,
        "entry_month": str(entry),
        "comparison_start": str(comparison_periods[0]),
        "comparison_end": str(comparison_periods[-1]),
        "comparison_months": int(len(comparison_periods)),
        "baseline_start": str(baseline_periods[0]),
        "baseline_end": str(baseline_periods[-1]),
        "min_market_passengers": int(min_market_passengers),
        "min_persistence_months": int(required_months),
        "incumbent_throughput": incumbent_traffic,
        "newcomer_throughput": newcomer_traffic,
        "combined_throughput": combined,
        "newcomer_share_pct": (
            100 * newcomer_traffic / combined if combined else np.nan
        ),
        "incumbent_destinations": sorted(incumbent_destinations),
        "newcomer_destinations": sorted(newcomer_destinations),
        "shared_destinations": sorted(shared),
        "incumbent_unique_destinations": sorted(incumbent_unique),
        "newcomer_unique_destinations": sorted(newcomer_unique),
        "combined_destination_count": int(len(combined_destinations)),
        "baseline_incumbent_destination_count": int(len(baseline_incumbent)),
        "jaccard_similarity": (
            len(shared) / len(combined_destinations)
            if combined_destinations
            else np.nan
        ),
        "incumbent_effective_destinations": effective_destinations(
            incumbent_links["passengers"]
        ),
        "newcomer_effective_destinations": effective_destinations(
            newcomer_links["passengers"]
        ),
        "baseline_incumbent_throughput": baseline_traffic,
        "combined_vs_baseline_throughput_change_pct": (
            100 * (combined / baseline_traffic - 1)
            if baseline_traffic
            else np.nan
        ),
        "combined_vs_baseline_destination_change": int(
            len(combined_destinations) - len(baseline_incumbent)
        ),
    }


def route_acquisition_sequence(
    routes: pd.DataFrame,
    newcomer: str,
    *,
    first_months: int = 24,
    segment_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """First observed positive month for every newcomer destination."""
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    links = segments[
        ((segments["airport_a"] == newcomer) | (segments["airport_b"] == newcomer))
        & (segments["passengers"] > 0)
    ].copy()
    if links.empty:
        return pd.DataFrame(
            columns=[
                "destination",
                "first_period",
                "ramp_month",
                "passengers_in_first_month",
            ]
        )
    links["destination"] = links.apply(
        lambda row: _counterpart(row, newcomer), axis=1
    )
    entry = links["period"].min()
    links["ramp_month"] = links["period"].map(
        lambda period: period.ordinal - entry.ordinal + 1
    )
    links = links[links["ramp_month"] <= first_months]
    first = (
        links.sort_values(["destination", "period"])
        .groupby("destination", as_index=False)
        .first()
        .rename(
            columns={
                "period": "first_period",
                "passengers": "passengers_in_first_month",
            }
        )
    )
    return first[
        [
            "destination",
            "first_period",
            "ramp_month",
            "passengers_in_first_month",
        ]
    ].sort_values(["ramp_month", "destination"]).reset_index(drop=True)


def annual_network_metrics(
    routes: pd.DataFrame,
    airport_monthly: pd.DataFrame,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    min_route_persistence_months: int = 3,
    segment_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Complete-calendar-year network concentration and breadth."""
    airport = add_month_period(airport_monthly)
    complete = airport.groupby("year")["month"].nunique()
    complete_years = sorted(int(year) for year in complete[complete == 12].index)
    if start_year is not None:
        complete_years = [year for year in complete_years if year >= start_year]
    if end_year is not None:
        complete_years = [year for year in complete_years if year <= end_year]
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    rows = []
    previous_routes: set[tuple[str, str]] | None = None
    for year in complete_years:
        periods = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
        traffic = (
            airport[airport["period"].isin(periods)]
            .groupby("airport")["passengers"]
            .sum()
        )
        traffic = traffic[traffic > 0]
        shares = traffic / traffic.sum()
        hhi = float((shares**2).sum())
        segment_metrics = window_segment_metrics(segments, periods)
        active = segment_metrics[
            (segment_metrics["passengers"] > 0)
            & (
                segment_metrics["persistence"]
                >= min_route_persistence_months
            )
        ]
        active_keys = set(active.index)
        network = airport_network_metrics(
            routes,
            airport_monthly,
            periods,
            min_persistence_months=min_route_persistence_months,
            segment_monthly=segments,
        )
        row = {
            "year": year,
            "top_five_airport_share_pct": float(
                100 * traffic.nlargest(5).sum() / traffic.sum()
            ),
            "traffic_hhi": hhi,
            "effective_traffic_centres": 1 / hhi,
            "active_airports": int(len(traffic)),
            "active_routes": int(len(active_keys)),
            "median_direct_destinations": float(
                network["direct_destinations"].median()
            ),
            "median_effective_destinations": float(
                network["effective_destinations"].median()
            ),
        }
        if previous_routes is not None:
            row.update(
                {
                    "route_births": int(len(active_keys - previous_routes)),
                    "route_deaths": int(len(previous_routes - active_keys)),
                    "route_survival_pct": float(
                        100
                        * len(active_keys & previous_routes)
                        / len(previous_routes)
                    ),
                }
            )
        rows.append(row)
        previous_routes = active_keys
    return pd.DataFrame(rows).set_index("year")


def structural_two_leg_opportunities(
    routes: pd.DataFrame,
    *,
    hub: str,
    periods: pd.PeriodIndex,
    previous_periods: pd.PeriodIndex | None = None,
    min_leg_passengers: int = 100_000,
    min_leg_persistence_months: int = 6,
    min_leg_yoy_pct: float = -10.0,
    direct_persistence_months: int = 6,
    coordinates: dict[str, tuple[float, float]] | None = None,
    max_detour_ratio: float | None = None,
) -> pd.DataFrame:
    """Topological two-leg paths ranked by the balanced-leg proxy.

    The result is structural only: it is not transfer demand or reusable
    capacity on either leg.
    """
    current = directed_window_metrics(routes, periods)
    previous = (
        directed_window_metrics(routes, previous_periods)
        if previous_periods is not None
        else None
    )

    def eligible_hub_legs(direction: str) -> pd.DataFrame:
        reset = current.reset_index()
        if direction == "inbound":
            legs = reset[reset["destination"] == hub].copy()
            legs["counterpart"] = legs["origin"]
        else:
            legs = reset[reset["origin"] == hub].copy()
            legs["counterpart"] = legs["destination"]
        if previous is None:
            legs["prior_passengers"] = legs["passengers"]
        else:
            def prior_passengers(counterpart: str) -> float:
                key = (
                    (counterpart, hub)
                    if direction == "inbound"
                    else (hub, counterpart)
                )
                return (
                    float(previous.loc[key, "passengers"])
                    if key in previous.index
                    else 0.0
                )

            legs["prior_passengers"] = legs["counterpart"].map(
                prior_passengers
            )
        legs["yoy_pct"] = (
            legs["passengers"]
            / legs["prior_passengers"].replace(0, np.nan)
            - 1
        ) * 100
        return legs[
            (legs["passengers"] >= min_leg_passengers)
            & (legs["persistence"] >= min_leg_persistence_months)
            & (legs["yoy_pct"] >= min_leg_yoy_pct)
        ].set_index("counterpart")

    inbound = eligible_hub_legs("inbound")
    outbound = eligible_hub_legs("outbound")
    rows = []
    for origin in sorted(inbound.index):
        for destination in sorted(outbound.index):
            if origin == destination:
                continue
            direct_key = (origin, destination)
            direct = current.loc[direct_key] if direct_key in current.index else None
            if (
                direct is not None
                and int(direct["persistence"]) >= direct_persistence_months
            ):
                continue

            detour_ratio = np.nan
            if coordinates is not None and {
                origin,
                hub,
                destination,
            } <= set(coordinates):
                direct_distance = haversine_km(
                    coordinates[origin], coordinates[destination]
                )
                path_distance = haversine_km(
                    coordinates[origin], coordinates[hub]
                ) + haversine_km(
                    coordinates[hub], coordinates[destination]
                )
                detour_ratio = (
                    path_distance / direct_distance
                    if direct_distance > 0
                    else np.nan
                )
                if (
                    max_detour_ratio is not None
                    and detour_ratio > max_detour_ratio
                ):
                    continue
            rows.append(
                {
                    "origin": origin,
                    "hub": hub,
                    "destination": destination,
                    "balanced_leg_passengers": int(
                        min(
                            inbound.loc[origin, "passengers"],
                            outbound.loc[destination, "passengers"],
                        )
                    ),
                    "inbound_leg_passengers": int(
                        inbound.loc[origin, "passengers"]
                    ),
                    "outbound_leg_passengers": int(
                        outbound.loc[destination, "passengers"]
                    ),
                    "inbound_leg_yoy_pct": float(
                        inbound.loc[origin, "yoy_pct"]
                    ),
                    "outbound_leg_yoy_pct": float(
                        outbound.loc[destination, "yoy_pct"]
                    ),
                    "direct_passengers": (
                        int(direct["passengers"]) if direct is not None else 0
                    ),
                    "direct_persistence_months": (
                        int(direct["persistence"]) if direct is not None else 0
                    ),
                    "detour_ratio": float(detour_ratio),
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "origin",
                "hub",
                "destination",
                "balanced_leg_passengers",
                "inbound_leg_passengers",
                "outbound_leg_passengers",
                "inbound_leg_yoy_pct",
                "outbound_leg_yoy_pct",
                "direct_passengers",
                "direct_persistence_months",
                "detour_ratio",
            ]
        )
    return pd.DataFrame(rows).sort_values(
        ["balanced_leg_passengers", "origin", "destination"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def triangle_closures(
    routes: pd.DataFrame,
    *,
    current_periods: pd.PeriodIndex,
    previous_periods: pd.PeriodIndex,
    min_direct_passengers: int = 50_000,
    min_direct_persistence_months: int = 6,
    min_prior_leg_persistence_months: int = 6,
    segment_monthly: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """New persistent direct routes previously two-edge-only in this network."""
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    current = window_segment_metrics(segments, current_periods)
    previous = window_segment_metrics(segments, previous_periods)
    previous_active = previous[
        previous["persistence"] >= min_prior_leg_persistence_months
    ].reset_index()
    adjacency: dict[str, set[str]] = {}
    for row in previous_active.itertuples():
        adjacency.setdefault(row.airport_a, set()).add(row.airport_b)
        adjacency.setdefault(row.airport_b, set()).add(row.airport_a)
    candidates = current[
        (current["passengers"] >= min_direct_passengers)
        & (
            current["persistence"]
            >= min_direct_persistence_months
        )
    ].reset_index()
    rows = []
    for row in candidates.itertuples():
        key = (row.airport_a, row.airport_b)
        if key in previous.index and previous.loc[key, "persistence"] > 0:
            continue
        hubs = sorted(
            adjacency.get(row.airport_a, set())
            & adjacency.get(row.airport_b, set())
        )
        if not hubs:
            continue
        rows.append(
            {
                "airport_a": row.airport_a,
                "airport_b": row.airport_b,
                "passengers": int(row.passengers),
                "persistence_months": int(row.persistence),
                "prior_two_edge_hubs": hubs,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "airport_a",
                "airport_b",
                "passengers",
                "persistence_months",
                "prior_two_edge_hubs",
            ]
        )
    return pd.DataFrame(rows).sort_values(
        ["passengers", "airport_a", "airport_b"],
        ascending=[False, True, True],
    ).reset_index(drop=True)


def coordinate_coverage(
    airport_monthly: pd.DataFrame,
    periods: pd.PeriodIndex,
    coordinates: dict[str, tuple[float, float]],
) -> dict:
    """Coordinate coverage by active-airport count and passenger share."""
    traffic = (
        add_month_period(airport_monthly)
        .loc[lambda d: d["period"].isin(periods)]
        .groupby("airport")["passengers"]
        .sum()
    )
    traffic = traffic[traffic > 0]
    covered = traffic[traffic.index.isin(coordinates)]
    missing = traffic[~traffic.index.isin(coordinates)].sort_values(
        ascending=False
    )
    return {
        "airports_with_coordinates": int(len(covered)),
        "active_airports": int(len(traffic)),
        "passenger_share_pct": float(100 * covered.sum() / traffic.sum()),
        "missing_airports_by_traffic": {
            str(code): int(value) for code, value in missing.items()
        },
    }
