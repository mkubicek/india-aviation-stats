"""Advisory validation checks for processed India aviation source data.

Validation never blocks the pipeline. Warnings are written to warnings.log and
printed for CI visibility.
"""

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
WARNINGS_PATH = ROOT / "warnings.log"
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())


def _period_range(start: pd.Period, end: pd.Period) -> list[pd.Period]:
    periods = []
    current = start
    while current <= end:
        periods.append(current)
        current += 1
    return periods


def _complete_years(monthly: pd.DataFrame) -> list[int]:
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


def check_required_files() -> list[str]:
    warnings = []
    for filename in ["airport_monthly.csv", "airport_yearly.csv", "carrier_monthly.csv"]:
        if not (PROCESSED_DIR / filename).exists():
            warnings.append(f"missing_file:{filename}")
    return warnings


def check_domestic_month_coverage(monthly: pd.DataFrame) -> list[str]:
    domestic = monthly[monthly["category"] == "domestic"]
    if domestic.empty:
        return ["coverage:domestic: no domestic rows"]

    observed = set(
        pd.Period(year=int(row.year), month=int(row.month), freq="M")
        for row in domestic[["year", "month"]].drop_duplicates().itertuples(index=False)
    )
    expected = set(_period_range(min(observed), max(observed)))
    missing = sorted(expected - observed)
    if not missing:
        return []
    labels = ", ".join(str(period) for period in missing[:12])
    suffix = "..." if len(missing) > 12 else ""
    return [f"coverage:domestic: missing {len(missing)} month(s): {labels}{suffix}"]


def check_international_quarter_coverage(monthly: pd.DataFrame) -> list[str]:
    international = monthly[monthly["category"] == "international"]
    if international.empty:
        return []

    observed = set(
        (int(row.year), int(row.month))
        for row in international[["year", "month"]].drop_duplicates().itertuples(index=False)
    )
    observed_periods = sorted(pd.Period(year=year, month=month, freq="M") for year, month in observed)
    expected = [
        period
        for period in _period_range(min(observed_periods), max(observed_periods))
        if period.month in {2, 5, 8, 11}
    ]
    missing = [period for period in expected if (period.year, period.month) not in observed]
    if not missing:
        return []
    labels = ", ".join(str(period) for period in missing[:12])
    suffix = "..." if len(missing) > 12 else ""
    return [f"coverage:international: missing {len(missing)} quarter(s): {labels}{suffix}"]


def check_negative_passengers(monthly: pd.DataFrame) -> list[str]:
    negative = monthly[monthly["passengers"] < 0]
    if negative.empty:
        return []
    return [f"values:passengers: {len(negative)} negative passenger row(s)"]


def check_duplicate_airport_periods(monthly: pd.DataFrame) -> list[str]:
    key = ["year", "month", "airport", "category"]
    duplicate_count = int(monthly.duplicated(key).sum())
    if duplicate_count == 0:
        return []
    examples = (
        monthly.loc[monthly.duplicated(key, keep=False), key]
        .drop_duplicates()
        .sort_values(key)
        .head(5)
    )
    labels = ", ".join(
        f"{row.year}-{int(row.month):02d}:{row.airport}:{row.category}"
        for row in examples.itertuples(index=False)
    )
    suffix = "..." if duplicate_count > len(examples) else ""
    return [
        "grain:airport_monthly: "
        f"{duplicate_count} duplicate airport-period-category row(s): "
        f"{labels}{suffix}"
    ]


def check_tier_consistency(monthly: pd.DataFrame, yearly: pd.DataFrame) -> list[str]:
    complete_years = _complete_years(monthly)
    if not complete_years:
        return []

    latest_year = complete_years[-1]
    latest = (
        yearly[yearly["year"] == latest_year]
        .groupby("airport")["passengers"]
        .sum()
    )

    warnings = []
    airports = MAPPINGS.get("airports", {})
    for iata, passengers in latest.items():
        if iata not in airports:
            continue
        defined_tier = airports[iata].get("tier", "tier3")
        if defined_tier == "greenfield":
            continue
        if passengers > 20_000_000 and defined_tier != "metro":
            warnings.append(
                f"tier:{iata}:{latest_year}: {passengers:,.0f} pax suggests metro, "
                f"defined as {defined_tier}"
            )
        elif 5_000_000 < passengers <= 20_000_000 and defined_tier not in ("tier1", "metro"):
            warnings.append(
                f"tier:{iata}:{latest_year}: {passengers:,.0f} pax suggests tier1, "
                f"defined as {defined_tier}"
            )
    return warnings


def main() -> None:
    print("=== Validating Data ===\n", flush=True)
    warnings = check_required_files()

    monthly_path = PROCESSED_DIR / "airport_monthly.csv"
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"
    if monthly_path.exists():
        monthly = pd.read_csv(monthly_path)
        warnings.extend(check_domestic_month_coverage(monthly))
        warnings.extend(check_international_quarter_coverage(monthly))
        warnings.extend(check_negative_passengers(monthly))
        warnings.extend(check_duplicate_airport_periods(monthly))

        if yearly_path.exists():
            yearly = pd.read_csv(yearly_path)
            warnings.extend(check_tier_consistency(monthly, yearly))

    WARNINGS_PATH.write_text("\n".join(warnings) + "\n" if warnings else "")
    print(f"  {len(warnings)} warning(s)")
    for warning in warnings:
        print(f"  WARNING: {warning}", flush=True)

    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
