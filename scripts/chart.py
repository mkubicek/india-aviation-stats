"""Chart generation for India aviation statistics.

Flagship charts:
  1. GDP–Flights Correlation (dual Y-axis, with projection)
  2. National Passenger Growth Projection (bar + line overlay)
  3. Top Airport Rankings Over Time (bump chart)
  4. Airport Passenger Race (animated GIF bar race)
  5. The Great Indian Airport Boom (animated GIF map)
  6. Milestones Table (hero)

All charts use the dark theme defined in AGENTS.md.
"""

import io
import json
import os
import sys
from datetime import date
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from PIL import Image

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
CHARTS_DIR = ROOT / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)

MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

# ── Dark theme constants ─────────────────────────────────────

BG = "#0d1117"
TEXT = "white"
SUBTLE = "#94a3b8"
GRID_COLOR = "#334155"
ACCENT_BLUE = "#3b82f6"
ACCENT_PINK = "#f72585"
ACCENT_GOLD = "#fbbf24"
ACCENT_GREEN = "#22c55e"

TIER_COLORS = MAPPINGS.get("tier_colors", {})
AIRPORT_COLORS = MAPPINGS.get("airport_colors", {})
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
]
MONTH_NAMES = {
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

DISCLAIMER = (
    "Personal project \u2014 views are my own, "
    "not those of any employer or affiliate"
)


# ── Helpers ──────────────────────────────────────────────────


def get_repo_url() -> str:
    """Get repository URL from env or git remote."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return f"https://github.com/{repo}"
    try:
        import subprocess

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            return url.replace(".git", "")
    except Exception:
        pass
    return ""


def load_metadata() -> dict:
    """Load metadata.json."""
    path = PROCESSED_DIR / "metadata.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


# Schema of projection.json this chart module expects. Bumped by project.py
# when regression fields or emitted structure change in a breaking way. We
# warn on mismatch rather than raising because charts are meant to render
# something even with slightly stale data, but we refuse to silently pretend.
EXPECTED_PROJECTION_SCHEMA = 1


def load_projection() -> dict | None:
    """Load projection.json, verifying schema_version with a warning on drift."""
    path = PROCESSED_DIR / "projection.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    version = data.get("schema_version")
    if version != EXPECTED_PROJECTION_SCHEMA:
        print(
            f"    WARNING: projection.json schema_version={version} but chart.py "
            f"expects {EXPECTED_PROJECTION_SCHEMA}. Charts may render incorrectly.",
            flush=True,
        )
    return data


def get_attribution(fontsize: int = 8) -> str:
    """Build attribution string for charts."""
    repo = get_repo_url()
    meta = load_metadata()
    short = repo.replace("https://github.com/", "github.com/") if repo else ""
    parts = []
    if short:
        parts.append(short)
    data_str = "Data: World Bank, DGCA, MoCA"
    if "data_date" in meta:
        data_str += f" (as of {meta['data_date']})"
    parts.append(data_str)
    parts.append(f"Generated {date.today()}")
    return " | ".join(parts)


def style_chart(
    ax,
    title: str,
    subtitle: str = "",
    xlabel: str = "",
    ylabel: str = "",
):
    """Apply dark theme styling to an axis."""
    ax.set_facecolor(BG)
    ax.set_title(
        title, fontsize=16, fontweight="bold", pad=25 if subtitle else 15, color=TEXT
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
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT, fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT, fontsize=11)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.grid(axis="y", alpha=0.2, color=GRID_COLOR, linestyle="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color(GRID_COLOR)
    ax.spines["left"].set_color(GRID_COLOR)


def add_attribution(ax, fontsize: int = 8):
    """Add attribution text at bottom-right of chart."""
    ax.text(
        1.0,
        -0.12,
        get_attribution(fontsize),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=fontsize,
        color=SUBTLE,
        alpha=0.7,
    )


def add_disclaimer(ax, fontsize: int = 7):
    """Add disclaimer text below attribution."""
    ax.text(
        1.0,
        -0.16,
        DISCLAIMER,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=fontsize,
        color=SUBTLE,
        alpha=0.5,
    )


# ── Chart 1: GDP–Flights Correlation ────────────────────────


def chart_gdp_flights_correlation():
    """Dual Y-axis: GDP per capita vs flights per capita, with projection."""
    print("  Generating: gdp_flights_correlation.png", flush=True)

    projection_path = PROCESSED_DIR / "projection.json"
    if not projection_path.exists():
        print("    WARNING: projection.json not found, skipping", flush=True)
        return

    proj = json.loads(projection_path.read_text())
    timeline = proj["national_timeline"]
    regression = proj["regression"]

    actual = [e for e in timeline if e["type"] == "actual"]
    projected = [e for e in timeline if e["type"] == "projected"]

    if not actual:
        print("    WARNING: No actual data in projection, skipping", flush=True)
        return

    fig, ax1 = plt.subplots(figsize=(14, 7), facecolor=BG)

    # GDP per capita (left axis)
    years_actual = [e["year"] for e in actual]
    gdp_actual = [e["gdp_per_capita_ppp"] for e in actual]

    years_proj = [e["year"] for e in projected]
    gdp_proj = [e["gdp_per_capita_ppp"] for e in projected]

    ax1.plot(years_actual, gdp_actual, color=ACCENT_BLUE, linewidth=2.5, label="GDP per capita (PPP)")
    ax1.plot(years_proj, gdp_proj, color=ACCENT_BLUE, linewidth=2, linestyle="--", alpha=0.6)

    style_chart(
        ax1,
        "India's GDP\u2013Flights Correlation",
        subtitle=(
            f"Log-log regression R\u00b2 = {regression['r_squared']:.3f} | "
            f"Elasticity = {regression['slope']:.2f} | "
            f"Scheduled commercial passengers at Indian airports"
        ),
        ylabel="GDP per Capita, PPP (US$)",
    )

    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # Flights per capita (right axis)
    ax2 = ax1.twinx()
    fpc_actual = [e["flights_per_capita"] for e in actual]
    fpc_proj = [e["flights_per_capita"] for e in projected]

    ax2.plot(years_actual, fpc_actual, color=ACCENT_PINK, linewidth=2.5, label="Flights per capita")
    ax2.plot(years_proj, fpc_proj, color=ACCENT_PINK, linewidth=2, linestyle="--", alpha=0.6)

    # Confidence band
    if projected and "flights_per_capita_low" in projected[0]:
        fpc_low = [e.get("flights_per_capita_low", e["flights_per_capita"]) for e in projected]
        fpc_high = [e.get("flights_per_capita_high", e["flights_per_capita"]) for e in projected]
        ax2.fill_between(years_proj, fpc_low, fpc_high, color=ACCENT_PINK, alpha=0.1)

    ax2.set_ylabel("Flights per Capita", color=TEXT, fontsize=11)
    ax2.tick_params(colors=TEXT, labelsize=9)
    for spine in ax2.spines.values():
        spine.set_color(GRID_COLOR)

    # Annotations for key milestones
    milestones = MAPPINGS.get("milestones", [])
    for m in milestones:
        m_date = m["date"]
        if len(m_date) == 7:
            m_year = int(m_date[:4])
        elif len(m_date) > 7:
            m_year = int(m_date[:4])
        else:
            continue

        if m_year in years_actual and m["label"] in (
            "COVID-19 lockdown",
            "UDAN scheme launched",
            "Full recovery milestone",
        ):
            idx = years_actual.index(m_year)
            ax2.annotate(
                m["label"],
                xy=(m_year, fpc_actual[idx]),
                xytext=(0, 20),
                textcoords="offset points",
                fontsize=7,
                color=SUBTLE,
                ha="center",
                arrowprops=dict(arrowstyle="->", color=SUBTLE, lw=0.8),
            )

    # Set x-axis ticks to show every year (or every 5 years if range is large)
    all_years = sorted(set(years_actual + years_proj))
    if len(all_years) > 20:
        tick_years = [y for y in all_years if y % 5 == 0]
    else:
        tick_years = all_years
    ax1.set_xticks(tick_years)
    ax1.set_xticklabels([str(y) for y in tick_years], rotation=45)

    # Vertical line at projection start
    if years_actual and years_proj:
        split_year = years_actual[-1]
        ax1.axvline(x=split_year, color=SUBTLE, linestyle=":", alpha=0.4)
        ax1.text(
            split_year + 0.5,
            ax1.get_ylim()[1] * 0.95,
            "Projected \u2192",
            fontsize=8,
            color=SUBTLE,
            alpha=0.6,
        )

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        fontsize=9,
        facecolor=BG,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT,
    )

    add_attribution(ax1)
    add_disclaimer(ax1)

    fig.tight_layout()
    out = CHARTS_DIR / "gdp_flights_correlation.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"    Saved: {out.name}")


# ── Chart 2: Passenger Growth Projection ────────────────────


def chart_passenger_projection():
    """Bar chart: historical + projected annual passengers with flights/capita overlay."""
    print("  Generating: passenger_projection.png", flush=True)

    projection_path = PROCESSED_DIR / "projection.json"
    if not projection_path.exists():
        print("    WARNING: projection.json not found, skipping", flush=True)
        return

    proj = json.loads(projection_path.read_text())
    timeline = proj["national_timeline"]

    actual = [e for e in timeline if e["type"] == "actual"]
    projected = [e for e in timeline if e["type"] == "projected"]

    if not actual:
        print("    WARNING: No actual data, skipping", flush=True)
        return

    fig, ax1 = plt.subplots(figsize=(16, 8), facecolor=BG)

    # Historical bars (solid)
    years_a = [e["year"] for e in actual]
    pax_a = [e["passengers"] / 1e6 for e in actual]
    ax1.bar(years_a, pax_a, color=ACCENT_BLUE, alpha=0.9, label="Actual passengers")

    # Projected bars (hatched/transparent)
    years_p = [e["year"] for e in projected]
    pax_p = [e["passengers"] / 1e6 for e in projected]
    bars = ax1.bar(
        years_p,
        pax_p,
        color=ACCENT_BLUE,
        alpha=0.3,
        hatch="//",
        edgecolor=ACCENT_BLUE,
        linewidth=0.5,
        label="Projected passengers",
    )

    # Confidence band
    if projected and "passengers_low" in projected[0]:
        pax_low = [e.get("passengers_low", e["passengers"]) / 1e6 for e in projected]
        pax_high = [e.get("passengers_high", e["passengers"]) / 1e6 for e in projected]
        ax1.fill_between(
            years_p, pax_low, pax_high, color=ACCENT_BLUE, alpha=0.1, label="\u00b12\u03c3 band"
        )

    style_chart(
        ax1,
        "India's Passenger Growth Projection",
        subtitle="Scheduled commercial passengers | GDP-based log-log regression model",
        ylabel="Annual Passengers (Millions)",
    )

    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:,.0f}M"))

    # Overlay: flights per capita (right axis)
    ax2 = ax1.twinx()
    fpc_all = []
    years_all = []
    for e in actual + projected:
        if "flights_per_capita" in e and e["flights_per_capita"]:
            years_all.append(e["year"])
            fpc_all.append(e["flights_per_capita"])

    ax2.plot(years_all, fpc_all, color=ACCENT_PINK, linewidth=2, label="Flights per capita")
    ax2.set_ylabel("Flights per Capita", color=TEXT, fontsize=11)
    ax2.tick_params(colors=TEXT, labelsize=9)
    for spine in ax2.spines.values():
        spine.set_color(GRID_COLOR)

    # Annotations
    if actual:
        latest = actual[-1]
        ax1.annotate(
            f"Current: {latest['passengers'] / 1e6:.0f}M",
            xy=(latest["year"], latest["passengers"] / 1e6),
            xytext=(-60, 30),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            color=TEXT,
            arrowprops=dict(arrowstyle="->", color=TEXT, lw=1),
        )

    if projected:
        last_proj = projected[-1]
        ax1.annotate(
            f"Projected: {last_proj['passengers'] / 1e6:.0f}M+ by {last_proj['year']}",
            xy=(last_proj["year"], last_proj["passengers"] / 1e6),
            xytext=(-80, 30),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            color=ACCENT_GOLD,
            arrowprops=dict(arrowstyle="->", color=ACCENT_GOLD, lw=1),
        )

    # X-axis
    all_years = sorted(years_a + years_p)
    tick_years = [y for y in all_years if y % 5 == 0]
    ax1.set_xticks(tick_years)
    ax1.set_xticklabels([str(y) for y in tick_years], rotation=45)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left",
        fontsize=9,
        facecolor=BG,
        edgecolor=GRID_COLOR,
        labelcolor=TEXT,
    )

    add_attribution(ax1)
    add_disclaimer(ax1)

    fig.tight_layout()
    out = CHARTS_DIR / "passenger_projection.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"    Saved: {out.name}")


# ── Chart 3: Top Airport Rankings Over Time ─────────────────


def _complete_airport_years(monthly: pd.DataFrame) -> list[int]:
    """Return annual years with complete domestic months and international quarters."""
    years_by_category: list[set[int]] = []

    domestic = monthly[monthly["category"] == "domestic"]
    if not domestic.empty:
        domestic_years = (
            domestic.groupby("year")["month"].nunique().loc[lambda s: s == 12].index
        )
        years_by_category.append(set(int(year) for year in domestic_years))

    international = monthly[monthly["category"] == "international"]
    if not international.empty:
        international_years = (
            international.groupby("year")["month"].nunique().loc[lambda s: s == 4].index
        )
        years_by_category.append(set(int(year) for year in international_years))

    if not years_by_category:
        return []
    complete = set.intersection(*years_by_category)
    return sorted(complete)


def chart_airport_rankings():
    """Bump chart: current top airport rankings across complete DGCA years."""
    print("  Generating: airport_rankings.png", flush=True)

    yearly_path = PROCESSED_DIR / "airport_yearly.csv"
    monthly_path = PROCESSED_DIR / "airport_monthly.csv"
    if not yearly_path.exists() or not monthly_path.exists():
        print("    WARNING: airport processed data not found, skipping", flush=True)
        return

    yearly = pd.read_csv(yearly_path)
    monthly = pd.read_csv(monthly_path)
    complete_years = _complete_airport_years(monthly)
    if not complete_years:
        print("    WARNING: no complete annual airport years found, skipping", flush=True)
        return

    annual = (
        yearly[yearly["year"].isin(complete_years)]
        .assign(airport=lambda df: df["airport"].astype(str).str.upper())
        .groupby(["year", "airport"], as_index=False)["passengers"]
        .sum()
    )
    if annual.empty:
        print("    WARNING: no complete annual airport records found, skipping", flush=True)
        return

    annual["rank"] = annual.groupby("year")["passengers"].rank(
        ascending=False, method="min"
    )
    latest_year = max(complete_years)
    latest = annual[annual["year"] == latest_year].nlargest(10, "passengers")
    top_airports = latest["airport"].tolist()
    if not top_airports:
        print("    WARNING: no ranked airports found, skipping", flush=True)
        return

    ranked = annual[annual["airport"].isin(top_airports)].copy()
    all_years = list(range(min(complete_years), max(complete_years) + 1))
    max_rank = int(np.ceil(ranked["rank"].max()))

    fig, ax = plt.subplots(figsize=(14, 8), facecolor=BG)

    latest_lookup = latest.set_index("airport")["passengers"].to_dict()
    for idx, airport in enumerate(top_airports):
        airport_data = (
            ranked[ranked["airport"] == airport]
            .sort_values("year")
            .set_index("year")
            .reindex(all_years)
        )
        color = AIRPORT_COLORS.get(airport, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])
        ax.plot(
            all_years,
            airport_data["rank"],
            marker="o",
            linewidth=2.5,
            color=color,
            markersize=7,
            zorder=3,
        )

        valid = airport_data.dropna(subset=["rank"])
        if not valid.empty:
            last = valid.iloc[-1]
            label = f"{airport}  {latest_lookup.get(airport, 0) / 1e6:.1f}M"
            ax.annotate(
                label,
                (int(last.name), last["rank"]),
                textcoords="offset points",
                xytext=(8, 0),
                fontsize=9,
                fontweight="bold",
                color=color,
                va="center",
                clip_on=False,
            )

    ax.invert_yaxis()
    ax.set_yticks(range(1, max_rank + 1))
    ax.set_yticklabels([f"#{rank}" for rank in range(1, max_rank + 1)])
    ax.set_xticks(all_years)
    ax.set_xticklabels([str(year) for year in all_years])
    ax.grid(axis="x", alpha=0.2, color=GRID_COLOR, linestyle="--")
    ax.set_xlim(min(all_years) - 0.4, max(all_years) + 1.15)
    ax.set_ylim(max_rank + 0.6, 0.4)

    style_chart(
        ax,
        "India's Top Airport Rankings Over Time",
        subtitle=(
            f"Current top 10 airports by annual passengers | Complete DGCA years only "
            f"| Latest complete year: {latest_year}"
        ),
        ylabel="Rank",
    )
    ax.set_xlabel("")

    missing_years = sorted(set(all_years) - set(complete_years))
    for year in missing_years:
        ax.axvspan(year - 0.5, year + 0.5, color=GRID_COLOR, alpha=0.10, zorder=0)
        ax.text(
            year,
            max_rank + 0.35,
            "partial",
            ha="center",
            va="bottom",
            fontsize=7,
            color=SUBTLE,
            rotation=90,
            alpha=0.7,
        )

    add_attribution(ax)
    add_disclaimer(ax)

    fig.tight_layout()
    out = CHARTS_DIR / "airport_rankings.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"    Saved: {out.name}")


# ── Chart 4: Airport Passenger Race (animated GIF) ──────────


def _domestic_trailing_airport_passengers(
    monthly: pd.DataFrame,
    window: int = 12,
) -> pd.DataFrame:
    """Return complete rolling domestic passenger totals by airport-month."""
    domestic = monthly[monthly["category"] == "domestic"].copy()
    if domestic.empty:
        return pd.DataFrame()

    domestic["period"] = pd.to_datetime(
        {
            "year": domestic["year"].astype(int),
            "month": domestic["month"].astype(int),
            "day": 1,
        }
    ).dt.to_period("M")
    airport_monthly = (
        domestic.groupby(["period", "airport"], as_index=False)["passengers"].sum()
    )
    pivot = (
        airport_monthly.pivot(index="period", columns="airport", values="passengers")
        .fillna(0)
        .sort_index()
    )

    available_periods = set(pivot.index)
    complete_periods = [
        period
        for period in pivot.index
        if all((period - offset) in available_periods for offset in range(window))
    ]
    if not complete_periods:
        return pd.DataFrame()

    return pivot.rolling(window, min_periods=window).sum().loc[complete_periods]


def chart_airport_passenger_race():
    """Animated bar race: top airports by trailing 12-month domestic passengers."""
    print("  Generating: airport_passenger_race.gif", flush=True)

    monthly_path = PROCESSED_DIR / "airport_monthly.csv"
    if not monthly_path.exists():
        print("    WARNING: airport_monthly.csv not found, skipping", flush=True)
        return

    monthly = pd.read_csv(monthly_path)
    trailing = _domestic_trailing_airport_passengers(monthly)
    if trailing.empty:
        print("    WARNING: no complete trailing passenger windows found, skipping", flush=True)
        return

    global_max = float(trailing.max(axis=1).max())
    fixed_xlim = global_max * 1.28
    frame_periods = list(trailing.index)
    attribution = get_attribution(fontsize=11)

    images = []
    for frame_idx, period in enumerate(frame_periods, start=1):
        series = trailing.loc[period].sort_values(ascending=False)
        top10 = series.head(10)
        if top10.empty:
            continue

        airports = list(reversed(top10.index.tolist()))
        values = list(reversed(top10.values.tolist()))
        colors = [
            AIRPORT_COLORS.get(
                airport,
                FALLBACK_COLORS[i % len(FALLBACK_COLORS)],
            )
            for i, airport in enumerate(airports)
        ]
        national_total = float(trailing.loc[period].sum())

        fig, ax = plt.subplots(figsize=(14, 8), facecolor=BG)
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
                f"{value / 1e6:.1f}M",
                va="center",
                ha="left",
                fontsize=10,
                color=TEXT,
                fontweight="bold",
            )

        ax.set_yticks(range(len(airports)))
        ax.set_yticklabels(
            airports,
            fontsize=12,
            color=TEXT,
            fontweight="bold",
        )
        ax.set_xlim(0, fixed_xlim)
        ax.set_xlabel("Trailing 12-Month Domestic Passengers", color=TEXT, fontsize=11)
        ax.xaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, _: f"{x / 1e6:.0f}M")
        )
        ax.tick_params(colors=TEXT, labelsize=9)
        ax.grid(axis="x", alpha=0.2, color=GRID_COLOR, linestyle="--")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_color(GRID_COLOR)
        ax.spines["left"].set_color(GRID_COLOR)

        month_label = f"{MONTH_NAMES[int(period.month)]} {int(period.year)}"
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
            color=ACCENT_GOLD,
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
            color=TEXT,
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
            f"{national_total / 1e6:,.0f}M passengers",
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
            attribution,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=11,
            color=SUBTLE,
            alpha=0.7,
        )
        ax.text(
            1.0,
            -0.215,
            DISCLAIMER,
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            color=SUBTLE,
            alpha=0.5,
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
        print("    WARNING: no race frames generated, skipping", flush=True)
        return

    durations = [300] * len(images)
    durations[-1] = 3000
    out = CHARTS_DIR / "airport_passenger_race.gif"
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"    Saved: {out.name} ({len(images)} frames)")


# ── Chart 5: The Great Indian Airport Boom (animated GIF) ───


def chart_airport_map():
    """Animated GIF: India map with airport circles growing over time."""
    print("  Generating: airport_boom.gif", flush=True)

    projection_path = PROCESSED_DIR / "projection.json"
    if not projection_path.exists():
        print("    WARNING: projection.json not found, skipping", flush=True)
        return

    proj = json.loads(projection_path.read_text())
    timeline = proj["national_timeline"]
    airport_proj = proj.get("airport_projections", [])

    airports = MAPPINGS.get("airports", {})
    greenfield = MAPPINGS.get("greenfield_airports", {})
    tier_colors = MAPPINGS.get("tier_colors", {})

    # Try loading India GeoJSON for base map
    india_geojson = None
    try:
        import geopandas as gpd

        geojson_path = ROOT / "data" / "india.geojson"
        if geojson_path.exists():
            india_geojson = gpd.read_file(geojson_path)
            print(f"    Loaded India GeoJSON ({len(india_geojson)} features)", flush=True)
    except Exception as e:
        print(f"    Note: Could not load GeoJSON ({e}), using outline only", flush=True)

    # Build timeline frames: every year from 2015 to 2040 for smooth animation
    actual_years = sorted(set(e["year"] for e in timeline if e["type"] == "actual"))
    projected_years = sorted(set(e["year"] for e in timeline if e["type"] == "projected"))
    all_timeline_years = sorted(set(actual_years + projected_years))
    frame_years = [y for y in all_timeline_years if y >= 2015]

    if not frame_years:
        print("    WARNING: No years to animate, skipping", flush=True)
        return

    # Build airport data lookup: {(iata, year): passengers}
    airport_lookup = {}
    # From airport_yearly.csv (actual data)
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"
    if yearly_path.exists():
        yearly = pd.read_csv(yearly_path)
        for _, row in yearly.iterrows():
            key = (row["airport"], int(row["year"]))
            airport_lookup[key] = airport_lookup.get(key, 0) + row["passengers"]

    # From projections
    for ap in airport_proj:
        key = (ap["airport"], ap["year"])
        airport_lookup[key] = ap["passengers"]

    # Get national totals per year
    national_by_year = {}
    for e in timeline:
        national_by_year[e["year"]] = e["passengers"]

    # Find global max for consistent circle scaling
    all_pax = [v for v in airport_lookup.values() if v > 0]
    global_max = max(all_pax) if all_pax else 1

    # India bounding box for consistent framing
    india_bbox = {"lon_min": 68, "lon_max": 98, "lat_min": 6, "lat_max": 38}

    # Generate frames
    images = []
    for year in frame_years:
        fig, ax = plt.subplots(figsize=(10, 12), facecolor=BG)
        ax.set_facecolor(BG)

        # Draw India outline
        if india_geojson is not None:
            try:
                india_geojson.boundary.plot(ax=ax, color=GRID_COLOR, linewidth=0.5)
            except Exception:
                pass

        # Set bounds
        ax.set_xlim(india_bbox["lon_min"], india_bbox["lon_max"])
        ax.set_ylim(india_bbox["lat_min"], india_bbox["lat_max"])
        ax.set_aspect("equal")
        ax.axis("off")

        # Title
        is_projected = year > actual_years[-1] if actual_years else True
        year_label = f"{year} {'(projected)' if is_projected else ''}"
        ax.set_title(
            "The Great Indian Airport Boom",
            fontsize=18,
            fontweight="bold",
            color=TEXT,
            pad=20,
        )
        ax.text(
            0.5,
            0.97,
            year_label,
            transform=ax.transAxes,
            ha="center",
            fontsize=14,
            fontfamily="monospace",
            color=ACCENT_GOLD if is_projected else TEXT,
        )

        # Plot airports
        for iata, info in airports.items():
            lat = info.get("lat")
            lon = info.get("lon")
            tier = info.get("tier", "tier3")

            if lat is None or lon is None:
                continue

            # Check if airport is open in this year
            opened = info.get("opened_year", 0)
            if year < opened:
                continue

            # Get passenger count
            pax = airport_lookup.get((iata, year), 0)
            if pax <= 0 and tier != "greenfield":
                # Try to interpolate from nearest year
                for offset in range(1, 4):
                    pax = airport_lookup.get((iata, year - offset), 0)
                    if pax > 0:
                        break

            if pax <= 0:
                continue

            # Circle size (sqrt scale for perceptual area accuracy)
            size = np.sqrt(pax / global_max) * 800
            size = max(size, 10)  # Minimum visible size

            color = tier_colors.get(tier, SUBTLE)
            # Use specific airport color if defined
            if iata in AIRPORT_COLORS:
                color = AIRPORT_COLORS[iata]

            ax.scatter(
                lon,
                lat,
                s=size,
                c=color,
                alpha=0.7,
                edgecolors="white",
                linewidth=0.3,
                zorder=5,
            )

            # Label metros and highlighted airports
            if tier == "metro" or iata in AIRPORT_COLORS:
                ax.annotate(
                    iata,
                    (lon, lat),
                    textcoords="offset points",
                    xytext=(5, 5),
                    fontsize=7,
                    fontweight="bold",
                    color=TEXT,
                    alpha=0.8,
                )

        # National total counter
        national = national_by_year.get(year, 0)
        if national > 0:
            ax.text(
                0.95,
                0.05,
                f"{national / 1e6:,.0f}M passengers",
                transform=ax.transAxes,
                ha="right",
                va="bottom",
                fontsize=14,
                fontweight="bold",
                fontfamily="monospace",
                color=TEXT,
                bbox=dict(boxstyle="round,pad=0.4", facecolor=BG, edgecolor=GRID_COLOR, alpha=0.8),
            )

        # Legend
        legend_y = 0.25
        for tier_name, tier_color in tier_colors.items():
            ax.scatter(
                [],
                [],
                s=60,
                c=tier_color,
                label=tier_name.replace("_", " ").title(),
            )
        ax.legend(
            loc="lower left",
            fontsize=8,
            facecolor=BG,
            edgecolor=GRID_COLOR,
            labelcolor=TEXT,
            framealpha=0.8,
        )

        # Attribution (smaller for GIF)
        ax.text(
            0.5,
            0.01,
            get_attribution(fontsize=11),
            transform=ax.transAxes,
            ha="center",
            fontsize=7,
            color=SUBTLE,
            alpha=0.5,
        )

        # Save frame to buffer
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        buf.seek(0)
        images.append(Image.open(buf).copy())
        buf.close()

    if not images:
        print("    WARNING: No frames generated, skipping GIF", flush=True)
        return

    # Save GIF
    durations = [300] * len(images)
    durations[-1] = 3000  # Pause on last frame

    out = CHARTS_DIR / "airport_boom.gif"
    images[0].save(
        out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"    Saved: {out.name} ({len(images)} frames)")


# ── Chart 6: Milestones Table (hero) ─────────────────────────


def _format_threshold(threshold, metric: str) -> str:
    """Human-format the threshold cell by metric type."""
    if metric == "tier_share":
        return f"{threshold * 100:.0f}%"
    t = float(threshold)
    if t >= 1e9:
        return f"{t / 1e9:.1f}B pax"
    if t >= 1e6:
        return f"{t / 1e6:.0f}M pax"
    return f"{t:,.0f}"


def _format_year_cell(entry: dict) -> tuple[str, str, str]:
    """Return (p10, p50, p90) strings for a milestone entry.

    Handles achieved (actual year in center), projected (p10/p50/p90),
    beyond_horizon (">2040" marker), deterministic (center only).
    """
    if "actual_year" in entry:
        return ("", f"{entry['actual_year']} (actual)", "")
    status = entry.get("status")
    if status == "beyond_horizon":
        return ("—", ">2040", "—")
    method = entry.get("method")
    if method == "deterministic" and entry.get("p50_year") is None:
        return ("—", ">2040", "—")
    p10 = str(entry.get("p10_year") or "—")
    p50 = str(entry.get("p50_year") or "—")
    p90 = str(entry.get("p90_year") or "—")
    return (p10, p50, p90)


def chart_milestones_table():
    """Hero chart: operational milestones with p10/p50/p90 year bands.

    Reads milestones.json (must be produced by scripts/milestones.py first)
    and renders a dark-theme table in three visually distinct row groups:
    achieved, projected, scheduled.
    """
    print("  Generating: milestones_table.png", flush=True)

    path = PROCESSED_DIR / "milestones.json"
    if not path.exists():
        print("    WARNING: milestones.json not found, skipping", flush=True)
        print("    (run scripts/milestones.py after project.py)", flush=True)
        return

    m = json.loads(path.read_text())

    # Flatten all three blocks into ordered rows with group tags so we can
    # paint background strips by group.
    rows: list[dict] = []
    for mid, e in (m.get("achieved") or {}).items():
        rows.append({"group": "achieved", "id": mid, "entry": e})
    for mid, e in (m.get("projected") or {}).items():
        rows.append({"group": "projected", "id": mid, "entry": e})
    for mid, e in (m.get("scheduled") or {}).items():
        rows.append({"group": "scheduled", "id": mid, "entry": e})

    if not rows:
        print("    WARNING: milestones.json has no rows, skipping", flush=True)
        return

    # Figure: wide enough to avoid label wrap, tall enough per row for dark
    # table legibility on phone screenshot.
    fig_height = 1.5 + 0.5 * len(rows)
    fig, ax = plt.subplots(figsize=(13, fig_height))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.axis("off")

    # Header band
    col_x = [0.02, 0.50, 0.65, 0.80, 0.92]
    col_align = ["left", "right", "center", "center", "center"]
    headers = ["Milestone", "Threshold", "p10", "p50", "p90"]
    header_y = 1.0 - 0.08
    for x, h, al in zip(col_x, headers, col_align):
        ax.text(
            x, header_y, h,
            transform=ax.transAxes, ha=al, va="center",
            fontsize=11, fontweight="bold", color=TEXT,
        )

    # Divider below header
    ax.plot(
        [0.02, 0.98], [header_y - 0.04, header_y - 0.04],
        transform=ax.transAxes, color=GRID_COLOR, linewidth=1,
    )

    row_height = 0.92 / max(len(rows) + 1, 8)
    y = header_y - 0.06 - row_height

    # Group colors (dark-theme-safe, colorblind-aware):
    #   achieved   = accent green (already happened)
    #   projected  = white / subtle (the MC rows)
    #   scheduled  = accent gold italic (per AGENTS.md greenfield palette)
    group_color = {
        "achieved": ACCENT_GREEN,
        "projected": TEXT,
        "scheduled": ACCENT_GOLD,
    }
    group_style = {
        "achieved": "normal",
        "projected": "normal",
        "scheduled": "italic",
    }
    # Group headers appear once per block if that block has >=1 row.
    last_group: str | None = None
    for row in rows:
        group = row["group"]
        if group != last_group:
            # Group label on a thin row above the first row of the group
            ax.text(
                0.02, y, group.upper(),
                transform=ax.transAxes, ha="left", va="center",
                fontsize=9, color=SUBTLE, fontweight="bold",
            )
            y -= row_height
            last_group = group

        entry = row["entry"]
        color = group_color[group]
        style = group_style[group]
        p10, p50, p90 = _format_year_cell(entry)

        # Label
        ax.text(
            col_x[0], y, entry.get("label", row["id"]),
            transform=ax.transAxes, ha=col_align[0], va="center",
            fontsize=10, color=color, style=style,
        )

        # Threshold column — skip for scheduled (uses phase1_capacity instead)
        if group == "scheduled":
            cap = entry.get("phase1_capacity")
            cap_text = f"phase1: {cap/1e6:.0f}M pax" if cap else ""
            ax.text(
                col_x[1], y, cap_text,
                transform=ax.transAxes, ha=col_align[1], va="center",
                fontsize=10, color=color, style=style,
            )
            # p10/p50/p90 columns: scheduled date in center cell
            sd = entry.get("scheduled_date") or "—"
            ax.text(
                col_x[3], y, sd,
                transform=ax.transAxes, ha=col_align[3], va="center",
                fontsize=10, color=color, style=style,
            )
        else:
            metric = entry.get("metric", "")
            thr = entry.get("threshold")
            thr_text = _format_threshold(thr, metric) if thr is not None else ""
            ax.text(
                col_x[1], y, thr_text,
                transform=ax.transAxes, ha=col_align[1], va="center",
                fontsize=10, color=color, style=style,
            )
            for xi, text in zip(col_x[2:], (p10, p50, p90)):
                ax.text(
                    xi, y, text,
                    transform=ax.transAxes, ha="center", va="center",
                    # Emphasize p50 (the quotable number)
                    fontsize=11 if xi == col_x[3] else 10,
                    fontweight="bold" if xi == col_x[3] else "normal",
                    color=color, style=style,
                )
        y -= row_height

    # Title + subtitle
    fig.suptitle(
        "When will India's aviation milestones arrive?",
        color=TEXT, fontsize=18, fontweight="bold", y=0.97,
    )
    meta = load_metadata()
    data_date = meta.get("data_date", "")
    n_draws = m.get("n_draws", 1000)
    subtitle = (
        f"p10/p50/p90 from {n_draws} Monte Carlo draws over regression + GDP path "
        f"uncertainty (excludes structural-break risk)   |   as of {data_date}"
    )
    ax.text(
        0.5, header_y + 0.035, subtitle,
        transform=ax.transAxes, ha="center", va="bottom",
        fontsize=9, color=SUBTLE,
    )

    # Attribution + disclaimer (per AGENTS.md) at bottom
    ax.text(
        1.0, -0.02, get_attribution(8),
        transform=ax.transAxes, ha="right", va="top",
        fontsize=8, color=SUBTLE, alpha=0.7,
    )
    ax.text(
        1.0, -0.05, DISCLAIMER,
        transform=ax.transAxes, ha="right", va="top",
        fontsize=7, color=SUBTLE, alpha=0.5,
    )

    out = CHARTS_DIR / "milestones_table.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"    Saved: {out.name}")


# ── Main ─────────────────────────────────────────────────────


def main():
    skip_gifs = "--skip-gifs" in sys.argv

    print("=== Generating Charts ===\n", flush=True)

    macro_path = PROCESSED_DIR / "india_macro.csv"
    proj_path = PROCESSED_DIR / "projection.json"

    if not macro_path.exists() and not proj_path.exists():
        print("ERROR: No processed data. Run process.py and project.py first.")
        return

    chart_milestones_table()
    chart_gdp_flights_correlation()
    chart_passenger_projection()
    chart_airport_rankings()

    if skip_gifs:
        print("  Skipping GIF generation (--skip-gifs)")
    else:
        chart_airport_passenger_race()
        chart_airport_map()

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
