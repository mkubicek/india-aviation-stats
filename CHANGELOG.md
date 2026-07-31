# Changelog

## Unreleased

### Fixed

- Corrected the public domestic national dashboard scale: national domestic demand
  now uses scheduled-domestic carrier passengers carried (`carrier_monthly.csv`)
  instead of summed airport endpoint throughput, which double-counts every domestic
  journey. May 2026 latest-month domestic now reads **15.4M passengers carried**
  (was 30.8M - exactly 2× the carrier figure); trailing-12-month reads **168.3M**.

### Changed

- Clarified passenger metric semantics across chart labels, dashboard cards,
  manifest metadata, data dictionary, methodology, and README. Airport charts are
  relabelled as **airport throughput** (arrivals + departures); the international
  chart as **Indian gateway throughput**. Airport-level charts are unchanged in
  scale - only national passenger-carried demand moved to the carrier layer.
- `dashboard_summary.json` domestic keys are now metric-explicit
  (`latest_month_passengers_carried`, `trailing_12m_passengers_carried`,
  `airport_throughput_latest_month`, `passengers_metric`); the ambiguous
  `latest_month_passengers`/`trailing_12m_passengers` keys are removed.

### Added

- `scripts/metrics.py` - the single home for passenger metric semantics
  (passengers carried vs airport throughput vs gateway throughput).
- `charts/manifest.json` records `primary_source_table` and `metric_semantics`
  per chart.
- Passenger-metric-semantics advisory validation check
  (`semantics.domestic_airport_throughput_vs_carrier`) and regression tests so
  airport endpoint throughput cannot be reused as national passengers carried.
- `docs/external-smoke-checks.md` - independent scale checks vs published DGCA
  figures.

## 0.1.0

Initial public release - a clean, canonical dataset of Indian aviation passenger
traffic from DGCA's public workbooks.

- **Four single-grain tables** in `data/processed/`: domestic monthly,
  international quarterly, derived yearly, and carrier monthly. One airport = one
  entity; integer passengers; `schema_version` per table.
- **Table-driven entity resolution** with validity windows - resolves source
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
