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
- **Domestic route rows:** Monthly directed segment passengers, with both
  endpoints resolved to canonical airports.
- **Domestic airport rows:** Monthly city-pair passenger flows aggregated to
  airport arrivals, departures, and total passengers.
- **International airport rows:** Quarterly city-pair passenger flows filtered
  to known Indian airports, published with a **real `quarter` column** in
  `airport_international_quarterly.csv` (no midpoint-month hack — domestic and
  international never share a cadence).
- **Unit:** Passengers (whole-person integers). Charted passenger totals are not
  flight/movement counts.

---

## Passenger metric semantics

The repository contains both **airport-throughput** and **carrier-passenger**
metrics, and they are not interchangeable even though both columns are named
`passengers`.

Domestic airport rows are **endpoint-throughput** rows: each domestic passenger
appears once at the origin airport (a departure) and once at the destination
airport (an arrival). This is correct for airport-traffic charts and airport
market-share charts, but **national domestic demand must not be computed by
summing airport endpoints** — doing so double-counts every domestic journey
(nationally, airport throughput ≈ 2× journeys).

Domestic route rows are **directed-segment** rows. A passenger appears once on
the observed segment direction in `domestic_route_monthly.csv`. The national
directed route sum equals national airport departures and national airport
arrivals separately; summing airport `passengers` still counts both endpoints.
Segment rows do not reveal the passenger's true origin/final destination or
whether the segment was part of a connection.

National domestic demand uses `carrier_monthly.csv` filtered to
`service_type == scheduled_domestic`, which counts **passengers carried** once per
journey. This is the source for the domestic demand pulse chart and the domestic
dashboard cards (latest month, trailing-12-month total, and their YoY).

International gateway charts use `airport_international_quarterly.csv`, where
foreign counterpart cities are dropped and only Indian airport gateway endpoints
are retained — so the metric is **Indian gateway throughput**, not airline-carried
international passengers.

The conservation relationship (national airport throughput ≈ 2× scheduled-domestic
passengers carried) is asserted as an advisory validation check
(`semantics.domestic_airport_throughput_vs_carrier`) and regression-tested in
`tests/test_metrics.py`, so airport endpoint throughput can never be silently
reused as national passengers carried. The metric each chart represents is
recorded per chart in `charts/manifest.json` (`primary_source_table`,
`metric_semantics`).

---

## Normalization

### Domestic City-Pair Data

Source rows contain `City1`, `City2`, `PaxToCity2`, and `PaxFromCity2`.

- Directed route `City1 → City2 = PaxToCity2`
- Directed route `City2 → City1 = PaxFromCity2`
- For `City1`: departures = `PaxToCity2`, arrivals = `PaxFromCity2`
- For `City2`: arrivals = `PaxToCity2`, departures = `PaxFromCity2`
- Airport total = arrivals + departures across all routes
- **Blank one-direction cells are treated as zero, not dropped.** DGCA reports
  some routes in one direction only, leaving the reverse passenger cell blank;
  counting it as zero (rather than dropping the row) keeps one-direction airport
  totals correct. Locked by a test in `tests/test_clean.py`.

### Canonical domestic route layer

`scripts/routes.py` builds `data/processed/domestic_route_monthly.csv` before
deriving the domestic airport table from those same directed records. Both
endpoints pass through the period-aware table resolver. Duplicate canonical
route-months are summed deterministically; zero-direction observations remain
published but are excluded from weighted graph calculations.

An unresolved domestic endpoint is a hard failure. A source row whose two labels
resolve to the same airport may be excluded only through an exact,
period-specific `domestic_route_exclusions` entry in `mappings.yaml` backed by a
falsifiable assumption. There is no chart-side cleanup.

The route layer must reconcile exactly for every airport-month:

```text
sum(outgoing route passengers) = airport_monthly.departures
sum(incoming route passengers) = airport_monthly.arrivals
```

Validation also requires a unique `(year, month, origin, destination)` key,
canonical distinct endpoints, non-negative integer passengers, national
conservation, and no unexplained disappearance of a previously published
route-month key.

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

Charts are generated only from the published tables in `data/processed/`. The
domestic demand pulse uses `carrier_monthly.csv` (passengers carried);
airport-level domestic charts use `airport_monthly.csv` (airport throughput);
the international gateway chart uses `airport_international_quarterly.csv`; and
route/network charts use `domestic_route_monthly.csv`, with `airport_monthly.csv`
only for reconciled airport throughput. The script writes `charts/manifest.json`
with input hashes, output hashes, chart parameters, exact periods, selection
rules, shown/eligible counts, and per-chart metric semantics. It also writes
`data/processed/dashboard_summary.json` and
`data/processed/route_analysis_summary.json`.

### India Domestic Demand Pulse

`india_domestic_demand_pulse.png` — national monthly **scheduled domestic
passengers carried** (from `carrier_monthly.csv`) plus a trailing 12-month carried
total. The KPI block reports the latest month, latest month YoY, latest trailing
12-month total, and trailing 12-month YoY. This is passengers carried (counted
once per journey), not summed airport endpoint throughput.

### Top Airport Traffic Trends

`top_airport_traffic_trends.png` — trailing 12-month domestic **airport passenger
movements** (arrivals + departures) for the union of the current and previous top
10 airports, capped at 12 lines with deterministic airport-code tie-breaks.

### Newcomer Airport Ramp-up

`newcomer_airport_rampup_24m.png` — monthly domestic **airport passenger
movements** during each airport's first 24 DGCA-observed months. Airports first
seen in the first 12 months of the dataset are excluded to avoid left-censoring.
An airport qualifies with at least 3 observed months and either 100,000 cumulative
ramp movements or a 20,000-movement peak month.

### Market Share Movers

`domestic_market_share_gainers.png` — change in each airport's share of domestic
**airport throughput** between the latest trailing 12 months and the previous
trailing 12 months, requiring at least 100,000 throughput in either window. The
chart shows the top 10 share gainers and top 10 decliners; the subtitle states the
selection (how many of the total airports), the metric scope (share of domestic
airport throughput), and the explicit comparison windows so the subset is never
read as the full field or as passengers carried.

`international_gateway_share_gainers.png` — change in each gateway's share of
Indian **gateway throughput** between the latest 4 quarters and the previous 4
quarters, requiring at least 50,000 throughput in either window. The chart shows
the top 8 gainers and top 8 decliners, with the same on-chart disclosure of
selection, scope, and windows. The latest 4 quarters end at the latest
**published** quarter, which can trail the current calendar quarter.

### Airport Seasonality Fingerprint

`airport_seasonality_fingerprint.png` — airport-month **throughput** seasonality
indexed to each airport's own average month (`100 = average month`). Only complete calendar
years are used; airports need at least 3 complete years and 100,000 latest
trailing 12-month domestic passengers. The heatmap uses a fixed 60/100/140 color
scale.

### Observable DEL Route-Market Frontier

`ncr_route_opportunity_frontier.png` — every DEL market with at least 250,000
bidirectional segment passengers in both the latest and prior trailing-12-month
windows and positive traffic in at least 9 latest-window months. All eligible
markets are shown. Labels identify the markets not dominated on latest volume
and year-over-year growth; no composite score is computed. DEL is an observable
NCR demand proxy, not NIA demand, diversion, a forecast, or a recommendation.

### Dual-Airport Network Roles

`dual_airport_network_roles.png` — parameterised comparison of GOI/GOX, DEL/HDO,
and BOM/NMIA. A persistent market has at least 10,000 bidirectional passengers
and positive traffic in at least half the comparison months. The chart reports
newcomer share of pair throughput, shared/unique destinations, effective
destinations, and combined breadth versus an equal-length pre-entry incumbent
baseline. `route_analysis_summary.json` also retains incumbent, newcomer, and
combined monthly throughput from 12 months before entry through the latest
published month, plus the first-24-month route-acquisition sequence.
Comparisons are observational, not causal.

### Domestic Network Decentralisation

`domestic_network_decentralisation.png` — every complete calendar year from
2016 onward. It shows top-five airport throughput share, effective traffic
centres (`1 / HHI`), active airports, and bidirectional routes observed in at
least three months. The chart describes national structure; it does not
establish demand or route economics for an individual airport.

The accompanying
[`docs/noida-route-network-analysis.md`](docs/noida-route-network-analysis.md)
documents the competing theses, sensitivity checks, discarded tests, and claim
boundaries. Structural two-leg paths use the balanced-leg proxy
`min(first-leg passengers, second-leg passengers)` only as a topology
diagnostic; it is never described as transfer demand or summed as reusable
capacity.

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
| Directed route integrity | BLOCKING | canonical distinct endpoints, unique keys, non-negative integers, exact airport-month and national reconciliation |
| Route-history continuity | BLOCKING | no previously published route-month key disappears without an explicit override and review |
| Conservation | TRIPWIRE | per month `sum(departures) == sum(arrivals)` — true by construction; catches a future refactor only |
| Carrier value-domain | BLOCKING / ADVISORY | one row per key; load factors 0–100 and metrics ≥ 0 |
| Assumptions ledger | BLOCKING | re-test each `assumptions/<id>.md` falsification → HOLDS/TRIGGERED/STALE/ORPHANED |
| Reverse gate | BLOCKING | any anomaly with no covering assumption file is an undocumented quirk |
| High-volume unmapped name | ADVISORY | a real airport we failed to map is silent loss |
| Coverage continuity | ADVISORY | missing months/quarters |
| Passenger metric semantics | ADVISORY | national airport throughput ≈ 2× scheduled-domestic passengers carried — endpoint throughput must not be reused as national passengers carried |

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
5. Domestic segments do not identify passenger origin/final destination,
   transfers, schedules, seats, fares, yields, or profitability.
6. DEL traffic is an observable NCR proxy only; the data does not estimate DXN
   catchment share or diversion.

---

## Methodology Evolution

The methodology is expected to evolve as reviews find better correction rules. A correction becomes part of the methodology when it is reusable, source-grounded, and improves future reviews rather than only explaining one chart.

Methodology changes should preserve review integrity: evaluate a chart or projection against the current methodology first, then update the methodology explicitly for future rounds. Each material change should record what failure or new evidence caused the update.

---

## Methodology Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-07 | 0.2.0 | Added the canonical directed domestic route layer with exact airport reconciliation and history continuity; added transparent route-market, dual-airport, and national-decentralisation analyses; documented why transfer-path and triangle-closure hypotheses were not selected. |
| 2026-06 | 0.1.0 | Canonical multi-table dataset: cadence split, table-driven entity resolution with validity windows, falsifiable assumptions ledger + overlap gate, carrier link-not-collapse, tiers moved to presentation-only, six-chart dashboard surface |
| 2026-06 | 0.1.0 | Review correction (release QC): Share Movers charts now disclose their top-N-of-total selection and name the explicit comparison windows on the chart. Evidence — a reviewer read the ~20-bar chart as the full airport field and could only infer the comparison period (latest published quarter ≠ current quarter) from the footer. |
| 2026-06 | 0.1.x | Corrected domestic national dashboard metric. The prior dashboard summed domestic airport endpoint throughput, producing May 2026 = 30,779,402, exactly 2× the scheduled-domestic carrier passenger count of 15,389,701. National domestic demand now uses `carrier_monthly.csv` (`service_type == scheduled_domestic`) passengers carried; airport-level charts remain on endpoint throughput and were relabelled accordingly. Added the passenger-metric-semantics advisory check, manifest `metric_semantics`/`primary_source_table`, and regression tests. |
