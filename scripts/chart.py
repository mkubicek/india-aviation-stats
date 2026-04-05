"""Chart generation for India aviation statistics.

Three flagship charts:
  1. GDP–Flights Correlation (dual Y-axis, with projection)
  2. National Passenger Growth Projection (bar + line overlay)
  3. The Great Indian Airport Boom (animated GIF map)

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


def get_attribution(fontsize: int = 8) -> str:
    """Build attribution string for charts."""
    repo = get_repo_url()
    meta = load_metadata()
    short = repo.replace("https://github.com/", "github.com/") if repo else ""
    parts = []
    if short:
        parts.append(short)
    data_str = "Data: World Bank, Vonter/india-aviation-traffic"
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
    for spine in ax.spines.values():
        spine.set_color(GRID_COLOR)


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


# ── Chart 3: The Great Indian Airport Boom (animated GIF) ───


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


# ── Main ─────────────────────────────────────────────────────


def main():
    skip_gifs = "--skip-gifs" in sys.argv

    print("=== Generating Charts ===\n", flush=True)

    macro_path = PROCESSED_DIR / "india_macro.csv"
    proj_path = PROCESSED_DIR / "projection.json"

    if not macro_path.exists() and not proj_path.exists():
        print("ERROR: No processed data. Run process.py and project.py first.")
        return

    chart_gdp_flights_correlation()
    chart_passenger_projection()

    if skip_gifs:
        print("  Skipping GIF generation (--skip-gifs)")
    else:
        chart_airport_map()

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
