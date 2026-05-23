"""Monte Carlo inverse prediction for operational milestones.

Reads:
  - data/processed/projection.json (produced by project.py)
  - data/processed/airport_yearly.csv (for airport shares)
  - milestones.yaml (threshold config)
  - mappings.yaml (airport tiers, greenfield dates)

Writes:
  - data/processed/milestones.json

Methodology (design doc step 1, autoplan eng consensus):
  1. Sample regression coefficients (b0, b1) JOINTLY from cov_params via
     multivariate_normal. Independent marginal sampling is wrong here because
     Cov(intercept, slope) is structurally negative and large.
  2. Sample a single GDP perturbation per draw: triangular(-10%, 0, +10%)
     scaling factor applied CORRELATED across all post-2029 years, not iid.
     Per-year noise would inflate the bands dishonestly.
  3. For each draw, derive the projected passenger trajectory per metric.
  4. Find first PERSISTENT crossing: pax[y] >= threshold AND pax[y+1] >=
     threshold. Kills single-year blips from non-monotonic draws.
  5. Report {p10, p50, p90} years. If <50% of draws cross by 2040, emit
     status="beyond_horizon" with null year fields.

The `achieved` block uses the actual-data latest year; never draws. A
milestone is achieved iff the threshold was crossed in the observed data
at data_date. This keeps historical claims separate from MC claims.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"

# Bump on breaking changes to milestones.json (rename/remove fields,
# change units, change methodology semantics). Additive changes do not bump.
MILESTONES_SCHEMA_VERSION = 1
# Compatible projection.json schema. milestones.py refuses to run against
# a projection produced by a different schema version.
EXPECTED_PROJECTION_SCHEMA = 1

# Deterministic seed so re-runs produce byte-identical output. This is the
# canary for check_milestone_stability: if drift appears, it reflects real
# data change, not RNG drift.
SEED = 20260424
N_DRAWS = 1000

# Horizon. Matches PROJECTION_END in project.py.
HORIZON = 2040

# GDP perturbation. ±10% triangular, correlated across all post-2029 years.
# Pre-2029 uses the central estimate (no perturbation).
GDP_PERTURBATION_START_YEAR = 2030
GDP_PERTURBATION_LO = 0.90
GDP_PERTURBATION_HI = 1.10


# ── Loaders + schema guards ───────────────────────────────────


def load_projection() -> dict:
    """Load projection.json and verify schema_version."""
    path = PROCESSED_DIR / "projection.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — run project.py first. "
            f"milestones.py depends on projection.json's regression + national_timeline."
        )
    data = json.loads(path.read_text())
    version = data.get("schema_version")
    if version != EXPECTED_PROJECTION_SCHEMA:
        raise ValueError(
            f"projection.json schema_version={version}, "
            f"milestones.py expects {EXPECTED_PROJECTION_SCHEMA}. "
            f"Re-run scripts/project.py to regenerate."
        )
    return data


def load_milestones_config() -> dict:
    path = ROOT / "milestones.yaml"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    return yaml.safe_load(path.read_text())


def load_mappings() -> dict:
    return yaml.safe_load((ROOT / "mappings.yaml").read_text())


def load_airport_yearly() -> pd.DataFrame | None:
    path = PROCESSED_DIR / "airport_yearly.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def load_metadata() -> dict:
    path = PROCESSED_DIR / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ── Monte Carlo core ──────────────────────────────────────────


def sample_regression_coefficients(regression: dict, rng: np.random.Generator) -> np.ndarray:
    """Draw N samples of (intercept, slope) from the full covariance.

    Returns shape (N_DRAWS, 2).
    """
    mean = np.array([regression["intercept"], regression["slope"]])
    cov = np.asarray(regression["cov_params"])
    if cov.shape != (2, 2):
        raise ValueError(
            f"regression.cov_params must be 2x2, got {cov.shape}. "
            f"Re-run project.py to regenerate with full covariance."
        )
    # Eigenvalue check: sampling from a non-PSD covariance silently produces
    # garbage. Catch it here with a named error rather than trusting numpy.
    eigvals = np.linalg.eigvalsh(cov)
    if (eigvals < -1e-9).any():
        raise ValueError(
            f"regression.cov_params is not positive semi-definite "
            f"(min eigenvalue {eigvals.min():.2e}). Check project.py OLS fit."
        )
    return rng.multivariate_normal(mean, cov, size=N_DRAWS)


def sample_gdp_perturbations(rng: np.random.Generator) -> np.ndarray:
    """One triangular(0.9, 1.0, 1.1) scaling factor per draw.

    Same factor is applied to every post-GDP_PERTURBATION_START_YEAR year within
    a draw. This is the "correlated single-draw scaling" required by the design
    — per-year iid noise would produce unrealistically wide bands.
    """
    return rng.triangular(
        GDP_PERTURBATION_LO, 1.0, GDP_PERTURBATION_HI, size=N_DRAWS
    )


def first_persistent_crossing(pax_series: np.ndarray, years: np.ndarray, threshold: float) -> int | None:
    """Return the first year y where pax[y] >= threshold AND pax[y+1] >= threshold.

    Returns None if no such year exists within the provided series. The last
    year of the series is never returned because we can't verify persistence
    for it.
    """
    if len(pax_series) < 2:
        return None
    meets = pax_series >= threshold
    # Persistent crossing: meets[i] AND meets[i+1]. Vectorize via roll.
    persistent = meets[:-1] & meets[1:]
    idx = np.argmax(persistent)
    if not persistent[idx]:
        return None
    return int(years[idx])


def run_mc_for_threshold(
    projection: dict,
    threshold: float,
    airport_share: float,
    rng: np.random.Generator,
) -> dict:
    """Run Monte Carlo inverse prediction for a national or airport threshold.

    airport_share=1.0 means the threshold is national. Otherwise the threshold
    is tested against national * airport_share each year.

    Returns dict with status + {p10_year, p50_year, p90_year, method,
    draws_total, draws_crossed}.
    """
    reg = projection["regression"]
    timeline = projection["national_timeline"]

    projected = [e for e in timeline if e["type"] == "projected"]
    if not projected:
        return {
            "status": "beyond_horizon",
            "p10_year": None,
            "p50_year": None,
            "p90_year": None,
            "method": "monte_carlo_n1000",
            "draws_total": 0,
            "draws_crossed": 0,
            "reason": "no projected years in timeline",
        }

    proj_years = np.array([e["year"] for e in projected])
    proj_gdp = np.array([e["gdp_per_capita_ppp"] for e in projected])
    proj_pop = np.array([e["population"] for e in projected])

    coefs = sample_regression_coefficients(reg, rng)
    perturbs = sample_gdp_perturbations(rng)

    post_mask = proj_years >= GDP_PERTURBATION_START_YEAR

    crossings: list[int] = []
    for b0, b1, perturb in zip(coefs[:, 0], coefs[:, 1], perturbs):
        # Apply GDP perturbation only to post-2029 years; pre-2030 uses central.
        gdp = np.where(post_mask, proj_gdp * perturb, proj_gdp)
        log_fpc = b0 + b1 * np.log(gdp)
        fpc = np.exp(log_fpc)
        # Overflow guard: extreme draws can push fpc to inf. Clamp.
        if not np.isfinite(fpc).all():
            continue
        pax = fpc * proj_pop * airport_share
        year = first_persistent_crossing(pax, proj_years, threshold)
        if year is not None:
            crossings.append(year)

    draws_total = len(coefs)
    draws_crossed = len(crossings)

    if draws_crossed < draws_total / 2:
        return {
            "status": "beyond_horizon",
            "p10_year": None,
            "p50_year": None,
            "p90_year": None,
            "method": "monte_carlo_n1000",
            "draws_total": draws_total,
            "draws_crossed": draws_crossed,
        }

    crossings_arr = np.array(crossings)
    p10 = int(np.quantile(crossings_arr, 0.10, method="nearest"))
    p50 = int(np.quantile(crossings_arr, 0.50, method="nearest"))
    p90 = int(np.quantile(crossings_arr, 0.90, method="nearest"))

    return {
        "status": "projected",
        "p10_year": p10,
        "p50_year": p50,
        "p90_year": p90,
        "method": "monte_carlo_n1000",
        "draws_total": draws_total,
        "draws_crossed": draws_crossed,
    }


# ── Metric handlers ───────────────────────────────────────────


def latest_actual(projection: dict) -> dict:
    """Latest {year, passengers} from national_timeline actual entries."""
    actual = [e for e in projection["national_timeline"] if e["type"] == "actual"]
    if not actual:
        return {"year": None, "passengers": None}
    last = max(actual, key=lambda e: e["year"])
    return {"year": last["year"], "passengers": last["passengers"]}


def compute_airport_share(airport: str, yearly: pd.DataFrame) -> float:
    """Latest-year share of national for an airport (frozen v1 assumption)."""
    if yearly is None or yearly.empty:
        return 0.0
    latest_year = int(yearly["year"].max())
    latest = yearly[yearly["year"] == latest_year].groupby("airport")["passengers"].sum()
    national = latest.sum()
    if national == 0 or airport not in latest.index:
        return 0.0
    return float(latest[airport] / national)


def compute_tier_share(tier: str, yearly: pd.DataFrame, mappings: dict) -> float:
    """Latest-year cumulative share for a tier (metro/tier1/tier2/tier3).

    Under v1 share-freeze, tier shares are constant across projected years,
    so this is deterministic.
    """
    if yearly is None or yearly.empty:
        return 0.0
    airports = mappings.get("airports", {})
    tier_iatas = {iata for iata, info in airports.items() if info.get("tier") == tier}
    latest_year = int(yearly["year"].max())
    latest = yearly[yearly["year"] == latest_year].groupby("airport")["passengers"].sum()
    national = latest.sum()
    if national == 0:
        return 0.0
    tier_total = sum(
        float(latest[iata]) for iata in tier_iatas if iata in latest.index
    )
    return tier_total / float(national)


def resolve_projected_milestone(
    mid: str,
    spec: dict,
    projection: dict,
    yearly: pd.DataFrame | None,
    mappings: dict,
    rng: np.random.Generator,
) -> tuple[str, dict]:
    """Classify + compute a single projected-config milestone.

    Returns (block, entry) where block is one of "achieved", "projected",
    "deterministic". Block membership is decided by comparing the threshold
    against the current actual value; never against Monte Carlo draws.
    """
    metric = spec.get("metric")
    threshold = spec.get("threshold")
    label = spec.get("label", mid)

    common = {
        "label": label,
        "metric": metric,
        "threshold": threshold,
    }

    if metric == "national_passengers":
        last = latest_actual(projection)
        if last["passengers"] is not None and last["passengers"] >= threshold:
            return "achieved", {
                **common,
                "actual_year": last["year"],
                "actual_value": last["passengers"],
            }
        mc = run_mc_for_threshold(projection, threshold, airport_share=1.0, rng=rng)
        return "projected", {**common, **mc}

    if metric == "airport_passengers":
        airport = spec.get("airport")
        common["airport"] = airport
        share = compute_airport_share(airport, yearly)
        if share == 0.0:
            return "projected", {
                **common,
                "status": "beyond_horizon",
                "p10_year": None,
                "p50_year": None,
                "p90_year": None,
                "method": "monte_carlo_n1000",
                "reason": f"airport {airport} has zero share in latest actual year",
                "airport_share": share,
            }
        # Check if airport has already crossed threshold in latest actual year
        if yearly is not None:
            latest_year = int(yearly["year"].max())
            latest_airport = (
                yearly[(yearly["year"] == latest_year) & (yearly["airport"] == airport)][
                    "passengers"
                ].sum()
            )
            if latest_airport >= threshold:
                return "achieved", {
                    **common,
                    "actual_year": latest_year,
                    "actual_value": int(latest_airport),
                    "airport_share": share,
                }
        mc = run_mc_for_threshold(projection, threshold, airport_share=share, rng=rng)
        return "projected", {**common, **mc, "airport_share": share}

    if metric == "tier_share":
        tier = spec.get("tier")
        common["tier"] = tier
        current = compute_tier_share(tier, yearly, mappings)
        # Under v1 share-freeze, tier_share is constant across projected years.
        # Either already >= threshold (achieved) or never reaches it in v1 (beyond_horizon).
        if current >= threshold:
            return "achieved", {
                **common,
                "actual_year": int(yearly["year"].max()) if yearly is not None else None,
                "actual_value": round(current, 4),
                "method": "deterministic",
                "note": "Under v1 share-freeze (METHODOLOGY.md Step 4 v1 caveat), "
                "tier shares are held fixed at latest-year observation. "
                "Tier 2 share is structurally constant until tier-CAGR is implemented (TODOS P1).",
            }
        return "projected", {
            **common,
            "status": "beyond_horizon",
            "p10_year": None,
            "p50_year": None,
            "p90_year": None,
            "method": "deterministic",
            "current_value": round(current, 4),
            "note": "Deterministic under v1 share-freeze; will not cross without tier-CAGR model (TODOS P1).",
        }

    raise ValueError(f"Unknown metric '{metric}' for milestone '{mid}'")


def resolve_scheduled_milestone(mid: str, spec: dict, mappings: dict) -> dict:
    """Pull scheduled airport info from mappings.yaml."""
    airport = spec.get("airport")
    greenfield = mappings.get("greenfield_airports", {}).get(airport, {})
    return {
        "label": spec.get("label", mid),
        "airport": airport,
        "scheduled_date": greenfield.get("opening"),
        "phase1_capacity": greenfield.get("phase1"),
        "ultimate_capacity": greenfield.get("ultimate"),
        "note": "Scheduled date from public announcements (mappings.yaml). "
        "Slippage is typical in Indian greenfield projects; treat as schedule, not projection.",
    }


# ── Main ──────────────────────────────────────────────────────


def main():
    print("=== Computing Milestones ===\n", flush=True)
    config = load_milestones_config()
    projection = load_projection()
    mappings = load_mappings()
    yearly = load_airport_yearly()
    metadata = load_metadata()

    rng = np.random.default_rng(SEED)

    result = {
        "schema_version": MILESTONES_SCHEMA_VERSION,
        "as_of": metadata.get("processed_date", "")[:7] if metadata.get("processed_date") else None,
        "data_date": metadata.get("data_date"),
        "seed": SEED,
        "n_draws": N_DRAWS,
        "horizon": HORIZON,
        "achieved": {},
        "projected": {},
        "scheduled": {},
    }

    for mid, spec in (config.get("projected") or {}).items():
        block, entry = resolve_projected_milestone(
            mid, spec, projection, yearly, mappings, rng
        )
        result[block][mid] = entry
        status_label = entry.get("status") or block
        if block == "projected" and entry.get("status") == "projected":
            print(
                f"  {mid}: p10={entry['p10_year']} p50={entry['p50_year']} p90={entry['p90_year']}",
                flush=True,
            )
        elif block == "achieved":
            print(f"  {mid}: ACHIEVED in {entry.get('actual_year')}", flush=True)
        else:
            print(f"  {mid}: {status_label}", flush=True)

    for mid, spec in (config.get("scheduled") or {}).items():
        result["scheduled"][mid] = resolve_scheduled_milestone(mid, spec, mappings)
        print(f"  {mid}: scheduled {result['scheduled'][mid].get('scheduled_date')}", flush=True)

    out_path = PROCESSED_DIR / "milestones.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\n  Saved: {out_path.name}")
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
