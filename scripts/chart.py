"""Chart generation for current India aviation passenger data.

Charts:
  1. Top Airport Rankings Over Time (static bump chart)
  2. Airport Passenger Race (animated GIF bar race)

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

BG = "#0d1117"
TEXT = "white"
SUBTLE = "#94a3b8"
GRID_COLOR = "#334155"
ACCENT_GOLD = "#fbbf24"

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
    "This is a personal open-source project. Views and analysis are my own "
    "and do not represent Flughafen Zürich AG, Noida International Airport, "
    "or any affiliated entity."
)


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
    path = PROCESSED_DIR / "metadata.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def get_attribution() -> str:
    repo = get_repo_url()
    meta = load_metadata()
    short = repo.replace("https://github.com/", "github.com/") if repo else ""
    parts = []
    if short:
        parts.append(short)
    data_str = "Data: DGCA, MoCA"
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
) -> None:
    ax.set_facecolor(BG)
    ax.set_title(
        title,
        fontsize=16,
        fontweight="bold",
        pad=25 if subtitle else 15,
        color=TEXT,
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


def add_attribution(ax, fontsize: int = 8) -> None:
    ax.text(
        1.0,
        -0.12,
        get_attribution(),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=fontsize,
        color=SUBTLE,
        alpha=0.7,
    )


def add_disclaimer(ax, fontsize: int = 7) -> None:
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


def _complete_airport_years(monthly: pd.DataFrame) -> list[int]:
    """Return years with complete domestic months and international quarters."""
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
    return sorted(set.intersection(*years_by_category))


def chart_airport_rankings() -> None:
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
        ascending=False,
        method="min",
    )
    latest_year = max(complete_years)
    latest = annual[annual["year"] == latest_year].nlargest(10, "passengers")
    top_airports = latest["airport"].tolist()
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
        if valid.empty:
            continue
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
            "Domestic + international passenger totals | Complete DGCA source years "
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


def chart_airport_passenger_race() -> None:
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
    attribution = get_attribution()

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


def main() -> None:
    skip_gifs = "--skip-gifs" in sys.argv

    print("=== Generating Charts ===\n", flush=True)

    monthly_path = PROCESSED_DIR / "airport_monthly.csv"
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"
    if not monthly_path.exists() or not yearly_path.exists():
        print("ERROR: No processed airport data. Run process.py first.")
        return

    chart_airport_rankings()

    if skip_gifs:
        print("  Skipping GIF generation (--skip-gifs)")
    else:
        chart_airport_passenger_race()

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
