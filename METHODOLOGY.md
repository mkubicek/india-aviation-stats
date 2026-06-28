# Methodology

How DGCA's public workbooks become the canonical dataset: ingestion,
normalization, entity resolution, and validation.

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
  source URLs, normalized locally by `scripts/normalize.py`. A committed
  fingerprint manifest (`data/sources_manifest.csv`) detects when a source file
  is re-published.
- **Coverage:** Domestic monthly city-pair and carrier data; international
  quarterly city-pair, country, carrier, and carrier-month tables
- **Current local coverage:** 2015 through latest available DGCA workbook
- **Access:** Public HTTP GET, no authentication
- **Known quirk:** DGCA portal links are sometimes not the exact S3 object key.
  The downloader retries common filename variants such as uppercase month names
  and an extra space after commas.
- **Temporary source workaround:** If a DGCA international Table 4 Excel file is
  listed by the portal but not publicly retrievable, the matching public PDF is
  ingested for that quarter. Such rows are marked as `source_type=pdf` with a
  note in `data/sources_manifest.csv`.

---

## Statistical Population

- **Scope:** Scheduled passenger traffic reported in DGCA public aviation
  statistics.
- **Domestic airport rows:** Monthly city-pair passenger flows aggregated to
  airport arrivals, departures, and total passengers.
- **International airport rows:** Quarterly city-pair passenger flows filtered
  to known Indian airports, published with a **real `quarter` column** in
  `airport_international_quarterly.csv` (no midpoint-month hack — domestic and
  international never share a cadence).
- **Unit:** Passengers (whole-person integers). Charted passenger totals are not
  flight/movement counts.

---

## Normalization

### Domestic City-Pair Data

Source rows contain `City1`, `City2`, `PaxToCity2`, and `PaxFromCity2`.

- For `City1`: departures = `PaxToCity2`, arrivals = `PaxFromCity2`
- For `City2`: arrivals = `PaxToCity2`, departures = `PaxFromCity2`
- Airport total = arrivals + departures across all routes
- **Blank one-direction cells are treated as zero, not dropped.** DGCA reports
  some routes in one direction only, leaving the reverse passenger cell blank;
  counting it as zero (rather than dropping the row) keeps one-direction airport
  totals correct. Locked by a test in `tests/test_clean.py`.

### Entity resolution (the cleanup model)

All source labels are mapped to canonical airports through a single **reviewed
entity table** in `mappings.yaml` — never fuzzy matching. A label may carry a
**validity window** (`valid_from`/`valid_to`) because a label's meaning can
change over time: the bare `GOA` label is Dabolim (`GOI`) through 2018 and Mopa
(`GOX`) from 2023. The resolver refuses to build if a label maps to two airports
with overlapping windows. Alternate spellings (BOMBAY→BOM) live in a flat
`airport_aliases` map; every airport label that previously needed code-side
aliases is now in the table. Resolution is 100% table-driven — there is no
hardcoded fallback.

### International City-Pair Data

Source rows are quarterly. Foreign counterpart cities resolve to nothing and are
dropped; only Indian airports are kept, on a real `quarter` grain.

### Carrier Data

Domestic carrier workbooks are cleaned into a documented tidy schema (one row per
airline × service_type × month; named metric columns; aggregate "Total" rows
dropped). Airlines **link, not collapse**: a merged brand (Vistara) keeps its own
series with a `succeeded_by` link, so standalone series survive.

---

## Airport tiers are presentation-only

The metro/tier bands are a project-defined editorial opinion, **not data**. They
do not appear in any published CSV — they live only in chart-coloring config
(`mappings.yaml: airport_colors`). They are not official DGCA/AAI or
industry-standard classifications.

---

## Charts

The visible dashboard charts are generated only from the published tables in
`data/processed/`. Monthly domestic charts use `airport_monthly.csv`; the
international gateway chart uses `airport_international_quarterly.csv`. The
script writes `charts/manifest.json` with input hashes, output hashes, and chart
parameters, and `data/processed/dashboard_summary.json` for the dashboard cards.

### India Domestic Demand Pulse

`india_domestic_demand_pulse.png` — national monthly domestic passengers plus a
trailing 12-month passenger total. The KPI block reports the latest month,
latest month YoY, latest trailing 12-month total, and trailing 12-month YoY.

### Top Airport Traffic Trends

`top_airport_traffic_trends.png` — trailing 12-month domestic passenger totals
for the union of the current and previous top 10 airports, capped at 12 lines
with deterministic airport-code tie-breaks.

### Newcomer Airport Ramp-up

`newcomer_airport_rampup_24m.png` — monthly domestic passengers during each
airport's first 24 DGCA-observed months. Airports first seen in the first 12
months of the dataset are excluded to avoid left-censoring. An airport qualifies
with at least 3 observed months and either 100,000 cumulative ramp passengers or
a 20,000-passenger peak month.

### Market Share Movers

`domestic_market_share_gainers.png` — domestic airport share change between the
latest trailing 12 months and the previous trailing 12 months, requiring at
least 100,000 passengers in either window.

`international_gateway_share_gainers.png` — international airport share change
between the latest 4 quarters and the previous 4 quarters, requiring at least
50,000 passengers in either window.

### Airport Seasonality Fingerprint

`airport_seasonality_fingerprint.png` — airport-month seasonality indexed to
each airport's own average month (`100 = average month`). Only complete calendar
years are used; airports need at least 3 complete years and 100,000 latest
trailing 12-month domestic passengers. The heatmap uses a fixed 60/100/140 color
scale.

### Optional Animation

`airport_passenger_race.gif` — optional trailing 12-month domestic passenger
race, generated only with `uv run python scripts/chart.py --include-gifs`.

---

## Validation

Validation is a partial CI gate, not just advisory. `python -m validate`
emits `validation_report.json` (machine) and `warnings.log` (human).

| Check | Severity | Purpose |
|-------|----------|---------|
| Overlap-classification gate | BLOCKING | refuse to sum two concurrent source labels into one airport unless declared in `concurrent_labels` |
| Cadence integrity | BLOCKING | one row per key; the quarterly table's `quarter ∈ 1..4`; no cross-table cadence mixing |
| Definitional | BLOCKING | `passengers == departures + arrivals`; non-negative integers |
| Schema conformance | BLOCKING | columns/dtypes match the data dictionary; `schema_version` present |
| Conservation | TRIPWIRE | per month `sum(departures) == sum(arrivals)` — true by construction; catches a future refactor only |
| Carrier value-domain | BLOCKING / ADVISORY | one row per key; load factors 0–100 and metrics ≥ 0 |
| Assumptions ledger | BLOCKING | re-test each `assumptions/<id>.md` falsification → HOLDS/TRIGGERED/STALE/ORPHANED |
| Reverse gate | BLOCKING | any anomaly with no covering assumption file is an undocumented quirk |
| High-volume unmapped name | ADVISORY | a real airport we failed to map is silent loss |
| Coverage continuity | ADVISORY | missing months/quarters |

The cleanup knowledge base lives in `assumptions/` (Open Knowledge Format) and is
re-tested by the `validate-assumptions` skill. Restated published values are
disclosed in `data/processed/REVISIONS.md` (diffed against the last data commit).

The ledger's tests are **internal** — the data re-checked against itself — so the
gate stays deterministic. Classifying a *new* label (is it a new airport, a
rename, or a distinct airport sharing a code?) needs world knowledge, so it is
handled off the blocking path by an advisory `validate --triage` mode: it turns
each label the gate can detect but not classify into a research question and a
citable OKF skeleton. Web research and human sign-off happen there; only a
confirmed, cited assumption ever reaches `mappings.yaml`.

---

## Known Limitations

1. DGCA source publication timing and workbook layouts may change.
2. International data is quarterly, not monthly (published as its own table).
3. Passenger charts show passenger flow, not aircraft movement count.
4. Airport/airline mapping is only as complete as the reviewed entity tables in
   `mappings.yaml`; an unmapped high-volume label is surfaced as advisory.

---

## Methodology Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-06 | 0.1.0 | Canonical multi-table dataset: cadence split, table-driven entity resolution with validity windows, falsifiable assumptions ledger + overlap gate, carrier link-not-collapse, tiers moved to presentation-only, six-chart dashboard surface |
