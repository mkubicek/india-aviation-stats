"""End-to-end pipeline test on a tiny synthetic fixture.

Exercises the real clean helpers + resolver + validate checks on a fixture that
packs the three cleanup shapes the design cares about into a handful of rows:

  - Goa-style split: one source label (`SHARED`) is airport AAA in an early era
    and airport BBB in a later era (disjoint validity windows).
  - Rename: airport CCC carries two labels over time (`OLDTOWN` -> `NEWTOWN`).
  - Distinct-overlap: two name-similar labels map to different airports (AAA vs
    BBB) — kept apart by construction (different canonical keys).

It proves the chain produces a tidy, conserved domestic-monthly table and that the overlap gate
blocks an undeclared concurrent merge.
"""

from pathlib import Path

import pandas as pd

from clean import _finalize, _split_endpoints
from entities import build_airport_resolver
from routes import airport_monthly_from_routes, build_domestic_routes
from validate.checks import check_cadence, check_definitional
from validate.overlap import overlap_gate

FIXTURE = {
    "airports": {
        "AAA": {"city": "Alpha", "variants": [{"label": "SHARED", "valid_to": "2020-12"}]},
        "BBB": {"city": "Beta", "variants": [{"label": "SHARED", "valid_from": "2023-01"}]},
        "CCC": {"city": "Gamma", "variants": [
            {"label": "OLDTOWN", "valid_to": "2021-12"},
            {"label": "NEWTOWN", "valid_from": "2022-01"},
        ]},
    }
}


def _raw(rows):
    return pd.DataFrame(
        rows, columns=["Year", "Month", "City1", "City2", "PaxToCity2", "PaxFromCity2"]
    )


def _run_clean(raw):
    resolver = build_airport_resolver(FIXTURE)
    ep = _split_endpoints(raw, ["Year", "Month"]).rename(columns={"Year": "year", "Month": "month"})
    ep["airport"] = ep.apply(lambda r: resolver.resolve(r["city"], r["year"], r["month"]), axis=1)
    ep = ep[ep["airport"].notna()]
    return _finalize(ep, ["year", "month", "airport"])


def test_full_clean_splits_renames_and_conserves():
    raw = _raw([
        # SHARED in 2017 -> AAA (early era); SHARED in 2024 -> BBB (later era)
        [2017, 6, "SHARED", "HUB", 100, 80],
        [2024, 6, "SHARED", "HUB", 200, 150],
        # CCC rename: OLDTOWN (2020) and NEWTOWN (2023), same airport
        [2020, 3, "OLDTOWN", "HUB", 10, 10],
        [2023, 3, "NEWTOWN", "HUB", 30, 20],
    ])
    layer1 = _run_clean(raw)

    # Goa-style split: the SHARED label resolves to two different airports by era.
    a = layer1[(layer1.airport == "AAA") & (layer1.year == 2017)]
    b = layer1[(layer1.airport == "BBB") & (layer1.year == 2024)]
    assert len(a) == 1 and len(b) == 1
    assert layer1[(layer1.airport == "AAA")].year.max() == 2017      # AAA never in 2024
    assert "SHARED" not in set(layer1.airport)                       # raw label never leaks

    # Rename: both OLDTOWN and NEWTOWN land on CCC.
    ccc_years = set(layer1[layer1.airport == "CCC"].year)
    assert ccc_years == {2020, 2023}

    # Tidy + conserved + integer.
    assert (layer1.passengers == layer1.departures + layer1.arrivals).all()
    assert layer1.passengers.dtype == "int64"
    assert not [f for f in check_definitional(layer1, "e2e") if f.status == "fail"]
    assert not [f for f in check_cadence(layer1, None) if f.status == "fail"]


def test_overlap_gate_blocks_then_passes_with_declaration(tmp_path):
    # Two distinct labels feeding ONE airport in the SAME month = concurrent merge.
    raw_csv = tmp_path / "city.csv"
    raw_csv.write_text(
        "Year,Month,City1,City2,PaxToCity2,PaxFromCity2\n"
        "2024,6,KOCHI,HUB,100,90\n"
        "2024,6,COCHIN,HUB,5,4\n"
    )
    mappings = {
        "airports": {"COK": {"city": "Kochi"}},
        "airport_aliases": {"KOCHI": "COK", "COCHIN": "COK"},
    }
    # Undeclared -> blocks.
    fails = [f for f in overlap_gate(mappings, raw_csv) if f.status == "fail"]
    assert any("COK" in f.check for f in fails)

    # Declared -> passes.
    mappings["concurrent_labels"] = [{"airport": "COK", "labels": ["KOCHI", "COCHIN"]}]
    assert not [f for f in overlap_gate(mappings, raw_csv) if f.status == "fail"]


def test_raw_city_pair_to_route_table_to_airport_reconciliation():
    raw = _raw([
        [2025, 1, "Alpha", "Beta", 100, 80],
        [2025, 1, "Alpha", "Gamma", 5, 0],
    ])
    route_fixture = {
        "airports": {
            "AAA": {"city": "Alpha"},
            "BBB": {"city": "Beta"},
            "CCC": {"city": "Gamma"},
        }
    }
    routes = build_domestic_routes(raw, build_airport_resolver(route_fixture))
    airport = airport_monthly_from_routes(routes)

    assert len(routes) == 4  # two directed observations per source pair
    by_airport = airport.set_index("airport")
    assert by_airport.loc["AAA", "departures"] == 105
    assert by_airport.loc["AAA", "arrivals"] == 80
    assert airport["departures"].sum() == routes["passengers"].sum()
    assert airport["arrivals"].sum() == routes["passengers"].sum()
