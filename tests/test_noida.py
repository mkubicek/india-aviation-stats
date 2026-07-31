"""Mechanical checks for the Noida focus page generator.

These pin the review rules that are testable without real data: page/copy
consistency, sign-derived verdict language, gap honesty, and crash resistance
on hostile publication patterns.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import noida
from metrics import KNOWN_ZERO_MONTHS, domestic_demand_series


@pytest.fixture(autouse=True)
def clean_register():
    noida.REGISTER.clear()
    yield
    noida.REGISTER.clear()


def month_frame(rows: list[tuple[int, int, str, int]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["year", "month", "airport", "passengers"])


# ---------------------------------------------------------------------------
# Page structure
# ---------------------------------------------------------------------------

def test_page_order_matches_copy_and_semantics():
    assert set(noida.PAGE_ORDER) == set(noida.EXHIBIT_COPY)
    assert set(noida.PENDING_REASON) <= set(noida.PAGE_ORDER)
    assert set(noida.PAGE_ORDER) <= set(noida.NOIDA_SEMANTICS)


def test_write_page_with_nothing_generated_renders_placeholders(tmp_path, monkeypatch):
    monkeypatch.setattr(noida, "PAGE_PATH", tmp_path / "noida.html")
    page = noida.write_page([], "2026-07-19", monthly=month_frame([(2024, 1, "DEL", 100)]))
    html = page.read_text(encoding="utf-8")
    assert html.count("Pending exhibit.") == len(noida.PAGE_ORDER)
    assert "\u2014" not in html  # no em-dashes anywhere on the page
    assert "Not yet testable" in html
    assert "published no DXN airport rows yet" in html


def test_dxn_status_item_flips_when_rows_land():
    no_rows = noida.dxn_status_item(month_frame([(2024, 1, "DEL", 100)]))
    assert "no DXN airport rows yet" in no_rows
    with_rows = noida.dxn_status_item(
        month_frame([(2026, 6, "DXN", 20_058), (2026, 7, "DXN", 30_000)])
    )
    assert "published 2 DXN months so far (from Jun 2026" in with_rows
    assert "no DXN airport rows" not in with_rows


def test_white_space_moves_from_untestable_to_tested_with_stats():
    tested, untestable = noida.register_entries([])
    assert any("white space" in claim for claim, _ in untestable)

    noida.REGISTER["white_space"] = dict(
        floor=100_000, n_candidates=60, n_del_markets=92, n_white=0,
        top_white=None, window="Jul 2025-Jun 2026",
    )
    tested, untestable = noida.register_entries([])
    assert not any("white space" in claim for claim, _ in untestable)
    verdict = dict(tested)["Noida opens into empty white space no airline serves."]
    assert verdict.startswith("Rejected")

    noida.REGISTER["white_space"].update(n_white=3, top_white=("IXZ", 250_000.0))
    tested, _ = noida.register_entries([])
    verdict = dict(tested)["Noida opens into empty white space no airline serves."]
    assert verdict.startswith("Largely rejected: only") and "3 of 60" in verdict

    noida.REGISTER["white_space"].update(n_white=20)
    tested, _ = noida.register_entries([])
    verdict = dict(tested)["Noida opens into empty white space no airline serves."]
    assert verdict.startswith("Partly supported") and "20 of 60" in verdict


# ---------------------------------------------------------------------------
# Verdict language derives from computed signs
# ---------------------------------------------------------------------------

def test_small_city_verdict_flips_with_direction():
    noida.REGISTER["small_city"] = dict(now=43.0, first=35.0, first_year=2016, last_year=2025)
    (claim, verdict), = noida.register_entries([])[0]
    assert verdict.startswith("Rejected") and "rose" in verdict

    noida.REGISTER["small_city"] = dict(now=16.0, first=35.0, first_year=2016, last_year=2025)
    (claim, verdict), = noida.register_entries([])[0]
    assert verdict.startswith("Supported") and "fell" in verdict
    assert "rose" not in verdict


def test_supply_verdict_flips_with_direction():
    noida.REGISTER["supply"] = dict(ask_yoy=-7.2, rpk_yoy=-9.3)
    (claim, verdict), = noida.register_entries([])[0]
    assert verdict.startswith("Supported")
    assert "fell 7.2%" in verdict


def test_relief_verdict_grades_by_displacement_and_shuns_causal_language():
    noida.REGISTER["relief"] = dict(bom_yoy=-2.5, sys_yoy=8.2, months=5, displaced=0.24)
    noida.REGISTER["hindon"] = dict(
        ceiling_k=3, quiet_years=4, quiet_observed=38, quiet_calendar=48,
        peak_k=159.0, peak_month="Aug 2025", latest_k=46.0, latest_month="May 2026",
        receded=True,
    )
    tested, _ = noida.register_entries([])
    relief_verdict = dict(tested)["A second airport mostly cannibalizes the incumbent."]
    assert relief_verdict.startswith("Not supported so far (5 published months)")
    for _, verdict in tested:
        assert "committed" not in verdict and "receded" not in verdict

    noida.REGISTER["relief"]["displaced"] = 0.8
    tested, _ = noida.register_entries([])
    relief_verdict = dict(tested)["A second airport mostly cannibalizes the incumbent."]
    assert relief_verdict.startswith("Partly supported")


def test_hindon_verdict_requires_breakout_margin():
    noida.REGISTER["hindon"] = dict(
        ceiling_k=3, quiet_years=4, quiet_observed=38, quiet_calendar=48,
        peak_k=9.0, peak_month="Aug 2025", latest_k=9.0, latest_month="May 2026",
        receded=False,
    )
    (claim, verdict), = noida.register_entries([])[0]
    assert verdict.startswith("Consistent with the data so far")


def test_pct_phrase_signs():
    assert noida.pct_phrase(3.1) == "grew +3.1%"
    assert noida.pct_phrase(-7.8) == "fell 7.8%"
    assert "flat" in noida.pct_phrase(0.02)
    assert noida.year_word(1) == "1 year"
    assert noida.year_word(4) == "4 years"


# ---------------------------------------------------------------------------
# Gap honesty
# ---------------------------------------------------------------------------

def test_t12_series_breaks_on_unpublished_month():
    rows = [(2024, m, "LKO", 100) for m in range(1, 13)]
    rows += [(2025, m, "LKO", 100) for m in range(1, 13) if m != 6]  # 2025-06 missing
    t12 = noida.t12_series(month_frame(rows), "LKO")
    assert t12 is not None
    assert t12.loc[pd.Period("2024-12", "M")] == 1200
    # every window spanning the missing month is void, not zero-filled
    assert np.isnan(t12.loc[pd.Period("2025-12", "M")])


def test_domestic_demand_series_voids_unknown_gaps_but_zeroes_known_month():
    def carrier_frame(missing: pd.Period) -> pd.DataFrame:
        periods = pd.period_range("2019-01", "2021-12", freq="M")
        rows = [
            {"airline": "IndiGo", "service_type": "scheduled_domestic",
             "year": p.year, "month": p.month, "passengers": 1000}
            for p in periods
            if p != missing
        ]
        return pd.DataFrame(rows)

    known = KNOWN_ZERO_MONTHS[0]  # 2020-04
    demand = domestic_demand_series(carrier_frame(known))
    assert demand.national.loc[known] == 0  # documented real zero
    assert demand.trailing_12m.loc[pd.Period("2021-03", "M")] == 11_000

    other = pd.Period("2021-03", "M")
    demand = domestic_demand_series(carrier_frame(other))
    assert np.isnan(demand.national.loc[other])
    assert np.isnan(demand.trailing_12m.loc[pd.Period("2021-12", "M")])


# ---------------------------------------------------------------------------
# Crash resistance on hostile publication patterns
# ---------------------------------------------------------------------------

def test_hindon_alternating_months_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(noida, "OUT_DIR", tmp_path)
    rows = [(2020 + (m // 12), (m % 12) + 1, "HDO", 1000) for m in range(0, 48, 2)]
    assert noida.chart_hindon_lesson(
        month_frame(rows), coverage="x", fingerprint="y"
    ) is None


def test_relief_valve_missing_bom_month_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(noida, "OUT_DIR", tmp_path)
    rows = [(2025, m, "BOM", 3_000_000) for m in range(1, 13) if m != 2]
    rows += [(2026, m, "BOM", 3_000_000) for m in range(1, 6)]
    rows += [(2026, m, "NMIA", 200_000) for m in range(1, 6)]
    assert noida.chart_relief_valve(
        month_frame(rows), coverage="x", fingerprint="y"
    ) is None


def test_relief_valve_complete_windows_generates(tmp_path, monkeypatch):
    monkeypatch.setattr(noida, "OUT_DIR", tmp_path)
    rows = [(2025, m, "BOM", 3_000_000) for m in range(1, 13)]
    rows += [(2026, m, "BOM", 3_000_000) for m in range(1, 6)]
    rows += [(2026, m, "NMIA", 200_000) for m in range(1, 6)]
    assert noida.chart_relief_valve(
        month_frame(rows), coverage="x", fingerprint="y"
    ) == "noida_relief_valve"
    assert noida.REGISTER["relief"]["months"] == 5


def test_white_space_refuses_to_publish_on_a_broken_del_baseline(capsys):
    """A collapsed DEL baseline means DEL's rows are missing, not that the
    country lost its Delhi routes; no verdict may be published from it."""
    rows = []
    for m in range(1, 13):
        for other in ("BLR", "HYD", "MAA"):
            rows.append({"year": 2026, "month": m, "origin": other,
                         "destination": "BOM", "passengers": 50_000})
    routes = pd.DataFrame(rows)
    routes["period"] = pd.PeriodIndex(
        pd.to_datetime(dict(year=routes.year, month=routes.month, day=1)), freq="M")
    noida.white_space_stats(routes)
    assert "white_space" not in noida.REGISTER
    tested, untestable = noida.register_entries([])
    assert any("white space" in claim for claim, _ in untestable)


def test_white_space_ignores_zero_passenger_del_rows():
    rows = []
    partners = [f"A{i:02d}" for i in range(40)]
    for m in range(1, 13):
        for p in partners:
            rows.append({"year": 2026, "month": m, "origin": "DEL",
                         "destination": p, "passengers": 20_000})
        # a published but empty DEL market: must NOT count as served
        rows.append({"year": 2026, "month": m, "origin": "DEL",
                     "destination": "ZZZ", "passengers": 0})
        rows.append({"year": 2026, "month": m, "origin": "ZZZ",
                     "destination": "A00", "passengers": 20_000})
    routes = pd.DataFrame(rows)
    routes["period"] = pd.PeriodIndex(
        pd.to_datetime(dict(year=routes.year, month=routes.month, day=1)), freq="M")
    noida.white_space_stats(routes)
    ws = noida.REGISTER["white_space"]
    assert ws["n_del_markets"] == len(partners)  # ZZZ's 0-pax rows do not count
    assert ws["n_white"] == 1
    assert ws["top_white"] is not None and ws["top_white"][0] == "ZZZ"
