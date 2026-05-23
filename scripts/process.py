"""Process official-source India aviation aggregates into chart-ready tables.

Aviation aggregate format:
  - domestic/city.csv: Year, Month, City1, City2, PaxToCity2, PaxFromCity2, ...
  - international/city.csv: Year(2-digit), Quarter, City1, City2, PaxToCity2, PaxFromCity2, ...
  - domestic/carrier.csv: carrier-level data

Outputs (in data/processed/):
  - airport_monthly.csv  Airport passenger data. Domestic rows are monthly;
                         international rows are quarterly source values mapped
                         to the middle month of each quarter.
  - airport_yearly.csv   Calendar-year airport passenger totals by category.
  - carrier_monthly.csv  Domestic carrier source rows.
  - metadata.json        Processing metadata.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
AVIATION_AGG_DIR = RAW_DIR / "aviation" / "aggregated"
PROCESSED_DIR = ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

# City name → IATA code mapping (DGCA source files use city names, not IATA codes)
# Built from mappings.yaml airports section
CITY_TO_IATA = {}
for iata, info in MAPPINGS.get("airports", {}).items():
    city = info.get("city", "").upper()
    if city:
        CITY_TO_IATA[city] = iata
    # Also map by common variations
    name = info.get("name", "").upper()
    if name:
        CITY_TO_IATA[name] = iata

# Additional city name mappings (DGCA source files use inconsistent naming)
CITY_ALIASES = {
    "DELHI": "DEL",
    "NEW DELHI": "DEL",
    "MUMBAI": "BOM",
    "BOMBAY": "BOM",
    "BANGALORE": "BLR",
    "BENGALURU": "BLR",
    "HYDERABAD": "HYD",
    "CHENNAI": "MAA",
    "MADRAS": "MAA",
    "KOLKATA": "CCU",
    "CALCUTTA": "CCU",
    "GOA": "GOI",
    "MORMUGAO": "GOI",
    "KOCHI": "COK",
    "COCHIN": "COK",
    "AHMEDABAD": "AMD",
    "PUNE": "PNQ",
    "JAIPUR": "JAI",
    "GUWAHATI": "GAU",
    "LUCKNOW": "LKO",
    "THIRUVANANTHAPURAM": "TRV",
    "TRIVANDRUM": "TRV",
    "MANGALORE": "IXE",
    "MANGALURU": "IXE",
    "KOZHIKODE": "CCJ",
    "CALICUT": "CCJ",
    "SRINAGAR": "SXR",
    "BHUBANESWAR": "BBI",
    "RANCHI": "IXR",
    "VISAKHAPATNAM": "VTZ",
    "VIZAG": "VTZ",
    "NAGPUR": "NAG",
    "INDORE": "IDR",
    "PATNA": "PAT",
    "CHANDIGARH": "IXC",
    "VARANASI": "VNS",
    "SILIGURI": "IXB",
    "BAGDOGRA": "IXB",
    "RAIPUR": "RPR",
    "KANNUR": "MAQ",
    "AGARTALA": "IXA",
    "IMPHAL": "IMF",
    "DIBRUGARH": "DIB",
    "JABALPUR": "JLR",
    "UDAIPUR": "UDR",
    "VADODARA": "BDQ",
    "BARODA": "BDQ",
    "RAJKOT": "RAJ",
    "JAMMU": "IXJ",
    "DEOGHAR": "DEP",
    "JODHPUR": "JDH",
    "GAYA": "GAY",
    "PORT BLAIR": "IXZ",
    "AMRITSAR": "ATQ",
    "TIRUPATI": "TIR",
    "COIMBATORE": "CJB",
    "SURAT": "STV",
    "SILCHAR": "IXS",
    "TIRUCHIRAPPALLI": "TRZ",
    "TRICHY": "TRZ",
    "DEHRADUN": "DED",
    "MADURAI": "IXM",
    "BHOPAL": "BHO",
    "AIZAWL": "AJL",
    "DIMAPUR": "DMU",
    "JORHAT": "JRH",
    "HUBLI": "HBX",
    "SHILLONG": "SHL",
    "KANPUR": "KNU",
    "AGRA": "AGR",
    "KULLU": "KUU",
    "DHARAMSHALA": "DHM",
    "ITANAGAR": "HGI",
    "DURGAPUR": "DGH",
    "GORAKHPUR": "GOP",
}
CITY_ALIASES = {k.upper(): v for k, v in CITY_ALIASES.items()}


def city_to_iata(city_name: str) -> str:
    """Map a source city name to IATA code. Returns city name if no mapping."""
    name = city_name.strip().upper()
    if name in CITY_ALIASES:
        return CITY_ALIASES[name]
    if name in CITY_TO_IATA:
        return CITY_TO_IATA[name]
    return name  # Return as-is if no mapping found


def source_csv(rel_path: str) -> Path:
    """Return a normalized direct-source aggregate path."""
    return AVIATION_AGG_DIR / rel_path


# ── Aviation city data ───────────────────────────────────────


def process_domestic_city():
    """Parse domestic/city.csv into airport-level monthly data.

    Format: Year, Month, City1, City2, PaxToCity2, PaxFromCity2, Freight..., Mail...
    PaxToCity2 = passengers flying City1→City2
    PaxFromCity2 = passengers flying City2→City1
    """
    path = source_csv("domestic/city.csv")
    if not path.exists():
        print("  WARNING: domestic/city.csv not found, skipping", flush=True)
        return None

    print(f"  Processing {path.relative_to(ROOT)}...", flush=True)
    df = pd.read_csv(path)
    print(f"    Raw rows: {len(df):,}, columns: {list(df.columns)}")

    # Convert passenger columns to numeric
    df["PaxToCity2"] = pd.to_numeric(df["PaxToCity2"], errors="coerce").fillna(0)
    df["PaxFromCity2"] = pd.to_numeric(df["PaxFromCity2"], errors="coerce").fillna(0)

    # Aggregate by airport: each city appears as both City1 and City2
    # When city = City1: departures = PaxToCity2, arrivals = PaxFromCity2
    # When city = City2: arrivals = PaxToCity2, departures = PaxFromCity2
    # Total passengers at airport = departures + arrivals for all routes

    # As City1 (origin)
    as_origin = (
        df.groupby(["Year", "Month", "City1"])
        .agg(departures=("PaxToCity2", "sum"), arrivals=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City1": "city"})
    )

    # As City2 (destination)
    as_dest = (
        df.groupby(["Year", "Month", "City2"])
        .agg(arrivals=("PaxToCity2", "sum"), departures=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City2": "city"})
    )

    # Combine: total passengers = departures + arrivals from both roles
    combined = pd.concat([as_origin, as_dest], ignore_index=True)
    monthly = (
        combined.groupby(["Year", "Month", "city"])
        .agg(departures=("departures", "sum"), arrivals=("arrivals", "sum"))
        .reset_index()
    )
    monthly["passengers"] = monthly["departures"] + monthly["arrivals"]
    monthly = monthly.rename(columns={"Year": "year", "Month": "month"})

    # Map city names to IATA codes
    monthly["airport"] = monthly["city"].apply(city_to_iata)
    monthly["category"] = "domestic"

    result = monthly[["year", "month", "airport", "category", "passengers", "departures", "arrivals"]]
    print(f"    Processed: {len(result):,} airport-month records, "
          f"{result['airport'].nunique()} unique airports")
    return result


def process_international_city():
    """Parse international/city.csv into airport-level quarterly data.

    Format: Year(2-digit), Quarter, City1, City2, PaxToCity2, PaxFromCity2, Freight...
    Note: Year is 2-digit (15=2015, 20=2020, etc.)
    """
    path = source_csv("international/city.csv")
    if not path.exists():
        print("  WARNING: international/city.csv not found, skipping", flush=True)
        return None

    print(f"  Processing {path.relative_to(ROOT)}...", flush=True)
    df = pd.read_csv(path)
    print(f"    Raw rows: {len(df):,}, columns: {list(df.columns)}")

    # Fix 2-digit year: assume 20xx
    df["Year"] = df["Year"].apply(lambda y: y + 2000 if y < 100 else y)

    df["PaxToCity2"] = pd.to_numeric(df["PaxToCity2"], errors="coerce").fillna(0)
    df["PaxFromCity2"] = pd.to_numeric(df["PaxFromCity2"], errors="coerce").fillna(0)

    # Aggregate by Indian city only (filter to Indian airports)
    # International routes: City1 or City2 may be foreign cities
    all_indian_cities = set(CITY_ALIASES.keys()) | set(
        info.get("city", "").upper() for info in MAPPINGS.get("airports", {}).values()
    )

    # As City1 (Indian origin for international routes)
    as_origin = (
        df.groupby(["Year", "Quarter", "City1"])
        .agg(departures=("PaxToCity2", "sum"), arrivals=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City1": "city"})
    )

    # As City2 (Indian destination for international routes)
    as_dest = (
        df.groupby(["Year", "Quarter", "City2"])
        .agg(arrivals=("PaxToCity2", "sum"), departures=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City2": "city"})
    )

    combined = pd.concat([as_origin, as_dest], ignore_index=True)
    quarterly = (
        combined.groupby(["Year", "Quarter", "city"])
        .agg(departures=("departures", "sum"), arrivals=("arrivals", "sum"))
        .reset_index()
    )
    quarterly["passengers"] = quarterly["departures"] + quarterly["arrivals"]
    quarterly = quarterly.rename(columns={"Year": "year", "Quarter": "quarter"})

    # Map city names to IATA codes
    quarterly["airport"] = quarterly["city"].apply(city_to_iata)

    # Filter to known Indian airports (discard foreign city rows)
    known_iata = set(MAPPINGS.get("airports", {}).keys())
    indian_mask = quarterly["airport"].isin(known_iata)
    quarterly = quarterly[indian_mask].copy()

    quarterly["category"] = "international"

    # Convert quarterly to pseudo-monthly (assign to middle month of quarter)
    # Q1=1→month 2, Q2=2→month 5, Q3=3→month 8, Q4=4→month 11
    quarter_to_month = {1: 2, 2: 5, 3: 8, 4: 11}
    quarterly["month"] = quarterly["quarter"].map(quarter_to_month)

    result = quarterly[["year", "month", "airport", "category", "passengers", "departures", "arrivals"]]
    print(f"    Processed: {len(result):,} airport-quarter records, "
          f"{result['airport'].nunique()} unique Indian airports")
    return result


def classify_airport(iata: str, annual_pax: float) -> str:
    """Classify an airport into a tier based on mappings.yaml and volume."""
    airports = MAPPINGS.get("airports", {})
    if iata in airports:
        return airports[iata].get("tier", "tier3")

    # Fallback: classify by volume
    if annual_pax > 20_000_000:
        return "metro"
    elif annual_pax > 5_000_000:
        return "tier1"
    elif annual_pax > 1_000_000:
        return "tier2"
    else:
        return "tier3"


def process_airport_data():
    """Build airport_monthly.csv and airport_yearly.csv from aviation data."""
    frames = []

    domestic = process_domestic_city()
    if domestic is not None:
        frames.append(domestic)

    international = process_international_city()
    if international is not None:
        frames.append(international)

    if not frames:
        print("  WARNING: No aviation city data available", flush=True)
        return

    combined = pd.concat(frames, ignore_index=True)

    # Save monthly
    monthly_out = PROCESSED_DIR / "airport_monthly.csv"
    combined.to_csv(monthly_out, index=False)
    print(f"  Saved: {monthly_out.name} ({len(combined):,} rows)")

    # Yearly aggregation
    yearly = (
        combined.groupby(["year", "airport", "category"])["passengers"]
        .sum()
        .reset_index()
    )
    yearly["tier"] = yearly.apply(
        lambda r: classify_airport(r["airport"], r["passengers"]), axis=1
    )
    yearly_out = PROCESSED_DIR / "airport_yearly.csv"
    yearly.to_csv(yearly_out, index=False)
    print(f"  Saved: {yearly_out.name} ({len(yearly):,} rows)")

    # Top airports summary
    total_by_airport = (
        yearly.groupby("airport")["passengers"].sum().sort_values(ascending=False)
    )
    print(f"\n  Top 10 airports (all years, all categories):")
    for iata, pax in total_by_airport.head(10).items():
        tier = classify_airport(iata, pax / yearly["year"].nunique())
        print(f"    {iata:>10s}: {pax:>15,.0f}  ({tier})")


# ── Aviation carrier data ────────────────────────────────────


def process_carrier_data():
    """Build carrier_monthly.csv from source carrier data."""
    path = source_csv("domestic/carrier.csv")
    if not path.exists():
        print("  WARNING: domestic/carrier.csv not found, skipping", flush=True)
        return

    print(f"  Processing {path.relative_to(ROOT)}...", flush=True)
    df = pd.read_csv(path)
    print(f"    Raw rows: {len(df):,}, columns: {list(df.columns)}")

    # Save processed carrier data
    out = PROCESSED_DIR / "carrier_monthly.csv"
    df.to_csv(out, index=False)
    print(f"  Saved: {out.name} ({len(df):,} rows)")


def write_metadata():
    """Write metadata.json with processing date."""
    meta = {
        "data_date": str(date.today()),
        "processed_date": str(date.today()),
    }
    (PROCESSED_DIR / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"  Saved: metadata.json (data_date={meta['data_date']})")


# ── Main ─────────────────────────────────────────────────────


def main():
    print("=== Processing Data ===\n", flush=True)
    process_airport_data()
    process_carrier_data()
    write_metadata()
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
