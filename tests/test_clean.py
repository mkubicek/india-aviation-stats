"""Tests for the clean stage (table-driven resolution + cadence-split helpers)."""

from pathlib import Path

import pandas as pd

from clean import (
    _finalize,
    _split_endpoints,
    build_yearly,
    resolve_airport,
    source_csv,
)

ROOT = Path(__file__).resolve().parent.parent


def test_resolve_airport_uses_table_and_aliases():
    # City name resolves via the entity table; alternate spellings via airport_aliases.
    assert resolve_airport("Bengaluru", 2024, 6) == "BLR"
    assert resolve_airport("BOMBAY", 2024, 6) == "BOM"
    assert resolve_airport("TRIVANDRUM", 2024, 6) == "TRV"


def test_resolve_airport_is_period_aware_for_goa():
    assert resolve_airport("GOA", 2017, 6) == "GOI"   # Dabolim era
    assert resolve_airport("GOA", 2024, 6) == "GOX"   # Mopa era


def test_resolve_airport_returns_none_for_foreign_city():
    # Foreign counterpart cities are unmapped and dropped by Layer 2.
    assert resolve_airport("DUBAI", 2024, 6) is None


def test_source_csv_points_to_direct_aviation_aggregate():
    path = source_csv("domestic/city.csv")
    assert path.as_posix().endswith("data/raw/aviation/aggregated/domestic/city.csv")


def test_finalize_dedups_and_keeps_integer_conservation():
    rows = pd.DataFrame(
        [
            {"year": 2025, "month": 1, "airport": "COK", "departures": 6.0, "arrivals": 4.0},
            {"year": 2025, "month": 1, "airport": "COK", "departures": 7.0, "arrivals": 13.0},
        ]
    )
    result = _finalize(rows, ["year", "month", "airport"])
    assert len(result) == 1
    row = result.iloc[0]
    assert row["departures"] == 13 and row["arrivals"] == 17
    assert row["passengers"] == 30                       # recomputed as dep + arr
    assert result["passengers"].dtype == "int64"
    assert (result["passengers"] == result["departures"] + result["arrivals"]).all()


def test_blank_one_direction_pax_cells_are_treated_as_zero():
    # DGCA reports some routes in one direction only, leaving the reverse cell
    # blank. We treat blanks as zero and keep the row (rather than dropping it,
    # which would understate one-direction airport totals). Documented policy.
    raw = pd.DataFrame(
        [{"Year": 2025, "Month": 1, "City1": "DEL", "City2": "BOM",
          "PaxToCity2": 100, "PaxFromCity2": ""}]
    )
    ep = _split_endpoints(raw, ["Year", "Month"])
    delhi = ep[ep["city"] == "DEL"].iloc[0]
    mumbai = ep[ep["city"] == "BOM"].iloc[0]
    assert delhi["departures"] == 100 and delhi["arrivals"] == 0
    assert mumbai["arrivals"] == 100 and mumbai["departures"] == 0


def test_build_yearly_keeps_only_complete_years():
    # 2024 has all 12 months (complete); 2025 has only 1 month (dropped).
    monthly = pd.concat(
        [
            pd.DataFrame(
                {"year": 2024, "month": list(range(1, 13)), "airport": "DEL",
                 "passengers": 100, "departures": 50, "arrivals": 50}
            ),
            pd.DataFrame(
                [{"year": 2025, "month": 1, "airport": "DEL",
                  "passengers": 100, "departures": 50, "arrivals": 50}]
            ),
        ],
        ignore_index=True,
    )
    yearly = build_yearly(monthly, None)
    assert set(yearly["year"]) == {2024}
    assert yearly.iloc[0]["passengers"] == 1200
    assert yearly.iloc[0]["category"] == "domestic"
    assert "tier" not in yearly.columns


# ── Regressions against the real published Layer 1 ──

def _layer1():
    return pd.read_csv(ROOT / "data" / "processed" / "airport_monthly.csv")


def test_goa_splits_into_two_distinct_airports_in_published_data():
    m = _layer1()
    goi = m[m.airport == "GOI"]
    gox = m[m.airport == "GOX"]
    assert len(goi) and len(gox)
    assert int(gox.year.min()) >= 2023            # Mopa opened 2023
    # GOI (Dabolim) is the larger airport overall.
    assert goi.passengers.sum() > gox.passengers.sum()


def test_2026_rename_wave_folds_into_existing_airports():
    m = _layer1()
    # MUMBAI MUMBAI (2026 long-form) must fold into BOM, not fragment it.
    bom_2026 = m[(m.airport == "BOM") & (m.year == 2026)]
    assert len(bom_2026) > 0
    # No raw long-form label leaks as an airport code.
    leaked = {a for a in m.airport.unique() if " " in str(a)}
    assert not leaked, f"raw labels leaked as airport codes: {leaked}"


def test_no_category_or_tier_in_layer1():
    m = _layer1()
    assert "category" not in m.columns and "tier" not in m.columns
    assert m.passengers.dtype == "int64"
