"""Tests for direct-source ingestion parsers."""

import pandas as pd

from normalize import (
    _dgca_source_url_variants,
    _split_combined_pdf_city,
    aggregate_international,
    cleanup_obsolete_international_pdf_fallbacks,
    missing_international_table4_pdf_urls,
    parse_domestic_carrier_file,
    parse_domestic_city_file,
)


def _write_xlsx(path, rows):
    pd.DataFrame(rows).to_excel(path, header=False, index=False)


def test_dgca_source_url_variants_try_uppercase_month_and_extra_space():
    url = (
        "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/"
        "InventoryList/dataReports/aviationDataStatistics/airTransport/"
        "domestic/monthly/DOM CITYPAIR DATA, May 2021.xlsx"
    )

    variants = _dgca_source_url_variants(url)

    decoded = [variant.replace("%20", " ") for variant in variants]
    assert any("DOM CITYPAIR DATA, MAY 2021.xlsx" in variant for variant in decoded)
    assert any("DOM CITYPAIR DATA,  MAY 2021.xlsx" in variant for variant in decoded)


def test_international_table4_pdf_fallback_only_when_excel_is_absent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for table in [1, 2, 3]:
        (source / f"26Q1_{table}.xlsx").write_bytes(b"x")
    for table in [1, 2, 3, 4]:
        (source / f"25Q4_{table}.xlsx").write_bytes(b"x")

    urls = missing_international_table4_pdf_urls(source)

    assert urls == [
        "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/"
        "InventoryList/dataReports/aviationDataStatistics/airTransport/"
        "international/quaterly/26Q1_4.pdf"
    ]


def test_obsolete_international_table4_pdf_fallback_is_removed(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    pdf = source / "26Q1_4.pdf"
    pdf.write_bytes(b"pdf")
    (source / "26Q1_4.xlsx").write_bytes(b"xlsx")

    assert cleanup_obsolete_international_pdf_fallbacks(source) == 1
    assert not pdf.exists()


def test_pdf_combined_city_split_uses_known_airport_source_labels():
    assert _split_combined_pdf_city("BANDAR SERI BEGAWANCHENNAI") == (
        "BANDAR SERI BEGAWAN",
        "CHENNAI",
    )
    assert _split_combined_pdf_city("HAA DHAALU ATOLLTRIVANDRUM") == (
        "HAA DHAALU ATOLL",
        "TRIVANDRUM",
    )


def test_parse_domestic_city_file(tmp_path):
    path = tmp_path / "DOM CITYPAIR DATA, APRIL 2025.xlsx"
    _write_xlsx(
        path,
        [
            ["City Pair wise Passenger, Freight & Mail Traffic Statistics For April 2025"],
            ["Passengers ( In Number ), Freight ( In Tonne ), Mail ( In Tonne )"],
            [
                "S.No.",
                "CITY 1",
                "CITY 2",
                "PASSENGERS TO CITY 2",
                "PASSENGERS FROM CITY 2",
                "FREIGHT TO CITY 2",
                "FREIGHT FROM CITY 2",
                "MAIL TO CITY 2",
                "MAIL FROM CITY 2",
            ],
            [1, "Agartala", "Bengaluru", "3,661", 4247, 2.741, 20.626, 0, 0.252],
        ],
    )

    parsed = parse_domestic_city_file(path)

    assert len(parsed) == 1
    row = parsed.iloc[0]
    assert row["Year"] == 2025
    assert row["Month"] == "04"
    assert row["City1"] == "AGARTALA"
    assert row["City2"] == "BENGALURU"
    assert row["PaxToCity2"] == 3661.0
    assert row["FreightFromCity2"] == 20.626


def test_parse_domestic_city_file_keeps_blank_reverse_direction(tmp_path):
    path = tmp_path / "DOM CITYPAIR DATA, APRIL 2025.xlsx"
    _write_xlsx(
        path,
        [
            ["City Pair wise Passenger Traffic Statistics For April 2025"],
            [
                "S.No.",
                "CITY 1",
                "CITY 2",
                "PASSENGERS TO CITY 2",
                "PASSENGERS FROM CITY 2",
            ],
            [1, "Delhi", "Mumbai", 100, None],
        ],
    )

    parsed = parse_domestic_city_file(path)

    assert len(parsed) == 1
    assert parsed.iloc[0]["PaxToCity2"] == 100
    assert parsed.iloc[0]["PaxFromCity2"] == 0


def test_parse_domestic_carrier_file(tmp_path):
    path = tmp_path / "indigo25.xlsx"
    _write_xlsx(
        path,
        [
            [
                "2025",
                "",
                "Monthly Traffic And Operating Statistics ( Scheduled Domestic Services)",
            ],
            ["MONTH", "AIRCRAFT FLOWN"],
            ["JAN", 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
            [
                "2025",
                "",
                "Monthly Traffic And Operating Statistics (Non- Scheduled International Services)",
            ],
            ["FEB", 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116],
        ],
    )

    parsed = parse_domestic_carrier_file(path)

    assert list(parsed["Type"]) == ["ScheduledDomestic", "NonScheduledInternational"]
    assert list(parsed["Airline"]) == ["IndiGo", "IndiGo"]
    assert list(parsed["Year"]) == [2025, 2025]
    assert list(parsed["Month"]) == ["01", "02"]
    assert parsed.iloc[0]["Passenger Number"] == 4
    assert parsed.iloc[0]["Freight Tonne Kilometer"] == 12
    assert parsed.iloc[0]["Mail Tonne Kilometer"] == 13


def test_aggregate_international_table4(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "out"
    source.mkdir()
    _write_xlsx(
        source / "25Q1_4.xlsx",
        [
            ["TABLE 4. CITYPAIRWISE INTERNATIONAL PASSENGER AND FREIGHT STATISTICS"],
            ["SL.No.", "CITY 1", "CITY 2", "PASSENGERS TO CITY 2", "PASSENGERS FROM CITY 2", "FREIGHT TO CITY 2", "FREIGHT FROM CITY 2"],
            [1, "Abudhabi", "Ahmedabad", 44597, 55527, 84.098, 393.701],
        ],
    )

    result = aggregate_international(source, output)

    city = result["city"]
    assert len(city) == 1
    row = city.iloc[0]
    assert row["Year"] == 25
    assert row["Quarter"] == 1
    assert row["City1"] == "ABUDHABI"
    assert row["City2"] == "AHMEDABAD"
    assert row["PaxFromCity2"] == 55527
    assert (output / "international" / "city.csv").exists()
