"""Monthly delta report generator for India aviation statistics.

Generates markdown reports with:
  - National passenger totals (MoM, YoY, YTD comparisons)
  - Top airports by volume
  - Growth highlights
  - Projection status

Output: reports/YYYY-MM.md
"""

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
SNAPSHOTS_MONTHLY = PROCESSED_DIR / "snapshots" / "monthly"
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}

DISCLAIMER = (
    "This is a personal open-source project. Views and analysis are my own "
    "and do not represent Flughafen Zürich AG, Noida International Airport, "
    "or any affiliated entity."
)


def pct_change(new: float, old: float) -> str:
    """Format percentage change with arrow."""
    if old == 0:
        return "N/A"
    change = (new - old) / old * 100
    arrow = "+" if change >= 0 else ""
    return f"{arrow}{change:.1f}%"


def delta_str(new: float, old: float) -> str:
    """Format absolute + percentage change."""
    diff = new - old
    pct = pct_change(new, old)
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:,.0f} ({pct})"


def _load_milestones() -> dict | None:
    """Load milestones.json if present. Returns None if missing/invalid."""
    path = PROCESSED_DIR / "milestones.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _load_prior_monthly_snapshot(year: int, month: int) -> dict | None:
    """Load the most recent monthly snapshot that predates (year, month)."""
    if not SNAPSHOTS_MONTHLY.exists():
        return None
    tag = f"{year:04d}-{month:02d}"
    prior = sorted(p for p in SNAPSHOTS_MONTHLY.glob("*.json") if p.stem < tag)
    if not prior:
        return None
    try:
        return json.loads(prior[-1].read_text())
    except json.JSONDecodeError:
        return None


def _build_milestones_section(year: int, month: int) -> list[str]:
    """Return markdown lines for the Milestones section of the monthly report.

    Surfaces projected→achieved transitions as lead items. Shows current
    projected milestones with p10/p50/p90 and, when a prior monthly snapshot
    exists, the year-over-year delta for each.
    """
    m = _load_milestones()
    if not m:
        return ["", "## Milestones", "", "_milestones.json not available — run scripts/milestones.py_"]

    prior = _load_prior_monthly_snapshot(year, month)

    lines: list[str] = ["", "## Milestones", ""]

    # Lead: newly-achieved milestones (transitioned from projected → achieved)
    newly_achieved: list[tuple[str, dict]] = []
    current_achieved = m.get("achieved") or {}
    prior_achieved = (prior or {}).get("achieved") or {}
    for mid, entry in current_achieved.items():
        if mid not in prior_achieved:
            newly_achieved.append((mid, entry))

    if newly_achieved:
        lines.append("### Newly achieved")
        lines.append("")
        for mid, entry in newly_achieved:
            label = entry.get("label", mid)
            yr = entry.get("actual_year")
            val = entry.get("actual_value")
            val_str = f" ({val:,.0f} pax)" if isinstance(val, (int, float)) else ""
            lines.append(f"- **{label}** — achieved in {yr}{val_str}")
        lines.append("")

    # Projected
    projected = m.get("projected") or {}
    prior_projected = (prior or {}).get("projected") or {}
    if projected:
        lines.append("### Projected")
        lines.append("")
        lines.append("| Milestone | Threshold | p10 | p50 | p90 | Δ p50 vs prior |")
        lines.append("|-----------|----------:|----:|----:|----:|---------------:|")
        for mid, entry in projected.items():
            label = entry.get("label", mid)
            thr = entry.get("threshold")
            thr_str = _format_threshold_for_report(thr, entry.get("metric", ""))
            p50 = entry.get("p50_year")
            if p50 is None:
                p_cells = ("—", ">2040", "—")
            else:
                p_cells = (
                    str(entry.get("p10_year") or "—"),
                    str(p50),
                    str(entry.get("p90_year") or "—"),
                )
            delta = ""
            prior_p50 = (prior_projected.get(mid) or {}).get("p50_year")
            if prior_p50 is not None and p50 is not None:
                diff = int(p50) - int(prior_p50)
                if diff == 0:
                    delta = "—"
                else:
                    sign = "+" if diff > 0 else ""
                    delta = f"{sign}{diff}y"
            lines.append(
                f"| {label} | {thr_str} | {p_cells[0]} | {p_cells[1]} | {p_cells[2]} | {delta} |"
            )
        lines.append("")

    # Scheduled (footnote style)
    scheduled = m.get("scheduled") or {}
    if scheduled:
        lines.append("### Scheduled (greenfield airports)")
        lines.append("")
        for mid, entry in scheduled.items():
            label = entry.get("label", mid)
            sd = entry.get("scheduled_date") or "TBD"
            cap = entry.get("phase1_capacity")
            cap_str = f", phase-1 capacity {cap/1e6:.0f}M" if cap else ""
            lines.append(f"- _{label}_ — scheduled {sd}{cap_str}")
        lines.append("")

    return lines


def _format_threshold_for_report(threshold, metric: str) -> str:
    if threshold is None:
        return ""
    if metric == "tier_share":
        return f"{threshold * 100:.0f}%"
    t = float(threshold)
    if t >= 1e9:
        return f"{t / 1e9:.1f}B pax"
    if t >= 1e6:
        return f"{t / 1e6:.0f}M pax"
    return f"{t:,.0f}"


def _write_monthly_snapshot(year: int, month: int) -> None:
    """Persist a monthly snapshot of milestones.json for next-month diffing."""
    m = _load_milestones()
    if not m:
        return
    SNAPSHOTS_MONTHLY.mkdir(parents=True, exist_ok=True)
    tag = f"{year:04d}-{month:02d}"
    (SNAPSHOTS_MONTHLY / f"{tag}.json").write_text(json.dumps(m, indent=2))


def generate_report(target_year: int = None, target_month: int = None):
    """Generate a monthly delta report."""
    # Load macro data for national overview
    macro_path = PROCESSED_DIR / "india_macro.csv"
    if not macro_path.exists():
        print("  WARNING: india_macro.csv not found, generating skeleton report")
        macro = pd.DataFrame()
    else:
        macro = pd.read_csv(macro_path)

    # Load projection data
    proj_path = PROCESSED_DIR / "projection.json"
    projection = {}
    if proj_path.exists():
        projection = json.loads(proj_path.read_text())

    # Load metadata
    meta_path = PROCESSED_DIR / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    data_date = meta.get("data_date", str(date.today()))

    # Determine report period
    today = date.today()
    if target_year and target_month:
        year, month = target_year, target_month
    else:
        # Default: most recent complete month
        if today.month == 1:
            year, month = today.year - 1, 12
        else:
            year, month = today.year, today.month - 1

    month_name = MONTH_NAMES.get(month, str(month))

    # Get latest available annual data
    latest_actual = None
    if not macro.empty and "air_passengers" in macro.columns:
        valid = macro.dropna(subset=["air_passengers"]).sort_values("year")
        if not valid.empty:
            latest_actual = valid.iloc[-1]

    # Projection data
    regression = projection.get("regression", {})
    nat_timeline = projection.get("national_timeline", [])

    # Find 2030, 2035, 2040 projections
    proj_milestones = {}
    for entry in nat_timeline:
        if entry.get("type") == "projected" and entry["year"] in (2030, 2035, 2040):
            proj_milestones[entry["year"]] = entry

    # ── Build report ──────────────────────────────────────────

    lines = [
        f"# India Aviation Market Report: {month_name} {year}",
        "",
        f"*Generated {datetime.now().strftime('%Y-%m-%d')} | "
        f"Data as of {data_date}*",
        "",
        f"> {DISCLAIMER}",
        "",
        "## Headlines",
        "",
    ]

    if latest_actual is not None:
        pax = latest_actual["air_passengers"]
        yr = int(latest_actual["year"])
        fpc = latest_actual.get("flights_per_capita", 0)
        gdp = latest_actual.get("gdp_per_capita_ppp", 0)

        lines.extend([
            f"- **{pax / 1e6:,.0f}M** air passengers in {yr} (latest annual data)",
            f"- Flights per capita: **{fpc:.3f}**",
            f"- GDP per capita (PPP): **${gdp:,.0f}**",
        ])
    else:
        lines.append("- Annual passenger data not yet available")

    if regression:
        lines.append(
            f"- GDP\u2013flights correlation: R\u00b2 = **{regression.get('r_squared', 0):.3f}**"
        )

    lines.extend(["", "## Growth Projection", ""])

    if proj_milestones:
        lines.extend([
            "| Year | Projected Passengers | Flights/Capita | GDP/Capita (PPP) |",
            "|------|---------------------:|---------------:|-----------------:|",
        ])
        for yr in sorted(proj_milestones.keys()):
            e = proj_milestones[yr]
            lines.append(
                f"| {yr} | {e['passengers'] / 1e6:,.0f}M | "
                f"{e.get('flights_per_capita', 0):.3f} | "
                f"${e.get('gdp_per_capita_ppp', 0):,.0f} |"
            )
    else:
        lines.append("Projection data not yet available. Run project.py first.")

    # \u2500\u2500 Milestones section (appended between Projection and Methodology) \u2500\u2500
    lines.extend(_build_milestones_section(year, month))

    lines.extend([
        "",
        "## Methodology",
        "",
        "Projections use a log-log OLS regression of flights per capita on "
        "GDP per capita (PPP), fitted on 20 years of Indian data excluding "
        "COVID years (2020\u20132021). GDP for 2025\u20132040 uses log-linear "
        "extrapolation from the last 10 observed years; IMF WEO integration "
        "is a planned v1.1 upgrade. See [METHODOLOGY.md](../METHODOLOGY.md) "
        "for full details and known limitations.",
        "",
        "## Key Context",
        "",
    ])

    # Recent milestones
    milestones = MAPPINGS.get("milestones", [])
    recent_milestones = [
        m for m in milestones
        if m["date"][:4] in (str(year), str(year - 1))
    ]
    if recent_milestones:
        for m in recent_milestones[-5:]:
            lines.append(f"- **{m['date']}:** {m['label']} \u2014 {m['description']}")
    else:
        lines.append("- No recent milestones in reporting period")

    lines.extend([
        "",
        "---",
        "",
        f"*Data sources: World Bank Open Data, DGCA, MoCA*",
    ])

    # Save report
    filename = f"{year}-{month:02d}.md"
    report_path = REPORT_DIR / filename
    report_path.write_text("\n".join(lines) + "\n")
    print(f"  Saved: {report_path}")

    # Persist a monthly snapshot of milestones.json so next month can diff
    _write_monthly_snapshot(year, month)

    return report_path


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Generating Report ===\n", flush=True)
    generate_report()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
