"""Noida International Airport (DXN) focus page: charts + noida.html.

Generates the Noida chart set into charts/noida/ and writes noida.html.
Every title and annotation is computed from the published tables; charts whose
inputs are not yet published (the route layer, DXN airport rows) are skipped
and appear automatically once the data lands.

Run: uv run python scripts/noida.py
"""

from __future__ import annotations

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

SERIES = {  # fixed entity hues from the validated categorical order
    "DXN": "#2a78d6",
    "GOX": "#eb6834",
    "NMIA": "#1baf7a",
    "HDO": "#eda100",
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


def new_fig() -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=c.FIGSIZE_WIDE, facecolor=c.BG)
    return fig, ax


# ---------------------------------------------------------------------------
# Exhibits
# ---------------------------------------------------------------------------

def chart_ramp_benchmark(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    fig, ax = new_fig()
    series = {}
    for airport in ANALOGUES + [NEWCOMER]:
        s = month_series(monthly, airport).head(RAMP_WINDOW)
        if not s.empty:
            series[airport] = s
    if not any(a in series for a in ANALOGUES):
        plt.close(fig)
        return None

    for airport in ANALOGUES:
        if airport not in series:
            continue
        s = series[airport]
        x = range(1, len(s) + 1)
        ax.plot(x, s.values, color=SERIES[airport], **LINE)
        ax.annotate(
            c.airport_label(airport),
            (len(s), float(s.iloc[-1])),
            xytext=(7, 0),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            va="center",
        )

    has_newcomer = NEWCOMER in series
    if has_newcomer:
        s = series[NEWCOMER]
        ax.plot(
            range(1, len(s) + 1),
            s.values,
            linestyle="none",
            marker="o",
            markersize=8,
            markerfacecolor=c.BG,
            markeredgecolor=SERIES[NEWCOMER],
            markeredgewidth=2.5,
        )
        first = s.index[0]
        ax.annotate(
            f"{c.airport_label(NEWCOMER)}: {s.iloc[-1] / 1e3:.0f}K in {first.strftime('%b %Y')}",
            (len(s), float(s.iloc[-1])),
            xytext=(14, 30),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            arrowprops={"arrowstyle": "-", "color": c.MUTED, "lw": 0.8},
        )

    title = "Newcomer ramp-ups at India's dual-airport systems"
    if has_newcomer:
        title += f" — and {c.airport_label(NEWCOMER)}'s first months"
    labels = [c.airport_label(a) for a in ANALOGUES if a in series]
    c.style_axis(
        ax,
        title,
        f"Monthly airport passenger movements in the first {RAMP_WINDOW} observed months: "
        + ", ".join(labels),
        "Airport passenger movements",
    )
    ax.set_xlabel("Months since first DGCA-observed month", color=c.SUBTLE, fontsize=11)
    ax.set_xlim(0.5, RAMP_WINDOW + 5.5)
    ax.set_xticks([1, 6, 12, 18, 24])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_thousands))
    handles = [
        plt.Line2D([], [], color=SERIES[a], lw=2.2, label=c.airport_label(a))
        for a in ANALOGUES
        if a in series
    ]
    if has_newcomer:
        handles.append(
            plt.Line2D(
                [], [], linestyle="none", marker="o", markersize=7,
                markerfacecolor=c.BG, markeredgecolor=SERIES[NEWCOMER],
                markeredgewidth=2, label=f"{c.airport_label(NEWCOMER)} (opening months)",
            )
        )
    ax.legend(handles=handles, loc="upper right", frameon=False, fontsize=9, labelcolor=c.SUBTLE)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="A first observed month may be partial (mid-month opening). Analogues differ in catchment, era, and operating model — they bound plausibility, they do not predict.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.15)
    save(fig, "noida_ramp_benchmark")
    return "noida_ramp_benchmark"


def chart_nmia_tracker(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    nmia = month_series(monthly, "NMIA")
    bom = month_series(monthly, "BOM")
    if nmia.empty:
        return None
    share = (nmia / (nmia + bom.reindex(nmia.index))) * 100
    share = share.dropna()
    if share.empty:
        return None

    fig, ax = new_fig()
    x = np.arange(len(share))
    ax.plot(x, share.values, color=c.PRIMARY, **LINE, **MARK)
    for i in (0, len(share) - 1):
        ax.annotate(
            f"{share.iloc[i]:.1f}%",
            (i, share.iloc[i]),
            xytext=(0, 11),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
        )
    if len(share) >= 2:
        steps = share.diff().dropna()
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
        f"Navi Mumbai holds {share.iloc[-1]:.1f}% of Mumbai's two-airport traffic "
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
        caveat="Share steps reflect airlines moving capacity in blocks. Observational — not a Noida forecast.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_nmia_tracker")
    return "noida_nmia_tracker"


def chart_indigo_share(carrier: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    sd = carrier[carrier["service_type"] == "scheduled_domestic"]
    years = sorted(sd["year"].unique())
    complete = [y for y in years if sd[sd["year"] == y]["month"].nunique() == 12]
    if len(complete) < 2:
        return None
    shares = []
    for y in complete:
        a = sd[sd["year"] == y]
        total = a["passengers"].sum()
        indigo = a[a["airline"].str.contains("IndiGo", case=False, na=False)]["passengers"].sum()
        shares.append(indigo / total * 100 if total else np.nan)

    fig, ax = new_fig()
    ax.plot(complete, shares, color=c.PRIMARY, **LINE, **MARK)
    ax.fill_between(complete, shares, color=c.PRIMARY, alpha=0.10, linewidth=0)
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
        f"IndiGo carries {shares[-1]:.0f}% of India's domestic passengers "
        f"(was {shares[0]:.0f}% in {complete[0]})",
        "IndiGo share of scheduled domestic passengers carried, complete calendar years",
        "Share of passengers carried",
    )
    ax.set_xticks(complete)
    ax.set_ylim(0, 80)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="National share — DGCA does not publish airline traffic per airport.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_indigo_share")
    return "noida_indigo_share"


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
    trough = t12_clean.loc["2020":"2022"]
    if not trough.empty:
        tp = trough.idxmin()
        ax.annotate(
            "COVID-19",
            (mdates.date2num(tp.to_timestamp()) + 200, float(trough.min()) * 0.88),
            fontsize=9,
            color=c.MUTED,
        )
    c.style_axis(
        ax,
        f"India's domestic market grew {latest_yoy:+.1f}% in the latest 12 months, "
        f"against a {trend * 100:.0f}%-a-year {span_years}-year trend",
        "Scheduled domestic passengers carried, trailing 12-month total — counted once per journey",
        "Trailing 12-month passengers carried",
    )
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_millions))
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(x.min(), x.max() + pd.DateOffset(months=16))
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
    colors = [
        c.POSITIVE if yoy.get(m, 0) >= 1 else c.NEGATIVE if yoy.get(m, 0) <= -1 else c.DEEMPH
        for m in top.index
    ]
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
        title += f": {c.airport_label(grower)} grew fastest ({yoy[grower]:+.0f}%)"
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
            (c.DEEMPH, "Flat"),
            (c.NEGATIVE, "Declining (≤ −1%)"),
        )
    ]
    ax.legend(handles=handles, loc="lower right", frameon=False, fontsize=9, labelcolor=c.SUBTLE)
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Delhi (DEL) is an observable NCR proxy — a research queue, not a Noida forecast or route recommendation.",
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
    c.style_axis(
        ax,
        f"Delhi-region airports carried {ncr[-1]:.0f}M passengers in {complete[-1]}; "
        f"Mumbai-region {mmr[-1]:.0f}M",
        f"Annual domestic airport throughput by region: {'+'.join(NCR_AIRPORTS)} vs {'+'.join(MMR_AIRPORTS)}, complete years",
        "Annual airport passenger movements",
    )
    ax.set_xticks(complete)
    ax.set_xlim(complete[0] - 0.4, complete[-1] + 1.9)
    ax.set_ylim(0, c.clean_upper_bound(max(ncr) * 1.12))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}M")
    ax.legend(
        handles=[
            plt.Line2D([], [], color=c.PRIMARY, lw=2.2, label="Delhi region"),
            plt.Line2D([], [], color="#eb6834", lw=2.2, label="Mumbai region"),
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
        caveat="Airport throughput (arrivals + departures), not unique passengers; regions defined as listed airport sets.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_ncr_vs_mmr")
    return "noida_ncr_vs_mmr"


def chart_relief_valve(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    nmia = month_series(monthly, "NMIA")
    bom = month_series(monthly, "BOM")
    if nmia.empty or bom.empty:
        return None
    start = nmia.index[0] - 12
    periods = pd.period_range(start, bom.index.max(), freq="M")
    bom_w = bom.reindex(periods).fillna(0)
    nmia_w = nmia.reindex(periods).fillna(0)

    n = len(nmia)
    since = list(nmia.index)
    prior = [p - 12 for p in since]
    bom_since, bom_prior = bom.reindex(since).sum(), bom.reindex(prior).sum()
    sys_since = bom_since + nmia.sum()
    bom_yoy = (bom_since / bom_prior - 1) * 100 if bom_prior else np.nan
    sys_yoy = (sys_since / bom_prior - 1) * 100 if bom_prior else np.nan

    fig, ax = new_fig()
    x = periods.to_timestamp()
    ax.stackplot(x, bom_w.values, nmia_w.values, colors=[c.PRIMARY, "#eb6834"], alpha=0.85, linewidth=0)
    ax.plot(x, bom_w.values, color=c.BG, linewidth=1.5)
    entry = nmia.index[0].to_timestamp()
    ax.annotate(
        f"{c.airport_label('NMIA')} opens",
        (mdates.date2num(entry), float(bom_w.loc[nmia.index[0]] + nmia_w.loc[nmia.index[0]])),
        xytext=(-8, 16),
        textcoords="offset points",
        fontsize=9.5,
        fontweight="bold",
        color=c.TEXT,
        ha="right",
        arrowprops={"arrowstyle": "-", "color": c.MUTED, "lw": 0.8},
    )
    c.style_axis(
        ax,
        f"Since Navi Mumbai opened: CSMIA {bom_yoy:+.1f}%, the two-airport system {sys_yoy:+.1f}%",
        f"Monthly airport passenger movements at Mumbai's airports; {n}-month window since entry vs the same months a year earlier",
        "Monthly airport passenger movements",
    )
    ax.set_ylim(0, c.clean_upper_bound(float((bom_w + nmia_w).max()) * 1.15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_millions))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.legend(
        handles=[
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9, color=c.PRIMARY, label=c.airport_label("BOM")),
            plt.Line2D([], [], marker="s", linestyle="none", markersize=9, color="#eb6834", label=c.airport_label("NMIA")),
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
        caveat="Observational — system growth cannot be attributed causally to the new airport's entry.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_relief_valve")
    return "noida_relief_valve"


def chart_hindon_lesson(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    hdo = month_series(monthly, "HDO")
    if len(hdo) < 12:
        return None
    steps = hdo.diff().dropna()
    jump = steps.idxmax()
    peak = float(hdo.max())
    peak_period = hdo.idxmax()
    # Quiet window in calendar months (the series may have gaps), capped well
    # before the largest step so the ramp itself never defines the ceiling.
    first = hdo.index[0]
    quiet_span = min(60, max(12, (jump - first).n - 12))
    quiet = hdo[hdo.index < first + quiet_span]
    quiet_ceiling = float(quiet.max())
    quiet_years = quiet_span // 12

    fig, ax = new_fig()
    x = hdo.index.to_timestamp()
    ax.plot(x, hdo.values, color=c.PRIMARY, **LINE)
    ax.annotate(
        f"Largest step: {steps.max() / 1e3:+.0f}K in {jump.strftime('%b %Y')}",
        (mdates.date2num(jump.to_timestamp()), float(hdo.loc[jump])),
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
    c.style_axis(
        ax,
        f"Hindon stayed under {quiet_ceiling / 1e3:.0f}K a month in its first "
        f"{quiet_years} years, then reached {peak / 1e3:.0f}K in {peak_period.strftime('%b %Y')}",
        "Monthly airport passenger movements at Hindon (HDO), Delhi's second airport, since first DGCA observation",
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
        caveat="DGCA data shows the step, not its cause; capacity commitments can also recede.",
    )
    fig.subplots_adjust(left=0.08, right=0.95, top=0.84, bottom=0.13)
    save(fig, "noida_hindon_lesson")
    return "noida_hindon_lesson"


def chart_small_city_share(monthly: pd.DataFrame, *, coverage: str, fingerprint: str) -> str | None:
    metros = {code for code, info in c.MAPPINGS.get("airports", {}).items() if (info or {}).get("tier") == "metro"}
    complete = c.complete_calendar_years(monthly)
    if len(complete) < 2 or not metros:
        return None
    m = c.add_month_period(monthly)
    shares = []
    for y in complete:
        a = m[m["year"] == y]
        total = a["passengers"].sum()
        shares.append((1 - a[a["airport"].isin(metros)]["passengers"].sum() / total) * 100)

    fig, ax = new_fig()
    ax.bar(complete, shares, width=0.22, color=c.PRIMARY)
    for i in (0, len(complete) - 1):
        ax.annotate(
            f"{shares[i]:.0f}%",
            (complete[i], shares[i]),
            xytext=(0, 6),
            textcoords="offset points",
            fontsize=9.5,
            fontweight="bold",
            color=c.TEXT,
            ha="center",
            va="bottom",
        )
    c.style_axis(
        ax,
        f"Non-metro airports carry {shares[-1]:.0f}% of national throughput "
        f"(was {shares[0]:.0f}% in {complete[0]})",
        f"Share of national airport throughput outside the {len(metros)} metro airports, complete years",
        "Share of national throughput",
    )
    ax.set_xticks(complete)
    ax.set_ylim(0, max(50.0, max(shares) * 1.15))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(c.fmt_percent))
    c.add_footer(
        fig,
        coverage=coverage,
        fingerprint=fingerprint,
        caveat="Throughput counts each passenger at both endpoint airports; the metro set is the mappings.yaml tier classification.",
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
        "Every early Noida number reads against the national baseline — state it before someone else does.",
    ),
    "noida_beyond_trunk": (
        "The market Noida enters",
        "The realistic opportunity for a new airport is the middle market, not the metro trunk.",
    ),
    "noida_small_city_share": (
        "The market Noida enters",
        "Demand keeps spreading toward the kind of cities a second NCR airport can serve directly.",
    ),
    "noida_indigo_share": (
        "The market Noida enters",
        "A new airport's ramp-up is, in practice, a negotiation with two airline groups.",
    ),
    "noida_ncr_vs_mmr": (
        "The region",
        "The capital region's depth is the structural case for a third airport.",
    ),
    "noida_delhi_menu": (
        "The region",
        "Delhi's observable markets are the research queue for Noida's route development.",
    ),
    "noida_ramp_benchmark": (
        "The playbook",
        "The bounding curves — scale-up, replication, and flatline — frame first-24-month expectations.",
    ),
    "noida_nmia_tracker": (
        "The playbook",
        "Navi Mumbai is the live dress rehearsal: one number to watch every month.",
    ),
    "noida_relief_valve": (
        "The playbook",
        "What relief looks like: the incumbent flattens while the region grows.",
    ),
    "noida_hindon_lesson": (
        "The playbook",
        "Time does not ramp an airport; committed airline capacity does.",
    ),
}

PAGE_ORDER = [
    "noida_growth_pause",
    "noida_beyond_trunk",
    "noida_small_city_share",
    "noida_indigo_share",
    "noida_ncr_vs_mmr",
    "noida_delhi_menu",
    "noida_ramp_benchmark",
    "noida_nmia_tracker",
    "noida_relief_valve",
    "noida_hindon_lesson",
]


def write_page(generated: list[str], data_date: str | None) -> Path:
    sections: list[str] = []
    current_section = None
    for chart_id in PAGE_ORDER:
        if chart_id not in generated:
            continue
        section, standfirst = EXHIBIT_COPY[chart_id]
        if section != current_section:
            sections.append(f'      <h2 class="section-rule"><span>{section}</span></h2>')
            current_section = section
        sections.append(
            f"""      <section class="exhibit">
        <p class="standfirst">{standfirst}</p>
        <img class="chart-img" src="charts/noida/{chart_id}.png" alt="{chart_id.replace('_', ' ')}" loading="lazy">
      </section>"""
        )

    data_line = f"Data: DGCA public aviation statistics (as of {data_date})" if data_date else "Data: DGCA public aviation statistics"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Noida International Airport — india-aviation-stats</title>
  <meta name="description" content="What published DGCA data says about the market Noida International Airport (DXN) enters.">
  <meta property="og:title" content="Noida International Airport — DGCA data in charts">
  <meta property="og:image" content="charts/noida/noida_ramp_benchmark.png">
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
      ramp-up playbook written by India's other dual-airport systems — every number computed from
      published DGCA tables, every chart carrying its own caveat.</p>
      <p class="meta">Delhi (DEL) data is used throughout as an observable NCR proxy — nothing here is a
      Noida forecast. <a href="index.html">&larr; Main dashboard</a></p>
    </header>
{chr(10).join(sections)}
    <footer>
      <p>{data_line}. Charts regenerate from the published CSV tables in
      <a href="https://github.com/mkubicek/india-aviation-stats">india-aviation-stats</a>;
      exhibits that need the route-level table appear automatically once it is published.</p>
    </footer>
  </div>
</body>
</html>
"""
    PAGE_PATH.write_text(html, encoding="utf-8")
    return PAGE_PATH


def main() -> None:
    print("=== Generating Noida charts ===\n", flush=True)
    monthly = c.load_domestic_monthly()
    carrier = c.load_carrier_monthly()
    routes = load_routes()

    monthly_cov = c.domestic_coverage(monthly)
    carrier_cov = c.carrier_domestic_coverage(carrier)
    monthly_fp = c.input_fingerprint([c.DOMESTIC_MONTHLY_PATH])
    carrier_fp = c.input_fingerprint([c.CARRIER_MONTHLY_PATH])

    generated: list[str] = []
    for result in (
        chart_growth_pause(carrier, coverage=carrier_cov, fingerprint=carrier_fp),
        chart_indigo_share(carrier, coverage=carrier_cov, fingerprint=carrier_fp),
        chart_small_city_share(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
        chart_ncr_vs_mmr(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
        chart_ramp_benchmark(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
        chart_nmia_tracker(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
        chart_relief_valve(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
        chart_hindon_lesson(monthly, coverage=monthly_cov, fingerprint=monthly_fp),
    ):
        if result:
            generated.append(result)
            print(f"  Saved: charts/noida/{result}.png", flush=True)

    if routes is not None:
        route_cov = f"{routes['period'].min()}..{routes['period'].max()}"
        route_fp = c.input_fingerprint([ROUTE_MONTHLY_PATH])
        for result in (
            chart_beyond_trunk(routes, coverage=route_cov, fingerprint=route_fp),
            chart_delhi_menu(routes, coverage=route_cov, fingerprint=route_fp),
        ):
            if result:
                generated.append(result)
                print(f"  Saved: charts/noida/{result}.png", flush=True)
    else:
        print("  Skipped route-level exhibits (data/processed/domestic_route_monthly.csv not published)", flush=True)

    meta = c.load_metadata()
    page = write_page(generated, meta.get("data_date"))
    print(f"  Saved: {page.relative_to(ROOT)} ({len(generated)} exhibits)", flush=True)
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
