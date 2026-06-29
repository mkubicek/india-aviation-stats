"""Clean normalized DGCA aggregates into the standardized canonical tables.

Resolution is 100% table-driven (``mappings.yaml`` entity tables + the flat
``airport_aliases`` spelling map) via the validity-window resolver — there is no
hardcoded fallback. A label that does not resolve is foreign (international
counterpart city) and is dropped; a *domestic* label that fails to resolve is a
real coverage loss and is surfaced.

Published tables (in ``data/processed/``) — three source tables + one derived view:
  ``airport_monthly.csv``                domestic, monthly (the canonical core)
  ``airport_international_quarterly.csv`` international, real quarter
  ``carrier_monthly.csv``                airline monthly (see clean carrier)
  ``airport_yearly.csv``                 derived from monthly + quarterly (whole years)

Schema (the airport tables): ``passengers == departures + arrivals``, whole-person
integers. No ``tier`` (presentation-only, lives in chart config) and no
``category`` on airport_monthly (constant once domestic-only).
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from entities import build_airport_resolver, build_airline_resolver

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
AVIATION_AGG_DIR = RAW_DIR / "aviation" / "aggregated"
PROCESSED_DIR = ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

MAPPINGS = yaml.safe_load((ROOT / "mappings.yaml").read_text())

# Validity-window entity resolver. Handles labels whose meaning changes over time
# (Goa "GOA" = Dabolim through 2018, Mopa from 2023) and the flat spelling aliases
# (BOMBAY->BOM, TRIVANDRUM->TRV). Built once; the only resolution path.
AIRPORT_RESOLVER = build_airport_resolver(
    MAPPINGS, extra_aliases=MAPPINGS.get("airport_aliases")
)
KNOWN_IATA = set(MAPPINGS.get("airports", {}).keys())
AIRLINE_RESOLVER = build_airline_resolver(MAPPINGS)

# DGCA carrier "Type" -> tidy service_type.
SERVICE_TYPE = {
    "ScheduledDomestic": "scheduled_domestic",
    "NonScheduledDomestic": "nonscheduled_domestic",
    "ScheduledInternational": "scheduled_international",
    "NonScheduledInternational": "nonscheduled_international",
}
# Raw carrier column -> tidy column (documented, units in the data dictionary).
CARRIER_COLUMNS = {
    "Aircraft Kilometres": "aircraft_km",
    "Passenger Number": "passengers",
    "Passenger Kilometers": "passenger_km",      # RPK
    "Seat Kilometers": "seat_km",                # ASK
    "Passenger Load Factor": "passenger_load_factor",
    "Freight": "freight_tonnes",
    "Mail": "mail_tonnes",
    "Total Tonne Kilometer": "total_tonne_km",
    "Available Tonne Kilometer": "available_tonne_km",
    "Weight Load Factor": "weight_load_factor",
}
# Aggregate rows in the source that are not airlines.
CARRIER_TOTAL_ROWS = {"Total Domestic", "Total International"}

# Per-table schema versions (consumers detect breaking changes via metadata.json).
SCHEMA_VERSIONS = {
    "airport_monthly": "2.0",
    "airport_international_quarterly": "1.0",
    "airport_yearly": "2.0",
    "carrier_monthly": "1.0",
}
SCHEMA_CHANGELOG = [
    {
        "version": "2.0",
        "tables": ["airport_monthly", "airport_yearly"],
        "change": "Cadence split: airport_monthly is domestic-only (international "
        "moved to airport_international_quarterly with a real quarter column). "
        "Dropped 'category' from airport_monthly and 'tier' from all tables. "
        "Passenger columns are integers.",
    },
]

# Quarter -> representative month, used only to resolve validity-windowed labels
# for international rows. The published quarterly table keeps the real quarter.
_QUARTER_MIDPOINT = {1: 2, 2: 5, 3: 8, 4: 11}


def resolve_airport(label, year, month):
    """Resolve a source label to a canonical airport key, or None if unmapped."""
    return AIRPORT_RESOLVER.resolve(label, int(year), int(month))


def source_csv(rel_path: str) -> Path:
    return AVIATION_AGG_DIR / rel_path


def _split_endpoints(df: pd.DataFrame, period_cols: list[str]) -> pd.DataFrame:
    """City-pair rows -> per-airport departures/arrivals for the given period.

    Each pax count is attributed to BOTH endpoints (origin departure, destination
    arrival), the standard airport-traffic accounting. Returns a frame keyed by
    ``period_cols + ['city']`` with departures/arrivals summed.
    """
    df = df.copy()
    df["PaxToCity2"] = pd.to_numeric(df["PaxToCity2"], errors="coerce").fillna(0)
    df["PaxFromCity2"] = pd.to_numeric(df["PaxFromCity2"], errors="coerce").fillna(0)

    as_origin = (
        df.groupby(period_cols + ["City1"])
        .agg(departures=("PaxToCity2", "sum"), arrivals=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City1": "city"})
    )
    as_dest = (
        df.groupby(period_cols + ["City2"])
        .agg(arrivals=("PaxToCity2", "sum"), departures=("PaxFromCity2", "sum"))
        .reset_index()
        .rename(columns={"City2": "city"})
    )
    combined = pd.concat([as_origin, as_dest], ignore_index=True)
    return (
        combined.groupby(period_cols + ["city"])
        .agg(departures=("departures", "sum"), arrivals=("arrivals", "sum"))
        .reset_index()
    )


def _finalize(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    """One row per key, integer passenger columns, deterministic sort.

    Departures/arrivals are rounded to whole people, then passengers is recomputed
    as their sum so the definitional invariant holds exactly on integers.
    """
    out = (
        df.groupby(key_cols, as_index=False)
        .agg(departures=("departures", "sum"), arrivals=("arrivals", "sum"))
    )
    out["departures"] = out["departures"].round().astype("int64")
    out["arrivals"] = out["arrivals"].round().astype("int64")
    out["passengers"] = out["departures"] + out["arrivals"]
    cols = key_cols + ["passengers", "departures", "arrivals"]
    return out[cols].sort_values(key_cols).reset_index(drop=True)


# ── domestic monthly ────────────────────────────────


def process_domestic_monthly() -> pd.DataFrame | None:
    """domestic monthly: ``year, month, airport, passengers, departures, arrivals``."""
    path = source_csv("domestic/city.csv")
    if not path.exists():
        print("  WARNING: domestic/city.csv not found, skipping", flush=True)
        return None

    print(f"  Processing {path.relative_to(ROOT)} -> domestic monthly...", flush=True)
    df = pd.read_csv(path)
    monthly = _split_endpoints(df, ["Year", "Month"]).rename(
        columns={"Year": "year", "Month": "month"}
    )
    monthly["airport"] = monthly.apply(
        lambda r: resolve_airport(r["city"], r["year"], r["month"]), axis=1
    )

    unmapped = monthly[monthly["airport"].isna()]
    if not unmapped.empty:
        lost = unmapped.assign(pax=unmapped.departures + unmapped.arrivals)
        top = lost.groupby("city")["pax"].sum().sort_values(ascending=False)
        print(f"    WARNING: {len(top)} unmapped DOMESTIC label(s) dropped "
              f"(top: {', '.join(f'{c}={int(v):,}' for c, v in top.head(5).items())})")
    monthly = monthly[monthly["airport"].notna()]

    result = _finalize(monthly, ["year", "month", "airport"])
    print(f"    domestic monthly: {len(result):,} airport-month rows, "
          f"{result['airport'].nunique()} airports, "
          f"{int(result['year'].min())}-{int(result['year'].max())}")
    return result


# ── international quarterly ──────────────────────────


def process_international_quarterly() -> pd.DataFrame | None:
    """international quarterly: ``year, quarter, airport, passengers, departures, arrivals``.

    Real quarter column (no midpoint-month hack). Only Indian airports are kept;
    foreign counterpart cities resolve to None and are dropped.
    """
    path = source_csv("international/city.csv")
    if not path.exists():
        print("  WARNING: international/city.csv not found, skipping", flush=True)
        return None

    print(f"  Processing {path.relative_to(ROOT)} -> international quarterly...", flush=True)
    df = pd.read_csv(path)
    df["Year"] = df["Year"].apply(lambda y: y + 2000 if y < 100 else y)

    quarterly = _split_endpoints(df, ["Year", "Quarter"]).rename(
        columns={"Year": "year", "Quarter": "quarter"}
    )
    quarterly["airport"] = quarterly.apply(
        lambda r: resolve_airport(
            r["city"], r["year"], _QUARTER_MIDPOINT.get(int(r["quarter"]), 6)
        ),
        axis=1,
    )
    # Keep only resolved Indian airports (drops foreign counterpart cities).
    quarterly = quarterly[quarterly["airport"].isin(KNOWN_IATA)]

    result = _finalize(quarterly, ["year", "quarter", "airport"])
    print(f"    international quarterly: {len(result):,} airport-quarter rows, "
          f"{result['airport'].nunique()} Indian airports, "
          f"quarters {sorted(result['quarter'].unique())}")
    return result


# ── derived yearly view ─────────────────────────────


def build_yearly(monthly: pd.DataFrame | None, quarterly: pd.DataFrame | None) -> pd.DataFrame:
    """yearly (derived): ``year, airport, category, passengers``, whole years only.

    Domestic years need all 12 months; international years need all 4 quarters.
    """
    frames = []
    if monthly is not None and not monthly.empty:
        complete = monthly.groupby("year")["month"].nunique()
        years = set(complete[complete == 12].index)
        dom = monthly[monthly["year"].isin(years)]
        agg = dom.groupby(["year", "airport"], as_index=False)["passengers"].sum()
        agg["category"] = "domestic"
        frames.append(agg)
    if quarterly is not None and not quarterly.empty:
        complete = quarterly.groupby("year")["quarter"].nunique()
        years = set(complete[complete == 4].index)
        intl = quarterly[quarterly["year"].isin(years)]
        agg = intl.groupby(["year", "airport"], as_index=False)["passengers"].sum()
        agg["category"] = "international"
        frames.append(agg)
    if not frames:
        return pd.DataFrame(columns=["year", "airport", "category", "passengers"])
    out = pd.concat(frames, ignore_index=True)
    return out[["year", "airport", "category", "passengers"]].sort_values(
        ["year", "category", "airport"]
    ).reset_index(drop=True)


def process_airport_data() -> dict[str, pd.DataFrame]:
    """Build and write the monthly, quarterly, and yearly tables."""
    monthly = process_domestic_monthly()
    quarterly = process_international_quarterly()
    yearly = build_yearly(monthly, quarterly)

    written = {}
    if monthly is not None:
        out = PROCESSED_DIR / "airport_monthly.csv"
        monthly.to_csv(out, index=False)
        written["airport_monthly"] = monthly
        print(f"  Saved: {out.name} ({len(monthly):,} rows)")
    if quarterly is not None:
        out = PROCESSED_DIR / "airport_international_quarterly.csv"
        quarterly.to_csv(out, index=False)
        written["airport_international_quarterly"] = quarterly
        print(f"  Saved: {out.name} ({len(quarterly):,} rows)")
    out = PROCESSED_DIR / "airport_yearly.csv"
    yearly.to_csv(out, index=False)
    written["airport_yearly"] = yearly
    print(f"  Saved: {out.name} ({len(yearly):,} rows)")

    if not yearly.empty:
        total = yearly.groupby("airport")["passengers"].sum().sort_values(ascending=False)
        print("\n  Top 10 airports (derived yearly, all categories):")
        for iata, pax in total.head(10).items():
            print(f"    {iata:>10s}: {pax:>15,}")
    return written


# ── carrier monthly (passthrough for now; tidied in clean carrier step) ──


def process_carrier_data() -> pd.DataFrame | None:
    """carrier monthly: tidy airline-monthly operating stats.

    One row per (airline, service_type, year, month). Airline names are
    canonicalized for spelling only (Airheritage -> Air Heritage); brand/legal
    mergers are NOT collapsed (Vistara keeps its own series; the merger is
    recorded via succeeded_by in mappings.yaml). Aggregate "Total" rows dropped.
    """
    path = source_csv("domestic/carrier.csv")
    if not path.exists():
        print("  WARNING: domestic/carrier.csv not found, skipping", flush=True)
        return None
    print(f"  Processing {path.relative_to(ROOT)} -> carrier monthly...", flush=True)
    df = pd.read_csv(path)

    df = df[~df["Airline"].isin(CARRIER_TOTAL_ROWS)].copy()
    df["airline"] = df["Airline"].apply(
        lambda a: AIRLINE_RESOLVER.resolve(a, 2000, 1) or str(a).strip()
    )
    df["service_type"] = df["Type"].map(SERVICE_TYPE)
    df = df[df["service_type"].notna()]
    df = df.rename(columns={"Year": "year", "Month": "month", **CARRIER_COLUMNS})

    keep = ["airline", "service_type", "year", "month"] + list(CARRIER_COLUMNS.values())
    tidy = df[keep].copy()
    for col in CARRIER_COLUMNS.values():
        tidy[col] = pd.to_numeric(tidy[col], errors="coerce")
    tidy["passengers"] = tidy["passengers"].round().astype("Int64")
    # One row per (airline, service_type, year, month): sum spelling-merged duplicates.
    metrics = [c for c in CARRIER_COLUMNS.values() if c not in ("passenger_load_factor", "weight_load_factor")]
    agg = {c: "sum" for c in metrics}
    agg.update({"passenger_load_factor": "mean", "weight_load_factor": "mean"})
    tidy = (
        tidy.groupby(["airline", "service_type", "year", "month"], as_index=False).agg(agg)
        .sort_values(["year", "month", "service_type", "airline"])
        .reset_index(drop=True)
    )

    out = PROCESSED_DIR / "carrier_monthly.csv"
    tidy.to_csv(out, index=False)
    print(f"  Saved: {out.name} ({len(tidy):,} rows, {tidy['airline'].nunique()} airlines, "
          f"{tidy['service_type'].nunique()} service types)")
    return tidy


def write_metadata(written: dict[str, pd.DataFrame]) -> None:
    """metadata.json: data date + per-table schema_version + schema_changelog."""
    tables = {}
    for name, df in written.items():
        tables[name] = {
            "schema_version": SCHEMA_VERSIONS.get(name, "1.0"),
            "rows": int(len(df)),
            "columns": list(df.columns),
        }
    meta = {
        "data_date": str(date.today()),
        "processed_date": str(date.today()),
        "tables": tables,
        "schema_changelog": SCHEMA_CHANGELOG,
    }
    (PROCESSED_DIR / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"  Saved: metadata.json (data_date={meta['data_date']})")


def main() -> None:
    print("=== Cleaning Data ===\n", flush=True)
    written = process_airport_data()
    carrier = process_carrier_data()
    if carrier is not None:
        written["carrier_monthly"] = carrier
    write_metadata(written)
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
