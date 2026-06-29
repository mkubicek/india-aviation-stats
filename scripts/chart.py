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

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
CHARTS_DIR = ROOT / "charts"
DOMESTIC_MONTHLY_PATH = PROCESSED_DIR / "airport_monthly.csv"
INTERNATIONAL_QUARTERLY_PATH = PROCESSED_DIR / "airport_international_quarterly.csv"
METADATA_PATH = PROCESSED_DIR / "metadata.json"
DASHBOARD_SUMMARY_PATH = PROCESSED_DIR / "dashboard_summary.json"
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


def add_quarter_period(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["period"] = pd.PeriodIndex(
        out["year"].astype(int).astype(str) + "Q" + out["quarter"].astype(int).astype(str),
        freq="Q",
    )
    return out


def domestic_coverage(monthly: pd.DataFrame) -> str:
    m = add_month_period(monthly)
    periods = m["period"].sort_values()
    return f"{periods.iloc[0]}..{periods.iloc[-1]}"


def international_coverage(quarterly: pd.DataFrame) -> str:
    q = add_quarter_period(quarterly)
    periods = q["period"].sort_values()
    return f"{periods.iloc[0]}..{periods.iloc[-1]}"


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
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.1f}%"


def fmt_optional_millions(value: float | None) -> str:
    if value is None or pd.isna(value):
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


def domestic_airport_month_matrix(monthly: pd.DataFrame) -> pd.DataFrame:
    m = add_month_period(monthly)
    grouped = m.groupby(["period", "airport"], as_index=False)["passengers"].sum()
    return (
        grouped.pivot(index="period", columns="airport", values="passengers")
        .fillna(0)
        .sort_index()
    )


def international_airport_quarter_matrix(quarterly: pd.DataFrame) -> pd.DataFrame:
    q = add_quarter_period(quarterly)
    grouped = q.groupby(["period", "airport"], as_index=False)["passengers"].sum()
    return (
        grouped.pivot(index="period", columns="airport", values="passengers")
        .fillna(0)
        .sort_index()
    )


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
    fmt,
) -> str:
    """Disclose the top-N-of-total selection and name the explicit windows."""
    n_gainers = int((movers["delta_pp"] > 0).sum())
    n_losers = int((movers["delta_pp"] < 0).sum())
    latest_label = f"{fmt(latest_periods[0])}–{fmt(latest_periods[-1])}"
    previous_label = f"{fmt(previous_periods[0])}–{fmt(previous_periods[-1])}"
    return (
        f"Top {n_gainers} gainers & {n_losers} decliners of {active} {noun}  ·  "
        f"{latest_label} vs {previous_label}"
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
    monthly: pd.DataFrame,
    *,
    coverage: str,
    fingerprint: str,
) -> Path:
    m = add_month_period(monthly)
    national = m.groupby("period")["passengers"].sum().sort_index()
    t12 = national.rolling(12, min_periods=12).sum()
    monthly_yoy = national / national.shift(12) - 1
    t12_yoy = t12 / t12.shift(12) - 1

    latest_period = national.index.max()
    latest_month_passengers = float(national.loc[latest_period])
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
        label="Monthly passengers",
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
        "Scheduled domestic passenger flows by month and trailing 12-month total",
        "Trailing 12-month passengers",
    )
    style_secondary_axis(ax2, "Monthly passengers")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(0, clean_upper_bound(float(t12.max()) * 1.08))
    ax2.set_ylim(0, clean_upper_bound(float(national.max()) * 1.20))
    ax.legend(
        [line, bars],
        ["Trailing 12-month total", "Monthly passengers"],
        loc="upper left",
        frameon=False,
        labelcolor=TEXT,
        fontsize=9,
    )

    kpi = (
        f"Latest month: {fmt_optional_millions(latest_month_passengers)}"
        f" ({fmt_optional_pct(latest_month_yoy)} YoY)\n"
        f"Trailing 12 months: {fmt_optional_millions(latest_t12)}"
        f" ({fmt_optional_pct(latest_t12_yoy)} YoY)"
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
        "Trailing 12-month scheduled domestic passengers by airport",
        "Trailing 12-month passengers",
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
        "Monthly domestic passengers during each airport's first 24 DGCA-observed months",
        "Monthly passengers",
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
        fmt=format_month_period,
    )
    return chart_share_movers(
        movers,
        chart_id="domestic_market_share_gainers",
        title="Domestic Market Share Movers",
        subtitle=subtitle,
        pax_change_header="Dom pax change",
        latest_pax_header="Latest dom 12M pax",
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
        fmt=format_quarter_period,
    )
    return chart_share_movers(
        movers,
        chart_id="international_gateway_share_gainers",
        title="International Gateway Share Movers",
        subtitle=subtitle,
        pax_change_header="Intl pax change",
        latest_pax_header="Latest intl 4Q pax",
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
        "Monthly passenger index by airport; 100 = that airport's average month",
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


def generate_dashboard_summary(
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    *,
    fingerprint: str,
) -> dict:
    m = add_month_period(monthly)
    national = m.groupby("period")["passengers"].sum().sort_index()
    t12 = national.rolling(12, min_periods=12).sum()
    monthly_yoy = national / national.shift(12) - 1
    t12_yoy = t12 / t12.shift(12) - 1
    latest_month = national.index.max()

    q = add_quarter_period(quarterly)
    international = q.groupby("period")["passengers"].sum().sort_index()
    latest_4q = international.rolling(4, min_periods=4).sum()
    latest_4q_yoy = latest_4q / latest_4q.shift(4) - 1
    latest_quarter = international.index.max()

    def nullable_int(value: float) -> int | None:
        return None if pd.isna(value) else int(round(float(value)))

    def nullable_pct(value: float) -> float | None:
        return None if pd.isna(value) else round(float(value) * 100, 1)

    summary = {
        "data_date": load_metadata().get("data_date"),
        "generated_date": date.today().isoformat(),
        "domestic": {
            "latest_month": str(latest_month),
            "latest_month_passengers": nullable_int(national.loc[latest_month]),
            "latest_month_yoy_pct": nullable_pct(monthly_yoy.loc[latest_month]),
            "trailing_12m_passengers": nullable_int(t12.dropna().iloc[-1])
            if not t12.dropna().empty
            else None,
            "trailing_12m_yoy_pct": nullable_pct(t12_yoy.dropna().iloc[-1])
            if not t12_yoy.dropna().empty
            else None,
            "airports_latest_month": int(
                m.loc[m["period"] == latest_month, "airport"].nunique()
            ),
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
    *,
    fingerprint: str,
) -> Path:
    summary = generate_dashboard_summary(monthly, quarterly, fingerprint=fingerprint)
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
    domestic_coverage_text: str,
    international_coverage_text: str,
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
        },
        "charts": dict(sorted(chart_records.items())),
    }


def write_chart_manifest(
    chart_records: Mapping[str, dict],
    *,
    monthly: pd.DataFrame,
    quarterly: pd.DataFrame,
    domestic_coverage_text: str,
    international_coverage_text: str,
    overall_fingerprint: str,
) -> Path:
    manifest = build_chart_manifest(
        chart_records,
        monthly=monthly,
        quarterly=quarterly,
        domestic_coverage_text=domestic_coverage_text,
        international_coverage_text=international_coverage_text,
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
    }
    return params[chart_id]


def chart_inputs(chart_id: str) -> list[str]:
    if chart_id == "international_gateway_share_gainers":
        return ["airport_international_quarterly"]
    return ["airport_monthly"]


def register_chart(path: Path, chart_id: str) -> dict:
    return {
        "file": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
        "inputs": chart_inputs(chart_id),
        "params": chart_params(chart_id),
    }


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
        ax.set_xlabel("Trailing 12-month domestic passengers", color=TEXT, fontsize=11)
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
            "Scheduled domestic passenger flows by airport | Trailing 12-month total",
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
    *,
    only: str | None,
    include_gifs: bool,
    domestic_coverage_text: str,
    international_coverage_text: str,
    domestic_fingerprint: str,
    international_fingerprint: str,
) -> dict[str, dict]:
    selected_ids = [only] if only else CHART_IDS
    chart_records: dict[str, dict] = {}

    chart_functions = {
        "india_domestic_demand_pulse": lambda: chart_india_domestic_demand_pulse(
            monthly,
            coverage=domestic_coverage_text,
            fingerprint=domestic_fingerprint,
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
    }

    for chart_id in selected_ids:
        print(f"  Generating: {chart_id}.png", flush=True)
        path = chart_functions[chart_id]()
        chart_records[chart_id] = register_chart(path, chart_id)
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

    print("=== Generating Charts ===\n", flush=True)

    monthly = load_domestic_monthly()
    quarterly = load_international_quarterly()
    domestic_coverage_text = domestic_coverage(monthly)
    international_coverage_text = international_coverage(quarterly)
    domestic_fingerprint = input_fingerprint([DOMESTIC_MONTHLY_PATH])
    international_fingerprint = input_fingerprint([INTERNATIONAL_QUARTERLY_PATH])
    overall_fingerprint = input_fingerprint(
        [DOMESTIC_MONTHLY_PATH, INTERNATIONAL_QUARTERLY_PATH]
    )

    chart_records = generate_charts(
        monthly,
        quarterly,
        only=args.only,
        include_gifs=args.include_gifs and not args.skip_gifs,
        domestic_coverage_text=domestic_coverage_text,
        international_coverage_text=international_coverage_text,
        domestic_fingerprint=domestic_fingerprint,
        international_fingerprint=international_fingerprint,
    )

    if not args.skip_dashboard_summary:
        print("  Writing: data/processed/dashboard_summary.json", flush=True)
        summary_path = write_dashboard_summary(
            monthly,
            quarterly,
            fingerprint=overall_fingerprint,
        )
        print(f"    Saved: {summary_path.relative_to(ROOT)}", flush=True)

    if not args.skip_manifest:
        print("  Writing: charts/manifest.json", flush=True)
        manifest_path = write_chart_manifest(
            chart_records,
            monthly=monthly,
            quarterly=quarterly,
            domestic_coverage_text=domestic_coverage_text,
            international_coverage_text=international_coverage_text,
            overall_fingerprint=overall_fingerprint,
        )
        print(f"    Saved: {manifest_path.relative_to(ROOT)}", flush=True)

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
