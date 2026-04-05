"""Plausibility checks for India aviation data.

All checks are advisory — warnings are logged but never block the pipeline.
Output: warnings.log (unified with unmapped-value warnings from process.py).
"""

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
REFERENCE = yaml.safe_load((ROOT / "reference.yaml").read_text())
WARNINGS_PATH = ROOT / "warnings.log"

YEARLY_TOLERANCE = 0.05       # ±5% for national totals
AIRPORT_TOLERANCE = 0.10      # ±10% for airport totals
YOY_SPIKE_THRESHOLD = 0.50    # >50% YoY change flagged
COVID_YEARS = {2020, 2021}    # Excluded from spike checks


def check_national_totals(macro: pd.DataFrame) -> list[str]:
    """Compare yearly national passenger totals against reference."""
    warnings = []
    ref = REFERENCE.get("national_passengers", {})

    for _, row in macro.iterrows():
        year = int(row["year"])
        if year not in ref:
            continue
        if pd.isna(row.get("air_passengers")):
            continue

        actual = row["air_passengers"]
        expected = ref[year]
        diff_pct = abs(actual - expected) / expected

        if diff_pct > YEARLY_TOLERANCE:
            warnings.append(
                f"plausibility:national_total:{year}: "
                f"actual={actual:,.0f} vs reference={expected:,.0f} "
                f"(diff={diff_pct:.1%}, tolerance={YEARLY_TOLERANCE:.0%})"
            )

    return warnings


def check_airport_totals() -> list[str]:
    """Compare major airport totals against reference."""
    warnings = []
    ref_airports = REFERENCE.get("airport_passengers", {})
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"

    if not yearly_path.exists():
        return ["plausibility:airport_totals: airport_yearly.csv not found"]

    yearly = pd.read_csv(yearly_path)
    if yearly.empty:
        return []

    latest_year = yearly["year"].max()
    latest = yearly[yearly["year"] == latest_year]

    for iata, expected in ref_airports.items():
        airport_data = latest[latest["airport"].str.upper() == iata]
        if airport_data.empty:
            continue

        actual = airport_data["passengers"].sum()
        diff_pct = abs(actual - expected) / expected

        if diff_pct > AIRPORT_TOLERANCE:
            warnings.append(
                f"plausibility:airport_total:{iata}:{latest_year}: "
                f"actual={actual:,.0f} vs reference={expected:,.0f} "
                f"(diff={diff_pct:.1%}, tolerance={AIRPORT_TOLERANCE:.0%})"
            )

    return warnings


def check_growth_rates(macro: pd.DataFrame) -> list[str]:
    """Flag suspiciously large year-over-year changes (excluding COVID years)."""
    warnings = []
    pax = macro.dropna(subset=["air_passengers"]).sort_values("year")

    for i in range(1, len(pax)):
        year = int(pax.iloc[i]["year"])
        prev_year = int(pax.iloc[i - 1]["year"])

        if year in COVID_YEARS or prev_year in COVID_YEARS:
            continue
        if year != prev_year + 1:
            continue

        current = pax.iloc[i]["air_passengers"]
        previous = pax.iloc[i - 1]["air_passengers"]

        if previous > 0:
            change = abs(current - previous) / previous
            if change > YOY_SPIKE_THRESHOLD:
                direction = "increase" if current > previous else "decrease"
                warnings.append(
                    f"plausibility:yoy_spike:{year}: "
                    f"{change:.1%} {direction} vs {prev_year} "
                    f"({previous:,.0f} → {current:,.0f})"
                )

    return warnings


def check_tier_consistency() -> list[str]:
    """Verify airport tier matches actual passenger volume."""
    warnings = []
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"

    if not yearly_path.exists():
        return []

    yearly = pd.read_csv(yearly_path)
    if yearly.empty:
        return []

    latest_year = yearly["year"].max()
    latest = yearly[yearly["year"] == latest_year].groupby("airport")["passengers"].sum()

    mappings = yaml.safe_load((ROOT / "mappings.yaml").read_text())
    airports = mappings.get("airports", {})

    for iata, pax in latest.items():
        if iata not in airports:
            continue

        defined_tier = airports[iata].get("tier", "tier3")
        if defined_tier == "greenfield":
            continue

        # Check if volume matches tier
        if pax > 20_000_000 and defined_tier != "metro":
            warnings.append(
                f"plausibility:tier_mismatch:{iata}: "
                f"{pax:,.0f} pax suggests metro, defined as {defined_tier}"
            )
        elif 5_000_000 < pax <= 20_000_000 and defined_tier not in ("tier1", "metro"):
            warnings.append(
                f"plausibility:tier_mismatch:{iata}: "
                f"{pax:,.0f} pax suggests tier1, defined as {defined_tier}"
            )

    return warnings


def check_gdp_correlation() -> list[str]:
    """Advisory check: R² of GDP–flights correlation should exceed 0.85."""
    warnings = []
    macro_path = PROCESSED_DIR / "india_macro.csv"

    if not macro_path.exists():
        return []

    macro = pd.read_csv(macro_path)
    valid = macro.dropna(subset=["gdp_per_capita_ppp", "flights_per_capita"])

    if len(valid) < 5:
        return ["plausibility:gdp_correlation: insufficient data points"]

    import numpy as np

    x = np.log(valid["gdp_per_capita_ppp"].values)
    y = np.log(valid["flights_per_capita"].values)

    # Simple R² calculation
    correlation = np.corrcoef(x, y)[0, 1]
    r_squared = correlation ** 2

    if r_squared < 0.85:
        warnings.append(
            f"plausibility:gdp_correlation: R²={r_squared:.3f} "
            f"(below 0.85 threshold)"
        )
    else:
        print(f"  GDP–flights R² = {r_squared:.3f} (OK)", flush=True)

    return warnings


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Validating Data ===\n", flush=True)
    all_warnings = []

    # Load macro data
    macro_path = PROCESSED_DIR / "india_macro.csv"
    if macro_path.exists():
        macro = pd.read_csv(macro_path)
        all_warnings.extend(check_national_totals(macro))
        all_warnings.extend(check_growth_rates(macro))
        all_warnings.extend(check_gdp_correlation())
    else:
        all_warnings.append("plausibility:macro: india_macro.csv not found")

    all_warnings.extend(check_airport_totals())
    all_warnings.extend(check_tier_consistency())

    # Merge with any existing warnings (from process.py unmapped values)
    existing = []
    if WARNINGS_PATH.exists():
        existing = [
            line.strip()
            for line in WARNINGS_PATH.read_text().splitlines()
            if line.strip() and line.startswith("unmapped:")
        ]

    combined = existing + all_warnings
    WARNINGS_PATH.write_text("\n".join(combined) + "\n" if combined else "")

    n_plausibility = len(all_warnings)
    n_unmapped = len(existing)
    print(f"  {n_plausibility} plausibility warning(s), {n_unmapped} unmapped value(s)")
    for w in all_warnings:
        print(f"  ⚠ {w}", flush=True)

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
