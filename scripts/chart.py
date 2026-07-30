#!/usr/bin/env python3
"""Generate visible dashboard charts from published canonical datasets."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import yaml
from PIL import Image

from metrics import (
    add_month_period,
    add_quarter_period,
    domestic_airline_passengers_carried,
    domestic_airport_matrix,
    domestic_airport_throughput,
    domestic_demand_series,
    international_gateway_matrix,
    international_gateway_throughput,
)
from network import (
    annual_network_metrics,
    airport_network_metrics,
    bidirectional_segments,
    comparison_windows as route_comparison_windows,
    coordinate_coverage,
    dual_airport_monthly_development,
    dual_airport_metrics,
    eligible_route_markets,
    pareto_frontier,
    route_acquisition_sequence,
    route_market_frontier,
    structural_two_leg_opportunities,
    triangle_closures,
)

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
CHARTS_DIR = ROOT / "charts"
DOMESTIC_MONTHLY_PATH = PROCESSED_DIR / "airport_monthly.csv"
INTERNATIONAL_QUARTERLY_PATH = PROCESSED_DIR / "airport_international_quarterly.csv"
CARRIER_MONTHLY_PATH = PROCESSED_DIR / "carrier_monthly.csv"
DOMESTIC_ROUTE_MONTHLY_PATH = PROCESSED_DIR / "domestic_route_monthly.csv"
METADATA_PATH = PROCESSED_DIR / "metadata.json"
DASHBOARD_SUMMARY_PATH = PROCESSED_DIR / "dashboard_summary.json"
ROUTE_ANALYSIS_SUMMARY_PATH = PROCESSED_DIR / "route_analysis_summary.json"
MANIFEST_PATH = CHARTS_DIR / "manifest.json"

DPI = 150
FIGSIZE_WIDE = (14, 8)
FIGSIZE_TALL = (14, 10)
FIGSIZE_HEATMAP = (14, 12)

BG = "#0d1117"
PANEL_BG = "#0d1117"
TEXT = "#e6edf3"
TITLE = "#f0f6fc"
SUBTLE = "#94a3b8"
MUTED = "#64748b"
GRID = "#334155"

POSITIVE = "#4ade80"
NEGATIVE = "#f87171"
ACCENT = "#fbbf24"
PRIMARY = "#58a6ff"

FALLBACK_COLORS = [
    "#4cc9f0",
    "#f72585",
    "#4ade80",
    "#fbbf24",
    "#a78bfa",
    "#fb923c",
    "#22d3ee",
    "#f87171",
    "#34d399",
    "#e879f9",
    "#60a5fa",
    "#2dd4bf",
    "#facc15",
    "#c084fc",
    "#fb7185",
]

MONTH_ABBR = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

CHART_IDS = [
    "india_domestic_demand_pulse",
    "top_airport_traffic_trends",
    "newcomer_airport_rampup_24m",
    "domestic_market_share_gainers",
    "international_gateway_share_gainers",
    "airport_seasonality_fingerprint",
    "ncr_route_opportunity_frontier",
    "dual_airport_network_roles",
    "domestic_network_decentralisation",
]

RAMP_MONTHS = 24
LEFT_CENSOR_BUFFER_MONTHS = 12
RAMP_MIN_CUMULATIVE_AVAILABLE = 100_000
RAMP_MIN_PEAK_MONTH = 20_000
RAMP_MIN_OBSERVED_MONTHS = 3
RAMP_MAX_LABELS = 12

DOMESTIC_SHARE_WINDOW_MONTHS = 12
DOMESTIC_SHARE_MIN_TRAFFIC = 100_000
DOMESTIC_SHARE_TOP_N = 10

INTERNATIONAL_SHARE_WINDOW_QUARTERS = 4
INTERNATIONAL_SHARE_MIN_TRAFFIC = 50_000
INTERNATIONAL_SHARE_TOP_N = 8

SEASONALITY_MIN_COMPLETE_YEARS = 3
SEASONALITY_MIN_LATEST_T12 = 100_000
SEASONALITY_MAX_AIRPORTS = 60
SEASONALITY_VMIN = 60
SEASONALITY_VCENTER = 100
SEASONALITY_VMAX = 140

PASSENGER_RACE_FRAME_MS = 300
PASSENGER_RACE_LAST_FRAME_MS = 3000

ROUTE_WINDOW_MONTHS = 12
ROUTE_FRONTIER_MIN_T12 = 250_000
ROUTE_FRONTIER_MIN_PERSISTENCE = 9
ROUTE_FRONTIER_FOCAL = "DEL"
ROUTE_FRONTIER_PROXY = "HDO"
ROUTE_FRONTIER_DISTANCE_ORIGIN = "DXN"

DUAL_AIRPORT_PAIRS = [
    ("GOI", "GOX"),
    ("DEL", "HDO"),
    ("BOM", "NMIA"),
]
DUAL_MIN_MARKET_PASSENGERS = 10_000
DUAL_PERSISTENCE_FRACTION = 0.5

NETWORK_START_YEAR = 2016
NETWORK_MIN_ROUTE_PERSISTENCE = 3

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "figure.dpi": DPI,
        "savefig.dpi": DPI,
        "axes.unicode_minus": False,
    }
)


def load_metadata() -> dict:
    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    return {}


def load_mappings() -> dict:
    path = ROOT / "mappings.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


MAPPINGS = load_mappings()
AIRPORT_COLORS = MAPPINGS.get("airport_colors", {}) or {}


def repo_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo:
        return f"github.com/{repo}"

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return "github.com/mkubicek/india-aviation-stats"

    if result.returncode != 0:
        return "github.com/mkubicek/india-aviation-stats"

    url = result.stdout.strip().removesuffix(".git")
    if url.startswith("https://"):
        return url.removeprefix("https://")
    if url.startswith("git@github.com:"):
        return "github.com/" + url.removeprefix("git@github.com:")
    return url or "github.com/mkubicek/india-aviation-stats"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_fingerprint(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p.relative_to(ROOT))):
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def load_domestic_monthly() -> pd.DataFrame:
    return pd.read_csv(DOMESTIC_MONTHLY_PATH)


def load_international_quarterly() -> pd.DataFrame:
    return pd.read_csv(INTERNATIONAL_QUARTERLY_PATH)


def load_carrier_monthly() -> pd.DataFrame:
    return pd.read_csv(CARRIER_MONTHLY_PATH)


def load_domestic_routes() -> pd.DataFrame:
    return pd.read_csv(DOMESTIC_ROUTE_MONTHLY_PATH)


def domestic_coverage(monthly: pd.DataFrame) -> str:
    m = add_month_period(monthly)
    periods = m["period"].sort_values()
    return f"{periods.iloc[0]}..{periods.iloc[-1]}"


def international_coverage(quarterly: pd.DataFrame) -> str:
    q = add_quarter_period(quarterly)
    periods = q["period"].sort_values()
    return f"{periods.iloc[0]}..{periods.iloc[-1]}"


def carrier_domestic_coverage(carrier: pd.DataFrame) -> str:
    national = domestic_airline_passengers_carried(carrier)
    return f"{national.index.min()}..{national.index.max()}"


def route_coverage(routes: pd.DataFrame) -> str:
    periods = add_month_period(routes)["period"].sort_values()
    return f"{periods.iloc[0]}..{periods.iloc[-1]}"


def airport_coordinates() -> dict[str, tuple[float, float]]:
    return {
        code: (float(info["lat"]), float(info["lon"]))
        for code, info in MAPPINGS.get("airports", {}).items()
        if info.get("lat") is not None and info.get("lon") is not None
    }


def add_footer(fig: plt.Figure, *, coverage: str, fingerprint: str) -> None:
    meta = load_metadata()
    data_str = "Data: DGCA"
    if meta.get("data_date"):
        data_str += f" (as of {meta['data_date']})"
    footer = f"{repo_url()} | {data_str} | Generated {date.today()} | Coverage: {coverage}"
    fig.text(0.985, 0.018, footer, ha="right", va="bottom", fontsize=8, color=MUTED)


def style_axis(ax, title: str, subtitle: str = "", ylabel: str = "") -> None:
    ax.set_facecolor(BG)
    ax.set_title(
        title,
        fontsize=16,
        fontweight="bold",
        color=TITLE,
        pad=24 if subtitle else 16,
    )
    if subtitle:
        ax.text(
            0.5,
            1.01,
            subtitle,
            transform=ax.transAxes,
            ha="center",
            va="bottom",
            fontsize=9,
            color=SUBTLE,
        )
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=11, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.spines["left"].set_color(GRID)
    ax.grid(axis="y", alpha=0.2, color=GRID, linestyle="--")


def style_secondary_axis(ax, ylabel: str) -> None:
    ax.set_facecolor(BG)
    ax.set_ylabel(ylabel, fontsize=11, color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["right"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(False)


def fmt_millions(x, pos=None) -> str:
    return f"{x / 1_000_000:.0f}M"


def fmt_thousands(x, pos=None) -> str:
    return f"{x / 1_000:.0f}K"


def fmt_percent(x, pos=None) -> str:
    return f"{x:.0f}%"


def fmt_pp(x: float) -> str:
    return f"{x:+.2f} pp"


def fmt_axis_pp(x, pos=None) -> str:
    if abs(x) < 1e-9:
        return "0.0 pp"
    return f"{x:+.1f} pp"


def fmt_optional_pct(value: float | None) -> str:
    if value is None or pd.isna(value) or not np.isfinite(value):
        return "n/a"
    return f"{value:+.1f}%"


def fmt_optional_millions(value: float | None) -> str:
    if value is None or pd.isna(value) or not np.isfinite(value):
        return "n/a"
    return f"{value / 1_000_000:.1f}M"


def fmt_signed_millions(value: float) -> str:
    millions = value / 1_000_000
    if 0 < abs(millions) < 0.1:
        return f"{millions:+.2f}M"
    return f"{millions:+.1f}M"


def fmt_context_millions(value: float) -> str:
    return f"{value / 1_000_000:.1f}M"


def stable_color(key: str) -> str:
    explicit = AIRPORT_COLORS.get(key)
    if explicit:
        return explicit
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return FALLBACK_COLORS[int(digest[:8], 16) % len(FALLBACK_COLORS)]


def airport_label(iata: str) -> str:
    info = MAPPINGS.get("airports", {}).get(iata, {}) or {}
    city = info.get("city")
    return f"{iata} ({city})" if city else iata


def save_chart(fig: plt.Figure, chart_id: str) -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / f"{chart_id}.png"
    fig.savefig(
        path,
        dpi=DPI,
        facecolor=BG,
        edgecolor=BG,
        metadata={
            "Title": chart_id,
            "Author": "india-aviation-stats",
            "Source": "DGCA public aviation statistics",
        },
    )
    plt.close(fig)
    return path


def clean_upper_bound(value: float) -> float:
    if not np.isfinite(value) or value <= 0:
        return 1.0
    magnitude = 10 ** np.floor(np.log10(value))
    for step in (1, 1.25, 1.5, 2, 2.5, 5, 7.5, 10):
        candidate = step * magnitude
        if value <= candidate:
            return float(candidate)
    return float(10 * magnitude)


def spread_label_positions(
    points: Sequence[tuple[str, float]],
    *,
    lower: float,
    upper: float,
    min_gap: float,
) -> dict[str, float]:
    if not points:
        return {}
    if len(points) == 1:
        return {points[0][0]: min(max(points[0][1], lower), upper)}

    available = max(upper - lower, 0.0)
    min_gap = min(min_gap, available / (len(points) - 1) * 0.95)
    ordered = sorted(points, key=lambda item: (item[1], item[0]))
    adjusted: list[tuple[str, float]] = []
    for key, value in ordered:
        y = min(max(value, lower), upper)
        if adjusted:
            y = max(y, adjusted[-1][1] + min_gap)
        adjusted.append((key, y))

    overflow = adjusted[-1][1] - upper
    if overflow > 0:
        adjusted = [(key, y - overflow) for key, y in adjusted]

    underflow = lower - adjusted[0][1]
    if underflow > 0:
        adjusted = [(key, y + underflow) for key, y in adjusted]

    return {key: y for key, y in adjusted}


def period_month_distance(later: pd.Period, earlier: pd.Period) -> int:
    return later.ordinal - earlier.ordinal


def period_timestamp(period: pd.Period) -> pd.Timestamp:
    return period.to_timestamp()


# Airport-level endpoint-throughput matrices live in metrics.py (the single home
# for passenger metric semantics); these names are the airport-chart entry points.
domestic_airport_month_matrix = domestic_airport_matrix
international_airport_quarter_matrix = international_gateway_matrix


def complete_rolling_sum(pivot: pd.DataFrame, window: int) -> pd.DataFrame:
    available = set(pivot.index)
    complete_periods = [
        p for p in pivot.index if all((p - offset) in available for offset in range(window))
    ]
    if not complete_periods:
        return pd.DataFrame()
    return pivot.rolling(window, min_periods=window).sum().loc[complete_periods]


def _domestic_trailing_airport_passengers(
    monthly: pd.DataFrame,
    window: int = 12,
) -> pd.DataFrame:
    return complete_rolling_sum(domestic_airport_month_matrix(monthly), window)


def complete_share_window_periods(
    periods: Iterable[pd.Period],
    *,
    window: int,
) -> tuple[list[pd.Period], list[pd.Period]]:
    period_index = pd.PeriodIndex(sorted(periods))
    if period_index.empty:
        raise ValueError("Cannot build share windows from an empty period index")

    available = set(period_index)
    latest_end = period_index.max()
    latest_periods = [latest_end - i for i in range(window - 1, -1, -1)]
    previous_periods = [latest_end - i for i in range((window * 2) - 1, window - 1, -1)]
    missing = [p for p in previous_periods + latest_periods if p not in available]
    if missing:
        missing_text = ", ".join(str(p) for p in missing)
        raise ValueError(f"Share windows are incomplete; missing periods: {missing_text}")
    return latest_periods, previous_periods


def market_share_movers(
    pivot: pd.DataFrame,
    *,
    window: int,
    min_traffic: int,
    top_n: int,
) -> pd.DataFrame:
    latest_periods, previous_periods = complete_share_window_periods(
        pivot.index,
        window=window,
    )
    latest_airport = pivot.loc[latest_periods].sum(axis=0)
    previous_airport = pivot.loc[previous_periods].sum(axis=0)
    latest_share = latest_airport / latest_airport.sum()
    previous_share = previous_airport / previous_airport.sum()
    delta_pp = (latest_share - previous_share) * 100

    df = pd.DataFrame(
        {
            "airport": delta_pp.index,
            "delta_pp": delta_pp.values,
            "latest_passengers": latest_airport.reindex(delta_pp.index).values,
            "previous_passengers": previous_airport.reindex(delta_pp.index).values,
        }
    )
    eligible = (df["latest_passengers"] >= min_traffic) | (
        df["previous_passengers"] >= min_traffic
    )
    eligible_df = df[eligible].copy()
    gainers = eligible_df.sort_values(
        ["delta_pp", "airport"],
        ascending=[False, True],
    ).head(top_n)
    losers = eligible_df.sort_values(
        ["delta_pp", "airport"],
        ascending=[True, True],
    ).head(top_n)
    selected = pd.concat([losers, gainers], ignore_index=True).drop_duplicates(
        subset=["airport"],
        keep="first",
    )
    return selected.sort_values(["delta_pp", "airport"], ascending=[True, True]).reset_index(
        drop=True
    )


def format_month_period(period: pd.Period) -> str:
    return f"{MONTH_ABBR[int(period.month)]} {int(period.year)}"


def format_quarter_period(period: pd.Period) -> str:
    return f"{period.year}Q{period.quarter}"


def active_entity_count(pivot: pd.DataFrame, periods: Sequence[pd.Period]) -> int:
    """Airports/gateways carrying any traffic across the comparison windows."""
    window = pivot.loc[list(periods)]
    return int((window.sum(axis=0) > 0).sum())


def share_movers_subtitle(
    movers: pd.DataFrame,
    *,
    latest_periods: Sequence[pd.Period],
    previous_periods: Sequence[pd.Period],
    active: int,
    noun: str,
    scope: str,
    fmt,
) -> str:
    """Disclose the top-N-of-total selection, the metric scope, and the windows.

    ``scope`` names the metric population (e.g. "Share of domestic airport
    throughput") so the bars are never read as airline passengers carried.
    """
    n_gainers = int((movers["delta_pp"] > 0).sum())
    n_losers = int((movers["delta_pp"] < 0).sum())
    latest_label = f"{fmt(latest_periods[0])}–{fmt(latest_periods[-1])}"
    previous_label = f"{fmt(previous_periods[0])}–{fmt(previous_periods[-1])}"
    return (
        f"Top {n_gainers} gainers & {n_losers} decliners of {active} {noun}  ·  "
        f"{scope}  ·  {latest_label} vs {previous_label}"
    )


def newcomer_airport_ramps(
    monthly: pd.DataFrame,
    *,
    ramp_months: int = RAMP_MONTHS,
    left_censor_buffer_months: int = LEFT_CENSOR_BUFFER_MONTHS,
    min_cumulative_available: int = RAMP_MIN_CUMULATIVE_AVAILABLE,
    min_peak_month: int = RAMP_MIN_PEAK_MONTH,
    min_observed_months: int = RAMP_MIN_OBSERVED_MONTHS,
) -> pd.DataFrame:
    m = add_month_period(monthly)
    first_seen = m.groupby("airport")["period"].min()
    dataset_start = m["period"].min()
    records: list[dict] = []

    for airport in sorted(first_seen.index):
        first = first_seen.loc[airport]
        if first < dataset_start + left_censor_buffer_months:
            continue

        series = (
            m[m["airport"] == airport]
            .groupby("period")["passengers"]
            .sum()
            .sort_index()
        )
        ramp = series[(series.index >= first) & (series.index <= first + (ramp_months - 1))]
        observed_months = int(len(ramp))
        cumulative_available = int(ramp.sum())
        peak_month = int(ramp.max()) if observed_months else 0
        if observed_months < min_observed_months:
            continue
        if cumulative_available < min_cumulative_available and peak_month < min_peak_month:
            continue

        for period, passengers in ramp.items():
            records.append(
                {
                    "airport": airport,
                    "period": period,
                    "month_index": period_month_distance(period, first),
                    "passengers": int(passengers),
                    "first_period": first,
                    "observed_months": observed_months,
                    "cumulative_available": cumulative_available,
                    "peak_month": peak_month,
                }
            )

    if not records:
        return pd.DataFrame(
            columns=[
                "airport",
                "period",
                "month_index",
                "passengers",
                "first_period",
                "observed_months",
                "cumulative_available",
                "peak_month",
            ]
        )
    return pd.DataFrame(records).sort_values(
        ["cumulative_available", "airport", "month_index"],
        ascending=[False, True, True],
    )


def complete_calendar_years(monthly: pd.DataFrame) -> list[int]:
    months_per_year = monthly.groupby("year")["month"].nunique()
    return sorted(int(year) for year in months_per_year[months_per_year == 12].index)


def seasonality_fingerprint_matrix(
    monthly: pd.DataFrame,
    *,
    min_complete_years: int = SEASONALITY_MIN_COMPLETE_YEARS,
    min_latest_t12: int = SEASONALITY_MIN_LATEST_T12,
    max_airports: int = SEASONALITY_MAX_AIRPORTS,
) -> pd.DataFrame:
    complete_years = complete_calendar_years(monthly)
    if not complete_years:
        return pd.DataFrame(columns=range(1, 13))

    complete = monthly[monthly["year"].isin(complete_years)].copy()
    complete_year_count = complete.groupby("airport")["year"].nunique()
    t12 = complete_rolling_sum(domestic_airport_month_matrix(monthly), 12)
    if t12.empty:
        latest_t12 = pd.Series(0, index=complete_year_count.index, dtype=float)
    else:
        latest_t12 = t12.iloc[-1].reindex(complete_year_count.index).fillna(0)

    candidates = pd.DataFrame(
        {
            "airport": complete_year_count.index,
            "complete_years": complete_year_count.values,
            "latest_t12": latest_t12.reindex(complete_year_count.index).values,
        }
    )
    eligible = candidates[
        (candidates["complete_years"] >= min_complete_years)
        & (candidates["latest_t12"] >= min_latest_t12)
    ].copy()
    if eligible.empty:
        return pd.DataFrame(columns=range(1, 13))

    selected = eligible.sort_values(
        ["latest_t12", "airport"],
        ascending=[False, True],
    )["airport"].head(max_airports)

    annual = (
        complete.groupby(["airport", "year"], as_index=False)["passengers"]
        .sum()
        .rename(columns={"passengers": "annual_passengers"})
    )
    monthly_airport_year = complete.groupby(
        ["airport", "year", "month"],
        as_index=False,
    )["passengers"].sum()
    indexed = monthly_airport_year.merge(annual, on=["airport", "year"], how="left")
    indexed = indexed[indexed["annual_passengers"] > 0].copy()
    indexed["seasonality_index"] = (
        indexed["passengers"] / (indexed["annual_passengers"] / 12) * 100
    )
    fingerprint = (
        indexed.groupby(["airport", "month"])["seasonality_index"]
        .mean()
        .unstack("month")
    )
    return fingerprint.reindex(index=selected, columns=range(1, 13))


def chart_india_domestic_demand_pulse(
    carrier: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    # National domestic demand is passengers carried (counted once per journey),
    # sourced from the carrier table — NOT a national sum of airport endpoint
    # throughput, which double-counts every domestic journey. See metrics.py.
    national, t12, monthly_yoy, t12_yoy = domestic_demand_series(carrier)

    latest_period = national.index.max()
    latest_month_carried = float(national.loc[latest_period])
    latest_month_yoy = float(monthly_yoy.loc[latest_period] * 100)
    latest_t12 = float(t12.dropna().iloc[-1]) if not t12.dropna().empty else np.nan
    latest_t12_yoy = (
        float(t12_yoy.dropna().iloc[-1] * 100) if not t12_yoy.dropna().empty else np.nan
    )

    x = national.index.to_timestamp()
    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)
    ax2 = ax.twinx()
    bars = ax2.bar(
        x,
        national.values,
        width=25,
        color=PRIMARY,
        alpha=0.22,
        edgecolor="none",
        label="Monthly passengers carried",
    )
    line = ax.plot(
        t12.index.to_timestamp(),
        t12.values,
        color=ACCENT,
        linewidth=3,
        label="Trailing 12-month total",
    )[0]

    style_axis(
        ax,
        "India Domestic Aviation Demand Pulse",
        "Scheduled domestic passengers carried by month and trailing 12-month total",
        "Trailing 12-month passengers carried",
    )
    style_secondary_axis(ax2, "Monthly passengers carried")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(0, clean_upper_bound(float(t12.max()) * 1.08))
    ax2.set_ylim(0, clean_upper_bound(float(national.max()) * 1.20))
    ax.legend(
        [line, bars],
        ["Trailing 12-month total", "Monthly passengers carried"],
        loc="upper left",
        frameon=False,
        labelcolor=TEXT,
        fontsize=9,
    )

    kpi = (
        f"Latest month: {fmt_optional_millions(latest_month_carried)}"
        f" carried ({fmt_optional_pct(latest_month_yoy)} YoY)\n"
        f"Trailing 12 months: {fmt_optional_millions(latest_t12)}"
        f" carried ({fmt_optional_pct(latest_t12_yoy)} YoY)"
    )
    ax.text(
        0.985,
        0.94,
        kpi,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=10,
        color=TEXT,
        linespacing=1.5,
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": PANEL_BG,
            "edgecolor": GRID,
            "alpha": 0.92,
        },
    )

    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.86, bottom=0.12)
    return save_chart(fig, "india_domestic_demand_pulse")


def chart_top_airport_traffic_trends(
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    pivot = domestic_airport_month_matrix(monthly)
    t12 = complete_rolling_sum(pivot, window=12)
    if t12.empty:
        raise ValueError("No complete domestic trailing 12-month windows available")

    latest = t12.iloc[-1]
    latest_top = set(
        latest.sort_values(ascending=False).head(10).index
    )
    if len(t12) >= 13:
        previous = t12.iloc[-13]
        previous_top = set(previous.sort_values(ascending=False).head(10).index)
    else:
        previous_top = set()
    selected = sorted(latest_top | previous_top, key=lambda a: (-latest.get(a, 0), a))[:12]

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)
    x = t12.index.to_timestamp()
    max_value = 0.0
    endpoints: list[tuple[str, float]] = []
    for airport in selected:
        values = t12[airport]
        max_value = max(max_value, float(values.max()))
        color = stable_color(airport)
        ax.plot(
            x,
            values.values,
            color=color,
            linewidth=2.5,
            alpha=0.92,
        )
        endpoints.append((airport, float(values.iloc[-1])))

    style_axis(
        ax,
        "Top Airport Traffic Trends",
        "Trailing 12-month domestic airport passenger movements, arrivals + departures",
        "Domestic airport passenger movements",
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    y_upper = clean_upper_bound(max_value * 1.08)
    ax.set_ylim(0, y_upper)
    label_x = x[-1] + pd.DateOffset(months=1)
    adjusted = spread_label_positions(
        endpoints,
        lower=y_upper * 0.03,
        upper=y_upper * 0.96,
        min_gap=y_upper * 0.035,
    )
    for airport, value in endpoints:
        color = stable_color(airport)
        label_y = adjusted[airport]
        ax.plot(
            [x[-1], label_x],
            [value, label_y],
            color=color,
            alpha=0.45,
            linewidth=0.9,
        )
        ax.text(
            label_x,
            label_y,
            airport,
            va="center",
            ha="left",
            fontsize=9,
            fontweight="bold",
            color=color,
            clip_on=False,
        )
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=5))
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.08, right=0.88, top=0.86, bottom=0.12)
    return save_chart(fig, "top_airport_traffic_trends")


def chart_newcomer_airport_rampup(
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    ramps = newcomer_airport_ramps(monthly)
    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)

    if ramps.empty:
        max_value = 1
        ax.text(
            0.5,
            0.5,
            "No qualifying newcomer airports in the published data",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color=SUBTLE,
        )
    else:
        airport_order = (
            ramps[["airport", "cumulative_available"]]
            .drop_duplicates()
            .sort_values(["cumulative_available", "airport"], ascending=[False, True])
        )
        label_airports = set(airport_order.head(RAMP_MAX_LABELS)["airport"])
        max_value = float(ramps["passengers"].max())
        endpoints: list[tuple[str, float]] = []
        endpoint_rows: dict[str, pd.Series] = {}
        for airport in airport_order["airport"]:
            series = ramps[ramps["airport"] == airport].sort_values("month_index")
            color = stable_color(airport)
            should_label = airport in label_airports
            ax.plot(
                series["month_index"],
                series["passengers"],
                color=color,
                linewidth=2.4 if should_label else 1.3,
                alpha=0.9 if should_label else 0.25,
                marker="o" if should_label else None,
                markersize=3,
            )
            if should_label:
                endpoint = series.iloc[-1]
                endpoints.append((airport, float(endpoint["passengers"])))
                endpoint_rows[airport] = endpoint

    style_axis(
        ax,
        "Newcomer Airport Ramp-up",
        "Monthly domestic airport passenger movements during each airport's "
        "first 24 DGCA-observed months",
        "Airport passenger movements",
    )
    ax.set_xlabel("Months since first DGCA-observed month", color=TEXT, fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_thousands))
    ax.set_xlim(-0.5, RAMP_MONTHS + 2.2)
    ax.set_xticks(range(0, RAMP_MONTHS, 3))
    y_upper = clean_upper_bound(max_value * 1.15)
    ax.set_ylim(0, y_upper)
    if not ramps.empty:
        adjusted = spread_label_positions(
            endpoints,
            lower=y_upper * 0.025,
            upper=y_upper * 0.96,
            min_gap=y_upper * 0.035,
        )
        for airport, value in endpoints:
            endpoint = endpoint_rows[airport]
            color = stable_color(airport)
            label_y = adjusted[airport]
            label_x = min(float(endpoint["month_index"]) + 0.7, RAMP_MONTHS + 0.15)
            ax.plot(
                [endpoint["month_index"], label_x - 0.15],
                [value, label_y],
                color=color,
                alpha=0.45,
                linewidth=0.9,
            )
            ax.text(
                label_x,
                label_y,
                airport,
                va="center",
                ha="left",
                fontsize=9,
                fontweight="bold",
                color=color,
                clip_on=False,
            )
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.08, right=0.90, top=0.86, bottom=0.13)
    return save_chart(fig, "newcomer_airport_rampup_24m")


def chart_share_movers(
    movers: pd.DataFrame,
    *,
    chart_id: str,
    title: str,
    subtitle: str,
    pax_change_header: str,
    latest_pax_header: str,
    coverage: str,
    fingerprint: str,
) -> Path:
    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)

    if movers.empty:
        x_limit = 1.0
        ax.text(
            0.5,
            0.5,
            "No qualifying share movers in the published data",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color=SUBTLE,
        )
        airports: list[str] = []
    else:
        airports = movers["airport"].tolist()
        values = movers["delta_pp"].astype(float).values
        colors = [POSITIVE if value >= 0 else NEGATIVE for value in values]
        y = np.arange(len(movers))
        ax.barh(y, values, color=colors, edgecolor="none", height=0.68)
        x_limit = clean_upper_bound(float(np.max(np.abs(values))) * 1.35)
        label_offset = x_limit * 0.025
        for y_pos, row in enumerate(movers.itertuples(index=False)):
            value = float(row.delta_pp)
            ax.text(
                value + label_offset if value >= 0 else value - label_offset,
                y_pos,
                fmt_pp(value),
                va="center",
                ha="left" if value >= 0 else "right",
                fontsize=9,
                color=TEXT,
            )
            pax_change = float(row.latest_passengers - row.previous_passengers)
            pax_change_color = POSITIVE if pax_change >= 0 else NEGATIVE
            ax.text(
                1.13,
                y_pos,
                fmt_signed_millions(pax_change),
                transform=ax.get_yaxis_transform(),
                va="center",
                ha="right",
                fontsize=9,
                color=pax_change_color,
                clip_on=False,
            )
            ax.text(
                1.31,
                y_pos,
                fmt_context_millions(float(row.latest_passengers)),
                transform=ax.get_yaxis_transform(),
                va="center",
                ha="right",
                fontsize=9,
                color=TEXT,
                clip_on=False,
            )
        header_y = len(movers) + 0.15
        for x_pos, header in ((1.13, pax_change_header), (1.31, latest_pax_header)):
            ax.text(
                x_pos,
                header_y,
                header,
                transform=ax.get_yaxis_transform(),
                va="bottom",
                ha="right",
                fontsize=8,
                fontweight="bold",
                color=SUBTLE,
                clip_on=False,
            )
        ax.set_ylim(-0.75, len(movers) + 0.75)

    ax.axvline(0, color=SUBTLE, linewidth=1, alpha=0.75)
    ax.set_yticks(range(len(airports)))
    ax.set_yticklabels(airports, fontsize=10, color=TEXT, fontweight="bold")
    ax.set_xlim(-x_limit, x_limit)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(fmt_axis_pp))
    ax.set_xlabel("Percentage-point share change", color=TEXT, fontsize=11)
    style_axis(ax, title, subtitle, "")
    ax.grid(axis="x", alpha=0.2, color=GRID, linestyle="--")
    ax.grid(axis="y", visible=False)
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.10, right=0.72, top=0.86, bottom=0.13)
    return save_chart(fig, chart_id)


def chart_domestic_market_share_gainers(
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    pivot = domestic_airport_month_matrix(monthly)
    latest_periods, previous_periods = complete_share_window_periods(
        pivot.index,
        window=DOMESTIC_SHARE_WINDOW_MONTHS,
    )
    movers = market_share_movers(
        pivot,
        window=DOMESTIC_SHARE_WINDOW_MONTHS,
        min_traffic=DOMESTIC_SHARE_MIN_TRAFFIC,
        top_n=DOMESTIC_SHARE_TOP_N,
    )
    subtitle = share_movers_subtitle(
        movers,
        latest_periods=latest_periods,
        previous_periods=previous_periods,
        active=active_entity_count(pivot, latest_periods + previous_periods),
        noun="airports",
        scope="Share of domestic airport throughput",
        fmt=format_month_period,
    )
    return chart_share_movers(
        movers,
        chart_id="domestic_market_share_gainers",
        title="Domestic Airport Throughput Share Movers",
        subtitle=subtitle,
        pax_change_header="Throughput change",
        latest_pax_header="Latest 12M throughput",
        coverage=coverage,
        fingerprint=fingerprint,
    )


def chart_international_gateway_share_gainers(
    quarterly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    pivot = international_airport_quarter_matrix(quarterly)
    latest_periods, previous_periods = complete_share_window_periods(
        pivot.index,
        window=INTERNATIONAL_SHARE_WINDOW_QUARTERS,
    )
    movers = market_share_movers(
        pivot,
        window=INTERNATIONAL_SHARE_WINDOW_QUARTERS,
        min_traffic=INTERNATIONAL_SHARE_MIN_TRAFFIC,
        top_n=INTERNATIONAL_SHARE_TOP_N,
    )
    subtitle = share_movers_subtitle(
        movers,
        latest_periods=latest_periods,
        previous_periods=previous_periods,
        active=active_entity_count(pivot, latest_periods + previous_periods),
        noun="gateways",
        scope="Indian airport gateway throughput",
        fmt=format_quarter_period,
    )
    return chart_share_movers(
        movers,
        chart_id="international_gateway_share_gainers",
        title="International Gateway Throughput Share Movers",
        subtitle=subtitle,
        pax_change_header="Throughput change",
        latest_pax_header="Latest 4Q throughput",
        coverage=coverage,
        fingerprint=fingerprint,
    )


def chart_airport_seasonality_fingerprint(
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    matrix = seasonality_fingerprint_matrix(monthly)
    fig, ax = plt.subplots(figsize=FIGSIZE_HEATMAP, facecolor=BG)

    cmap = mcolors.LinearSegmentedColormap.from_list(
        "seasonality_dark",
        [PRIMARY, BG, ACCENT],
    )
    cmap.set_bad("#161b22")
    norm = mcolors.TwoSlopeNorm(
        vmin=SEASONALITY_VMIN,
        vcenter=SEASONALITY_VCENTER,
        vmax=SEASONALITY_VMAX,
    )

    if matrix.empty:
        im = ax.imshow(np.empty((0, 12)), aspect="auto", cmap=cmap, norm=norm)
        ax.text(
            0.5,
            0.5,
            "No qualifying airports for seasonality fingerprint",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=12,
            color=SUBTLE,
        )
    else:
        values = matrix.clip(SEASONALITY_VMIN, SEASONALITY_VMAX).to_numpy(dtype=float)
        im = ax.imshow(values, aspect="auto", cmap=cmap, norm=norm)

    ax.set_facecolor(BG)
    ax.set_title(
        "Airport Seasonality Fingerprint",
        fontsize=16,
        fontweight="bold",
        color=TITLE,
        pad=24,
    )
    ax.text(
        0.5,
        1.01,
        "Monthly airport-throughput index by airport; 100 = that airport's average month",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color=SUBTLE,
    )
    ax.set_xticks(range(12))
    ax.set_xticklabels([MONTH_ABBR[i] for i in range(1, 13)], color=TEXT)
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels(matrix.index.tolist(), color=TEXT, fontsize=8)
    ax.tick_params(axis="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.015)
    cbar.set_label("Index, 100 = airport average month", color=TEXT, fontsize=10)
    cbar.ax.tick_params(colors=TEXT, labelsize=8)
    cbar.outline.set_edgecolor(GRID)

    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.10, right=0.94, top=0.88, bottom=0.08)
    return save_chart(fig, "airport_seasonality_fingerprint")


def route_frontier_data(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    focal_airport: str = ROUTE_FRONTIER_FOCAL,
    proxy_airport: str | None = ROUTE_FRONTIER_PROXY,
    distance_origin: str | None = ROUTE_FRONTIER_DISTANCE_ORIGIN,
    window_months: int = ROUTE_WINDOW_MONTHS,
    min_t12_passengers: int = ROUTE_FRONTIER_MIN_T12,
    min_persistence_months: int = ROUTE_FRONTIER_MIN_PERSISTENCE,
    segment_monthly: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], object]:
    windows = route_comparison_windows(
        routes, window_months=window_months
    )
    frontier = route_market_frontier(
        routes,
        monthly,
        focal_airport=focal_airport,
        proxy_airport=proxy_airport,
        distance_origin=distance_origin,
        coordinates=airport_coordinates(),
        window_months=window_months,
        segment_monthly=segment_monthly,
    )
    eligible = eligible_route_markets(
        frontier,
        min_t12_passengers=min_t12_passengers,
        min_persistence_months=min_persistence_months,
    )
    pareto = pareto_frontier(
        eligible,
        {
            "latest_t12_passengers": True,
            "yoy_change_pct": True,
        },
    )
    return frontier, eligible, pareto, windows


def chart_route_market_frontier(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    focal_airport: str,
    proxy_airport: str | None,
    distance_origin: str | None,
    window_months: int,
    min_t12_passengers: int,
    min_persistence_months: int,
    proxy_min_t12_passengers: int,
    proxy_min_persistence_months: int,
    title: str,
    interpretation_note: str,
    chart_id: str,
    coverage: str,
    fingerprint: str,
    segment_monthly: pd.DataFrame | None = None,
) -> Path:
    frontier, eligible, pareto, windows = route_frontier_data(
        routes,
        monthly,
        focal_airport=focal_airport,
        proxy_airport=proxy_airport,
        distance_origin=distance_origin,
        window_months=window_months,
        min_t12_passengers=min_t12_passengers,
        min_persistence_months=min_persistence_months,
        segment_monthly=segment_monthly,
    )
    total_markets = int((frontier["latest_t12_passengers"] > 0).sum())
    pareto_mask = eligible.index.isin(pareto)
    standard = eligible[~pareto_mask]
    frontier_points = eligible[pareto_mask]
    proxy = eligible.iloc[0:0]
    if proxy_airport:
        proxy_volume = f"{proxy_airport.lower()}_t12_passengers"
        proxy_persistence = (
            f"{proxy_airport.lower()}_persistence_months"
        )
        proxy = eligible[
            (eligible[proxy_volume] >= proxy_min_t12_passengers)
            & (
                eligible[proxy_persistence]
                >= proxy_min_persistence_months
            )
        ]

    fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)
    ax.set_facecolor(BG)
    if len(standard):
        ax.scatter(
            standard["latest_t12_passengers"] / 1_000_000,
            standard["yoy_change_pct"],
            s=66,
            color=PRIMARY,
            alpha=0.72,
            edgecolors=BG,
            linewidths=0.8,
            label=f"Other eligible {focal_airport} markets",
        )
    if len(frontier_points):
        ax.scatter(
            frontier_points["latest_t12_passengers"] / 1_000_000,
            frontier_points["yoy_change_pct"],
            s=105,
            marker="D",
            color=ACCENT,
            edgecolors=TITLE,
            linewidths=0.8,
            zorder=4,
            label="Volume–growth Pareto frontier",
        )
        for idx, (airport, row) in enumerate(frontier_points.sort_index().iterrows()):
            offset = 11 if idx % 2 == 0 else -16
            ax.annotate(
                airport,
                (
                    row["latest_t12_passengers"] / 1_000_000,
                    row["yoy_change_pct"],
                ),
                xytext=(7, offset),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                color=TEXT,
                arrowprops={
                    "arrowstyle": "-",
                    "color": MUTED,
                    "lw": 0.7,
                },
            )
    if proxy_airport and len(proxy):
        ax.scatter(
            proxy["latest_t12_passengers"] / 1_000_000,
            proxy["yoy_change_pct"],
            s=145,
            marker="s",
            facecolors="none",
            edgecolors="#4cc9f0",
            linewidths=1.6,
            zorder=5,
            label=(
                f"Also at {proxy_airport} "
                f"(≥{proxy_min_t12_passengers / 1_000:g}K, "
                f"≥{proxy_min_persistence_months} months)"
            ),
        )

    ax.axhline(0, color=SUBTLE, linewidth=1, alpha=0.7)
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda value, _: f"{value:g}M")
    )
    ax.set_xlabel(
        f"Latest trailing-{window_months}-month bidirectional "
        f"{focal_airport} segment passengers (log scale)",
        color=TEXT,
        fontsize=11,
    )
    ax.set_ylabel("Year-over-year change", color=TEXT, fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_percent))
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.grid(alpha=0.2, color=GRID, linestyle="--")
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    latest_label = (
        f"{format_month_period(windows.latest[0])}–"
        f"{format_month_period(windows.latest[-1])}"
    )
    previous_label = (
        f"{format_month_period(windows.previous[0])}–"
        f"{format_month_period(windows.previous[-1])}"
    )
    ax.set_title(
        title,
        fontsize=17,
        fontweight="bold",
        color=TITLE,
        pad=34,
    )
    ax.text(
        0.5,
        1.02,
        f"{latest_label} vs {previous_label} | "
        f"{len(eligible)} of {total_markets} observed markets shown | "
        f"≥{min_t12_passengers / 1_000:.0f}K passengers in both windows, "
        f"≥{min_persistence_months}/{window_months} active months",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color=SUBTLE,
    )
    ax.text(
        0.0,
        -0.14,
        f"{interpretation_note} All eligible points shown; labels identify "
        "the non-dominated volume–growth frontier.",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
        color=SUBTLE,
    )
    ax.legend(
        loc="upper right",
        frameon=False,
        labelcolor=TEXT,
        fontsize=8.5,
    )
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.10, right=0.97, top=0.82, bottom=0.20)
    return save_chart(fig, chart_id)


def chart_ncr_route_opportunity_frontier(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
    segment_monthly: pd.DataFrame | None = None,
) -> Path:
    """Configured NCR case-study view using the generic frontier renderer."""
    return chart_route_market_frontier(
        routes,
        monthly,
        focal_airport=ROUTE_FRONTIER_FOCAL,
        proxy_airport=ROUTE_FRONTIER_PROXY,
        distance_origin=ROUTE_FRONTIER_DISTANCE_ORIGIN,
        window_months=ROUTE_WINDOW_MONTHS,
        min_t12_passengers=ROUTE_FRONTIER_MIN_T12,
        min_persistence_months=ROUTE_FRONTIER_MIN_PERSISTENCE,
        proxy_min_t12_passengers=DUAL_MIN_MARKET_PASSENGERS,
        proxy_min_persistence_months=6,
        title="Observable DEL Route-Market Frontier",
        interpretation_note=(
            "Observable DEL market / NCR demand proxy — not NIA demand, "
            "diversion, route economics, or a forecast."
        ),
        chart_id="ncr_route_opportunity_frontier",
        coverage=coverage,
        fingerprint=fingerprint,
        segment_monthly=segment_monthly,
    )


def dual_airport_role_data(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    airport_pairs: Sequence[tuple[str, str]] = DUAL_AIRPORT_PAIRS,
    min_market_passengers: int = DUAL_MIN_MARKET_PASSENGERS,
    persistence_fraction: float = DUAL_PERSISTENCE_FRACTION,
    segment_monthly: pd.DataFrame | None = None,
) -> list[dict]:
    return [
        dual_airport_metrics(
            routes,
            monthly,
            incumbent=incumbent,
            newcomer=newcomer,
            min_market_passengers=min_market_passengers,
            persistence_fraction=persistence_fraction,
            segment_monthly=segment_monthly,
        )
        for incumbent, newcomer in airport_pairs
    ]


def chart_dual_airport_network_roles(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
    airport_pairs: Sequence[tuple[str, str]] = DUAL_AIRPORT_PAIRS,
    min_market_passengers: int = DUAL_MIN_MARKET_PASSENGERS,
    persistence_fraction: float = DUAL_PERSISTENCE_FRACTION,
    title: str = "Observed Roles in Indian Dual-Airport Systems",
    chart_id: str = "dual_airport_network_roles",
    segment_monthly: pd.DataFrame | None = None,
) -> Path:
    pairs = dual_airport_role_data(
        routes,
        monthly,
        airport_pairs=airport_pairs,
        min_market_passengers=min_market_passengers,
        persistence_fraction=persistence_fraction,
        segment_monthly=segment_monthly,
    )
    fig, (share_ax, network_ax) = plt.subplots(
        1, 2, figsize=FIGSIZE_WIDE, facecolor=BG
    )
    y = np.arange(len(pairs))[::-1]
    labels = [
        f"{item['newcomer']} / {item['incumbent']}\n"
        f"{format_month_period(pd.Period(item['comparison_start'], freq='M'))}–"
        f"{format_month_period(pd.Period(item['comparison_end'], freq='M'))}"
        for item in pairs
    ]
    shares = [item["newcomer_share_pct"] for item in pairs]
    share_colors = [stable_color(item["newcomer"]) for item in pairs]
    share_ax.barh(y, shares, color=share_colors, height=0.55)
    for position, value, item in zip(y, shares, pairs):
        share_ax.text(
            value + 0.8,
            position,
            f"{value:.1f}%  ({item['newcomer_throughput'] / 1_000_000:.2f}M)",
            va="center",
            ha="left",
            fontsize=9,
            color=TEXT,
            fontweight="bold",
        )
    share_ax.set_xlim(0, max(shares) * 1.25)
    share_ax.set_yticks(y)
    share_ax.set_yticklabels(labels, color=TEXT, fontsize=9)
    share_ax.set_xlabel("Newcomer share of pair throughput", color=TEXT)
    share_ax.xaxis.set_major_formatter(mticker.FuncFormatter(fmt_percent))
    share_ax.set_title(
        "Traffic role",
        fontsize=13,
        fontweight="bold",
        color=TITLE,
        pad=12,
    )
    share_ax.grid(axis="x", alpha=0.2, color=GRID, linestyle="--")

    shared_counts = [len(item["shared_destinations"]) for item in pairs]
    unique_counts = [
        len(item["newcomer_unique_destinations"]) for item in pairs
    ]
    network_ax.barh(
        y,
        shared_counts,
        color=PRIMARY,
        height=0.55,
        label="Shared with incumbent",
    )
    network_ax.barh(
        y,
        unique_counts,
        left=shared_counts,
        color=ACCENT,
        height=0.55,
        label="Unique to newcomer",
    )
    for position, shared, unique, item in zip(
        y, shared_counts, unique_counts, pairs
    ):
        total = shared + unique
        network_ax.text(
            total + 0.7,
            position,
            f"{total} markets | D_eff {item['newcomer_effective_destinations']:.1f}\n"
            f"combined breadth {item['baseline_incumbent_destination_count']}"
            f"→{item['combined_destination_count']}",
            va="center",
            ha="left",
            fontsize=8.5,
            color=TEXT,
        )
    network_ax.set_xlim(
        0, max(s + u for s, u in zip(shared_counts, unique_counts)) * 1.45
    )
    network_ax.set_yticks(y)
    network_ax.set_yticklabels([])
    network_ax.set_xlabel("Persistent direct markets at newcomer", color=TEXT)
    network_ax.set_title(
        "Network role",
        fontsize=13,
        fontweight="bold",
        color=TITLE,
        pad=12,
    )
    network_ax.grid(axis="x", alpha=0.2, color=GRID, linestyle="--")
    network_ax.legend(
        loc="lower right",
        frameon=False,
        labelcolor=TEXT,
        fontsize=8.5,
    )
    for ax in (share_ax, network_ax):
        ax.set_facecolor(BG)
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.spines["left"].set_color(GRID)

    fig.suptitle(
        title,
        fontsize=17,
        fontweight="bold",
        color=TITLE,
        y=0.95,
    )
    fig.text(
        0.5,
        0.895,
        f"All {len(pairs)} supported pairs shown | Active market = "
        f"≥{min_market_passengers / 1_000:.0f}K bidirectional passengers "
        f"and observed in ≥{persistence_fraction:.0%} of comparison months",
        ha="center",
        va="bottom",
        fontsize=9,
        color=SUBTLE,
    )
    fig.text(
        0.02,
        0.075,
        "Observational analogues only: operating models, catchments, entry dates, "
        "and recovery conditions differ. Throughput and topology do not identify "
        "transfer passengers or causal traffic creation.",
        ha="left",
        va="bottom",
        fontsize=8.5,
        color=SUBTLE,
    )
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.13, right=0.96, top=0.80, bottom=0.16, wspace=0.26)
    return save_chart(fig, chart_id)


def chart_domestic_network_decentralisation(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
    start_year: int = NETWORK_START_YEAR,
    min_route_persistence_months: int = NETWORK_MIN_ROUTE_PERSISTENCE,
    title: str = "India's Domestic Network Is Becoming More Polycentric",
    chart_id: str = "domestic_network_decentralisation",
    segment_monthly: pd.DataFrame | None = None,
) -> Path:
    annual = annual_network_metrics(
        routes,
        monthly,
        start_year=start_year,
        min_route_persistence_months=min_route_persistence_months,
        segment_monthly=segment_monthly,
    )
    years = annual.index.to_numpy()
    fig, (concentration_ax, breadth_ax) = plt.subplots(
        1, 2, figsize=FIGSIZE_WIDE, facecolor=BG
    )

    concentration_ax.plot(
        years,
        annual["top_five_airport_share_pct"],
        color=PRIMARY,
        linewidth=2.5,
        marker="o",
        label="Top-five airport share",
    )
    concentration_ax.set_ylabel("Top-five share of airport throughput", color=PRIMARY)
    concentration_ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_percent))
    concentration_secondary = concentration_ax.twinx()
    concentration_secondary.plot(
        years,
        annual["effective_traffic_centres"],
        color=ACCENT,
        linewidth=2.5,
        marker="s",
        label="Effective traffic centres (1 / HHI)",
    )
    concentration_secondary.set_ylabel("Effective traffic centres", color=ACCENT)
    concentration_ax.set_title(
        "Traffic concentration",
        fontsize=13,
        fontweight="bold",
        color=TITLE,
        pad=12,
    )

    breadth_ax.plot(
        years,
        annual["active_airports"],
        color=POSITIVE,
        linewidth=2.5,
        marker="o",
        label="Active airports",
    )
    breadth_ax.set_ylabel("Active airports", color=POSITIVE)
    breadth_secondary = breadth_ax.twinx()
    breadth_secondary.plot(
        years,
        annual["active_routes"],
        color="#a78bfa",
        linewidth=2.5,
        marker="s",
        label="Persistent bidirectional routes",
    )
    breadth_secondary.set_ylabel("Persistent routes", color="#a78bfa")
    breadth_ax.set_title(
        "Observed network breadth",
        fontsize=13,
        fontweight="bold",
        color=TITLE,
        pad=12,
    )

    for ax in (concentration_ax, breadth_ax):
        ax.set_facecolor(BG)
        ax.set_xticks(years)
        ax.set_xticklabels(years, rotation=45, ha="right")
        ax.tick_params(colors=TEXT, labelsize=8.5)
        ax.grid(axis="y", alpha=0.2, color=GRID, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.spines["left"].set_color(GRID)
    for ax in (concentration_secondary, breadth_secondary):
        ax.tick_params(colors=TEXT, labelsize=8.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_color(GRID)

    concentration_ax.legend(
        [concentration_ax.lines[0], concentration_secondary.lines[0]],
        ["Top-five airport share", "Effective traffic centres (1 / HHI)"],
        loc="best",
        frameon=False,
        labelcolor=TEXT,
        fontsize=8.5,
    )
    breadth_ax.legend(
        [breadth_ax.lines[0], breadth_secondary.lines[0]],
        ["Active airports", "Persistent bidirectional routes"],
        loc="best",
        frameon=False,
        labelcolor=TEXT,
        fontsize=8.5,
    )
    for ax, column, color, formatter, offset, vertical_alignment in (
        (
            concentration_ax,
            "top_five_airport_share_pct",
            PRIMARY,
            lambda x: f"{x:.1f}%",
            (6, 0),
            "center",
        ),
        (
            concentration_secondary,
            "effective_traffic_centres",
            ACCENT,
            lambda x: f"{x:.1f}",
            (6, 0),
            "center",
        ),
        (
            breadth_ax,
            "active_airports",
            POSITIVE,
            lambda x: f"{int(x)}",
            (6, -7),
            "top",
        ),
        (
            breadth_secondary,
            "active_routes",
            "#a78bfa",
            lambda x: f"{int(x)}",
            (6, 7),
            "bottom",
        ),
    ):
        ax.annotate(
            formatter(annual.iloc[-1][column]),
            (years[-1], annual.iloc[-1][column]),
            xytext=offset,
            textcoords="offset points",
            va=vertical_alignment,
            fontsize=9,
            color=color,
            fontweight="bold",
        )

    fig.suptitle(
        title,
        fontsize=17,
        fontweight="bold",
        color=TITLE,
        y=0.95,
    )
    fig.text(
        0.5,
        0.895,
        f"Complete calendar years {annual.index.min()}–{annual.index.max()} | "
        "Traffic share uses airport throughput | Active route = bidirectional "
        f"segment observed in ≥{min_route_persistence_months} months",
        ha="center",
        va="bottom",
        fontsize=9,
        color=SUBTLE,
    )
    fig.text(
        0.02,
        0.075,
        "Describes national network structure; it does not by itself establish "
        "demand, diversion, or route economics for any airport.",
        ha="left",
        va="bottom",
        fontsize=8.5,
        color=SUBTLE,
    )
    add_footer(fig, coverage=coverage, fingerprint=fingerprint)
    fig.subplots_adjust(left=0.08, right=0.92, top=0.80, bottom=0.17, wspace=0.30)
    return save_chart(fig, chart_id)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    return value


def generate_route_analysis_summary(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    segment_monthly: pd.DataFrame | None = None,
) -> dict:
    segments = (
        segment_monthly
        if segment_monthly is not None
        else bidirectional_segments(routes)
    )
    frontier, eligible, pareto, windows = route_frontier_data(
        routes, monthly, segment_monthly=segments
    )
    sensitivity = []
    for volume in (100_000, 250_000, 500_000):
        for persistence in (6, 9, 12):
            candidates = eligible_route_markets(
                frontier,
                min_t12_passengers=volume,
                min_persistence_months=persistence,
            )
            sensitivity.append(
                {
                    "min_t12_passengers": volume,
                    "min_persistence_months": persistence,
                    "eligible_markets": int(len(candidates)),
                    "pareto_markets": pareto_frontier(
                        candidates,
                        {
                            "latest_t12_passengers": True,
                            "yoy_change_pct": True,
                        },
                    ),
                }
            )

    dual = dual_airport_role_data(
        routes, monthly, segment_monthly=segments
    )
    dual_sensitivity = []
    for volume in (5_000, 10_000, 25_000, 50_000):
        for persistence_fraction in (0.25, 0.5, 0.75):
            for incumbent, newcomer in DUAL_AIRPORT_PAIRS:
                result = dual_airport_metrics(
                    routes,
                    monthly,
                    incumbent=incumbent,
                    newcomer=newcomer,
                    min_market_passengers=volume,
                    persistence_fraction=persistence_fraction,
                    segment_monthly=segments,
                )
                dual_sensitivity.append(
                    {
                        "incumbent": incumbent,
                        "newcomer": newcomer,
                        "min_market_passengers": volume,
                        "persistence_fraction": persistence_fraction,
                        "newcomer_markets": len(
                            result["newcomer_destinations"]
                        ),
                        "shared_markets": len(
                            result["shared_destinations"]
                        ),
                        "newcomer_unique_markets": len(
                            result["newcomer_unique_destinations"]
                        ),
                        "jaccard_similarity": result[
                            "jaccard_similarity"
                        ],
                    }
                )
    for item in dual:
        development = dual_airport_monthly_development(
            monthly,
            incumbent=item["incumbent"],
            newcomer=item["newcomer"],
            pre_entry_months=12,
        ).reset_index()
        item["monthly_development_pre_entry_months"] = 12
        item["monthly_passenger_development"] = [
            {
                "period": str(row.period),
                "months_from_entry": int(row.months_from_entry),
                "incumbent_throughput": int(row.incumbent_throughput),
                "newcomer_throughput": int(row.newcomer_throughput),
                "combined_throughput": int(row.combined_throughput),
                "newcomer_share_pct": _json_safe(
                    row.newcomer_share_pct
                ),
            }
            for row in development.itertuples()
        ]
        acquisition = route_acquisition_sequence(
            routes,
            item["newcomer"],
            first_months=24,
            segment_monthly=segments,
        )
        item["first_24m_acquisition_sequence"] = [
            {
                "destination": row.destination,
                "first_period": str(row.first_period),
                "ramp_month": int(row.ramp_month),
                "passengers_in_first_month": int(
                    row.passengers_in_first_month
                ),
            }
            for row in acquisition.itertuples()
        ]

    annual = annual_network_metrics(
        routes,
        monthly,
        start_year=NETWORK_START_YEAR,
        min_route_persistence_months=NETWORK_MIN_ROUTE_PERSISTENCE,
        segment_monthly=segments,
    )
    first_year, last_year = int(annual.index.min()), int(annual.index.max())
    network_latest = airport_network_metrics(
        routes, monthly, windows.latest, segment_monthly=segments
    )
    scale_diversity_rank_correlation = float(
        network_latest[["throughput", "effective_destinations"]]
        .rank()
        .corr()
        .iloc[0, 1]
    )
    coords = airport_coordinates()
    dxn_structural = structural_two_leg_opportunities(
        routes,
        hub="DXN",
        periods=windows.latest,
        previous_periods=windows.previous,
        min_leg_passengers=100_000,
        min_leg_persistence_months=6,
        coordinates=coords,
        max_detour_ratio=1.5,
    )
    del_structural = structural_two_leg_opportunities(
        routes,
        hub="DEL",
        periods=windows.latest,
        previous_periods=windows.previous,
        min_leg_passengers=250_000,
        min_leg_persistence_months=9,
        coordinates=coords,
        max_detour_ratio=1.5,
    )
    closure_sensitivity = []
    for volume in (50_000, 100_000):
        closures = triangle_closures(
            routes,
            current_periods=windows.latest,
            previous_periods=windows.previous,
            min_direct_passengers=volume,
            min_direct_persistence_months=6,
            segment_monthly=segments,
        )
        closure_sensitivity.append(
            {
                "min_direct_passengers": volume,
                "qualifying_closures": int(len(closures)),
            }
        )
    coord_coverage = coordinate_coverage(monthly, windows.latest, coords)
    dxn_rows = add_month_period(monthly)
    dxn_rows = dxn_rows[
        (dxn_rows["airport"] == "DXN")
        & (dxn_rows["passengers"] > 0)
    ]

    market_columns = [
        "latest_t12_passengers",
        "previous_t12_passengers",
        "absolute_yoy_change",
        "yoy_change_pct",
        "cagr_3y_pct",
        "latest_persistence_months",
        "latest_monthly_cv",
        "destination_t12_throughput",
        "destination_direct_markets",
        "destination_effective_markets",
        "hdo_t12_passengers",
        "hdo_persistence_months",
        "distance_km",
    ]
    selected_markets = {
        market: {
            column: _json_safe(frontier.loc[market, column])
            for column in market_columns
        }
        for market in sorted(
            set(pareto)
            | set(frontier.head(10).index)
            | set(
                eligible.sort_values(
                    "yoy_change_pct", ascending=False
                ).head(10).index
            )
        )
    }
    summary = {
        "generated_date": date.today().isoformat(),
        "source_table": "data/processed/domestic_route_monthly.csv",
        "coverage": route_coverage(routes),
        "comparison_windows": {
            "latest": f"{windows.latest[0]}..{windows.latest[-1]}",
            "previous": f"{windows.previous[0]}..{windows.previous[-1]}",
        },
        "executive_finding": (
            "Observable route-market volume and persistent growth provide the "
            "strongest actionable evidence. Dual-airport analogues support a "
            "complementary origin/destination role; the segment data does not "
            "support a transfer-hub claim."
        ),
        "route_market_frontier": {
            "focal_airport": ROUTE_FRONTIER_FOCAL,
            "interpretation": "observable DEL market / NCR demand proxy",
            "not_interpretation": "NIA demand, diversion, forecast, or recommendation",
            "total_observed_latest_markets": int(
                (frontier["latest_t12_passengers"] > 0).sum()
            ),
            "selection": {
                "min_t12_passengers_each_window": ROUTE_FRONTIER_MIN_T12,
                "min_latest_persistence_months": ROUTE_FRONTIER_MIN_PERSISTENCE,
                "eligible_markets": int(len(eligible)),
            },
            "proxy_demonstration_thresholds": {
                "airport": ROUTE_FRONTIER_PROXY,
                "min_t12_passengers": DUAL_MIN_MARKET_PASSENGERS,
                "min_persistence_months": 6,
            },
            "pareto_dimensions": [
                "latest_t12_passengers (maximize)",
                "yoy_change_pct (maximize)",
            ],
            "pareto_markets": pareto,
            "market_metrics": selected_markets,
            "sensitivity": sensitivity,
        },
        "dual_airport_analogues": dual,
        "dual_airport_sensitivity": dual_sensitivity,
        "national_decentralisation": {
            "first_year": first_year,
            "last_year": last_year,
            "min_route_persistence_months": NETWORK_MIN_ROUTE_PERSISTENCE,
            "first_year_metrics": _json_safe(
                annual.loc[first_year].to_dict()
            ),
            "last_year_metrics": _json_safe(
                annual.loc[last_year].to_dict()
            ),
            "annual_metrics": _json_safe(
                annual.reset_index().to_dict(orient="records")
            ),
        },
        "tests_not_selected_as_headline_charts": {
            "traffic_scale_vs_network_diversity": {
                "spearman_rank_correlation": scale_diversity_rank_correlation,
                "conclusion": (
                    "Strongly correlated with traffic scale and cannot identify "
                    "transfer passengers; useful context, weak standalone thesis."
                ),
            },
            "structural_two_leg_paths": {
                "dxn_qualifying_paths": int(len(dxn_structural)),
                "dxn_thresholds": {
                    "min_leg_passengers": 100_000,
                    "min_leg_persistence_months": 6,
                    "min_leg_yoy_pct": -10,
                    "direct_persistence_months": 6,
                    "max_known_coordinate_detour_ratio": 1.5,
                },
                "del_proxy_qualifying_paths": int(len(del_structural)),
                "del_proxy_paths_with_known_detour": int(
                    del_structural["detour_ratio"].notna().sum()
                ),
                "del_proxy_paths_without_known_detour": int(
                    del_structural["detour_ratio"].isna().sum()
                ),
                "del_proxy_thresholds": {
                    "min_leg_passengers": 250_000,
                    "min_leg_persistence_months": 9,
                    "min_leg_yoy_pct": -10,
                    "direct_persistence_months": 6,
                    "max_known_coordinate_detour_ratio": 1.5,
                },
                "conclusion": (
                    "DXN has no persistent qualifying legs. DEL proxy paths are "
                    "topological and cannot establish NIA transfer demand."
                ),
            },
            "triangle_closures": {
                "sensitivity": closure_sensitivity,
                "conclusion": (
                    "Qualifying routes disappear at the 100,000-passenger floor; "
                    "the result is too threshold-sensitive for a headline."
                ),
            },
        },
        "coordinate_coverage": coord_coverage,
        "dxn_observation": {
            "first_positive_month": (
                str(dxn_rows["period"].min()) if len(dxn_rows) else None
            ),
            "observed_months": int(dxn_rows["period"].nunique()),
            "observed_airport_throughput": int(
                dxn_rows["passengers"].sum()
            ),
            "interpretation": (
                "partial opening-month observation; insufficient for steady-state "
                "NIA performance analysis"
            ),
        },
        "claim_boundaries": [
            "Segment passengers are not true passenger origin/final destination.",
            "No transfer volumes, schedules, fares, capacity, yields, or profitability.",
            "DEL is an observable NCR market proxy, not an NIA demand forecast.",
            "Dual-airport comparisons are observational, not causal estimates.",
        ],
        "disclaimer": (
            "This is a personal open-source analysis. It does not represent "
            "Flughafen Zürich AG, Noida International Airport, or any affiliate."
        ),
    }
    return _json_safe(summary)


def write_route_analysis_summary(
    routes: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    segment_monthly: pd.DataFrame | None = None,
) -> Path:
    summary = generate_route_analysis_summary(
        routes, monthly, segment_monthly=segment_monthly
    )
    ROUTE_ANALYSIS_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return ROUTE_ANALYSIS_SUMMARY_PATH


def generate_dashboard_summary(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    *,
    fingerprint: str,
) -> dict:
    # Domestic headline = passengers carried (carrier table, counted once per
    # journey). Airport endpoint throughput is also reported, under an explicit
    # key, for airport-level context — it is ~2× passengers carried nationally.
    national, t12, monthly_yoy, t12_yoy = domestic_demand_series(carrier)
    latest_month = national.index.max()

    m = add_month_period(monthly)
    throughput = domestic_airport_throughput(monthly)
    # Airport context is keyed to the carrier headline month. The two layers are
    # published independently, so if the carrier extends a month beyond the
    # airport layer, report null rather than silently quoting a different month.
    airport_month_present = latest_month in throughput.index

    # International uses positional rolling(4)/shift(4). Unlike the carrier series
    # it is NOT gap-filled: a missing quarter here means "not yet published", not
    # "zero traffic" (filling 0 would understate the 4Q total). The quarterly
    # table is contiguous, and check_coverage warns if a quarter ever goes missing.
    international = international_gateway_throughput(quarterly)
    latest_4q = international.rolling(4, min_periods=4).sum()
    latest_4q_yoy = latest_4q / latest_4q.shift(4) - 1
    latest_quarter = international.index.max()
    q = add_quarter_period(quarterly)

    def nullable_int(value: float) -> int | None:
        if pd.isna(value) or not np.isfinite(value):
            return None
        return int(round(float(value)))

    def nullable_pct(value: float) -> float | None:
        # Non-finite (e.g. YoY against a zero base) serializes as a non-standard
        # `Infinity` JSON token that browsers reject — emit null instead.
        if pd.isna(value) or not np.isfinite(value):
            return None
        return round(float(value) * 100, 1)

    summary = {
        "data_date": load_metadata().get("data_date"),
        "generated_date": date.today().isoformat(),
        "domestic": {
            "latest_month": str(latest_month),
            "latest_month_passengers_carried": nullable_int(national.loc[latest_month]),
            "latest_month_yoy_pct": nullable_pct(monthly_yoy.loc[latest_month]),
            "trailing_12m_passengers_carried": nullable_int(t12.dropna().iloc[-1])
            if not t12.dropna().empty
            else None,
            "trailing_12m_yoy_pct": nullable_pct(t12_yoy.dropna().iloc[-1])
            if not t12_yoy.dropna().empty
            else None,
            "passengers_metric": "scheduled_domestic_passengers_carried",
            "airports_latest_month": int(
                m.loc[m["period"] == latest_month, "airport"].nunique()
            )
            if airport_month_present
            else None,
            "airport_throughput_latest_month": nullable_int(throughput.loc[latest_month])
            if airport_month_present
            else None,
        },
        "international": {
            "latest_quarter": str(latest_quarter),
            "latest_4q_passengers": nullable_int(latest_4q.dropna().iloc[-1])
            if not latest_4q.dropna().empty
            else None,
            "latest_4q_yoy_pct": nullable_pct(latest_4q_yoy.dropna().iloc[-1])
            if not latest_4q_yoy.dropna().empty
            else None,
            "gateways_latest_quarter": int(
                q.loc[q["period"] == latest_quarter, "airport"].nunique()
            ),
        },
        "fingerprint": fingerprint,
    }
    return summary


def write_dashboard_summary(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    *,
    fingerprint: str,
) -> Path:
    summary = generate_dashboard_summary(
        monthly, quarterly, carrier, fingerprint=fingerprint
    )
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return DASHBOARD_SUMMARY_PATH


def dataset_manifest_entry(
    path: Path,
    *,
    rows: int | None = None,
    coverage: str | None = None,
) -> dict:
    entry = {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
    }
    if rows is not None:
        entry["rows"] = int(rows)
    if coverage is not None:
        entry["coverage"] = coverage
    return entry


def build_chart_manifest(
    chart_records: Mapping[str, dict],
    *,
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    routes: pd.DataFrame,
    domestic_coverage_text: str,
    international_coverage_text: str,
    carrier_coverage_text: str,
    route_coverage_text: str,
    overall_fingerprint: str,
) -> dict:
    return {
        "manifest_version": 1,
        "chart_script": "scripts/chart.py",
        "input_fingerprint": overall_fingerprint,
        "datasets": {
            "airport_monthly": dataset_manifest_entry(
                DOMESTIC_MONTHLY_PATH,
                rows=len(monthly),
                coverage=domestic_coverage_text,
            ),
            "airport_international_quarterly": dataset_manifest_entry(
                INTERNATIONAL_QUARTERLY_PATH,
                rows=len(quarterly),
                coverage=international_coverage_text,
            ),
            "carrier_monthly": dataset_manifest_entry(
                CARRIER_MONTHLY_PATH,
                rows=len(carrier),
                coverage=carrier_coverage_text,
            ),
            "domestic_route_monthly": dataset_manifest_entry(
                DOMESTIC_ROUTE_MONTHLY_PATH,
                rows=len(routes),
                coverage=route_coverage_text,
            ),
        },
        "charts": dict(sorted(chart_records.items())),
    }


def write_chart_manifest(
    chart_records: Mapping[str, dict],
    *,
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    routes: pd.DataFrame,
    domestic_coverage_text: str,
    international_coverage_text: str,
    carrier_coverage_text: str,
    route_coverage_text: str,
    overall_fingerprint: str,
) -> Path:
    manifest = build_chart_manifest(
        chart_records,
        monthly=monthly,
        quarterly=quarterly,
        carrier=carrier,
        routes=routes,
        domestic_coverage_text=domestic_coverage_text,
        international_coverage_text=international_coverage_text,
        carrier_coverage_text=carrier_coverage_text,
        route_coverage_text=route_coverage_text,
        overall_fingerprint=overall_fingerprint,
    )
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return MANIFEST_PATH


def chart_params(chart_id: str) -> dict:
    params = {
        "india_domestic_demand_pulse": {"moving_average_months": 12},
        "top_airport_traffic_trends": {
            "trailing_window_months": 12,
            "latest_top_n": 10,
            "previous_top_n": 10,
            "max_lines": 12,
        },
        "newcomer_airport_rampup_24m": {
            "ramp_months": RAMP_MONTHS,
            "left_censor_buffer_months": LEFT_CENSOR_BUFFER_MONTHS,
            "min_cumulative_available": RAMP_MIN_CUMULATIVE_AVAILABLE,
            "min_peak_month": RAMP_MIN_PEAK_MONTH,
            "min_observed_months": RAMP_MIN_OBSERVED_MONTHS,
            "max_labels": RAMP_MAX_LABELS,
        },
        "domestic_market_share_gainers": {
            "window_months": DOMESTIC_SHARE_WINDOW_MONTHS,
            "min_traffic": DOMESTIC_SHARE_MIN_TRAFFIC,
            "top_n_each_side": DOMESTIC_SHARE_TOP_N,
        },
        "international_gateway_share_gainers": {
            "window_quarters": INTERNATIONAL_SHARE_WINDOW_QUARTERS,
            "min_traffic": INTERNATIONAL_SHARE_MIN_TRAFFIC,
            "top_n_each_side": INTERNATIONAL_SHARE_TOP_N,
        },
        "airport_seasonality_fingerprint": {
            "min_complete_years": SEASONALITY_MIN_COMPLETE_YEARS,
            "min_latest_t12": SEASONALITY_MIN_LATEST_T12,
            "max_airports": SEASONALITY_MAX_AIRPORTS,
            "vmin": SEASONALITY_VMIN,
            "vcenter": SEASONALITY_VCENTER,
            "vmax": SEASONALITY_VMAX,
        },
        "ncr_route_opportunity_frontier": {
            "focal_airport": ROUTE_FRONTIER_FOCAL,
            "proxy_airport": ROUTE_FRONTIER_PROXY,
            "distance_origin": ROUTE_FRONTIER_DISTANCE_ORIGIN,
            "window_months": ROUTE_WINDOW_MONTHS,
            "min_t12_passengers_each_window": ROUTE_FRONTIER_MIN_T12,
            "min_latest_persistence_months": ROUTE_FRONTIER_MIN_PERSISTENCE,
            "proxy_min_t12_passengers": DUAL_MIN_MARKET_PASSENGERS,
            "proxy_min_persistence_months": 6,
            "pareto_dimensions": [
                "latest_t12_passengers",
                "yoy_change_pct",
            ],
        },
        "dual_airport_network_roles": {
            "pairs": [list(pair) for pair in DUAL_AIRPORT_PAIRS],
            "min_market_passengers": DUAL_MIN_MARKET_PASSENGERS,
            "persistence_fraction": DUAL_PERSISTENCE_FRACTION,
        },
        "domestic_network_decentralisation": {
            "start_year": NETWORK_START_YEAR,
            "complete_calendar_years_only": True,
            "min_route_persistence_months": NETWORK_MIN_ROUTE_PERSISTENCE,
        },
    }
    return params[chart_id]


# Per-chart source table + metric semantics. The same `passengers` column means
# different things across layers, so reproducibility metadata must record which
# layer a chart reads and what the number actually means. Carrier = passengers
# carried (counted once); airport = endpoint throughput (arrivals + departures).
CHART_SEMANTICS = {
    "india_domestic_demand_pulse": (
        "carrier_monthly",
        "scheduled_domestic_passengers_carried",
    ),
    "top_airport_traffic_trends": (
        "airport_monthly",
        "domestic_airport_throughput_arrivals_plus_departures",
    ),
    "newcomer_airport_rampup_24m": (
        "airport_monthly",
        "domestic_airport_throughput_arrivals_plus_departures",
    ),
    "domestic_market_share_gainers": (
        "airport_monthly",
        "domestic_airport_throughput_share",
    ),
    "international_gateway_share_gainers": (
        "airport_international_quarterly",
        "indian_international_gateway_throughput",
    ),
    "airport_seasonality_fingerprint": (
        "airport_monthly",
        "domestic_airport_throughput_index",
    ),
    "ncr_route_opportunity_frontier": (
        "domestic_route_monthly",
        "observed_bidirectional_domestic_segment_passengers",
    ),
    "dual_airport_network_roles": (
        "domestic_route_monthly",
        "observed_airport_throughput_and_direct_market_topology",
    ),
    "domestic_network_decentralisation": (
        "domestic_route_monthly",
        "domestic_network_concentration_and_persistent_route_breadth",
    ),
}


CHART_INPUTS = {
    "ncr_route_opportunity_frontier": [
        "domestic_route_monthly",
        "airport_monthly",
    ],
    "dual_airport_network_roles": [
        "domestic_route_monthly",
        "airport_monthly",
    ],
    "domestic_network_decentralisation": [
        "domestic_route_monthly",
        "airport_monthly",
    ],
}

DATASET_PATHS = {
    "airport_monthly": DOMESTIC_MONTHLY_PATH,
    "airport_international_quarterly": INTERNATIONAL_QUARTERLY_PATH,
    "carrier_monthly": CARRIER_MONTHLY_PATH,
    "domestic_route_monthly": DOMESTIC_ROUTE_MONTHLY_PATH,
}


def chart_inputs(chart_id: str) -> list[str]:
    return CHART_INPUTS.get(chart_id, [CHART_SEMANTICS[chart_id][0]])


def register_chart(
    path: Path,
    chart_id: str,
    *,
    runtime_params: dict | None = None,
) -> dict:
    primary_source_table, metric_semantics = CHART_SEMANTICS[chart_id]
    params = chart_params(chart_id)
    if runtime_params:
        params.update(runtime_params)
    return {
        "file": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
        "inputs": chart_inputs(chart_id),
        "input_fingerprint": input_fingerprint(
            [DATASET_PATHS[name] for name in chart_inputs(chart_id)]
        ),
        "primary_source_table": primary_source_table,
        "metric_semantics": metric_semantics,
        "params": params,
    }


def chart_runtime_params(
    chart_id: str,
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    routes: pd.DataFrame,
    *,
    segment_monthly: pd.DataFrame | None = None,
) -> dict:
    if chart_id == "india_domestic_demand_pulse":
        national, _, _, _ = domestic_demand_series(carrier)
        return {
            "period": f"{national.index.min()}..{national.index.max()}",
            "months_shown": int(len(national)),
            "total_eligible_months": int(len(national)),
            "selection_rule": (
                "All published months of scheduled domestic carrier "
                "passengers carried are shown"
            ),
            "data_coverage": carrier_domestic_coverage(carrier),
        }
    if chart_id == "top_airport_traffic_trends":
        pivot = domestic_airport_month_matrix(monthly)
        trailing = complete_rolling_sum(pivot, window=12)
        latest = trailing.iloc[-1]
        latest_top = set(
            latest.sort_values(ascending=False).head(10).index
        )
        previous_top = (
            set(
                trailing.iloc[-13]
                .sort_values(ascending=False)
                .head(10)
                .index
            )
            if len(trailing) >= 13
            else set()
        )
        selected = sorted(
            latest_top | previous_top,
            key=lambda airport: (-latest.get(airport, 0), airport),
        )[:12]
        return {
            "period": f"{trailing.index.min()}..{trailing.index.max()}",
            "airports_shown": int(len(selected)),
            "total_eligible_airports": int((latest > 0).sum()),
            "selection_rule": (
                "Union of latest and year-prior top 10 trailing-12-month "
                "airports, capped at 12 with deterministic tie-breaks"
            ),
            "data_coverage": domestic_coverage(monthly),
        }
    if chart_id == "newcomer_airport_rampup_24m":
        ramps = newcomer_airport_ramps(monthly)
        airports = (
            sorted(ramps["airport"].unique()) if not ramps.empty else []
        )
        return {
            "period": domestic_coverage(monthly),
            "airports_shown": int(len(airports)),
            "total_eligible_airports": int(len(airports)),
            "airports_labeled": int(min(len(airports), RAMP_MAX_LABELS)),
            "selection_rule": (
                "All non-left-censored airports meeting the configured "
                "observed-month and traffic/peak eligibility thresholds"
            ),
            "data_coverage": domestic_coverage(monthly),
        }
    if chart_id in {
        "domestic_market_share_gainers",
        "international_gateway_share_gainers",
    }:
        domestic = chart_id == "domestic_market_share_gainers"
        pivot = (
            domestic_airport_month_matrix(monthly)
            if domestic
            else international_airport_quarter_matrix(quarterly)
        )
        window = (
            DOMESTIC_SHARE_WINDOW_MONTHS
            if domestic
            else INTERNATIONAL_SHARE_WINDOW_QUARTERS
        )
        min_traffic = (
            DOMESTIC_SHARE_MIN_TRAFFIC
            if domestic
            else INTERNATIONAL_SHARE_MIN_TRAFFIC
        )
        top_n = (
            DOMESTIC_SHARE_TOP_N
            if domestic
            else INTERNATIONAL_SHARE_TOP_N
        )
        latest_periods, previous_periods = complete_share_window_periods(
            pivot.index, window=window
        )
        latest_totals = pivot.loc[latest_periods].sum(axis=0)
        previous_totals = pivot.loc[previous_periods].sum(axis=0)
        eligible = (
            (latest_totals >= min_traffic)
            | (previous_totals >= min_traffic)
        )
        movers = market_share_movers(
            pivot,
            window=window,
            min_traffic=min_traffic,
            top_n=top_n,
        )
        coverage = (
            domestic_coverage(monthly)
            if domestic
            else international_coverage(quarterly)
        )
        return {
            "latest_period": (
                f"{latest_periods[0]}..{latest_periods[-1]}"
            ),
            "previous_period": (
                f"{previous_periods[0]}..{previous_periods[-1]}"
            ),
            "entities_shown": int(len(movers)),
            "total_eligible_entities": int(eligible.sum()),
            "selection_rule": (
                f"Top {top_n} share gainers and top {top_n} decliners among "
                "entities meeting the configured traffic floor"
            ),
            "data_coverage": coverage,
        }
    if chart_id == "airport_seasonality_fingerprint":
        matrix = seasonality_fingerprint_matrix(monthly)
        complete_years = complete_calendar_years(monthly)
        complete = monthly[monthly["year"].isin(complete_years)]
        complete_counts = complete.groupby("airport")["year"].nunique()
        trailing = complete_rolling_sum(
            domestic_airport_month_matrix(monthly), 12
        )
        latest_t12 = (
            trailing.iloc[-1]
            .reindex(complete_counts.index)
            .fillna(0)
            if not trailing.empty
            else pd.Series(0, index=complete_counts.index, dtype=float)
        )
        eligible = (
            (complete_counts >= SEASONALITY_MIN_COMPLETE_YEARS)
            & (latest_t12 >= SEASONALITY_MIN_LATEST_T12)
        )
        return {
            "period": (
                f"{min(complete_years)}..{max(complete_years)}"
                if complete_years
                else None
            ),
            "airports_shown": int(len(matrix)),
            "total_eligible_airports": int(eligible.sum()),
            "selection_rule": (
                "Top eligible airports by latest trailing-12-month "
                "throughput, capped at max_airports"
            ),
            "data_coverage": domestic_coverage(monthly),
        }
    if chart_id == "ncr_route_opportunity_frontier":
        frontier, eligible, pareto, windows = route_frontier_data(
            routes, monthly, segment_monthly=segment_monthly
        )
        return {
            "latest_period": f"{windows.latest[0]}..{windows.latest[-1]}",
            "previous_period": (
                f"{windows.previous[0]}..{windows.previous[-1]}"
            ),
            "markets_shown": int(len(eligible)),
            "total_observed_latest_markets": int(
                (frontier["latest_t12_passengers"] > 0).sum()
            ),
            "selection_rule": (
                "Both T12 windows meet the passenger floor; latest window meets "
                "the persistence floor; all eligible markets shown"
            ),
            "pareto_markets": pareto,
            "data_coverage": route_coverage(routes),
        }
    if chart_id == "dual_airport_network_roles":
        pairs = dual_airport_role_data(
            routes, monthly, segment_monthly=segment_monthly
        )
        return {
            "pairs_shown": len(pairs),
            "total_supported_pairs": len(DUAL_AIRPORT_PAIRS),
            "comparison_periods": {
                item["newcomer"]: (
                    f"{item['comparison_start']}..{item['comparison_end']}"
                )
                for item in pairs
            },
            "baseline_periods": {
                item["newcomer"]: (
                    f"{item['baseline_start']}..{item['baseline_end']}"
                )
                for item in pairs
            },
            "selection_rule": (
                "All mapped Indian dual-airport pairs with observed newcomer "
                "traffic and a defensible same-market incumbent are shown"
            ),
            "data_coverage": route_coverage(routes),
        }
    if chart_id == "domestic_network_decentralisation":
        annual = annual_network_metrics(
            routes,
            monthly,
            start_year=NETWORK_START_YEAR,
            min_route_persistence_months=NETWORK_MIN_ROUTE_PERSISTENCE,
            segment_monthly=segment_monthly,
        )
        return {
            "period": f"{annual.index.min()}..{annual.index.max()}",
            "years_shown": int(len(annual)),
            "total_eligible_complete_years": int(len(annual)),
            "selection_rule": (
                "All complete calendar years from the configured start year"
            ),
            "data_coverage": route_coverage(routes),
        }
    return {}


def chart_airport_passenger_race(
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    trailing = _domestic_trailing_airport_passengers(monthly)
    if trailing.empty:
        raise ValueError("No complete trailing passenger windows found")

    global_max = float(trailing.max(axis=1).max())
    fixed_xlim = global_max * 1.28
    frame_periods = list(trailing.index)
    meta = load_metadata()
    data_str = "Data: DGCA"
    if meta.get("data_date"):
        data_str += f" (as of {meta['data_date']})"
    footer = f"{repo_url()} | {data_str} | Generated {date.today()} | Coverage: {coverage}"

    images = []
    for frame_idx, period in enumerate(frame_periods, start=1):
        series = trailing.loc[period].sort_values(ascending=False)
        top10 = series.head(10)
        if top10.empty:
            continue

        airports = list(reversed(top10.index.tolist()))
        values = list(reversed(top10.values.tolist()))
        colors = [stable_color(airport) for airport in airports]
        national_total = float(trailing.loc[period].sum())

        fig, ax = plt.subplots(figsize=FIGSIZE_WIDE, facecolor=BG)
        ax.set_facecolor(BG)
        ax.barh(
            range(len(airports)),
            values,
            color=colors,
            height=0.72,
            edgecolor="none",
        )

        label_offset = global_max * 0.012
        for y_pos, value in enumerate(values):
            ax.text(
                value + label_offset,
                y_pos,
                f"{value / 1_000_000:.1f}M",
                va="center",
                ha="left",
                fontsize=10,
                color=TEXT,
                fontweight="bold",
            )

        ax.set_yticks(range(len(airports)))
        ax.set_yticklabels(airports, fontsize=12, color=TEXT, fontweight="bold")
        ax.set_xlim(0, fixed_xlim)
        ax.set_xlabel(
            "Trailing 12-month domestic airport passenger movements",
            color=TEXT,
            fontsize=11,
        )
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.grid(axis="x", alpha=0.2, color=GRID, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.spines["left"].set_color(GRID)

        month_label = f"{MONTH_ABBR[int(period.month)]} {int(period.year)}"
        ax.text(
            0.0,
            1.13,
            month_label,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=26,
            fontweight="bold",
            fontfamily="monospace",
            color=ACCENT,
        )
        ax.text(
            0.0,
            1.075,
            "India Airport Passenger Race",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=18,
            fontweight="bold",
            color=TITLE,
        )
        ax.text(
            0.0,
            1.035,
            "Domestic airport passenger movements by airport | Trailing 12-month total",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=9,
            color=SUBTLE,
        )
        ax.text(
            1.0,
            1.105,
            f"{national_total / 1_000_000:,.0f}M passengers",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=17,
            fontweight="bold",
            fontfamily="monospace",
            color=TEXT,
        )
        ax.text(
            1.0,
            1.06,
            "national trailing total",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            color=SUBTLE,
        )
        ax.text(
            1.0,
            -0.17,
            footer,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=10,
            color=MUTED,
        )

        fig.subplots_adjust(left=0.14, right=0.92, top=0.78, bottom=0.18)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, facecolor=BG)
        plt.close(fig)
        buf.seek(0)
        images.append(Image.open(buf).copy())
        buf.close()

        if frame_idx % 24 == 0:
            print(
                f"    airport_passenger_race: frame {frame_idx}/{len(frame_periods)}",
                flush=True,
            )

    if not images:
        raise ValueError("No race frames generated")

    durations = [PASSENGER_RACE_FRAME_MS] * len(images)
    durations[-1] = PASSENGER_RACE_LAST_FRAME_MS
    out = CHARTS_DIR / "airport_passenger_race.gif"
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    return out


def generate_charts(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    carrier: pd.DataFrame,
    routes: pd.DataFrame,
    *,
    only: str | None,
    include_gifs: bool,
    domestic_coverage_text: str,
    international_coverage_text: str,
    carrier_coverage_text: str,
    route_coverage_text: str,
    domestic_fingerprint: str,
    international_fingerprint: str,
    carrier_fingerprint: str,
    route_fingerprint: str,
    segment_monthly: pd.DataFrame | None = None,
) -> dict[str, dict]:
    selected_ids = [only] if only else CHART_IDS
    chart_records: dict[str, dict] = {}
    route_chart_ids = {
        "ncr_route_opportunity_frontier",
        "dual_airport_network_roles",
        "domestic_network_decentralisation",
    }
    segments = segment_monthly
    if segments is None and route_chart_ids.intersection(selected_ids):
        segments = bidirectional_segments(routes)

    chart_functions = {
        "india_domestic_demand_pulse": lambda: chart_india_domestic_demand_pulse(
            carrier,
            coverage=carrier_coverage_text,
            fingerprint=carrier_fingerprint,
        ),
        "top_airport_traffic_trends": lambda: chart_top_airport_traffic_trends(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
        ),
        "newcomer_airport_rampup_24m": lambda: chart_newcomer_airport_rampup(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
        ),
        "domestic_market_share_gainers": lambda: chart_domestic_market_share_gainers(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
        ),
        "international_gateway_share_gainers": lambda: chart_international_gateway_share_gainers(
            quarterly,
            coverage=international_coverage_text,
            fingerprint=international_fingerprint,
        ),
        "airport_seasonality_fingerprint": lambda: chart_airport_seasonality_fingerprint(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
        ),
        "ncr_route_opportunity_frontier": lambda: chart_ncr_route_opportunity_frontier(
            routes,
            monthly,
            coverage=route_coverage_text,
            fingerprint=route_fingerprint,
            segment_monthly=segments,
        ),
        "dual_airport_network_roles": lambda: chart_dual_airport_network_roles(
            routes,
            monthly,
            coverage=route_coverage_text,
            fingerprint=route_fingerprint,
            segment_monthly=segments,
        ),
        "domestic_network_decentralisation": lambda: chart_domestic_network_decentralisation(
            routes,
            monthly,
            coverage=route_coverage_text,
            fingerprint=route_fingerprint,
            segment_monthly=segments,
        ),
    }

    for chart_id in selected_ids:
        print(f"  Generating: {chart_id}.png", flush=True)
        path = chart_functions[chart_id]()
        chart_records[chart_id] = register_chart(
            path,
            chart_id,
            runtime_params=chart_runtime_params(
                chart_id,
                monthly,
                quarterly,
                carrier,
                routes,
                segment_monthly=segments,
            ),
        )
        print(f"    Saved: {path.relative_to(ROOT)}", flush=True)

    if include_gifs:
        print("  Generating: airport_passenger_race.gif", flush=True)
        gif_path = chart_airport_passenger_race(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
        )
        print(f"    Saved: {gif_path.relative_to(ROOT)}", flush=True)

    return chart_records


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate dashboard charts from published canonical datasets."
    )
    parser.add_argument(
        "--include-gifs",
        action="store_true",
        help="Also generate optional GIF animations.",
    )
    parser.add_argument(
        "--skip-gifs",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--only",
        choices=CHART_IDS,
        help="Generate one static chart instead of the full visible set.",
    )
    parser.add_argument(
        "--skip-dashboard-summary",
        action="store_true",
        help="Do not write data/processed/dashboard_summary.json.",
    )
    parser.add_argument(
        "--skip-manifest",
        action="store_true",
        help="Do not write charts/manifest.json.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)

    if not DOMESTIC_MONTHLY_PATH.exists():
        raise FileNotFoundError("No processed domestic airport data. Run clean.py first.")
    if not INTERNATIONAL_QUARTERLY_PATH.exists():
        raise FileNotFoundError("No processed international airport data. Run clean.py first.")
    if not CARRIER_MONTHLY_PATH.exists():
        raise FileNotFoundError("No processed carrier data. Run clean.py first.")
    if not DOMESTIC_ROUTE_MONTHLY_PATH.exists():
        raise FileNotFoundError(
            "No processed domestic route data. Run clean.py first."
        )

    print("=== Generating Charts ===\n", flush=True)

    monthly = load_domestic_monthly()
    quarterly = load_international_quarterly()
    carrier = load_carrier_monthly()
    routes = load_domestic_routes()
    route_segments = bidirectional_segments(routes)
    domestic_coverage_text = domestic_coverage(monthly)
    international_coverage_text = international_coverage(quarterly)
    carrier_coverage_text = carrier_domestic_coverage(carrier)
    route_coverage_text = route_coverage(routes)
    domestic_fingerprint = input_fingerprint([DOMESTIC_MONTHLY_PATH])
    international_fingerprint = input_fingerprint([INTERNATIONAL_QUARTERLY_PATH])
    carrier_fingerprint = input_fingerprint([CARRIER_MONTHLY_PATH])
    route_fingerprint = input_fingerprint(
        [DOMESTIC_ROUTE_MONTHLY_PATH, DOMESTIC_MONTHLY_PATH]
    )
    overall_fingerprint = input_fingerprint(
        [
            DOMESTIC_MONTHLY_PATH,
            INTERNATIONAL_QUARTERLY_PATH,
            CARRIER_MONTHLY_PATH,
            DOMESTIC_ROUTE_MONTHLY_PATH,
        ]
    )

    chart_records = generate_charts(
        monthly,
        quarterly,
        carrier,
        routes,
        only=args.only,
        include_gifs=args.include_gifs and not args.skip_gifs,
        domestic_coverage_text=domestic_coverage_text,
        international_coverage_text=international_coverage_text,
        carrier_coverage_text=carrier_coverage_text,
        route_coverage_text=route_coverage_text,
        domestic_fingerprint=domestic_fingerprint,
        international_fingerprint=international_fingerprint,
        carrier_fingerprint=carrier_fingerprint,
        route_fingerprint=route_fingerprint,
        segment_monthly=route_segments,
    )

    if not args.skip_dashboard_summary:
        print("  Writing: data/processed/dashboard_summary.json", flush=True)
        summary_path = write_dashboard_summary(
            monthly,
            quarterly,
            carrier,
            fingerprint=overall_fingerprint,
        )
        print(f"    Saved: {summary_path.relative_to(ROOT)}", flush=True)
        print("  Writing: data/processed/route_analysis_summary.json", flush=True)
        route_summary_path = write_route_analysis_summary(
            routes, monthly, segment_monthly=route_segments
        )
        print(f"    Saved: {route_summary_path.relative_to(ROOT)}", flush=True)

    if not args.skip_manifest:
        print("  Writing: charts/manifest.json", flush=True)
        manifest_path = write_chart_manifest(
            chart_records,
            monthly=monthly,
            quarterly=quarterly,
            carrier=carrier,
            routes=routes,
            domestic_coverage_text=domestic_coverage_text,
            international_coverage_text=international_coverage_text,
            carrier_coverage_text=carrier_coverage_text,
            route_coverage_text=route_coverage_text,
            overall_fingerprint=overall_fingerprint,
        )
        print(f"    Saved: {manifest_path.relative_to(ROOT)}", flush=True)

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
