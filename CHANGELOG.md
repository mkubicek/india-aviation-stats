# Changelog

## Unreleased

### Fixed

- Resolved the June 2026 `GAUTAM BUDDHA NAGAR` source label to Noida
  International Airport (`DXN`) and `GULBARGA` to Kalaburagi (`GBI`) through
  cited, falsifiable cleanup assumptions.
- Excluded the exact January 2025 `HYDERABAD`–`HYDERABAD` source anomaly before
  building both route and airport layers; a canonical airport can no longer
  produce a domestic self-loop or false endpoint movements.
- Corrected the public domestic national dashboard scale: national domestic demand
  now uses scheduled-domestic carrier passengers carried (`carrier_monthly.csv`)
  instead of summed airport endpoint throughput, which double-counts every domestic
  journey. The May 2026 correction benchmark reads **15.4M passengers carried**
  (was 30.8M — exactly 2× the carrier figure); trailing-12-month reads **168.3M**.

### Changed

- Domestic airport-month rows are now derived from the same canonical directed
  routes that are published in `domestic_route_monthly.csv`, making route-to-
  airport reconciliation exact by construction.
- Public DGCA domestic and carrier coverage advances through June 2026.
- Clarified passenger metric semantics across chart labels, dashboard cards,
  manifest metadata, data dictionary, methodology, and README. Airport charts are
  relabelled as **airport throughput** (arrivals + departures); the international
  chart as **Indian gateway throughput**. Airport-level charts are unchanged in
  scale — only national passenger-carried demand moved to the carrier layer.
- `dashboard_summary.json` domestic keys are now metric-explicit
  (`latest_month_passengers_carried`, `trailing_12m_passengers_carried`,
  `airport_throughput_latest_month`, `passengers_metric`); the ambiguous
  `latest_month_passengers`/`trailing_12m_passengers` keys are removed.

### Added

- `domestic_route_monthly.csv` (schema v1.0): canonical directed domestic
  segment passengers at `(year, month, origin, destination)` grain, including
  explicit zero-direction observations.
- Blocking route validation for unique keys, canonical distinct endpoints,
  non-negative integer passengers, exact airport-month/national conservation,
  and unexplained published-history disappearance.
- Reusable deterministic route/network metrics in `scripts/network.py`, with
  unit and end-to-end tests covering route construction, conservation, windows,
  Pareto selection, dual-airport metrics, and network structure.
- Three evidence-selected charts: observable DEL route-market frontier,
  dual-airport network roles, and domestic network decentralisation. Structural
  one-stop and triangle-closure tests remain documented but were not promoted
  because the evidence was weak or threshold-sensitive.
- `docs/noida-route-network-analysis.md` and
  `data/processed/route_analysis_summary.json`, including exact windows,
  sensitivity results, rejected theses, quantified findings, and explicit claim
  boundaries.
- `scripts/metrics.py` — the single home for passenger metric semantics
  (passengers carried vs airport throughput vs gateway throughput).
- `charts/manifest.json` records `primary_source_table` and `metric_semantics`
  per chart.
- Passenger-metric-semantics advisory validation check
  (`semantics.domestic_airport_throughput_vs_carrier`) and regression tests so
  airport endpoint throughput cannot be reused as national passengers carried.
- `docs/external-smoke-checks.md` — independent scale checks vs published DGCA
  figures.

## 0.1.0

Initial public release — a clean, canonical dataset of Indian aviation passenger
traffic from DGCA's public workbooks.

- **Four single-grain tables** in `data/processed/`: domestic monthly,
  international quarterly, derived yearly, and carrier monthly. One airport = one
  entity; integer passengers; `schema_version` per table.
- **Table-driven entity resolution** with validity windows — resolves source
  labels whose meaning changes over time (the `GOA` label is Dabolim through 2018,
  Mopa from 2023). All 107 previously-unmapped domestic labels mapped and audited.
- **Traceable, falsifiable cleanup.** Every non-trivial decision is an Open
  Knowledge Format file in `assumptions/`, re-tested against current data by the
  `validate-assumptions` skill; an overlap-classification gate refuses to silently
  merge two concurrent labels; a reverse gate blocks undocumented quirks.
- **Source-change detection** via committed `sources_manifest.csv`; restated
  values disclosed in `REVISIONS.md`.
- **Visible dashboard chart set** from the published tables: domestic
  demand pulse, top airport trends, newcomer ramp-up, domestic share movers,
  international gateway share movers, and seasonality fingerprint. The passenger
  race GIF is now opt-in.
- Validation runs as a partial CI gate; a blocking failure keeps last-good data
  and opens an issue.
- **Share Movers charts disclose their scope.** Both share-mover subtitles now
  state the top-N-of-total selection and name the explicit comparison windows on
  the chart, so the ~20-bar view is not mistaken for the full airport field or
  read as ending in the current (unpublished) period.
