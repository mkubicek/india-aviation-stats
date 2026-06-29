"""Tests for the table-driven entity resolver (scripts/entities.py).

The headline cases are Goa, where a single source label (``GOA``) means two
different physical airports in two different eras, and conflict detection, which
must refuse to build a resolver where a label is ambiguously mapped.
"""

from pathlib import Path

import pytest
import yaml

from entities import (
    EntityConflictError,
    build_airport_resolver,
)

ROOT = Path(__file__).resolve().parent.parent
MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())


def _resolver(airports):
    return build_airport_resolver({"airports": airports})


# ── Goa: the validity-window headline case, against the real mappings.yaml ──

def test_real_mappings_builds_without_conflict():
    # Building the resolver from the committed table asserts no label is
    # ambiguously windowed. This guards every future mappings.yaml edit.
    build_airport_resolver(MAPPINGS)


def test_goa_label_means_dabolim_before_mopa_opened():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("GOA", 2017, 6) == "GOI"      # only airport then = Dabolim
    assert r.resolve("GOA", 2018, 12) == "GOI"     # valid_to boundary is inclusive


def test_goa_label_means_mopa_after_mopa_opened():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("GOA", 2023, 1) == "GOX"      # valid_from boundary is inclusive
    assert r.resolve("GOA", 2024, 6) == "GOX"      # ~4.6M era = Mopa


def test_goa_label_is_unmapped_in_the_gap_years():
    # 2019-2022 the source used DABOLIM, not GOA; a stray GOA there is unmapped
    # (advisory), never silently attributed to the wrong airport.
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("GOA", 2019, 1) is None
    assert r.resolve("GOA", 2022, 12) is None


def test_dabolim_label_is_always_dabolim_from_2019():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("DABOLIM", 2019, 1) == "GOI"
    assert r.resolve("DABOLIM", 2025, 12) == "GOI"
    assert r.resolve("DABOLIM", 2018, 12) is None  # before the label appears


def test_2026_longform_labels_split_correctly():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("GOA DABOLIM SOUTH GOA", 2026, 3) == "GOI"
    assert r.resolve("GOA MOPA NORTH GOA", 2026, 3) == "GOX"
    assert r.resolve("MOPA GOA", 2023, 6) == "GOX"


def test_dabolim_and_goa_never_collapse_to_one_airport():
    # The bug this whole design exists to prevent: DABOLIM (Dabolim) and the
    # 2024 GOA label (Mopa) must resolve to DIFFERENT airports.
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("DABOLIM", 2024, 6) == "GOI"
    assert r.resolve("GOA", 2024, 6) == "GOX"
    assert r.resolve("DABOLIM", 2024, 6) != r.resolve("GOA", 2024, 6)


# ── Resolution mechanics ──

def test_resolution_is_case_and_whitespace_insensitive():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("goa", 2024, 1) == "GOX"
    assert r.resolve("  Dabolim  ", 2020, 1) == "GOI"


def test_unmapped_label_returns_none():
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("WAKANDA INTL", 2024, 1) is None


def test_city_name_fallback_for_airports_without_variants():
    # DEL has no explicit variants, so its city name resolves all-time.
    r = build_airport_resolver(MAPPINGS)
    assert r.resolve("DELHI", 2020, 1) == "DEL"


# ── Rename and distinct cases (synthetic, focused) ──

def test_rename_one_airport_many_labels_over_time():
    r = _resolver(
        {
            "XXX": {
                "variants": [
                    {"label": "OLD NAME", "valid_to": "2020-12"},
                    {"label": "NEW NAME", "valid_from": "2021-01"},
                ]
            }
        }
    )
    assert r.resolve("OLD NAME", 2019, 6) == "XXX"
    assert r.resolve("NEW NAME", 2021, 6) == "XXX"
    assert r.source_labels("XXX") == ["NEW NAME", "OLD NAME"]


def test_same_label_disjoint_windows_two_airports_is_allowed():
    # Exactly the Goa shape in miniature: one label, two airports, no overlap.
    r = _resolver(
        {
            "AAA": {"variants": [{"label": "SHARED", "valid_to": "2018-12"}]},
            "BBB": {"variants": [{"label": "SHARED", "valid_from": "2023-01"}]},
        }
    )
    assert r.resolve("SHARED", 2017, 1) == "AAA"
    assert r.resolve("SHARED", 2024, 1) == "BBB"
    assert r.resolve("SHARED", 2020, 1) is None  # the gap


# ── Conflict detection: refuse to build, never guess ──

def test_overlapping_windows_same_label_two_airports_raises():
    with pytest.raises(EntityConflictError):
        _resolver(
            {
                "AAA": {"variants": [{"label": "SHARED"}]},          # all-time
                "BBB": {"variants": [{"label": "SHARED", "valid_from": "2023-01"}]},
            }
        )


def test_partial_window_overlap_raises():
    with pytest.raises(EntityConflictError):
        _resolver(
            {
                "AAA": {"variants": [{"label": "SHARED", "valid_to": "2024-06"}]},
                "BBB": {"variants": [{"label": "SHARED", "valid_from": "2024-01"}]},  # overlaps Jan-Jun 2024
            }
        )
