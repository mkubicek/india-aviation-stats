"""Shared pytest fixtures.

Synthetic data helpers so tests don't depend on the live data pipeline
(data/processed/ files are gitignored and may not exist locally).
"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_macro():
    """A macro dataframe that recovers a known log-log relationship.

    ln(fpc) = -3.0 + 1.5 * ln(gdp) + N(0, 0.05)
    20 years, 2005-2024, with modest noise.
    """
    rng = np.random.default_rng(42)
    years = np.arange(2005, 2025)
    gdp = np.linspace(2000, 12000, len(years))
    true_intercept = -3.0
    true_slope = 1.5
    ln_fpc = true_intercept + true_slope * np.log(gdp) + rng.normal(0, 0.05, len(years))
    fpc = np.exp(ln_fpc)
    population = np.linspace(1.15e9, 1.45e9, len(years))
    air_passengers = fpc * population

    return pd.DataFrame(
        {
            "year": years,
            "gdp_per_capita_ppp": gdp,
            "population": population,
            "air_passengers": air_passengers,
            "flights_per_capita": fpc,
        }
    )


@pytest.fixture
def synthetic_macro_with_covid(synthetic_macro):
    """Same as synthetic_macro but with anomalous COVID years to confirm exclusion."""
    df = synthetic_macro.copy()
    df.loc[df["year"] == 2020, "flights_per_capita"] = (
        df.loc[df["year"] == 2020, "flights_per_capita"].iloc[0] * 0.3
    )
    df.loc[df["year"] == 2021, "flights_per_capita"] = (
        df.loc[df["year"] == 2021, "flights_per_capita"].iloc[0] * 0.5
    )
    return df


@pytest.fixture
def minimal_regression():
    """A plausible regression dict for downstream tests.

    Matches the shape emitted by fit_gdp_flights_regression.
    Covariance chosen so off-diagonal is structurally negative.
    """
    return {
        "intercept": -13.85,
        "slope": 1.295,
        "r_squared": 0.954,
        "r_squared_adj": 0.952,
        "std_err_slope": 0.051,
        "std_err_intercept": 0.414,
        "cov_params": [
            [0.17138, -0.02095],  # intercept var, cov
            [-0.02095, 0.00261],  # cov, slope var
        ],
        "n_observations": 33,
        "residual_std": 0.187,
        "years_used": list(range(1990, 2023)),
        "method": "OLS_log_log",
    }
