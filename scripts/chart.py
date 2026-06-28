"""Chart generation for the published canonical layers.

Charts (both sourced from Layer 1, domestic monthly):
  1. Airport Passenger Race (animated GIF bar race) — the hero.
  2. Who's Rising (airport_risers.png) — monthly ramp curves of genuine newcomer
     airports; depends on the dedup layer so it shows real new airports, never
     source-renames. Any newcomer auto-surfaces once it has rows — none special-cased.

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
    data_str = "Data: DGCA"
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



RISER_FIRST_PERIOD = pd.Period("2022-01", freq="M")  # "new" = first appeared 2022+
RISER_MIN_RECENT_PAX = 50_000   # last-12-month total to clear chart clutter
RISER_MAX_LINES = 7


def airport_label(iata: str) -> str:
    info = MAPPINGS.get("airports", {}).get(iata, {})
    city = info.get("city")
    return f"{iata} ({city})" if city else iata


def find_risers(monthly: pd.DataFrame) -> list[str]:
    """Genuine newcomer airports: canonical entities whose FIRST month of data is
    recent. Source renames are excluded for free — a renamed airport's canonical
    (e.g. IXD for Allahabad/Prayagraj) carries its full history, so its first
    month is old, not recent."""
    m = monthly.copy()
    m["period"] = pd.PeriodIndex(
        pd.to_datetime({"year": m["year"], "month": m["month"], "day": 1}), freq="M"
    )
    first = m.groupby("airport")["period"].min()
    newcomers = first[first >= RISER_FIRST_PERIOD].index
    last_period = m["period"].max()
    recent = (
        m[m["period"] > last_period - 12]
        .groupby("airport")["passengers"].sum()
    )
    qualified = [a for a in newcomers if recent.get(a, 0) >= RISER_MIN_RECENT_PAX]
    qualified.sort(key=lambda a: recent.get(a, 0), reverse=True)
    return qualified[:RISER_MAX_LINES]


def chart_airport_risers() -> None:
    """Who's rising: monthly ramp curves of genuine newcomer airports (Layer 1).

    Depends on the dedup layer: it shows physical newcomers (Mopa, Navi Mumbai,
    Ayodhya...), never source-renames (PRAYAGRAJ is Allahabad, MUMBAI MUMBAI is
    BOM — both carry old history under their canonical, so they are not new).
    Any new airport surfaces automatically the moment DGCA publishes its first
    month — no airport is special-cased; every line uses the shared palette.
    """
    print("  Generating: airport_risers.png", flush=True)

    monthly_path = PROCESSED_DIR / "airport_monthly.csv"
    if not monthly_path.exists():
        print("    WARNING: airport_monthly.csv not found, skipping", flush=True)
        return
    monthly = pd.read_csv(monthly_path)

    risers = find_risers(monthly)
    if not risers:
        print("    WARNING: no newcomer airports found, skipping", flush=True)
        return

    m = monthly.copy()
    m["period"] = pd.PeriodIndex(
        pd.to_datetime({"year": m["year"], "month": m["month"], "day": 1}), freq="M"
    )

    fig, ax = plt.subplots(figsize=(14, 8), facecolor=BG)
    for idx, airport in enumerate(risers):
        series = (
            m[m["airport"] == airport]
            .groupby("period")["passengers"].sum().sort_index()
        )
        x = [p.to_timestamp() for p in series.index]
        color = AIRPORT_COLORS.get(
            airport, FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])
        ax.plot(x, series.values / 1e3, marker="o", markersize=4,
                linewidth=2.0, color=color, zorder=3)
        last_x, last_y = x[-1], series.values[-1] / 1e3
        ax.annotate(f"  {airport_label(airport)}", (last_x, last_y),
                    fontsize=9, fontweight="bold", color=color, va="center", clip_on=False)

    style_chart(
        ax,
        "Who's Rising: India's Newcomer Airports",
        subtitle="Monthly domestic passengers since each airport's first DGCA data "
                 "(genuine new airports, not source-renames) | Source: Layer 1",
        ylabel="Passengers per month (thousands)",
    )
    ax.set_xlabel("")
    ax.grid(axis="y", alpha=0.2, color=GRID_COLOR, linestyle="--")
    add_attribution(ax)

    fig.tight_layout()
    out = CHARTS_DIR / "airport_risers.png"
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    print(f"    Saved: {out.name} ({len(risers)} newcomers: {', '.join(risers)})")


def _domestic_trailing_airport_passengers(
    monthly: pd.DataFrame,
    window: int = 12,
) -> pd.DataFrame:
    """Return complete rolling domestic passenger totals by airport-month.

    Layer 1 is domestic-only, so every row counts (no category filter).
    """
    domestic = monthly.copy()
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
    if not monthly_path.exists():
        print("ERROR: No processed airport data. Run clean.py first.")
        return

    chart_airport_risers()

    if skip_gifs:
        print("  Skipping GIF generation (--skip-gifs)")
    else:
        chart_airport_passenger_race()

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
