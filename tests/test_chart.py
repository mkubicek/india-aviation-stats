"""Tests for chart generation helpers and dashboard artifacts."""

import json
from pathlib import Path

import pandas as pd
import pytest

import chart

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def generated_chart_artifacts():
    chart.main([])
    return ROOT


def test_domestic_trailing_airport_passengers_requires_complete_windows():
    rows = []
    for month in range(1, 14):
        year = 2025 if month <= 12 else 2026
        real_month = month if month <= 12 else 1
        rows.extend(
            [
                {"year": year, "month": real_month, "airport": "DEL", "passengers": 10},
                {"year": year, "month": real_month, "airport": "BOM", "passengers": 5},
            ]
        )
    trailing = chart._domestic_trailing_airport_passengers(pd.DataFrame(rows))
    assert list(trailing.index.astype(str)) == ["2025-12", "2026-01"]
    assert trailing.loc[pd.Period("2025-12", freq="M"), "DEL"] == 120
    assert trailing.loc[pd.Period("2026-01", freq="M"), "BOM"] == 60


def test_chart_outputs_exist_after_generation(generated_chart_artifacts):
    expected = [
        "india_domestic_demand_pulse.png",
        "top_airport_traffic_trends.png",
        "newcomer_airport_rampup_24m.png",
        "domestic_market_share_gainers.png",
        "international_gateway_share_gainers.png",
        "airport_seasonality_fingerprint.png",
        "manifest.json",
    ]
    for filename in expected:
        assert (ROOT / "charts" / filename).exists()


def test_dashboard_summary_schema(generated_chart_artifacts):
    summary = json.loads((ROOT / "data/processed/dashboard_summary.json").read_text())
    assert set(summary) == {
        "data_date",
        "domestic",
        "fingerprint",
        "generated_date",
        "international",
    }
    assert summary["data_date"]
    assert summary["generated_date"]
    assert {
        "latest_month",
        "latest_month_passengers_carried",
        "latest_month_yoy_pct",
        "trailing_12m_passengers_carried",
        "trailing_12m_yoy_pct",
        "passengers_metric",
        "airports_latest_month",
        "airport_throughput_latest_month",
    } <= set(summary["domestic"])
    # The domestic headline is passengers carried (carrier table), and the old
    # ambiguous generic key must not survive.
    assert "latest_month_passengers" not in summary["domestic"]
    assert summary["domestic"]["passengers_metric"] == "scheduled_domestic_passengers_carried"
    assert {
        "latest_quarter",
        "latest_4q_passengers",
        "latest_4q_yoy_pct",
        "gateways_latest_quarter",
    } <= set(summary["international"])
    assert summary["fingerprint"].startswith("sha256:")


def test_chart_manifest_references_existing_files(generated_chart_artifacts):
    manifest = json.loads((ROOT / "charts/manifest.json").read_text())
    for record in manifest["charts"].values():
        path = ROOT / record["file"]
        assert path.exists()
        assert record["sha256"] == chart.sha256_file(path)


def test_newcomer_ramp_excludes_left_censored_airports():
    rows = []
    for month in (1, 2, 3):
        rows.append(
            {"year": 2020, "month": month, "airport": "OLD", "passengers": 80_000}
        )
    for month in (1, 2, 3):
        rows.append(
            {"year": 2021, "month": month, "airport": "NEW", "passengers": 80_000}
        )

    ramps = chart.newcomer_airport_ramps(
        pd.DataFrame(rows),
        min_cumulative_available=0,
        min_peak_month=0,
    )
    airports = set(ramps["airport"])
    assert "NEW" in airports
    assert "OLD" not in airports


def test_domestic_market_share_windows_are_disjoint_and_complete():
    rows = []
    for period in pd.period_range("2024-01", "2025-12", freq="M"):
        rows.extend(
            [
                {
                    "year": period.year,
                    "month": period.month,
                    "airport": "AAA",
                    "passengers": 100,
                },
                {
                    "year": period.year,
                    "month": period.month,
                    "airport": "BBB",
                    "passengers": 50,
                },
            ]
        )
    pivot = chart.domestic_airport_month_matrix(pd.DataFrame(rows))
    latest, previous = chart.complete_share_window_periods(pivot.index, window=12)
    assert len(latest) == 12
    assert len(previous) == 12
    assert set(latest).isdisjoint(previous)
    assert set(latest + previous) <= set(pivot.index)
    assert latest[-1] == pd.Period("2025-12", freq="M")
    assert previous[-1] == pd.Period("2024-12", freq="M")


def test_share_movers_subtitle_discloses_selection_and_windows():
    movers = pd.DataFrame(
        {
            "airport": ["AAA", "BBB", "CCC", "DDD"],
            "delta_pp": [1.5, 0.3, -0.2, -1.1],
        }
    )
    latest = list(pd.period_range("2025-06", "2026-05", freq="M"))
    previous = list(pd.period_range("2024-06", "2025-05", freq="M"))
    subtitle = chart.share_movers_subtitle(
        movers,
        latest_periods=latest,
        previous_periods=previous,
        active=138,
        noun="airports",
        scope="Share of domestic airport throughput",
        fmt=chart.format_month_period,
    )
    # Selection is disclosed: how many gainers/decliners of how many entities.
    assert "2 gainers" in subtitle
    assert "2 decliners" in subtitle
    assert "138 airports" in subtitle
    # The metric scope is named so the bars are not read as passengers carried.
    assert "domestic airport throughput" in subtitle
    # Comparison windows are named explicitly, not left to the footer.
    assert "Jun 2025–May 2026" in subtitle
    assert "Jun 2024–May 2025" in subtitle


def test_share_movers_subtitle_names_quarter_windows():
    movers = pd.DataFrame({"airport": ["AAA", "BBB"], "delta_pp": [0.5, -0.5]})
    latest = list(pd.period_range("2025Q2", "2026Q1", freq="Q"))
    previous = list(pd.period_range("2024Q2", "2025Q1", freq="Q"))
    subtitle = chart.share_movers_subtitle(
        movers,
        latest_periods=latest,
        previous_periods=previous,
        active=31,
        noun="gateways",
        scope="Indian airport gateway throughput",
        fmt=chart.format_quarter_period,
    )
    assert "31 gateways" in subtitle
    assert "gateway throughput" in subtitle
    assert "2025Q2–2026Q1" in subtitle
    assert "2024Q2–2025Q1" in subtitle


def test_international_share_windows_are_disjoint_and_complete():
    rows = []
    for period in pd.period_range("2024Q1", "2025Q4", freq="Q"):
        rows.extend(
            [
                {
                    "year": period.year,
                    "quarter": period.quarter,
                    "airport": "AAA",
                    "passengers": 100,
                },
                {
                    "year": period.year,
                    "quarter": period.quarter,
                    "airport": "BBB",
                    "passengers": 50,
                },
            ]
        )
    pivot = chart.international_airport_quarter_matrix(pd.DataFrame(rows))
    latest, previous = chart.complete_share_window_periods(pivot.index, window=4)
    assert len(latest) == 4
    assert len(previous) == 4
    assert set(latest).isdisjoint(previous)
    assert set(latest + previous) <= set(pivot.index)
    assert latest[-1] == pd.Period("2025Q4", freq="Q")
    assert previous[-1] == pd.Period("2024Q4", freq="Q")


def test_seasonality_uses_complete_years_only():
    rows = [
        {"year": 2023, "month": month, "airport": "AAA", "passengers": 1_000}
        for month in range(1, 13)
    ]
    rows.append({"year": 2024, "month": 1, "airport": "AAA", "passengers": 12_000})
    matrix = chart.seasonality_fingerprint_matrix(
        pd.DataFrame(rows),
        min_complete_years=1,
        min_latest_t12=0,
    )
    assert list(matrix.columns) == list(range(1, 13))
    assert matrix.loc["AAA", 1] == pytest.approx(100)
    assert matrix.loc["AAA", 12] == pytest.approx(100)


def test_stable_color_is_deterministic():
    assert chart.stable_color("DEL") == chart.stable_color("DEL")
    assert chart.stable_color("BOM") == chart.stable_color("BOM")


def test_chart_manifest_stable_for_same_inputs(generated_chart_artifacts):
    manifest = json.loads((ROOT / "charts/manifest.json").read_text())
    monthly = pd.read_csv(ROOT / "data/processed/airport_monthly.csv")
    quarterly = pd.read_csv(ROOT / "data/processed/airport_international_quarterly.csv")
    carrier = pd.read_csv(ROOT / "data/processed/carrier_monthly.csv")
    kwargs = {
        "monthly": monthly,
        "quarterly": quarterly,
        "carrier": carrier,
        "domestic_coverage_text": chart.domestic_coverage(monthly),
        "international_coverage_text": chart.international_coverage(quarterly),
        "carrier_coverage_text": chart.carrier_domestic_coverage(carrier),
        "overall_fingerprint": chart.input_fingerprint(
            [
                ROOT / "data/processed/airport_monthly.csv",
                ROOT / "data/processed/airport_international_quarterly.csv",
                ROOT / "data/processed/carrier_monthly.csv",
            ]
        ),
    }
    rebuilt_once = chart.build_chart_manifest(manifest["charts"], **kwargs)
    rebuilt_twice = chart.build_chart_manifest(manifest["charts"], **kwargs)
    assert rebuilt_once == rebuilt_twice
    assert rebuilt_once == manifest
