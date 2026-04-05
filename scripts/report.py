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

    lines.extend([
        "",
        "## Methodology",
        "",
        "Projections use a log-log OLS regression of flights per capita on "
        "GDP per capita (PPP), fitted on 20 years of Indian data excluding "
        "COVID years (2020\u20132021). GDP projections from IMF WEO forecasts "
        "extrapolated to 2040. See [METHODOLOGY.md](../METHODOLOGY.md) for "
        "full details.",
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
        f"*Data sources: World Bank Open Data, Vonter/india-aviation-traffic, "
        f"DGCA*",
    ])

    # Save report
    filename = f"{year}-{month:02d}.md"
    report_path = REPORT_DIR / filename
    report_path.write_text("\n".join(lines) + "\n")
    print(f"  Saved: {report_path}")
    return report_path


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Generating Report ===\n", flush=True)
    generate_report()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
