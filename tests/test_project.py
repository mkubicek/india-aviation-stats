"""Tests for scripts/project.py — GDP-flights regression + national projection.

Focuses on the methodology-critical functions whose output drives every public
claim: `fit_gdp_flights_regression` and `compute_national_projection`.
"""

import numpy as np
import pandas as pd
import pytest

from project import (
    COVID_YEARS,
    compute_national_projection,
    fit_gdp_flights_regression,
    project_gdp,
    project_population,
)


# ── fit_gdp_flights_regression ────────────────────────────────


def test_regression_synthetic_recovery(synthetic_macro):
    """Known log-log data → regression recovers slope within tolerance."""
    result = fit_gdp_flights_regression(synthetic_macro)

    assert 1.40 < result["slope"] < 1.60, f"slope {result['slope']} not near 1.5"
    assert result["r_squared"] > 0.95, f"r² {result['r_squared']} too low"
    # synthetic_macro has 20 years (2005-2024), 2020 and 2021 unconditionally excluded
    assert result["n_observations"] == 18
    assert result["method"].startswith("OLS_log_log")


def test_regression_raises_on_few_points():
    """Fewer than 5 valid rows → ValueError."""
    df = pd.DataFrame(
        {
            "year": [2010, 2011, 2012, 2013],
            "gdp_per_capita_ppp": [3000, 3300, 3600, 4000],
            "flights_per_capita": [0.01, 0.012, 0.014, 0.016],
        }
    )
    with pytest.raises(ValueError, match="at least 5"):
        fit_gdp_flights_regression(df)


def test_regression_excludes_covid(synthetic_macro_with_covid):
    """COVID years (2020, 2021) dropped from years_used regardless of input."""
    result = fit_gdp_flights_regression(synthetic_macro_with_covid)
    years = set(result["years_used"])
    assert 2020 not in years
    assert 2021 not in years
    # non-COVID years should survive
    assert 2019 in years
    assert 2022 in years
    # n_observations reflects exclusion
    assert result["n_observations"] == len(synthetic_macro_with_covid) - len(COVID_YEARS)


def test_regression_drops_nonpositive_fpc():
    """Rows with fpc <= 0 dropped, never log(0) → -inf leaking into fit."""
    df = pd.DataFrame(
        {
            "year": [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017],
            "gdp_per_capita_ppp": [3000, 3300, 3600, 4000, 4400, 4800, 5200, 5600],
            "flights_per_capita": [0.01, 0.012, 0.0, 0.016, 0.018, 0.020, 0.022, 0.024],
        }
    )
    result = fit_gdp_flights_regression(df)
    # 2012 row dropped (fpc=0) → 7 observations
    assert result["n_observations"] == 7
    # No NaN/inf leaked
    assert np.isfinite(result["slope"])
    assert np.isfinite(result["intercept"])
    assert np.isfinite(result["r_squared"])


def test_regression_cov_params_shape_and_sign(synthetic_macro):
    """cov_params is 2×2, off-diagonal is structurally negative.

    For OLS on (intercept, slope): Cov(intercept, slope) = -x̄ * Var(slope).
    Synthetic data has x̄ = mean(ln(gdp)) > 0, so off-diagonal is negative.
    Diagonal must match marginal standard errors squared.
    """
    result = fit_gdp_flights_regression(synthetic_macro)
    cov = result["cov_params"]

    assert len(cov) == 2 and len(cov[0]) == 2, "cov_params must be 2×2"
    # Symmetric
    assert cov[0][1] == pytest.approx(cov[1][0], rel=1e-9)
    # Off-diagonal negative (Cov(intercept, slope) = -x̄ * Var(slope) and x̄ > 0)
    assert cov[0][1] < 0, "Cov(intercept, slope) should be negative at positive x̄"
    # Diagonals match marginal std errors squared
    assert cov[0][0] == pytest.approx(result["std_err_intercept"] ** 2, rel=1e-6)
    assert cov[1][1] == pytest.approx(result["std_err_slope"] ** 2, rel=1e-6)
    # Positive semi-definite
    eigvals = np.linalg.eigvalsh(np.array(cov))
    assert (eigvals >= -1e-9).all(), f"cov not PSD, eigvals={eigvals}"


# ── project_gdp + project_population ──────────────────────────


def test_project_gdp_monotone_growth(synthetic_macro):
    """Synthetic GDP is linear-log → projection should also be growing."""
    proj = project_gdp(synthetic_macro)
    # Every projected year should be >= the year before (under positive trend)
    assert (proj["gdp_per_capita_ppp"].diff().dropna() > 0).all()
    # Projection extends to 2040
    assert proj["year"].max() == 2040


def test_project_population_reaches_2040(synthetic_macro):
    proj = project_population(synthetic_macro)
    assert proj["year"].max() == 2040
    assert not proj["population"].isna().any()


# ── compute_national_projection ───────────────────────────────


def test_national_projection_year_uniqueness(synthetic_macro, minimal_regression):
    """No year appears in both historical and projected entries."""
    gdp_proj = project_gdp(synthetic_macro)
    pop_proj = project_population(synthetic_macro)
    timeline = compute_national_projection(
        synthetic_macro, minimal_regression, gdp_proj, pop_proj
    )

    actual_years = {e["year"] for e in timeline if e["type"] == "actual"}
    projected_years = {e["year"] for e in timeline if e["type"] == "projected"}
    assert actual_years.isdisjoint(projected_years)


def test_national_projection_band_ordering(synthetic_macro, minimal_regression):
    """For every projected year, low ≤ mid ≤ high for both fpc and passengers."""
    gdp_proj = project_gdp(synthetic_macro)
    pop_proj = project_population(synthetic_macro)
    timeline = compute_national_projection(
        synthetic_macro, minimal_regression, gdp_proj, pop_proj
    )

    projected = [e for e in timeline if e["type"] == "projected"]
    assert len(projected) > 0
    for entry in projected:
        assert entry["passengers_low"] <= entry["passengers"] <= entry["passengers_high"]
        assert (
            entry["flights_per_capita_low"]
            <= entry["flights_per_capita"]
            <= entry["flights_per_capita_high"]
        )


def test_national_projection_empty_gdp_yields_no_projections(
    synthetic_macro, minimal_regression
):
    """Empty gdp_proj → no projected entries, not a crash."""
    empty_gdp = pd.DataFrame(columns=["year", "gdp_per_capita_ppp"])
    pop_proj = project_population(synthetic_macro)
    timeline = compute_national_projection(
        synthetic_macro, minimal_regression, empty_gdp, pop_proj
    )
    projected = [e for e in timeline if e["type"] == "projected"]
    assert projected == []
    # Historical entries still present
    actual = [e for e in timeline if e["type"] == "actual"]
    assert len(actual) > 0
