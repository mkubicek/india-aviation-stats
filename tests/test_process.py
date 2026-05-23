"""Tests for source processing helpers."""

from process import city_to_iata, source_csv


def test_city_to_iata_aliases_common_city_names():
    assert city_to_iata("Bengaluru") == "BLR"
    assert city_to_iata("Bombay") == "BOM"
    assert city_to_iata("Trivandrum") == "TRV"


def test_city_to_iata_keeps_unknown_as_uppercase_source_name():
    assert city_to_iata("Unknown Field") == "UNKNOWN FIELD"


def test_source_csv_points_to_direct_aviation_aggregate():
    path = source_csv("domestic/city.csv")
    assert path.as_posix().endswith("data/raw/aviation/aggregated/domestic/city.csv")
