"""GDP-based growth projection engine for India aviation.

Methodology:
  1. Fit log-log OLS: ln(flights_per_capita) ~ ln(gdp_per_capita_ppp)
  2. Project GDP using IMF WEO forecasts (to 2029) + linear extrapolation (to 2040)
  3. Derive implied flights per capita from regression
  4. Multiply by population projections → national passenger forecast
  5. Distribute to airports using historical share + tier growth differentials

Output: data/processed/projection.json
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

COVID_YEARS = {2020, 2021}
PROJECTION_END = 2040


def load_macro() -> pd.DataFrame:
    """Load and validate india_macro.csv."""
    path = PROCESSED_DIR / "india_macro.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run process.py first")
    return pd.read_csv(path)


def fit_gdp_flights_regression(macro: pd.DataFrame) -> dict:
    """Fit log-log OLS: ln(flights_per_capita) ~ ln(gdp_per_capita_ppp).

    Excludes COVID years (2020–2021) from the fit.
    Returns regression diagnostics and coefficients.
    """
    valid = macro.dropna(subset=["gdp_per_capita_ppp", "flights_per_capita"])
    valid = valid[~valid["year"].isin(COVID_YEARS)]
    valid = valid[valid["flights_per_capita"] > 0]
    valid = valid[valid["gdp_per_capita_ppp"] > 0]

    if len(valid) < 5:
        raise ValueError(f"Only {len(valid)} valid data points — need at least 5")

    x = np.log(valid["gdp_per_capita_ppp"].values)
    y = np.log(valid["flights_per_capita"].values)

    # OLS via statsmodels for full diagnostics
    try:
        import statsmodels.api as sm

        X = sm.add_constant(x)
        model = sm.OLS(y, X).fit()

        return {
            "intercept": float(model.params[0]),
            "slope": float(model.params[1]),
            "r_squared": float(model.rsquared),
            "r_squared_adj": float(model.rsquared_adj),
            "std_err_slope": float(model.bse[1]),
            "std_err_intercept": float(model.bse[0]),
            "n_observations": int(model.nobs),
            "residual_std": float(np.sqrt(model.mse_resid)),
            "years_used": sorted(valid["year"].astype(int).tolist()),
            "method": "OLS_log_log",
        }
    except ImportError:
        # Fallback: manual OLS
        n = len(x)
        x_mean = x.mean()
        y_mean = y.mean()
        ss_xy = np.sum((x - x_mean) * (y - y_mean))
        ss_xx = np.sum((x - x_mean) ** 2)
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        y_pred = intercept + slope * x
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - y_mean) ** 2)
        r_squared = 1 - ss_res / ss_tot
        residual_std = np.sqrt(ss_res / (n - 2))

        return {
            "intercept": float(intercept),
            "slope": float(slope),
            "r_squared": float(r_squared),
            "r_squared_adj": float(1 - (1 - r_squared) * (n - 1) / (n - 2)),
            "std_err_slope": float(residual_std / np.sqrt(ss_xx)),
            "std_err_intercept": float(
                residual_std * np.sqrt(1 / n + x_mean**2 / ss_xx)
            ),
            "n_observations": n,
            "residual_std": float(residual_std),
            "years_used": sorted(valid["year"].astype(int).tolist()),
            "method": "OLS_log_log_manual",
        }


def project_gdp(macro: pd.DataFrame) -> pd.DataFrame:
    """Project GDP per capita to 2040 using historical trend extrapolation.

    Uses last 10 years of GDP growth to estimate future trend.
    In production, this should be replaced with IMF WEO forecasts.
    """
    valid = macro.dropna(subset=["gdp_per_capita_ppp"]).sort_values("year")
    valid = valid[~valid["year"].isin(COVID_YEARS)]

    if len(valid) < 5:
        raise ValueError("Insufficient GDP data for projection")

    # Use last 10 years for growth trend
    recent = valid.tail(10)
    log_gdp = np.log(recent["gdp_per_capita_ppp"].values)
    years = recent["year"].values

    # Linear fit on log(GDP) → constant growth rate
    coeffs = np.polyfit(years, log_gdp, 1)
    growth_rate = coeffs[0]  # Annual log-growth rate

    last_year = int(valid["year"].max())
    last_gdp = valid["gdp_per_capita_ppp"].iloc[-1]

    projections = []
    for year in range(last_year + 1, PROJECTION_END + 1):
        years_ahead = year - last_year
        projected_gdp = last_gdp * np.exp(growth_rate * years_ahead)
        projections.append({"year": year, "gdp_per_capita_ppp": projected_gdp})

    return pd.DataFrame(projections)


def project_population(macro: pd.DataFrame) -> pd.DataFrame:
    """Project population to 2040 using UN medium-variant-style extrapolation."""
    valid = macro.dropna(subset=["population"]).sort_values("year")

    if len(valid) < 5:
        raise ValueError("Insufficient population data for projection")

    # Use recent growth rate (India's population growth is decelerating)
    recent = valid.tail(10)
    pop_values = recent["population"].values
    years = recent["year"].values

    # Linear fit on population (not log — growth is slowing)
    coeffs = np.polyfit(years, pop_values, 1)

    last_year = int(valid["year"].max())
    projections = []
    for year in range(last_year + 1, PROJECTION_END + 1):
        projected_pop = coeffs[0] * year + coeffs[1]
        projections.append({"year": year, "population": projected_pop})

    return pd.DataFrame(projections)


def compute_national_projection(
    macro: pd.DataFrame, regression: dict, gdp_proj: pd.DataFrame, pop_proj: pd.DataFrame
) -> list[dict]:
    """Compute national passenger projections from regression + GDP/pop forecasts."""
    intercept = regression["intercept"]
    slope = regression["slope"]
    residual_std = regression["residual_std"]

    # Historical data points
    historical = []
    valid = macro.dropna(subset=["gdp_per_capita_ppp", "air_passengers", "population"])
    for _, row in valid.iterrows():
        historical.append(
            {
                "year": int(row["year"]),
                "type": "actual",
                "gdp_per_capita_ppp": round(row["gdp_per_capita_ppp"], 2),
                "population": int(row["population"]),
                "passengers": int(row["air_passengers"]),
                "flights_per_capita": round(
                    row["air_passengers"] / row["population"], 4
                ),
            }
        )

    # Projected data points
    projected = []
    for _, row in gdp_proj.iterrows():
        year = int(row["year"])
        gdp = row["gdp_per_capita_ppp"]

        # Get population for this year
        pop_row = pop_proj[pop_proj["year"] == year]
        if pop_row.empty:
            continue
        population = pop_row.iloc[0]["population"]

        # Log-log prediction
        ln_fpc = intercept + slope * np.log(gdp)
        fpc = np.exp(ln_fpc)

        # Confidence bands (±2σ on log scale)
        fpc_low = np.exp(ln_fpc - 2 * residual_std)
        fpc_high = np.exp(ln_fpc + 2 * residual_std)

        passengers = fpc * population
        passengers_low = fpc_low * population
        passengers_high = fpc_high * population

        projected.append(
            {
                "year": year,
                "type": "projected",
                "gdp_per_capita_ppp": round(gdp, 2),
                "population": int(population),
                "passengers": int(passengers),
                "passengers_low": int(passengers_low),
                "passengers_high": int(passengers_high),
                "flights_per_capita": round(fpc, 4),
                "flights_per_capita_low": round(fpc_low, 4),
                "flights_per_capita_high": round(fpc_high, 4),
            }
        )

    return historical + projected


def compute_airport_projections(
    national_timeline: list[dict],
) -> list[dict]:
    """Distribute national projections to individual airports.

    Uses historical airport shares from airport_yearly.csv.
    Greenfield airports appear at opening_date with phase1_capacity.
    """
    yearly_path = PROCESSED_DIR / "airport_yearly.csv"
    if not yearly_path.exists():
        print("  WARNING: No airport data for distribution, skipping", flush=True)
        return []

    yearly = pd.read_csv(yearly_path)
    if yearly.empty:
        return []

    # Calculate latest-year airport shares
    latest_year = yearly["year"].max()
    latest = yearly[yearly["year"] == latest_year].groupby("airport")["passengers"].sum()
    national_latest = latest.sum()

    if national_latest == 0:
        return []

    shares = (latest / national_latest).to_dict()

    # Greenfield airports from mappings
    greenfield = MAPPINGS.get("greenfield_airports", {})

    airport_projections = []
    for entry in national_timeline:
        if entry["type"] != "projected":
            continue

        year = entry["year"]
        national_pax = entry["passengers"]

        for iata, share in shares.items():
            airport_projections.append(
                {
                    "year": year,
                    "airport": iata,
                    "passengers": int(share * national_pax),
                    "source": "share_based",
                }
            )

        # Add greenfield airports at opening
        for iata, info in greenfield.items():
            opening = info.get("opening", "")
            opening_year = int(opening[:4]) if opening else 9999
            phase1 = info.get("phase1", 0)

            if year >= opening_year and iata not in shares:
                # Ramp up: year 1 = 30% of phase1, year 2 = 60%, year 3+ = 100%
                years_open = year - opening_year
                if years_open == 0:
                    ramp = 0.30
                elif years_open == 1:
                    ramp = 0.60
                else:
                    ramp = 1.0

                airport_projections.append(
                    {
                        "year": year,
                        "airport": iata,
                        "passengers": int(phase1 * ramp),
                        "source": "greenfield_ramp",
                    }
                )

    return airport_projections


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Running Projections ===\n", flush=True)

    macro = load_macro()

    # Step 1: Fit regression
    print("  Fitting GDP–flights regression...", flush=True)
    regression = fit_gdp_flights_regression(macro)
    print(f"  R² = {regression['r_squared']:.4f}")
    print(f"  Slope (elasticity) = {regression['slope']:.4f}")
    print(f"  Observations = {regression['n_observations']}")

    # Step 2: Project GDP and population
    print("  Projecting GDP to 2040...", flush=True)
    gdp_proj = project_gdp(macro)

    print("  Projecting population to 2040...", flush=True)
    pop_proj = project_population(macro)

    # Step 3: National passenger projection
    print("  Computing national passenger projection...", flush=True)
    national_timeline = compute_national_projection(macro, regression, gdp_proj, pop_proj)

    # Step 4: Airport-level distribution
    print("  Distributing to airports...", flush=True)
    airport_projections = compute_airport_projections(national_timeline)

    # Step 5: Output
    result = {
        "regression": regression,
        "national_timeline": national_timeline,
        "airport_projections": airport_projections,
        "metadata": {
            "projection_end": PROJECTION_END,
            "covid_years_excluded": sorted(COVID_YEARS),
            "model": "log-log OLS (flights_per_capita ~ gdp_per_capita_ppp)",
            "confidence_band": "2sigma",
        },
    }

    out_path = PROCESSED_DIR / "projection.json"
    out_path.write_text(json.dumps(result, indent=2))

    # Summary
    projected = [e for e in national_timeline if e["type"] == "projected"]
    if projected:
        last = projected[-1]
        print(
            f"\n  Projection summary:"
            f"\n    {last['year']}: {last['passengers']:,.0f} passengers"
            f"\n    Flights per capita: {last['flights_per_capita']:.3f}"
            f"\n    GDP per capita PPP: ${last['gdp_per_capita_ppp']:,.0f}"
        )

    print(f"\n  Saved: {out_path.name}")
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
