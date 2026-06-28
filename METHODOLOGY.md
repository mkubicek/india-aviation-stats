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
  fingerprint manifest (`data/sources_manifest.csv`) detects when a workbook is
  re-published.
- **Coverage:** Domestic monthly city-pair and carrier data; international
  quarterly city-pair, country, carrier, and carrier-month tables
- **Current local coverage:** 2015 through latest available DGCA workbook
- **Access:** Public HTTP GET, no authentication
- **Known quirk:** DGCA portal links are sometimes not the exact S3 object key.
  The downloader retries common filename variants such as uppercase month names
  and an extra space after commas.

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
- **Unit:** Passengers (whole-person integers). The passenger race is not a
  flight/movement count.

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

Both charts source the published Layer 1 (domestic monthly) so they never mix
cadences.

### Airport Passenger Race

`airport_passenger_race.gif` — each frame is a trailing 12-month sum ending in
that month. Domestic only, so there are no artificial jumps from quarterly data.

### Who's Rising

`airport_risers.png` — monthly ramp curves of genuine newcomer airports
(canonical entities whose first month of data is recent). It depends on the
deduplication layer: a source-rename (PRAYAGRAJ = Allahabad, MUMBAI MUMBAI = BOM)
carries its full history under its canonical key, so it is never mistaken for a
new airport. Any genuine new airport surfaces automatically once DGCA publishes
its first month — none is special-cased.

---

## Validation

Validation is a partial CI gate, not just advisory. `python -m validate`
emits `validation_report.json` (machine) and `warnings.log` (human).

| Check | Severity | Purpose |
|-------|----------|---------|
| Overlap-classification gate | BLOCKING | refuse to sum two concurrent source labels into one airport unless declared in `concurrent_labels` |
| Cadence integrity | BLOCKING | one row per key; Layer 2 `quarter ∈ 1..4`; no cross-layer contamination |
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

---

## Known Limitations

1. DGCA source publication timing and workbook layouts may change.
2. International data is quarterly, not monthly (published as its own layer).
3. Domestic passenger race is passenger flow, not aircraft movement count.
4. Airport/airline mapping is only as complete as the reviewed entity tables in
   `mappings.yaml`; an unmapped high-volume label is surfaced as advisory.

---

## Methodology Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-06 | 0.1.0 | Canonical layered dataset: cadence split, table-driven entity resolution with validity windows, falsifiable assumptions ledger + overlap gate, carrier link-not-collapse, tiers moved to presentation-only |
