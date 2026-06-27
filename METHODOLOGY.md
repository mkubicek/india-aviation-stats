# Methodology

This document describes the current `main` branch methodology: official-source
aviation data ingestion, normalization, validation, and observed passenger
charts. Projection work is intentionally out of scope for now.

## Disclaimer

> This is a personal open-source project. Views and analysis are my own and do
> not represent Flughafen Zürich AG, Noida International Airport, or any
> affiliated entity.

---

## Data Sources

### DGCA Monthly and Quarterly Statistics

- **Provider:** Directorate General of Civil Aviation, India
- **URL:** <https://www.dgca.gov.in/digigov-portal/>
- **Format:** Public Excel files discovered through the DGCA portal and S3
  source URLs, normalized locally by `scripts/ingest_sources.py`
- **Coverage:** Domestic monthly city-pair and carrier data; international
  quarterly city-pair, country, carrier, and carrier-month tables
- **Current local coverage:** 2015 through latest available DGCA workbook
- **Access:** Public HTTP GET, no authentication
- **Known quirk:** DGCA portal links are sometimes not the exact S3 object key.
  The downloader retries common filename variants such as uppercase month names
  and an extra space after commas.

### MoCA Daily Summaries

- **Provider:** Ministry of Civil Aviation, India
- **URL:** <https://www.civilaviation.gov.in/>
- **Format:** HTML snapshots parsed into `daily.csv`
- **Access:** Public HTML; historical snapshots via Internet Archive CDX API
- **Status:** Optional. Enable with `INCLUDE_MCA_DAILY=1`.

---

## Statistical Population

- **Scope:** Scheduled passenger traffic reported in DGCA public aviation
  statistics.
- **Domestic airport rows:** Monthly city-pair passenger flows aggregated to
  airport arrivals, departures, and total passengers.
- **International airport rows:** Quarterly city-pair passenger flows filtered
  to known Indian airports. In `airport_monthly.csv`, each quarterly row is
  assigned to the quarter midpoint month (Q1=Feb, Q2=May, Q3=Aug, Q4=Nov).
- **Unit:** Passengers. The passenger race is not a flight/movement count.

---

## Normalization

### Domestic City-Pair Data

Source rows contain `City1`, `City2`, `PaxToCity2`, and `PaxFromCity2`.

- For `City1`: departures = `PaxToCity2`, arrivals = `PaxFromCity2`
- For `City2`: arrivals = `PaxToCity2`, departures = `PaxFromCity2`
- Airport total = arrivals + departures across all routes

City names are mapped to IATA codes through `mappings.yaml` plus explicit
aliases in `scripts/process.py`. Unknown city names remain as uppercase source
names so they are visible in processed data rather than silently discarded.

### International City-Pair Data

Source rows are quarterly. Foreign city rows are discarded by filtering the
mapped city value against known Indian airport IATA codes in `mappings.yaml`.

### Carrier Data

Domestic carrier workbooks are normalized into `carrier_monthly.csv` with the
source workbook columns preserved.

---

## Airport Classification

Airport tiers are defined in `mappings.yaml`.

| Annual Passengers | Classification |
|-------------------|----------------|
| > 20M             | Metro |
| 5M-20M            | Tier 1 |
| 1M-5M             | Tier 2 |
| < 1M              | Tier 3 |
| Not yet open      | Greenfield |

The current pipeline does not project tiers. Validation only flags obvious tier
mismatches in the latest complete observed DGCA year.

---

## Charts

### Airport Rankings

`airport_rankings.png` ranks the current top 10 airports by annual passengers.
It uses domestic + international totals and only includes years with complete
domestic months and complete international quarters.

### Airport Passenger Race

`airport_passenger_race.gif` uses domestic monthly airport rows only. Each frame
is a trailing 12-month sum ending in that month. The chart intentionally avoids
international rows because those are quarterly source values and would create
artificial month-to-month jumps in a monthly race.

---

## Validation Checks

Validation is advisory and writes `warnings.log`.

| Check | Purpose |
|-------|---------|
| Required files | Ensure processed CSV outputs exist |
| Domestic month coverage | Detect missing monthly domestic source periods |
| International quarter coverage | Detect missing quarterly international source periods |
| Negative passengers | Catch impossible passenger values |
| Tier consistency | Flag airport tier definitions that no longer match observed volume |

---

## Known Limitations

1. DGCA source publication timing and workbook layouts may change.
2. International data is quarterly, not monthly.
3. Domestic passenger race is passenger flow, not aircraft movement count.
4. Airport code mapping is only as complete as `mappings.yaml` and the alias
   table in `scripts/process.py`.
5. GDP correlation, projections, and milestone estimates are intentionally not
   included on `main` right now.

---

## Methodology Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-06 | 0.1.0 | Initial observed-data release methodology |
