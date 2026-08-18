"""Noida International Airport (DXN) focus page: charts + noida.html.

Generates the Noida chart set into charts/noida/ and writes noida.html.
Every title and annotation is computed from the published tables; charts whose
inputs are not yet published (the route layer, DXN airport rows) are skipped
and appear automatically once the data lands.

Run: uv run python scripts/noida.py
"""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

import chart as c

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "charts" / "noida"
ROUTE_MONTHLY_PATH = ROOT / "data" / "processed" / "domestic_route_monthly.csv"
PAGE_PATH = ROOT / "noida.html"

# The three observed Indian dual-airport-system newcomers; DXN joins the ramp
# benchmark automatically once it has published airport rows.
ANALOGUES = ["GOX", "NMIA", "HDO"]
NEWCOMER = "DXN"
NCR_AIRPORTS = ["DEL", "HDO", "DXN"]
MMR_AIRPORTS = ["BOM", "NMIA"]
RAMP_WINDOW = 24
MENU_TOP_N = 15
TRUNK_TOP_N = 50
# Comparison horizon for the indexed supply/incumbent/catchment exhibits:
# 36 trailing-12M points = a three-year growth read.
INDEX_WINDOW_MONTHS = 36
UP_EMPHASIS_N = 2

# Numbers that the page's "tested and rejected" register cites. Chart functions
# deposit their computed stats here so the register can never drift from what
# the exhibits themselves show; an entry missing (chart skipped) drops the
# register line rather than showing a stale number.
REGISTER: dict[str, dict] = {}

# Fixed entity hues come from mappings.yaml (airport_colors) so every chart
# and page shows the same airport in the same colour. stable_color() keeps a
# missing mapping entry from killing the whole refresh at import time.
SERIES = {
    code: c.AIRPORT_COLORS.get(code) or c.stable_color(code)
    for code in ["DXN", "GOX", "NMIA", "HDO", "BOM"]
}

LINE = dict(linewidth=2.2, solid_capstyle="round", solid_joinstyle="round")
MARK = dict(marker="o", markersize=5.5, markeredgewidth=1.2, markeredgecolor=c.BG)


def save(fig: plt.Figure, chart_id: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{chart_id}.png"
    fig.savefig(
        path,
        dpi=c.DPI,
        facecolor=c.BG,
        edgecolor=c.BG,
        metadata={
            "Title": chart_id,
            "Author": "india-aviation-stats",
            "Source": "DGCA public aviation statistics",
        },
    )
    plt.close(fig)
    return path


def month_series(monthly: pd.DataFrame, airport: str) -> pd.Series:
    m = c.add_month_period(monthly)
    s = m[m["airport"] == airport].groupby("period")["passengers"].sum().sort_index()
    return s


def t12_series(monthly: pd.DataFrame, airport: str) -> pd.Series | None:
    """Gap-honest trailing 12-month throughput: the airport's observed months
    reindexed to their calendar range, so any unpublished month voids every
    window that spans it (NaN breaks the plotted line, nothing is zero-filled).
    """
    s = month_series(monthly, airport)
    if s.empty:
        return None
    full = pd.period_range(s.index.min(), s.index.max(), freq="M")
    return s.reindex(full).rolling(12, min_periods=12).sum()


def new_fig() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=c.FIGSIZE_WIDE, facecolor=c.BG)
    return fig, ax


def clip_xticks_to_data(ax, xmax_num: float) -> None:
    """Drop x-ticks that fall in the label margin beyond the last data point,
    so the padding added for end labels never fabricates an empty period.
    Ticks outside the left limit are dropped too: keeping them in the fixed
    tick list would re-expand the axis into an empty pre-data region."""
    xmin, _ = ax.get_xlim()
    ax.set_xticks([t for t in ax.get_xticks() if xmin <= t <= xmax_num])


def fmt_mixed_scale(x, pos=None) -> str:
    if x == 0:
        return "0"
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:g}M"
    return f"{x / 1_000:.0f}K"


def pct_phrase(value: float, *, flat_band: float = 0.05) -> str:
    """Sign-correct growth phrase: 'grew +X%', 'fell X%', or 'was flat'."""
    if value >= flat_band:
        return f"grew {value:+.1f}%"
    if value <= -flat_band:
        return f"fell {abs(value):.1f}%"
    return f"was flat ({value:+.1f}%)"


def moved_phrase(value: float) -> str:
    """Direction-neutral one-word rendering for titles: '+22%' or '-3%'."""
    return f"{value:+.0f}%"


def year_word(n: int) -> str:
    return f"{n} year" if n == 1 else f"{n} years"


def label_scale(value: float) -> str:
    return f"{value / 1e6:.1f}M" if value >= 1e6 else f"{value / 1e3:.0f}K"


# ---------------------------------------------------------------------------
# Exhibits
# ---------------------------------------------------------------------------

def ramp_window_series(monthly: pd.DataFrame, airport: str) -> pd.Series | None:
    """First RAMP_WINDOW calendar months, NaN where no month was published."""
    s = month_series(monthly, airport)
    if s.empty:
        return None
    first = s.index[0]
    full = pd.period_range(first, first + RAMP_WINDOW - 1, freq="M")
    return s.reindex(full)


def chart_ramp_benchmark(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    fig, ax = new_fig()
    series: dict[str, pd.Series] = {}
    for airport in ANALOGUES + [NEWCOMER]:
        s = ramp_window_series(monthly, airport)
        if s is not None:
            series[airport] = s
    if not any(a in series for a in ANALOGUES):
        plt.close(fig)
        return None

    latest_period = c.add_month_period(monthly)["period"].max()
    x = np.arange(1, RAMP_WINDOW + 1)
    clauses: list[tuple[float, str]] = []
    # The newcomer is drawn by the same loop, with the same line style, label and
    # computed clause as its analogues: AGENTS.md forbids gilding any airport,
    # and a focus page's subject is not an exception.
    for airport in ANALOGUES + [NEWCOMER]:
        if airport not in series:
            continue
        s = series[airport]
        observed = s.dropna()
        last_pos = int(s.index.get_loc(observed.index[-1])) + 1
        window_open = s.index[-1] > latest_period
        label = c.airport_label(airport)
        if window_open:
            label += f" ({last_pos} months so far)"
        ax.plot(x, s.values, color=SERIES[airport], **LINE)
        ax.annotate(
            label,
            (last_pos, float(observed.iloc[-1])),
            xytext=(7, 0),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
        peak = float(observed.max())
        if peak < 10_000:
            clauses.append((peak, f"{airport} under {math.ceil(peak / 1000)}K throughout"))
        else:
            clauses.append(
                (float(observed.iloc[-1]),
                 f"{airport} at {label_scale(float(observed.iloc[-1]))} by month {last_pos}")
            )

    title = "Newcomer ramp-ups: " + "; ".join(
        text for _, text in sorted(clauses, key=lambda item: -item[0])
    )
    windows = ", ".join(
        f"{a} from {series[a].index[0].strftime('%b %Y')}"
        for a in ANALOGUES + [NEWCOMER]
        if a in series
    )
    c.style_axis(
        ax,
        title,
        f"Monthly airport passenger movements in each airport's first {RAMP_WINDOW} calendar months"
        f" · windows: {windows}",
        "Airport passenger movements",
    )
    ax.set_xlabel("Months since first DGCA-observed month", color=c.SUBTLE, fontsize=11)
    ax.set_xlim(0.5, RAMP_WINDOW + 5.5)
    ax.set_xticks([1, 6, 12, 18, 24])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_thousands))
    handles = [
        plt.Line2D([], [], color=SERIES[a], lw=2.2, label=c.airport_label(a))
        for a in ANALOGUES + [NEWCOMER]
        if a in series
    ]
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9, labelcolor=c.SUBTLE)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="A first observed month may be partial (mid-month opening); months with no published DGCA row appear as line gaps. Analogues differ in catchment, era, and operating model; they bound plausibility, they do not predict.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.15)
    save(fig, "noida_ramp_benchmark")
    return "noida_ramp_benchmark"


def chart_nmia_tracker(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    nmia = month_series(monthly, "NMIA")
    bom = month_series(monthly, "BOM")
    if nmia.empty:
        return None
    # Calendar reindex: a missing month breaks the line and never produces a
    # cross-gap "step"; the month count is calendar months since opening.
    full_range = pd.period_range(nmia.index.min(), nmia.index.max(), freq="M")
    share = (nmia / (nmia + bom)).reindex(full_range) * 100
    observed = share.dropna()
    if observed.empty:
        return None

    fig, ax = new_fig()
    x = np.arange(len(share))
    ax.plot(x, share.values, color=c.PRIMARY, **LINE, **MARK)
    for period in (observed.index[0], observed.index[-1]):
        ax.annotate(
            f"{share.loc[period]:.1f}%",
            (int(share.index.get_loc(period)), share.loc[period]),
            xytext=(0, 11),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
        )
    steps = share.diff().dropna()
    if not steps.empty:
        jump_period = steps.idxmax()
        jump_idx = int(share.index.get_loc(jump_period))
        ax.annotate(
            f"{steps.max():+.1f} pp in {jump_period.strftime('%b %Y')}",
            (jump_idx, share.loc[jump_period]),
            xytext=(-12, 26),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="right",
            arrowprops={"arrowstyle": "-", "color": c.MUTED, "lw": 0.8},
        )

    c.style_axis(
        ax,
        f"Navi Mumbai holds {observed.iloc[-1]:.1f}% of Mumbai's two-airport traffic "
        f"after {len(share)} months",
        "NMIA share of combined NMIA + BOM airport passenger movements, by month since opening",
        "Share of Mumbai-system throughput",
    )
    ax.set_xticks(x)
    ax.set_xticklabels([p.strftime("%b %Y") for p in share.index], fontsize=9)
    upper = max(20.0, float(share.max()) * 1.25)
    ax.set_ylim(0, upper)
    ax.set_yticks(np.arange(0, upper + 0.1, 5))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Share steps reflect airlines moving capacity in blocks. Observational, not a Noida forecast.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_nmia_tracker")
    return "noida_nmia_tracker"


def chart_airline_groups(carrier: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    groups = c.MAPPINGS.get("airline_groups_retrospective", {}) or {}
    group_order = [g for g in ("IndiGo", "Air India Group") if g in groups]
    if len(group_order) < 2:
        return None
    sd = carrier[carrier["service_type"] == "scheduled_domestic"]
    years = sorted(sd["year"].unique())
    complete = [y for y in years if sd[sd["year"] == y]["month"].nunique() == 12]
    if len(complete) < 2:
        return None
    span = list(range(complete[0], complete[-1] + 1))
    excluded = [y for y in span if y not in complete]

    shares: dict[str, dict[int, float]] = {g: {} for g in group_order}
    # Case-insensitive label matching: DGCA capitalisation drifts (e.g.
    # "Air India (Erstwhile Vistara)") and an exact-string miss would silently
    # zero a group.
    lowered = {g: {m.lower() for m in groups[g]} for g in group_order}
    airline_lower = sd["airline"].str.lower()
    for y in complete:
        year_mask = sd["year"] == y
        total = sd.loc[year_mask, "passengers"].sum()
        for g in group_order:
            member = sd.loc[year_mask & airline_lower.isin(lowered[g]), "passengers"].sum()
            shares[g][y] = member / total * 100 if total else np.nan
    # A major group matching nothing means the mapping broke, not that the
    # group vanished; refuse to publish a false duopoly-collapse chart.
    if any(shares[g][complete[-1]] < 1 for g in group_order):
        print("  Skipped noida_airline_groups: a group matched (almost) no rows; check airline_groups_retrospective", flush=True)
        return None

    fig, ax = new_fig()
    colors = c.MAPPINGS.get("airline_colors", {}) or {}
    last_values = {g: shares[g][complete[-1]] for g in group_order}
    crowded = abs(last_values[group_order[0]] - last_values[group_order[1]]) < 6
    for i, g in enumerate(group_order):
        color = colors.get(g, c.PRIMARY)
        plot_y = [shares[g].get(y, np.nan) for y in span]  # gaps break the line
        ax.plot(span, plot_y, color=color, **LINE, **MARK)
        last = shares[g][complete[-1]]
        offset_y = 0 if not crowded else (8 if i == 0 else -8)
        ax.annotate(
            f"{g}  {last:.0f}%",
            (complete[-1], last),
            xytext=(8, offset_y),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
        ax.annotate(
            f"{shares[g][complete[0]]:.0f}%",
            (complete[0], shares[g][complete[0]]),
            xytext=(0, 12),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
        )

    # The headline sums the ROUNDED endpoint labels so the visible arithmetic
    # always reconciles with the two on-chart numbers.
    combined_last = sum(round(shares[g][complete[-1]]) for g in group_order)
    combined_first = sum(round(shares[g][complete[0]]) for g in group_order)
    REGISTER["duopoly"] = dict(
        combined=combined_last,
        combined_first=combined_first,
        first_year=complete[0],
        last_year=complete[-1],
    )
    observed = set(sd["airline"].unique())
    ai_members = [m for m in groups["Air India Group"] if m.lower() in {o.lower() for o in observed}]
    subtitle = (
        "Share of scheduled domestic passengers carried, complete calendar years"
        " · groups consolidated retrospectively as constituted today"
    )
    if excluded:
        subtitle += " · omitted as incomplete: " + ", ".join(str(y) for y in excluded)
    c.style_axis(
        ax,
        f"IndiGo and the Air India group carried {combined_last:.0f}% of domestic "
        f"passengers in {complete[-1]} (was {combined_first:.0f}% in {complete[0]})",
        subtitle,
        "Share of passengers carried",
    )
    ax.set_xticks(span)
    ax.set_xlim(span[0] - 0.4, span[-1] + 2.2)
    ax.set_ylim(0, max(80.0, max(last_values.values()) + 15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat=f"Air India group = {', '.join(ai_members)}, today's membership applied across the full window; DGCA does not publish airline traffic per airport.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_airline_groups")
    return "noida_airline_groups"


def chart_growth_pause(carrier: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    national, t12, _, t12_yoy = c.domestic_demand_series(carrier)
    t12_clean = t12.dropna()
    if len(t12_clean) < 24:
        return None
    latest_yoy = float(t12_yoy.dropna().iloc[-1] * 100)
    span_years = min(10, (len(t12_clean) - 1) // 12)
    base = float(t12_clean.iloc[-(span_years * 12) - 1])
    trend = (float(t12_clean.iloc[-1]) / base) ** (1 / span_years) - 1 if base > 0 else np.nan

    fig, ax = new_fig()
    x = t12_clean.index.to_timestamp()
    ax.plot(x, t12_clean.values, color=c.PRIMARY, **LINE)
    ax.fill_between(x, t12_clean.values, color=c.PRIMARY, alpha=0.10, linewidth=0)
    ax.plot([x[-1]], [float(t12_clean.iloc[-1])], **MARK, color=c.PRIMARY, linestyle="none")
    ax.annotate(
        f"{t12_clean.iloc[-1] / 1e6:.0f}M\n{latest_yoy:+.1f}% vs prior year",
        (mdates.date2num(x[-1]), float(t12_clean.iloc[-1])),
        xytext=(10, -4),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        va="top",
    )
    # The title's trend claim, drawn: where the last 12 months would have landed
    # had they compounded at the long-run rate. Computed from the plotted series.
    if np.isfinite(trend):
        anchor = float(t12_clean.iloc[-13])
        trend_end = anchor * (1 + trend)
        ax.plot(
            [x[-13], x[-1]],
            [anchor, trend_end],
            color=c.MUTED,
            linewidth=1.4,
            solid_capstyle="round",
        )
        above = trend_end >= float(t12_clean.iloc[-1])
        ax.annotate(
            f"Path at the {span_years}-year trend ({trend * 100:+.1f}%/yr)",
            (mdates.date2num(x[-1]), trend_end),
            xytext=(-6, 6 if above else -6),
            textcoords="offset points",
            fontsize=8.5,
            color=c.TEXT,
            va="bottom" if above else "top",
            ha="right",
        )
    c.style_axis(
        ax,
        f"India's domestic market {pct_phrase(latest_yoy)} in the latest 12 months, "
        f"against a {trend * 100:.1f}%-a-year {span_years}-year trend",
        "Scheduled domestic passengers carried, trailing 12-month total, counted once "
        f"per journey; trend = compound annual growth over the trailing {span_years} years",
        "Trailing 12-month passengers carried",
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_millions))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=16))
    clip_xticks_to_data(ax, mdates.date2num(x.max()))
    ax.set_ylim(0, c.clean_upper_bound(float(t12_clean.max()) * 1.1))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="The data cannot distinguish a cyclical pause from a structural slowdown; early Noida traffic reads against this baseline.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_growth_pause")
    return "noida_growth_pause"


def chart_supply_demand(carrier: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    from metrics import KNOWN_ZERO_MONTHS

    sd = c.add_month_period(carrier[carrier["service_type"] == "scheduled_domestic"])
    by_month = (
        sd.groupby("period")[["passengers", "seat_km", "passenger_km"]].sum().sort_index()
    )
    full = pd.period_range(by_month.index.min(), by_month.index.max(), freq="M")
    by_month = by_month.reindex(full)
    for period in KNOWN_ZERO_MONTHS:
        if period in by_month.index and by_month.loc[period].isna().all():
            by_month.loc[period] = 0
    if by_month.isna().any().any():
        # An unpublished month that is not a documented zero: refuse to plot
        # windows that would silently read it as a collapse.
        print("  Skipped noida_supply_demand: carrier months missing beyond known zeros", flush=True)
        return None
    t12 = by_month.rolling(12, min_periods=12).sum().dropna()
    if len(t12) < INDEX_WINDOW_MONTHS + 1:
        return None
    window = t12.iloc[-(INDEX_WINDOW_MONTHS + 1):]
    base = window.iloc[0]
    anchor = t12.iloc[-13]
    if min(float(base["seat_km"]), float(base["passenger_km"]), float(base["passengers"])) <= 0:
        return None
    if min(float(anchor["seat_km"]), float(anchor["passenger_km"]), float(anchor["passengers"])) <= 0:
        return None
    # Like-for-like: both series are distance-weighted, so their ratio IS the
    # load factor shown in the panel. Passenger headcount is quoted alongside.
    ask_idx = window["seat_km"] / float(base["seat_km"]) * 100
    rpk_idx = window["passenger_km"] / float(base["passenger_km"]) * 100
    ask_g = float(ask_idx.iloc[-1]) - 100
    rpk_g = float(rpk_idx.iloc[-1]) - 100
    pax_g = (float(window["passengers"].iloc[-1]) / float(base["passengers"]) - 1) * 100
    plf = t12["passenger_km"] / t12["seat_km"] * 100
    plf_now = float(plf.iloc[-1])
    plf_peak = float(plf.max())
    plf_peak_period = plf.idxmax()
    ask_yoy = (float(t12["seat_km"].iloc[-1]) / float(anchor["seat_km"]) - 1) * 100
    rpk_yoy = (float(t12["passenger_km"].iloc[-1]) / float(anchor["passenger_km"]) - 1) * 100
    REGISTER["supply"] = dict(ask_yoy=ask_yoy, rpk_yoy=rpk_yoy)

    fig, ax = new_fig()
    x = window.index.to_timestamp()
    series = [
        ("Seat-km capacity", ask_idx, "#eb6834"),
        ("Passenger-km demand", rpk_idx, c.PRIMARY),
    ]
    crowded = abs(float(ask_idx.iloc[-1]) - float(rpk_idx.iloc[-1])) < 2
    for i, (label, values, color) in enumerate(series):
        ax.plot(x, values.values, color=color, **LINE)
        higher = float(values.iloc[-1]) >= float(series[1 - i][1].iloc[-1])
        offset_y = 0 if not crowded else (8 if higher else -8)
        ax.annotate(
            f"{label}  {float(values.iloc[-1]) - 100:+.0f}%",
            (mdates.date2num(x[-1]), float(values.iloc[-1])),
            xytext=(8, offset_y),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
    ax.axhline(100, color=c.BASELINE, linewidth=1)
    base_label = window.index[0].strftime("%b %Y")
    end_label = window.index[-1].strftime("%b %Y")
    c.style_axis(
        ax,
        f"Domestic seat-km capacity moved {moved_phrase(ask_g)} in three years; "
        f"passenger-km demand {moved_phrase(rpk_g)}",
        f"Scheduled domestic trailing-12-month totals, indexed to 100 in {base_label}, "
        f"through {end_label}; both series are distance-weighted",
        f"Index (100 = {base_label})",
    )
    ax.text(
        0.985,
        0.06,
        f"Trailing-12M passenger load factor: {plf_now:.1f}% (ratio of the plotted series)\n"
        f"Peak since {plf.index[0].strftime('%b %Y')}: {plf_peak:.1f}% in {plf_peak_period.strftime('%b %Y')}",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        color=c.TEXT,
        linespacing=1.5,
        bbox={
            "boxstyle": "round,pad=0.45",
            "facecolor": c.PANEL_BG,
            "edgecolor": c.GRID,
            "alpha": 0.92,
        },
    )
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=11))
    clip_xticks_to_data(ax, mdates.date2num(x.max()))
    low = min(98.0, float(min(rpk_idx.min(), ask_idx.min())) - 2)
    high = float(max(rpk_idx.max(), ask_idx.max())) + 5
    ax.set_ylim(low, high)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat=f"Both series weight by distance; passenger journeys moved {moved_phrase(pax_g)} on the same window. The data cannot show whether capacity followed demand or constrained it.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_supply_demand")
    return "noida_supply_demand"


# Candidate floor for the white-space test: annual route passenger movements
# an airport must show (across all its pairs) to count as a market an airline
# demonstrably serves. Disclosed in the register sentence.
WHITE_SPACE_FLOOR = 100_000
# DEL's observed market count is the test's baseline; below this the baseline
# itself is broken (DEL serves ~90 markets), so no verdict is published.
WHITE_SPACE_MIN_DEL_MARKETS = 30


def white_space_stats(routes: pd.DataFrame) -> None:
    """Deposit the white-space test result: domestic airports above the floor
    with no observed DEL route in the latest 12 contiguous months.

    Tests the claim "Noida opens into empty white space no airline serves":
    if every meaningful domestic market already appears in Delhi's observed
    menu, a Noida network is competition for served demand, not white space.
    NCR airports are excluded as candidates (no self-routes by definition).
    """
    periods = sorted(routes["period"].unique())
    if len(periods) < 12:
        return
    window = list(pd.period_range(periods[-12], periods[-1], freq="M"))
    if periods[-12:] != window:
        return
    w = routes[routes["period"].isin(window)]
    vol = (
        w.groupby("origin")["passengers"].sum()
        .add(w.groupby("destination")["passengers"].sum(), fill_value=0)
    )
    candidates = vol[vol >= WHITE_SPACE_FLOOR].drop(labels=NCR_AIRPORTS, errors="ignore")
    # A published row with zero passengers all window is not a served market.
    del_rows = w[((w["origin"] == "DEL") | (w["destination"] == "DEL")) & (w["passengers"] > 0)]
    del_partners = set(np.where(del_rows["origin"] == "DEL", del_rows["destination"], del_rows["origin"]))
    # Sanity floor: DEL serves ~90 markets. A collapsed baseline means DEL's
    # rows are missing or relabelled, not that the country lost its Delhi
    # routes; publishing a verdict off that would be absurd. Same for an empty
    # candidate set, which would make the claim vacuously "rejected".
    if len(del_partners) < WHITE_SPACE_MIN_DEL_MARKETS or candidates.empty:
        print(f"  Skipped white-space verdict: {len(del_partners)} DEL markets, "
              f"{len(candidates)} candidates (baseline implausible)", flush=True)
        return
    white = candidates.drop(labels=sorted(del_partners), errors="ignore").sort_values(ascending=False)
    REGISTER["white_space"] = dict(
        floor=WHITE_SPACE_FLOOR,
        n_candidates=int(len(candidates)),
        n_del_markets=int(len(del_partners)),
        n_white=int(len(white)),
        top_white=(white.index[0], float(white.iloc[0])) if len(white) else None,
        window=f"{window[0].strftime('%b %Y')}-{window[-1].strftime('%b %Y')}",
    )


def load_routes() -> pd.DataFrame | None:
    if not ROUTE_MONTHLY_PATH.exists():
        return None
    r = pd.read_csv(ROUTE_MONTHLY_PATH)
    r["period"] = pd.PeriodIndex(
        pd.to_datetime(r["year"].astype(str) + "-" + r["month"].astype(str).str.zfill(2)),
        freq="M",
    )
    r["a"] = r[["origin", "destination"]].min(axis=1)
    r["b"] = r[["origin", "destination"]].max(axis=1)
    return r


def chart_beyond_trunk(routes: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    years = sorted(routes["year"].unique())
    complete = [y for y in years if routes[routes["year"] == y]["month"].nunique() == 12]
    if len(complete) < 2:
        return None
    shares = []
    for y in complete:
        annual = routes[routes["year"] == y].groupby(["a", "b"])["passengers"].sum()
        top = annual.sort_values(ascending=False).head(TRUNK_TOP_N).sum()
        shares.append((1 - top / annual.sum()) * 100 if annual.sum() else np.nan)

    fig, ax = new_fig()
    ax.plot(complete, shares, color=c.PRIMARY, **LINE, **MARK)
    for i in (0, len(complete) - 1):
        ax.annotate(
            f"{shares[i]:.0f}%",
            (complete[i], shares[i]),
            xytext=(0, 12),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
        )
    c.style_axis(
        ax,
        f"{shares[-1]:.0f}% of domestic flying is outside the top-{TRUNK_TOP_N} routes "
        f"(was {shares[0]:.0f}% in {complete[0]})",
        f"Share of domestic route passengers on city pairs outside each year's {TRUNK_TOP_N} busiest, complete years",
        "Share of route passengers",
    )
    ax.set_xticks(complete)
    ax.set_ylim(0, max(60.0, max(shares) * 1.15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="A structural shift in demand geography; it does not by itself establish which off-trunk routes are viable from any airport.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_beyond_trunk")
    return "noida_beyond_trunk"


def chart_delhi_menu(routes: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    periods = sorted(routes["period"].unique())
    if len(periods) < 24:
        return None
    expected = list(pd.period_range(periods[-24], periods[-1], freq="M"))
    if periods[-24:] != expected:
        print("  Skipped noida_delhi_menu: route months are not contiguous", flush=True)
        return None
    latest = periods[-12:]
    prior = periods[-24:-12]

    def market_vol(window: list[pd.Period]) -> pd.Series:
        w = routes[routes["period"].isin(window)]
        w = w[(w["a"] == "DEL") | (w["b"] == "DEL")]
        other = np.where(w["a"] == "DEL", w["b"], w["a"])
        return w.assign(other=other).groupby("other")["passengers"].sum()

    mv_l, mv_p = market_vol(latest), market_vol(prior)
    top = mv_l.sort_values(ascending=False).head(MENU_TOP_N)
    if top.empty:
        return None
    yoy = {m: (mv_l[m] / mv_p[m] - 1) * 100 for m in top.index if mv_p.get(m, 0) > 0}

    fig = plt.figure(figsize=c.FIGSIZE_WIDE, facecolor=c.BG)
    ax = fig.add_axes((0.17, 0.13, 0.74, 0.66))
    ax.set_facecolor(c.BG)
    ypos = np.arange(len(top))[::-1]

    def market_class(m: str) -> str:
        g = yoy.get(m)
        if g is None:
            return c.DEEMPH  # no prior-year base: growth undefined, not "flat"
        return c.POSITIVE if g >= 1 else c.NEGATIVE if g <= -1 else c.DEEMPH

    colors = [market_class(m) for m in top.index]
    ax.barh(ypos, top.values, height=0.62, color=colors)
    for yp, market, value in zip(ypos, top.index, top.values):
        growth = yoy.get(market)
        growth_txt = f"   {growth:+.0f}%" if growth is not None else ""
        ax.annotate(
            f"{value / 1e6:.1f}M{growth_txt}",
            (value, yp),
            xytext=(6, 0),
            textcoords="offset points",
            fontsize=9,
            color=c.SUBTLE,
            va="center",
        )
    grower = max(yoy, key=yoy.get) if yoy else None
    title = f"Delhi's {len(top)} largest route markets"
    if grower is not None:
        best = yoy[grower]
        if best >= 0.5:
            title += f": {c.airport_label(grower)} grew fastest ({best:+.0f}%)"
        elif best > -0.5:
            title += f": the fastest ({c.airport_label(grower)}) was flat"
        else:
            title += ": every market with a prior-year base declined"
    ax.set_title(title, fontsize=16, fontweight="bold", color=c.TITLE, loc="left", pad=26)
    ax.text(
        0.0,
        1.012,
        "Bidirectional DEL city-pair passengers, "
        f"{latest[0].strftime('%b %Y')}–{latest[-1].strftime('%b %Y')} vs "
        f"{prior[0].strftime('%b %Y')}–{prior[-1].strftime('%b %Y')}"
        f" · top {len(top)} of {mv_l.index.nunique()} observed markets",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.5,
        color=c.SUBTLE,
    )
    ax.set_yticks(ypos)
    ax.set_yticklabels([c.airport_label(m) for m in top.index], fontsize=9.5, color=c.TEXT)
    ax.tick_params(colors=c.SUBTLE, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(c.BASELINE)
    ax.grid(axis="x", color=c.GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_millions))
    ax.set_xlim(0, float(top.max()) * 1.18)
    handles = [
        plt.Line2D([], [], marker="s", linestyle="none", markersize=9, color=col, label=lab)
        for col, lab in (
            (c.POSITIVE, "Growing (≥ +1%)"),
            (c.DEEMPH, "Flat or no prior-year base"),
            (c.NEGATIVE, "Declining (≤ −1%)"),
        )
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=9, labelcolor=c.SUBTLE)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Delhi (DEL) is an observable NCR proxy: a research queue, not a Noida forecast or route recommendation.",
    )
    save(fig, "noida_delhi_menu")
    return "noida_delhi_menu"


def chart_ncr_vs_mmr(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    m = c.add_month_period(monthly)
    complete = c.complete_calendar_years(monthly)
    if len(complete) < 2:
        return None

    def regional(codes: list[str]) -> list[float]:
        return [
            float(m[(m["year"] == y) & m["airport"].isin(codes)]["passengers"].sum()) / 1e6
            for y in complete
        ]

    ncr, mmr = regional(NCR_AIRPORTS), regional(MMR_AIRPORTS)
    fig, ax = new_fig()
    for values, color, label in ((ncr, c.PRIMARY, "Delhi region"), (mmr, "#eb6834", "Mumbai region")):
        ax.plot(complete, values, color=color, **LINE, **MARK)
        ax.annotate(
            f"{label}  {values[-1]:.0f}M",
            (complete[-1], values[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
    # Name only members with published rows; a defined member without rows is
    # disclosed as absent instead of silently reading as part of the sum.
    published = set(m["airport"].unique())
    ncr_present = [a for a in NCR_AIRPORTS if a in published]
    mmr_present = [a for a in MMR_AIRPORTS if a in published]
    missing = [a for a in NCR_AIRPORTS + MMR_AIRPORTS if a not in published]
    subtitle = (
        f"Annual domestic airport throughput by region: {'+'.join(ncr_present)} vs "
        f"{'+'.join(mmr_present)}, complete years"
    )
    if missing:
        subtitle += f" · no published rows yet: {', '.join(missing)}"
    c.style_axis(
        ax,
        f"Delhi-region airports handled {ncr[-1]:.0f}M passenger movements in {complete[-1]}; "
        f"Mumbai-region {mmr[-1]:.0f}M",
        subtitle,
        "Annual airport passenger movements",
    )
    ax.set_xticks(complete)
    ax.set_xlim(complete[0] - 0.4, complete[-1] + 1.9)
    ax.set_ylim(0, c.clean_upper_bound(max(max(ncr), max(mmr)) * 1.12))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}M")
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Airport throughput (arrivals + departures), not unique passengers. A complete year is national; an individual airport may have fewer published rows in it.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_ncr_vs_mmr")
    return "noida_ncr_vs_mmr"


def chart_del_vs_rest(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    pivot = c.domestic_airport_month_matrix(monthly)
    t12 = c.complete_rolling_sum(pivot, 12)
    if t12.empty or "DEL" not in t12.columns or len(t12) < INDEX_WINDOW_MONTHS + 1:
        return None
    base_row = t12.iloc[-(INDEX_WINDOW_MONTHS + 1)].drop("DEL")
    latest_row = t12.iloc[-1].drop("DEL")
    # Tripwire: a large airport whose rows stop publishing would read as a
    # national collapse under the matrix's zero-fill. Refuse to plot that.
    large_dormant = sorted(base_row.index[(base_row > 1_000_000) & (latest_row <= 0)])
    if large_dormant:
        print(f"  Skipped noida_del_vs_rest: large airports without current rows: {', '.join(large_dormant)}", flush=True)
        return None
    del_t12 = t12["DEL"]
    rest_t12 = t12.drop(columns=["DEL"]).sum(axis=1)
    window = slice(-(INDEX_WINDOW_MONTHS + 1), None)
    del_w, rest_w = del_t12.iloc[window], rest_t12.iloc[window]
    if float(del_w.iloc[0]) <= 0 or float(rest_w.iloc[0]) <= 0:
        return None
    del_idx = del_w / float(del_w.iloc[0]) * 100
    rest_idx = rest_w / float(rest_w.iloc[0]) * 100
    del_g = float(del_idx.iloc[-1]) - 100
    rest_g = float(rest_idx.iloc[-1]) - 100
    n_base = int((base_row > 0).sum())
    n_latest = int((latest_row > 0).sum())
    entrants = base_row.index[(base_row <= 0) & (latest_row > 0)]
    entrant_vol = float(latest_row[entrants].sum())

    fig, ax = new_fig()
    x = del_idx.index.to_timestamp()
    series = [
        (f"All other airports  {rest_g:+.1f}%", rest_idx, "#eb6834"),
        (f"{c.airport_label('DEL')}  {del_g:+.1f}%", del_idx, c.AIRPORT_COLORS["DEL"]),
    ]
    for label, values, color in series:
        ax.plot(x, values.values, color=color, **LINE)
        ax.annotate(
            label,
            (mdates.date2num(x[-1]), float(values.iloc[-1])),
            xytext=(8, 0),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
    ax.axhline(100, color=c.BASELINE, linewidth=1)
    base_label = del_idx.index[0].strftime("%b %Y")
    end_label = del_idx.index[-1].strftime("%b %Y")
    c.style_axis(
        ax,
        f"DEL {pct_phrase(del_g)} in three years; the rest of India's airports "
        f"{pct_phrase(rest_g)}",
        "Trailing-12-month domestic airport passenger movements, indexed to 100 in "
        f"{base_label}, through {end_label}; DEL vs all other airports combined "
        f"({n_base} with traffic at the base, {n_latest} at the latest)",
        f"Index (100 = {base_label})",
    )
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=11))
    clip_xticks_to_data(ax, mdates.date2num(x.max()))
    low = min(98.0, float(min(del_idx.min(), rest_idx.min())) - 2)
    high = float(max(del_idx.max(), rest_idx.max())) + 5
    ax.set_ylim(low, high)
    caveat = "Throughput, not capacity: the data cannot attribute DEL's pace to demand or to slot and terminal limits."
    if len(entrants) > 0 and entrant_vol > 0:
        caveat += (
            f" {len(entrants)} airports entered service inside the window and "
            f"contribute {entrant_vol / 1e6:.1f}M of the rest-of-India growth."
        )
    c.add_footer(fig, coverage=coverage, fingerprint=fingerprint, caveat=caveat)
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_del_vs_rest")
    return "noida_del_vs_rest"


def chart_del_international(quarterly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    pivot = c.international_airport_quarter_matrix(quarterly)
    t4 = c.complete_rolling_sum(pivot, 4)
    if t4.empty or "DEL" not in t4.columns or len(t4) < 5:
        return None
    total = t4.sum(axis=1)
    share = t4["DEL"] / total.where(total > 0) * 100
    share = share.dropna()
    if len(share) < 5:
        return None
    latest_share = float(share.iloc[-1])
    latest_vol = float(t4["DEL"].iloc[-1])
    latest_quarter = t4.index[-1]
    is_largest = float(t4.iloc[-1].drop("DEL").max()) < float(t4.iloc[-1]["DEL"])

    fig, ax = new_fig()
    x = share.index.to_timestamp()
    ax.plot(x, share.values, color=c.AIRPORT_COLORS["DEL"], **LINE)
    ax.plot([x[-1]], [latest_share], **MARK, color=c.AIRPORT_COLORS["DEL"], linestyle="none")
    ax.annotate(
        f"{latest_share:.0f}%\n{latest_vol / 1e6:.1f}M in the 4 quarters to {latest_quarter}",
        (mdates.date2num(x[-1]), latest_share),
        xytext=(-2, -10),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        va="top",
        ha="right",
    )
    ax.annotate(
        f"{float(share.iloc[0]):.0f}%",
        (mdates.date2num(x[0]), float(share.iloc[0])),
        xytext=(0, 12),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        ha="center",
    )
    peak_quarter = share.idxmax()
    if peak_quarter not in (share.index[0], share.index[-1]):
        ax.annotate(
            f"peak {float(share.max()):.1f}% in {peak_quarter}",
            (mdates.date2num(peak_quarter.to_timestamp()), float(share.max())),
            xytext=(0, 10),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
        )
    if is_largest:
        title = (
            f"DEL is India's largest international gateway: {latest_share:.0f}% "
            "of Indian gateway throughput"
        )
    else:
        title = f"DEL handles {latest_share:.0f}% of Indian international gateway throughput"
    c.style_axis(
        ax,
        title,
        "DEL share of international passenger throughput across Indian gateway "
        "airports, trailing 4 published quarters",
        "Share of Indian gateway throughput",
    )
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=14))
    clip_xticks_to_data(ax, mdates.date2num(x.max()))
    upper = max(40.0, float(share.max()) * 1.2)
    ax.set_ylim(0, upper)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Endpoint traffic at Indian gateways only; DGCA does not publish which foreign routes carry it.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_del_international")
    return "noida_del_international"


def chart_del_seasonality(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    m = c.add_month_period(monthly)
    del_rows = m[m["airport"] == "DEL"]
    months_per_year = del_rows.groupby("year")["month"].nunique()
    complete = sorted(int(y) for y in months_per_year[months_per_year == 12].index)
    if len(complete) < 3:
        return None
    rows = del_rows[del_rows["year"].isin(complete)]
    by_ym = rows.groupby(["year", "month"])["passengers"].sum().reset_index()
    annual = by_ym.groupby("year")["passengers"].transform("sum")
    by_ym["index"] = by_ym["passengers"] / (annual / 12) * 100
    profile = by_ym.groupby("month")["index"].median().reindex(range(1, 13))
    peak_month = int(profile.idxmax())
    trough_month = int(profile.idxmin())
    peak_dev = float(profile.max()) - 100
    trough_dev = float(profile.min()) - 100
    # How often the median-peak month actually led, so the title's precision
    # can be judged against the year-to-year spread.
    yearly_peaks = by_ym.loc[by_ym.groupby("year")["index"].idxmax(), "month"]
    peak_wins = int((yearly_peaks == peak_month).sum())
    covid_years = [y for y in (2020, 2021) if y in complete]
    ex_covid = by_ym[~by_ym["year"].isin(covid_years)]
    profile_ex = ex_covid.groupby("month")["index"].median().reindex(range(1, 13))

    fig, ax = new_fig()
    months = np.arange(1, 13)
    # Same encoding as the dashboard seasonality heatmap: red above the airport's
    # average month, blue below.
    bar_colors = [c.NEGATIVE if profile[mo] >= 100 else c.PRIMARY for mo in months]
    ax.bar(months, profile.values - 100, bottom=100, width=0.62, color=bar_colors)
    ax.axhline(100, color=c.BASELINE, linewidth=1)
    for mo in (peak_month, trough_month):
        value = float(profile[mo])
        ax.annotate(
            f"{value - 100:+.1f}%",
            (mo, value),
            xytext=(0, 7 if value >= 100 else -7),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
            va="bottom" if value >= 100 else "top",
        )
    c.style_axis(
        ax,
        f"Delhi's throughput peaks in {c.MONTH_ABBR[peak_month]} ({peak_dev:+.1f}% vs its "
        f"average month) and troughs in {c.MONTH_ABBR[trough_month]} ({trough_dev:+.1f}%)",
        f"Median monthly index of DEL domestic throughput across {len(complete)} complete "
        f"years; 100 = that year's average month · {c.MONTH_ABBR[peak_month]} was the peak "
        f"month in {peak_wins} of {len(complete)} years · red above average, blue below",
        "Index, 100 = average month",
    )
    ax.set_xticks(months)
    ax.set_xticklabels([c.MONTH_ABBR[mo] for mo in months])
    low = min(94.0, float(profile.min()) - 4)
    high = max(106.0, float(profile.max()) + 4)
    ax.set_ylim(low, high)
    caveat = "The incumbent's seasonality is NCR context, not a DXN forecast."
    if covid_years:
        caveat = (
            f"All complete years enter the median; excluding {'-'.join(str(y) for y in covid_years)} the "
            f"{c.MONTH_ABBR[peak_month]} median reads {float(profile_ex[peak_month]) - 100:+.1f}% and "
            f"{c.MONTH_ABBR[trough_month]} {float(profile_ex[trough_month]) - 100:+.1f}%. " + caveat
        )
    c.add_footer(fig, coverage=coverage, fingerprint=fingerprint, caveat=caveat)
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_del_seasonality")
    return "noida_del_seasonality"


def chart_up_catchment(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    up_codes = sorted(
        code
        for code, info in c.MAPPINGS.get("airports", {}).items()
        if (info or {}).get("state") == "Uttar Pradesh" and code not in NCR_AIRPORTS
    )
    series: dict[str, pd.Series] = {}
    for code in up_codes:
        t = t12_series(monthly, code)
        if t is not None and t.notna().any():
            series[code] = t
    if len(series) < 2:
        return None

    # Anchor month = the best-covered month among RECENT candidates (within a
    # year of the newest data), latest on ties: one airport publishing a month
    # early cannot shrink the headline to a two-airport subset, and a
    # long-dormant airport cannot drag the whole exhibit back to its era.
    def coverage_count(period: pd.Period) -> int:
        return sum(
            1 for t in series.values() if period in t.index and pd.notna(t.loc[period])
        )

    candidates = sorted({t.dropna().index.max() for t in series.values() if t.notna().any()})
    recent = [p for p in candidates if (candidates[-1] - p).n <= 12]
    latest_global = max(recent, key=lambda p: (coverage_count(p), p.ordinal))
    current = {
        code: float(t.loc[latest_global])
        for code, t in series.items()
        if latest_global in t.index and pd.notna(t.loc[latest_global])
    }
    if len(current) < 2:
        return None
    stale = {code: series[code].dropna().index.max() for code in series if code not in current}
    total = sum(current.values())
    prior_period = latest_global - INDEX_WINDOW_MONTHS
    prior = {
        code: float(series[code].loc[prior_period])
        for code in current
        if prior_period in series[code].index and pd.notna(series[code].loc[prior_period])
    }
    # The growth clause compares an identical airport set at both endpoints.
    growth_pct = None
    if set(prior) == set(current) and sum(prior.values()) > 0:
        growth_pct = (total / sum(prior.values()) - 1) * 100

    ranked = sorted(current, key=current.get, reverse=True)
    emphasis = ranked[:UP_EMPHASIS_N]
    # Hue follows the entity (mappings.yaml airport_colors), never the rank;
    # unmapped emphasis airports draw unused validated slots in fixed order.
    pool = [s for s in ["#2a78d6", "#eb6834"] if s not in {c.AIRPORT_COLORS.get(a) for a in emphasis}]
    colors = {}
    for code in emphasis:
        colors[code] = c.AIRPORT_COLORS.get(code) or (pool.pop(0) if pool else c.DEEMPH)
    gainer = None
    if prior:
        gains = {code: current[code] - prior[code] for code in prior}
        gainer = max(gains, key=gains.get)

    fig, ax = new_fig()
    endpoints: list[tuple[str, float]] = []
    for code, t in series.items():
        color = colors.get(code, c.DEEMPH)
        is_emphasis = code in colors
        x = t.index.to_timestamp()
        ax.plot(
            x,
            t.values,
            color=color,
            linewidth=2.2 if is_emphasis else 1.4,
            alpha=0.95 if is_emphasis else 0.7,
            solid_capstyle="round",
        )
        observed = t.dropna()
        if code in current:
            endpoints.append((code, float(observed.iloc[-1])))
        else:
            ax.annotate(
                f"{code} (to {observed.index[-1].strftime('%b %Y')})",
                (mdates.date2num(observed.index[-1].to_timestamp()), float(observed.iloc[-1])),
                xytext=(6, 8),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                color=c.TEXT,
            )

    max_val = max(float(t.max()) for t in series.values() if t.notna().any())
    y_upper = c.clean_upper_bound(max_val * 1.15)
    label_x = latest_global.to_timestamp() + pd.DateOffset(months=2)
    adjusted = c.spread_label_positions(
        endpoints,
        lower=y_upper * 0.025,
        upper=y_upper * 0.96,
        min_gap=y_upper * 0.045,
    )
    for code, value in endpoints:
        label = f"{code}  {label_scale(value)}"
        if code == gainer and growth_pct is not None and prior.get(code, 0) > 0:
            pct = (current[code] / prior[code] - 1) * 100
            label += f" ({pct:+.0f}% in 3y)"
        ax.plot(
            [latest_global.to_timestamp(), label_x],
            [value, adjusted[code]],
            color=colors.get(code, c.DEEMPH),
            alpha=0.45,
            linewidth=0.9,
        )
        ax.text(
            label_x,
            adjusted[code],
            label,
            va="center",
            ha="left",
            fontsize=9,
            fontweight="bold",
            color=c.TEXT,
            clip_on=False,
        )

    base_label = prior_period.strftime("%b %Y")
    end_label = latest_global.strftime("%b %Y")
    title = f"UP's airports beyond the NCR handle {total / 1e6:.1f}M passenger movements a year"
    if growth_pct is not None:
        title += f" ({growth_pct:+.0f}% in three years)"
    subtitle = (
        "Trailing-12-month passenger movements, UP airports outside the NCR set "
        f"(DEL, HDO, DXN excluded) · total = {len(current)} airports with windows "
        f"ending {end_label}"
    )
    if growth_pct is not None:
        subtitle += f" · 3-year change {base_label} to {end_label}"
    elif prior:
        subtitle += " · 3-year growth omitted: the airport set changed inside the window"
    c.style_axis(ax, title, subtitle, "Airport passenger movements")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_mixed_scale))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    earliest = min(t.index.min() for t in series.values())
    ax.set_xlim(earliest.to_timestamp(), latest_global.to_timestamp() + pd.DateOffset(months=16))
    clip_xticks_to_data(ax, mdates.date2num(latest_global.to_timestamp()))
    ax.set_ylim(0, y_upper)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Proximity does not establish catchment overlap with DXN; one unpublished month voids the twelve windows spanning it; the growth label marks the largest absolute gain.",
    )
    fig.subplots_adjust(left=0.08, right=0.90, top=0.84, bottom=0.13)
    save(fig, "noida_up_catchment")
    return "noida_up_catchment"


def chart_relief_valve(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    nmia = month_series(monthly, "NMIA")
    bom = month_series(monthly, "BOM")
    if nmia.empty or bom.empty:
        return None
    since = list(pd.period_range(nmia.index[0], nmia.index.max(), freq="M"))
    prior = [p - 12 for p in since]
    # The YoY claim needs every month of both windows published on both sides;
    # a silently skipped month would swing the headline by double digits.
    windows_complete = all(p in bom.index for p in since + prior) and all(
        p in nmia.index for p in since
    )
    if not windows_complete:
        print("  Skipped noida_relief_valve: BOM/NMIA windows have unpublished months", flush=True)
        return None
    n = len(since)
    bom_since = float(bom.loc[since].sum())
    bom_prior = float(bom.loc[prior].sum())
    nmia_vol = float(nmia.loc[since].sum())
    if bom_prior <= 0:
        return None
    bom_yoy = (bom_since / bom_prior - 1) * 100
    sys_yoy = ((bom_since + nmia_vol) / bom_prior - 1) * 100
    displaced = max(0.0, bom_prior - bom_since) / nmia_vol if nmia_vol > 0 else np.nan
    REGISTER["relief"] = dict(
        bom_yoy=bom_yoy, sys_yoy=sys_yoy, months=n, displaced=displaced
    )

    start = nmia.index[0] - 12
    periods = pd.period_range(start, max(bom.index.max(), nmia.index.max()), freq="M")
    # Gap-honest areas: BOM stays NaN where unpublished (fill_between breaks);
    # NMIA is a real zero only before its first published month.
    bom_w = bom.reindex(periods)
    nmia_w = nmia.reindex(periods)
    nmia_w[periods < nmia.index[0]] = 0

    fig, ax = new_fig()
    x = periods.to_timestamp()
    total = bom_w + nmia_w
    ax.fill_between(x, 0, bom_w.values, color=SERIES["BOM"], alpha=0.85, linewidth=0)
    ax.fill_between(x, bom_w.values, total.values, color=SERIES["NMIA"], alpha=0.85, linewidth=0)
    ax.plot(x, bom_w.values, color=c.BG, linewidth=1.5)
    entry = nmia.index[0]
    if entry in total.index and pd.notna(total.loc[entry]):
        ax.annotate(
            f"{c.airport_label('NMIA')} first published month",
            (mdates.date2num(entry.to_timestamp()), float(total.loc[entry])),
            xytext=(-8, 16),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="right",
            arrowprops={"arrowstyle": "-", "color": c.MUTED, "lw": 0.8},
        )
    window_label = (
        f"{since[0].strftime('%b %Y')}-{since[-1].strftime('%b %Y')} vs "
        f"{prior[0].strftime('%b %Y')}-{prior[-1].strftime('%b %Y')}"
    )
    c.style_axis(
        ax,
        f"Since NMIA's first published month: BOM {bom_yoy:+.1f}%, "
        f"the two-airport system {sys_yoy:+.1f}%",
        f"Monthly airport passenger movements at Mumbai's airports; {n}-month window "
        f"{window_label}",
        "Monthly airport passenger movements",
    )
    ax.set_ylim(0, c.clean_upper_bound(float(total.max()) * 1.15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_millions))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(
        handles=[
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9, color=SERIES["BOM"], label=c.airport_label("BOM")),
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9, color=SERIES["NMIA"], label=c.airport_label("NMIA")),
        ],
        loc="upper left",
        frameon=False,
        fontsize=9,
        labelcolor=c.SUBTLE,
    )
    caveat = "Observational; system growth cannot be attributed causally to the new airport's entry."
    if np.isfinite(displaced) and displaced > 0:
        caveat += (
            f" BOM's shortfall vs the prior year equals {displaced:.0%} of NMIA's "
            "volume; no counterfactual is observable."
        )
    elif np.isfinite(displaced):
        caveat += " BOM grew alongside NMIA's entry in this window."
    c.add_footer(fig, coverage=coverage, fingerprint=fingerprint, caveat=caveat)
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_relief_valve")
    return "noida_relief_valve"


def chart_hindon_lesson(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    hdo = month_series(monthly, "HDO")
    if len(hdo) < 24:
        return None
    # Reindex to the full calendar range: unpublished months become NaN, so
    # diffs never span a gap and the plotted line breaks where data is missing.
    full_range = pd.period_range(hdo.index.min(), hdo.index.max(), freq="M")
    hdo_full = hdo.reindex(full_range)
    steps = hdo_full.diff().dropna()
    if steps.empty:
        print("  Skipped noida_hindon_lesson: no two adjacent published months", flush=True)
        return None
    jump = steps.idxmax()
    peak = float(hdo.max())
    peak_period = hdo.idxmax()
    # Quiet window: whole years before the BREAKOUT month (first published
    # month above 4x the first observed year's ceiling). Anchoring on the first
    # crossing keeps the window stable as new data appends; anchoring on the
    # largest step would rewrite the headline whenever a bigger step arrives.
    first = hdo.index[0]
    base_ceiling = float(hdo.iloc[:12].max())
    if base_ceiling <= 0:
        return None
    crossings = hdo[hdo >= 4 * base_ceiling]
    if crossings.empty:
        print("  Skipped noida_hindon_lesson: no breakout month observed", flush=True)
        return None
    breakout = crossings.index[0]
    quiet_years = (breakout - first).n // 12
    if quiet_years < 2:
        print("  Skipped noida_hindon_lesson: breakout too close to first observation", flush=True)
        return None
    quiet = hdo[hdo.index < first + quiet_years * 12]
    quiet_ceiling_k = math.ceil(float(quiet.max()) / 1000)
    quiet_observed = int(len(quiet))
    quiet_calendar = quiet_years * 12
    # The recede is part of the lesson: commitments can leave as fast as they
    # arrive. The clause appears only once the observed tail is well off peak.
    latest_period = hdo.index[-1]
    latest_value = float(hdo.iloc[-1])
    receded = latest_period > peak_period and latest_value < 0.6 * peak

    fig, ax = new_fig()
    x = hdo_full.index.to_timestamp()
    ax.plot(x, hdo_full.values, color=c.PRIMARY, **LINE)
    if receded:
        ax.annotate(
            f"{latest_value / 1e3:.0f}K",
            (mdates.date2num(latest_period.to_timestamp()), latest_value),
            xytext=(8, 0),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )
    ax.annotate(
        f"Largest step: {steps.max() / 1e3:+.0f}K in {jump.strftime('%b %Y')}",
        (mdates.date2num(jump.to_timestamp()), float(hdo_full.loc[jump])),
        xytext=(-110, 30),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        arrowprops={"arrowstyle": "-", "color": c.MUTED, "lw": 0.8},
    )
    ax.annotate(
        f"{peak / 1e3:.0f}K",
        (mdates.date2num(peak_period.to_timestamp()), peak),
        xytext=(0, 7),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        ha="center",
    )
    title = (
        f"Hindon never topped {quiet_ceiling_k}K in a published month of its first "
        f"{year_word(quiet_years)}, then reached {peak / 1e3:.0f}K in {peak_period.strftime('%b %Y')}"
    )
    if receded:
        title += f", back to {latest_value / 1e3:.0f}K by {latest_period.strftime('%b %Y')}"
    REGISTER["hindon"] = dict(
        ceiling_k=quiet_ceiling_k,
        quiet_years=quiet_years,
        quiet_observed=quiet_observed,
        quiet_calendar=quiet_calendar,
        peak_k=peak / 1e3,
        peak_month=peak_period.strftime("%b %Y"),
        latest_k=latest_value / 1e3,
        latest_month=latest_period.strftime("%b %Y"),
        receded=receded,
    )
    c.style_axis(
        ax,
        title,
        "Monthly airport passenger movements at Hindon (HDO), Delhi's second airport, "
        f"since first DGCA observation · {quiet_observed} of {quiet_calendar} months in "
        "the quiet window have published rows",
        "Monthly airport passenger movements",
    )
    ax.set_ylim(0, peak * 1.2)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_thousands))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="DGCA data shows the step, not its cause; capacity commitments can also recede. Months with no published row appear as line gaps.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_hindon_lesson")
    return "noida_hindon_lesson"


def chart_small_city_share(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    airports_map = c.MAPPINGS.get("airports", {})
    metros = {code for code, info in airports_map.items() if (info or {}).get("tier") == "metro"}
    tier1 = {code for code, info in airports_map.items() if (info or {}).get("tier") == "tier1"}
    complete = c.complete_calendar_years(monthly)
    if len(complete) < 2 or not metros or not tier1:
        return None
    m = c.add_month_period(monthly)
    tier1_shares, beyond_shares = [], []
    for y in complete:
        a = m[m["year"] == y]
        total = a["passengers"].sum()
        metro_sum = a[a["airport"].isin(metros)]["passengers"].sum()
        tier1_sum = a[a["airport"].isin(tier1)]["passengers"].sum()
        tier1_shares.append(tier1_sum / total * 100)
        beyond_shares.append((total - metro_sum - tier1_sum) / total * 100)
    nonmetro = [t + b for t, b in zip(tier1_shares, beyond_shares)]

    fig, ax = new_fig()
    # Two ordered segments of the non-metro share; hairline BG edges keep the
    # segments separable, identity is carried by the legend and total labels.
    segment_colors = {"tier1": c.PRIMARY, "beyond": "#eb6834"}
    ax.bar(
        complete, tier1_shares, width=0.55,
        color=segment_colors["tier1"], edgecolor=c.BG, linewidth=1.2,
    )
    ax.bar(
        complete, beyond_shares, bottom=tier1_shares, width=0.55,
        color=segment_colors["beyond"], edgecolor=c.BG, linewidth=1.2,
    )
    for i in (0, len(complete) - 1):
        ax.annotate(
            f"{nonmetro[i]:.0f}%",
            (complete[i], nonmetro[i]),
            xytext=(0, 6),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
            va="bottom",
        )
    REGISTER["small_city"] = dict(
        now=nonmetro[-1],
        first=nonmetro[0],
        first_year=complete[0],
        last_year=complete[-1],
    )
    c.style_axis(
        ax,
        f"Non-metro airports handle {nonmetro[-1]:.0f}% of national throughput; "
        f"{beyond_shares[-1]:.0f} pp of it beyond the Tier-1 cities",
        f"Share of national airport throughput outside the {len(metros)} metro airports, "
        "complete years, split by this project's own tier bands (mappings.yaml; "
        "not a DGCA or AAI classification)",
        "Share of national throughput",
    )
    ax.set_xticks(complete)
    ax.set_ylim(0, max(50.0, max(nonmetro) * 1.15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    ax.legend(
        handles=[
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9,
                       color=segment_colors["tier1"], label=f"Tier-1 cities ({len(tier1)} airports)"),
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9,
                       color=segment_colors["beyond"], label="Beyond Tier 1 (smaller & unclassified)"),
        ],
        loc="upper left",
        frameon=False,
        fontsize=9,
        labelcolor=c.SUBTLE,
    )
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Throughput counts each passenger at both endpoint airports; the tier bands are project-defined presentation, not an official classification.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_small_city_share")
    return "noida_small_city_share"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

EXHIBIT_COPY = {
    "noida_growth_pause": (
        "The market Noida enters",
        "Every early Noida number reads against this national baseline.",
    ),
    "noida_supply_demand": (
        "The market Noida enters",
        "Capacity-led and demand-led pauses have different implications for a market entrant; the two series separate them.",
    ),
    "noida_beyond_trunk": (
        "The market Noida enters",
        "The realistic opportunity for a new airport is the middle market, not the metro trunk.",
    ),
    "noida_small_city_share": (
        "The market Noida enters",
        "How much demand sits beyond the metros, and beyond the Tier-1 cities, frames what a second NCR airport can serve directly.",
    ),
    "noida_airline_groups": (
        "The market Noida enters",
        "Two groups carry most of India's domestic passengers; that is the counterparty structure any new airport faces.",
    ),
    "noida_ncr_vs_mmr": (
        "The region",
        "The capital region's depth is the structural case for a third airport.",
    ),
    "noida_del_vs_rest": (
        "The region",
        "How fast the incumbent grows against the rest of the country frames the spillover case.",
    ),
    "noida_del_international": (
        "The region",
        "Delhi is the international benchmark a second NCR airport gets measured against.",
    ),
    "noida_del_seasonality": (
        "The region",
        "Slot planning starts with the shape of a Delhi year, not its size.",
    ),
    "noida_up_catchment": (
        "The region",
        "Catchment context: the traffic Uttar Pradesh's own airports already handle.",
    ),
    "noida_delhi_menu": (
        "The region",
        "Delhi's observable markets are the research queue for Noida's route development.",
    ),
    "noida_ramp_benchmark": (
        "The playbook",
        "The bounding curves (scale-up, replication, flatline) frame first-24-month expectations.",
    ),
    "noida_nmia_tracker": (
        "The playbook",
        "Navi Mumbai is the closest live analogue; its monthly share of the Mumbai system is the leading indicator.",
    ),
    "noida_relief_valve": (
        "The playbook",
        "Incumbent versus system is the relief-valve question; Navi Mumbai gives the first observed read.",
    ),
    "noida_hindon_lesson": (
        "The playbook",
        "Ramp-ups move in steps, not with time, and the steps can reverse.",
    ),
}

PAGE_ORDER = [
    "noida_growth_pause",
    "noida_supply_demand",
    "noida_beyond_trunk",
    "noida_small_city_share",
    "noida_airline_groups",
    "noida_ncr_vs_mmr",
    "noida_del_vs_rest",
    "noida_del_international",
    "noida_del_seasonality",
    "noida_up_catchment",
    "noida_delhi_menu",
    "noida_ramp_benchmark",
    "noida_nmia_tracker",
    "noida_relief_valve",
    "noida_hindon_lesson",
]

# Exhibits that are coded but await qualifying input data render as a visible
# placeholder instead of silently vanishing, so readers can see the queue.
# The route table is derived by this repo from DGCA's city-pair source; it is
# a pipeline milestone, not data DGCA withholds.
ROUTE_PENDING = (
    "Generates once this repo publishes the route table "
    "(data/processed/domestic_route_monthly.csv), derived from DGCA's "
    "city-pair source, with enough qualifying months."
)
PENDING_REASON = {
    "noida_beyond_trunk": ROUTE_PENDING,
    "noida_delhi_menu": ROUTE_PENDING,
}
GENERIC_PENDING = (
    "This exhibit did not generate on the current data refresh (its input is "
    "incomplete or below the disclosed thresholds); it returns automatically "
    "when the inputs qualify."
)


def register_entries(generated: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(tested, untestable) claim/verdict pairs for the register section.

    Every number comes from REGISTER, deposited by the chart functions in this
    run; a skipped chart drops its entry rather than showing a stale number.
    Verdict words are DERIVED FROM THE COMPUTED SIGNS, never hardcoded, so a
    refresh that flips a number flips the verdict with it. Verdicts state what
    the data shows and never assert causes (the charts' caveats forbid that).
    """
    tested: list[tuple[str, str]] = []
    untestable: list[tuple[str, str]] = []
    if "relief" in REGISTER:
        r = REGISTER["relief"]
        cannibalized = np.isfinite(r["displaced"]) and r["displaced"] >= 0.5
        if cannibalized:
            verdict = f"Partly supported so far ({r['months']} published months): "
        else:
            verdict = f"Not supported so far ({r['months']} published months): "
        verdict += (
            f"BOM moved {r['bom_yoy']:+.1f}% and the two-airport system "
            f"{r['sys_yoy']:+.1f}% against the same months a year earlier"
        )
        if np.isfinite(r["displaced"]):
            verdict += f"; BOM's shortfall equals {r['displaced']:.0%} of NMIA's volume"
        tested.append((
            "A second airport mostly cannibalizes the incumbent.",
            verdict + ".",
        ))
    if "hindon" in REGISTER:
        h = REGISTER["hindon"]
        broke_out = h["peak_k"] >= 5 * h["ceiling_k"]
        verdict = "Rejected: " if broke_out else "Consistent with the data so far: "
        verdict += (
            f"Hindon never topped {h['ceiling_k']}K in a published month for "
            f"{year_word(h['quiet_years'])} ({h['quiet_observed']} of "
            f"{h['quiet_calendar']} months published), then reached "
            f"{h['peak_k']:.0f}K in {h['peak_month']}"
        )
        if h["receded"]:
            verdict += f"; by {h['latest_month']} it was back to {h['latest_k']:.0f}K"
        tested.append((
            "Hindon proves the Delhi region cannot fill a second airport.",
            verdict + ".",
        ))
    if "small_city" in REGISTER:
        s = REGISTER["small_city"]
        delta = s["now"] - s["first"]
        if delta > 0.5:
            verdict, verb = "Rejected: ", "rose"
        elif delta < -0.5:
            verdict, verb = "Supported by current data: ", "fell"
        else:
            verdict, verb = "Inconclusive: ", "held"
        tested.append((
            "Growth is re-concentrating into the metros.",
            f"{verdict}the non-metro share of national throughput {verb} from "
            f"{s['first']:.0f}% in {s['first_year']} to {s['now']:.0f}% in {s['last_year']}.",
        ))
    if "supply" in REGISTER:
        s = REGISTER["supply"]
        if s["ask_yoy"] > 0.5:
            verdict = "Rejected: "
        elif s["ask_yoy"] < -0.5:
            verdict = "Supported by current data: "
        else:
            verdict = "Borderline: "
        tested.append((
            "Airlines have stopped adding domestic capacity.",
            f"{verdict}seat-km capacity {pct_phrase(s['ask_yoy'])} in the latest 12 "
            f"months, while passenger-km demand {pct_phrase(s['rpk_yoy'])}.",
        ))
    if "duopoly" in REGISTER:
        d = REGISTER["duopoly"]
        delta = d["combined"] - d["combined_first"]
        if delta > 1:
            verdict, verb = "Rejected: ", "rose"
        elif delta < -1:
            verdict, verb = "Supported by current data: ", "fell"
        else:
            verdict, verb = "Inconclusive: ", "held"
        tested.append((
            "The domestic market is fragmenting across many carriers.",
            f"{verdict}the two leading groups' combined share of passengers carried "
            f"{verb} from {d['combined_first']:.0f}% in {d['first_year']} to "
            f"{d['combined']:.0f}% in {d['last_year']}.",
        ))
    if "white_space" in REGISTER:
        ws = REGISTER["white_space"]
        claim = "Noida opens into empty white space no airline serves."
        if ws["n_white"] == 0:
            tested.append((
                claim,
                f"Rejected: all {ws['n_candidates']} domestic airports above "
                f"{ws['floor'] / 1e3:.0f}K annual route passenger movements already "
                f"appear in Delhi's observed route menu ({ws['n_del_markets']} markets, "
                f"{ws['window']}). The opportunity is served demand, not empty space.",
            ))
        else:
            code, vol = ws["top_white"]
            ratio = ws["n_white"] / ws["n_candidates"] if ws["n_candidates"] else 0
            grade = "Largely rejected: only" if ratio < 0.15 else "Partly supported:"
            tested.append((
                claim,
                f"{grade} {ws['n_white']} of {ws['n_candidates']} domestic "
                f"airports above {ws['floor'] / 1e3:.0f}K annual route passenger "
                f"movements have no observed DEL route ({ws['window']}), led by "
                f"{c.airport_label(code)} at {label_scale(vol)}.",
            ))
    else:
        untestable.append((
            "Noida opens into empty white space no airline serves.",
            "Not yet testable on current data: the test needs 12 contiguous "
            "months of the route table derived from DGCA's city-pair source; "
            "its verdict computes here automatically.",
        ))
    return tested, untestable


def dxn_status_item(monthly: pd.DataFrame) -> str:
    """The page's DXN limitation entry, computed from the published rows so a
    refresh that lands DXN's first months can never leave a false sentence."""
    dxn = month_series(monthly, NEWCOMER)
    if dxn.empty:
        return (
            "<li><strong>Noida itself.</strong> DGCA has published no DXN airport rows yet; every "
            "exhibit here is the market around the airport, not the airport. DXN joins the ramp "
            "benchmark automatically once rows land.</li>"
        )
    n = int(len(dxn))
    first = dxn.index[0].strftime("%b %Y")
    return (
        f"<li><strong>Noida itself.</strong> DGCA has published {n} DXN month{'s' if n != 1 else ''} "
        f"so far (from {first}, shown on the ramp benchmark); an opening month is a partial "
        "observation, and nothing here is steady-state NIA performance.</li>"
    )


def write_page(generated: list[str], data_date: str | None, *, monthly: pd.DataFrame) -> Path:
    sections: list[str] = []
    current_section = None
    for chart_id in PAGE_ORDER:
        pending = chart_id not in generated
        section, standfirst = EXHIBIT_COPY[chart_id]
        if section != current_section:
            sections.append(f'      <h2 class="section-rule"><span>{section}</span></h2>')
            current_section = section
        if pending:
            reason = PENDING_REASON.get(chart_id, GENERIC_PENDING)
            sections.append(
                f"""      <section class="exhibit">
        <p class="standfirst">{standfirst}</p>
        <div class="pending"><strong>Pending exhibit.</strong> {reason}</div>
      </section>"""
            )
        else:
            sections.append(
                f"""      <section class="exhibit">
        <p class="standfirst">{standfirst}</p>
        <img class="chart-img" src="charts/noida/{chart_id}.png" alt="{chart_id.replace('_', ' ')}" loading="lazy">
      </section>"""
            )

    tested, untestable = register_entries(generated)
    tested_items = "\n".join(
        f"      <li><strong>&ldquo;{claim}&rdquo;</strong> {verdict}</li>"
        for claim, verdict in tested
    )
    sections.append(
        f"""      <h2 class="section-rule"><span>Claims tested against the data</span></h2>
      <section class="exhibit">
        <p class="standfirst">Common counter-narratives, checked against the same tables as the exhibits.
        Verdict wording derives from the computed numbers on every refresh.</p>
        <ul class="register">
{tested_items}
        </ul>
      </section>"""
    )
    if untestable:
        untestable_items = "\n".join(
            f"      <li><strong>&ldquo;{claim}&rdquo;</strong> {verdict}</li>"
            for claim, verdict in untestable
        )
        sections.append(
            f"""      <h2 class="section-rule"><span>Not yet testable</span></h2>
      <section class="exhibit">
        <ul class="register">
{untestable_items}
        </ul>
      </section>"""
        )
    sections.append(
        f"""      <h2 class="section-rule"><span>What this data cannot tell you</span></h2>
      <section class="exhibit">
        <p class="standfirst">Limits of the source data. None of the following is observable in DGCA's
        published tables.</p>
        <ul class="register">
      {dxn_status_item(monthly)}
      <li><strong>Airline commitments.</strong> DGCA reports flown traffic, not schedules, fleet plans, or
      base decisions; the single biggest ramp-up driver is invisible here until it flies.</li>
      <li><strong>True origin&ndash;destination demand.</strong> Airport rows are endpoint throughput and route rows
      are segments; connecting itineraries cannot be separated from local demand.</li>
      <li><strong>Fares and yields.</strong> No public Indian fare series is published at a granularity that
      joins to these tables.</li>
      <li><strong>Capacity ceilings.</strong> Aircraft movements, slots, and terminal limits are operator and AAI
      data; DGCA passenger tables cannot show how full DEL's runways are.</li>
      <li><strong>Surface catchment.</strong> Who drives to which airport is not aviation data; UP airport traffic
      shows regional demand, not DXN's future share of it.</li>
      <li><strong>Cargo by airport.</strong> DGCA carrier freight is airline-level; airport-wise cargo volumes are
      published by AAI, not here.</li>
        </ul>
      </section>"""
    )

    data_line = f"Data: DGCA public aviation statistics (as of {data_date})" if data_date else "Data: DGCA public aviation statistics"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Noida International Airport | india-aviation-stats</title>
  <meta name="description" content="What published DGCA data says about the market Noida International Airport (DXN) enters.">
  <meta property="og:title" content="Noida International Airport: DGCA data in charts">
  <meta property="og:image" content="https://mkubicek.github.io/india-aviation-stats/charts/noida/noida_ramp_benchmark.png">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: #f9f9f7;
      color: #0b0b0b;
      font-family: "Helvetica Neue", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      line-height: 1.6;
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 2.5rem 1rem 4rem; }}
    header.mast {{ border-bottom: 2px solid #0b0b0b; padding-bottom: 1.2rem; margin-bottom: 0.6rem; }}
    .kicker {{ font-size: 0.75rem; letter-spacing: 0.14em; text-transform: uppercase; color: #2a78d6; font-weight: 600; margin-bottom: 0.6rem; }}
    h1 {{ font-size: clamp(1.7rem, 4vw, 2.4rem); line-height: 1.15; margin-bottom: 0.6rem; }}
    .lede {{ font-family: Georgia, "Times New Roman", serif; font-size: 1.05rem; color: #52514e; max-width: 62ch; }}
    .meta {{ font-size: 0.8rem; color: #898781; margin-top: 0.9rem; }}
    .meta a {{ color: #2a78d6; }}
    .section-rule {{ margin: 2.8rem 0 0.4rem; font-size: 0.8rem; letter-spacing: 0.14em; text-transform: uppercase; color: #52514e; display: flex; align-items: center; gap: 0.9rem; }}
    .section-rule::after {{ content: ""; flex: 1; border-top: 1px solid #e1e0d9; }}
    .exhibit {{ margin-top: 1.6rem; }}
    .standfirst {{ font-family: Georgia, "Times New Roman", serif; font-size: 0.95rem; color: #52514e; max-width: 72ch; margin-bottom: 0.7rem; }}
    .chart-img {{ display: block; width: 100%; height: auto; background: #fcfcfb; border: 1px solid #e1e0d9; border-radius: 6px; padding: 4px; }}
    .pending {{ border: 1px solid #e1e0d9; background: #fcfcfb; border-radius: 6px; padding: 1.1rem 1.3rem; font-size: 0.9rem; color: #52514e; }}
    .register {{ list-style: none; max-width: 78ch; }}
    .register li {{ font-size: 0.92rem; color: #52514e; padding: 0.55rem 0; border-bottom: 1px solid #e1e0d9; }}
    .register li:last-child {{ border-bottom: none; }}
    .register strong {{ color: #0b0b0b; }}
    footer {{ margin-top: 3rem; font-size: 0.8rem; color: #898781; border-top: 1px solid #e1e0d9; padding-top: 1rem; }}
    footer a {{ color: #2a78d6; }}
  </style>
</head>
<body>
  <div class="container">
    <header class="mast">
      <p class="kicker">Noida International Airport (DXN) · DGCA data</p>
      <h1>The market Noida enters, in charts</h1>
      <p class="lede">The national market a new Delhi-region airport joins, the region it serves, and the
      ramp-up playbook written by India's other dual-airport systems. Every number is computed from
      published DGCA tables, every chart carrying its own caveat.</p>
      <p class="meta">Delhi (DEL) data is used throughout as an observable NCR proxy; nothing here is a
      Noida forecast. <a href="index.html">&larr; Main dashboard</a></p>
    </header>
{chr(10).join(sections)}
    <footer>
      <p>{data_line}. Charts regenerate from the published CSV tables in
      <a href="https://github.com/mkubicek/india-aviation-stats">india-aviation-stats</a>;
      pending exhibits render in place automatically once their inputs qualify.
      See the <a href="https://github.com/mkubicek/india-aviation-stats/blob/main/docs/noida-theses.md">thesis register</a>,
      <a href="https://github.com/mkubicek/india-aviation-stats/blob/main/METHODOLOGY.md">methodology</a>, and
      <a href="https://github.com/mkubicek/india-aviation-stats/blob/main/docs/data-dictionary.md">data dictionary</a>.</p>
    </footer>
  </div>
</body>
</html>
"""
    PAGE_PATH.write_text(html, encoding="utf-8")
    return PAGE_PATH


# Metric provenance per exhibit, mirroring the dashboard manifest: the same
# `passengers` column means different things across the three source layers.
NOIDA_SEMANTICS = {
    "noida_growth_pause": ("carrier_monthly", "scheduled_domestic_passengers_carried"),
    "noida_supply_demand": ("carrier_monthly", "scheduled_domestic_seat_km_vs_passenger_km"),
    "noida_airline_groups": ("carrier_monthly", "scheduled_domestic_passengers_carried_share"),
    "noida_beyond_trunk": ("domestic_route_monthly", "domestic_route_segment_passengers"),
    "noida_delhi_menu": ("domestic_route_monthly", "domestic_route_segment_passengers"),
    "noida_small_city_share": ("airport_monthly", "domestic_airport_throughput_share"),
    "noida_ncr_vs_mmr": ("airport_monthly", "domestic_airport_throughput_arrivals_plus_departures"),
    "noida_del_vs_rest": ("airport_monthly", "domestic_airport_throughput_index"),
    "noida_del_international": ("airport_international_quarterly", "indian_international_gateway_throughput_share"),
    "noida_del_seasonality": ("airport_monthly", "domestic_airport_throughput_index"),
    "noida_up_catchment": ("airport_monthly", "domestic_airport_throughput_arrivals_plus_departures"),
    "noida_ramp_benchmark": ("airport_monthly", "domestic_airport_throughput_arrivals_plus_departures"),
    "noida_nmia_tracker": ("airport_monthly", "domestic_airport_throughput_share"),
    "noida_relief_valve": ("airport_monthly", "domestic_airport_throughput_arrivals_plus_departures"),
    "noida_hindon_lesson": ("airport_monthly", "domestic_airport_throughput_arrivals_plus_departures"),
}


def write_manifest(records: list[dict]) -> Path:
    manifest = {
        "generated": str(date.today()),
        "charts": {
            r["id"]: {
                "file": f"charts/noida/{r['id']}.png",
                "sha256": c.sha256_file(OUT_DIR / f"{r['id']}.png"),
                "inputs": r["inputs"],
                "input_fingerprint": r["fingerprint"],
                "coverage": r["coverage"],
                "primary_source_table": NOIDA_SEMANTICS[r["id"]][0],
                "metric_semantics": NOIDA_SEMANTICS[r["id"]][1],
            }
            for r in records
        },
    }
    path = OUT_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    print("=== Generating Noida charts ===\n", flush=True)
    monthly = c.load_domestic_monthly()
    carrier = c.load_carrier_monthly()
    intl = c.load_international_quarterly()
    try:
        routes = load_routes()
    except Exception as exc:  # noqa: BLE001 - a malformed route table must not
        # abort the 13 working exhibits, the manifest, or the page.
        print(f"  Route table unreadable, skipping route exhibits: {exc}", flush=True)
        routes = None

    monthly_cov = c.domestic_coverage(monthly)
    carrier_cov = c.carrier_domestic_coverage(carrier)
    intl_cov = c.international_coverage(intl)
    monthly_fp = c.input_fingerprint([c.DOMESTIC_MONTHLY_PATH])
    carrier_fp = c.input_fingerprint([c.CARRIER_MONTHLY_PATH])
    intl_fp = c.input_fingerprint([c.INTERNATIONAL_QUARTERLY_PATH])
    carrier_inputs = [str(c.CARRIER_MONTHLY_PATH.relative_to(ROOT))]
    monthly_inputs = [str(c.DOMESTIC_MONTHLY_PATH.relative_to(ROOT))]
    intl_inputs = [str(c.INTERNATIONAL_QUARTERLY_PATH.relative_to(ROOT))]

    records: list[dict] = []

    failures: list[str] = []

    def run(fn, data, coverage, fingerprint, inputs):
        try:
            result = fn(data, coverage=coverage, fingerprint=fingerprint)
        except Exception as exc:  # noqa: BLE001 - one exhibit's crash must not
            # discard the rest of the refresh; the page shows its placeholder.
            failures.append(f"{fn.__name__}: {exc}")
            print(f"  ERROR in {fn.__name__}: {exc}", flush=True)
            return
        if result:
            records.append(
                dict(id=result, coverage=coverage, fingerprint=fingerprint, inputs=inputs)
            )
            print(f"  Saved: charts/noida/{result}.png", flush=True)

    run(chart_growth_pause, carrier, carrier_cov, carrier_fp, carrier_inputs)
    run(chart_supply_demand, carrier, carrier_cov, carrier_fp, carrier_inputs)
    run(chart_airline_groups, carrier, carrier_cov, carrier_fp, carrier_inputs)
    run(chart_small_city_share, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_ncr_vs_mmr, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_del_vs_rest, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_del_international, intl, intl_cov, intl_fp, intl_inputs)
    run(chart_del_seasonality, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_up_catchment, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_ramp_benchmark, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_nmia_tracker, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_relief_valve, monthly, monthly_cov, monthly_fp, monthly_inputs)
    run(chart_hindon_lesson, monthly, monthly_cov, monthly_fp, monthly_inputs)

    if routes is not None:
        route_cov = f"{routes['period'].min()}..{routes['period'].max()}"
        route_fp = c.input_fingerprint([ROUTE_MONTHLY_PATH])
        route_inputs = [str(ROUTE_MONTHLY_PATH.relative_to(ROOT))]
        run(chart_beyond_trunk, routes, route_cov, route_fp, route_inputs)
        run(chart_delhi_menu, routes, route_cov, route_fp, route_inputs)
        white_space_stats(routes)
    else:
        print("  Skipped route-level exhibits (data/processed/domestic_route_monthly.csv not published)", flush=True)

    generated = [r["id"] for r in records]
    manifest_path = write_manifest(records)
    print(f"  Saved: {manifest_path.relative_to(ROOT)}", flush=True)
    meta = c.load_metadata()
    page = write_page(generated, meta.get("data_date"), monthly=monthly)
    print(f"  Saved: {page.relative_to(ROOT)} ({len(generated)} exhibits)", flush=True)
    if failures:
        # Exit 0 on purpose: the page's visible "pending" placeholder is the
        # failure signal, and a non-zero exit would make CI discard the whole
        # monthly data commit along with the 12+ healthy exhibits.
        print(f"\nDone with {len(failures)} exhibit error(s): " + "; ".join(failures), flush=True)
        return
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
