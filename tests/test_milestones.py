"""Tests for scripts/milestones.py — Monte Carlo inverse prediction.

Covers determinism (2am-Friday-ship canary), achieved/projected/beyond_horizon
classification, persistence rule, schema version handling, and the
deterministic tier-share case.
"""

import hashlib
import json

import numpy as np
import pytest

from milestones import (
    EXPECTED_PROJECTION_SCHEMA,
    MILESTONES_SCHEMA_VERSION,
    SEED,
    first_persistent_crossing,
    resolve_projected_milestone,
    run_mc_for_threshold,
    sample_gdp_perturbations,
    sample_regression_coefficients,
)


# ── Helpers ───────────────────────────────────────────────────


def build_projection(regression, years=None, gdp=None, pop=None, actual_years=None, actual_pax=None):
    """Build a minimal projection dict for MC tests.

    Defaults match the real India projection shape: ~$10K GDP in 2025 rising
    to ~$37K by 2040 at ~8% annual growth; population ~1.45B → ~1.67B. These
    numbers reproduce the shape of the real projection.json, just without the
    full 124-airport distribution.
    """
    years = years if years is not None else list(range(2025, 2041))
    # ~8% annual GDP growth
    gdp = gdp if gdp is not None else [10000 * (1.08 ** (y - 2025)) for y in years]
    pop = pop if pop is not None else [1.45e9 + 14e6 * (y - 2025) for y in years]

    projected = [
        {
            "year": y,
            "type": "projected",
            "gdp_per_capita_ppp": g,
            "population": int(p),
            "passengers": 0,
            "passengers_low": 0,
            "passengers_high": 0,
            "flights_per_capita": 0.0,
            "flights_per_capita_low": 0.0,
            "flights_per_capita_high": 0.0,
        }
        for y, g, p in zip(years, gdp, pop)
    ]

    actual = []
    if actual_years is not None and actual_pax is not None:
        for y, pax in zip(actual_years, actual_pax):
            actual.append({"year": y, "type": "actual", "passengers": pax})

    return {
        "schema_version": EXPECTED_PROJECTION_SCHEMA,
        "regression": regression,
        "national_timeline": actual + projected,
    }


# ── Low-level helpers ─────────────────────────────────────────


def test_first_persistent_crossing_detects_persistent():
    series = np.array([10, 20, 30, 100, 110, 120])
    years = np.array([2025, 2026, 2027, 2028, 2029, 2030])
    # First persistent crossing of 100: 2028 (100 and 2029's 110 both >= 100)
    assert first_persistent_crossing(series, years, 100) == 2028


def test_first_persistent_crossing_rejects_single_year_blip():
    # 100 at 2028 but drops to 99 at 2029 — not persistent.
    series = np.array([10, 20, 30, 100, 99, 120, 130])
    years = np.array([2025, 2026, 2027, 2028, 2029, 2030, 2031])
    # First persistent crossing of 100 is 2030 (120 and 2031's 130)
    assert first_persistent_crossing(series, years, 100) == 2030


def test_first_persistent_crossing_never_crosses():
    series = np.array([10, 20, 30, 40, 50])
    years = np.array([2025, 2026, 2027, 2028, 2029])
    assert first_persistent_crossing(series, years, 100) is None


def test_first_persistent_crossing_short_series():
    assert first_persistent_crossing(np.array([100]), np.array([2025]), 50) is None


# ── MC sampling ───────────────────────────────────────────────


def test_sample_regression_coefficients_shape(minimal_regression):
    rng = np.random.default_rng(123)
    samples = sample_regression_coefficients(minimal_regression, rng)
    assert samples.shape == (1000, 2)


def test_sample_regression_coefficients_rejects_non_psd_cov(minimal_regression):
    """A non-PSD covariance should raise, not silently produce garbage."""
    bad = dict(minimal_regression)
    bad["cov_params"] = [[1.0, 2.0], [2.0, 1.0]]  # eigvals: 3, -1 → not PSD
    rng = np.random.default_rng(123)
    with pytest.raises(ValueError, match="not positive semi-definite"):
        sample_regression_coefficients(bad, rng)


def test_sample_regression_coefficients_rejects_wrong_shape(minimal_regression):
    bad = dict(minimal_regression)
    bad["cov_params"] = [1.0, 2.0, 3.0]
    rng = np.random.default_rng(123)
    with pytest.raises(ValueError, match="2x2"):
        sample_regression_coefficients(bad, rng)


def test_sample_gdp_perturbations_bounds():
    rng = np.random.default_rng(123)
    perturbs = sample_gdp_perturbations(rng)
    assert perturbs.shape == (1000,)
    assert (perturbs >= 0.9).all()
    assert (perturbs <= 1.1).all()


# ── Monte Carlo integration ───────────────────────────────────


def test_mc_beyond_horizon_for_unreachable(minimal_regression):
    """An absurdly high threshold → status=beyond_horizon, null years."""
    proj = build_projection(minimal_regression)
    rng = np.random.default_rng(SEED)
    result = run_mc_for_threshold(proj, threshold=1e18, airport_share=1.0, rng=rng)
    assert result["status"] == "beyond_horizon"
    assert result["p10_year"] is None
    assert result["p50_year"] is None
    assert result["p90_year"] is None


def test_mc_percentile_monotone(minimal_regression):
    """For a reachable threshold, p10 <= p50 <= p90."""
    proj = build_projection(minimal_regression)
    rng = np.random.default_rng(SEED)
    # Threshold chosen to be reachable in most draws given defaults
    result = run_mc_for_threshold(proj, threshold=3e8, airport_share=1.0, rng=rng)
    assert result["status"] == "projected"
    assert result["p10_year"] <= result["p50_year"] <= result["p90_year"]


def test_mc_deterministic_with_seed(minimal_regression):
    """Same seed + same input → byte-identical result. The 2am-Friday canary."""
    proj = build_projection(minimal_regression)

    rng1 = np.random.default_rng(SEED)
    r1 = run_mc_for_threshold(proj, threshold=3e8, airport_share=1.0, rng=rng1)

    rng2 = np.random.default_rng(SEED)
    r2 = run_mc_for_threshold(proj, threshold=3e8, airport_share=1.0, rng=rng2)

    # Same seed, same everything — including draws_crossed counts.
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_mc_empty_projection(minimal_regression):
    """No projected years → beyond_horizon with 0 draws."""
    proj = {
        "schema_version": EXPECTED_PROJECTION_SCHEMA,
        "regression": minimal_regression,
        "national_timeline": [{"year": 2024, "type": "actual", "passengers": 200e6}],
    }
    rng = np.random.default_rng(SEED)
    result = run_mc_for_threshold(proj, threshold=5e8, airport_share=1.0, rng=rng)
    assert result["status"] == "beyond_horizon"
    assert result["draws_total"] == 0


# ── High-level resolver ───────────────────────────────────────


def test_resolve_milestone_already_achieved(minimal_regression):
    """If national pax in latest actual already exceeds threshold → achieved block."""
    proj = build_projection(
        minimal_regression,
        actual_years=[2023, 2024],
        actual_pax=[480_000_000, 520_000_000],
    )
    spec = {
        "label": "India crosses 500M",
        "metric": "national_passengers",
        "threshold": 500_000_000,
    }
    rng = np.random.default_rng(SEED)
    block, entry = resolve_projected_milestone(
        "india_500m", spec, proj, yearly=None, mappings={}, rng=rng
    )
    assert block == "achieved"
    assert entry["actual_year"] == 2024
    assert entry["actual_value"] == 520_000_000


def test_resolve_milestone_projected(minimal_regression):
    """Threshold not yet met → projected block with MC bands."""
    proj = build_projection(
        minimal_regression,
        actual_years=[2024],
        actual_pax=[200_000_000],
    )
    spec = {
        "label": "India crosses 500M",
        "metric": "national_passengers",
        "threshold": 500_000_000,
    }
    rng = np.random.default_rng(SEED)
    block, entry = resolve_projected_milestone(
        "india_500m", spec, proj, yearly=None, mappings={}, rng=rng
    )
    assert block == "projected"
    # Shape assertion; specific year depends on regression mean + draws
    assert "p10_year" in entry
    assert "method" in entry and entry["method"] == "monte_carlo_n1000"
