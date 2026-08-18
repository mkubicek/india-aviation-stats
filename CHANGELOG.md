# Changelog

## Unreleased

### Fixed

- Every float column of `carrier_monthly.csv` is published at one fixed
  precision, 3 decimals (`metrics.CARRIER_DECIMALS`), instead of inheriting
  whatever an upstream dtype accident produced. A single all-cargo workbook with
  a blank load-factor column made the aggregate column object dtype, which
  silently disabled its float formatting and rewrote every airline's published
  load factor from `86.66` to `86.66023056391617`. The tonne columns had the
  same exposure and also carried summing artefacts (`846.2399999999999`). This
  restates 1,913 rows once, disclosed in `REVISIONS.md`; the information lost is
  a gram of freight.
- Corrected the public domestic national dashboard scale: national domestic demand
  now uses scheduled-domestic carrier passengers carried (`carrier_monthly.csv`)
  instead of summed airport endpoint throughput, which double-counts every domestic
  journey. May 2026 latest-month domestic now reads **15.4M passengers carried**
  (was 30.8M - exactly 2× the carrier figure); trailing-12-month reads **168.3M**.

### Changed

- The Noida ramp benchmark draws DXN with the same line, label, and legend
  treatment as its analogues, instead of ring markers, an arrow callout, and a
  dedicated legend entry. AGENTS.md forbids gilding any airport and now says
  explicitly that a focus page's subject is not an exception.
- CI runs the test suite after `clean.py` rather than before `fetch.py`, so the
  tests that read `data/processed/` assert against the tables the run is about
  to publish. The monthly schedule gained an 18th-of-month run: DGCA lands a
  month's workbooks between roughly the 14th and the 29th of the following
  month, so a lone run on the 5th always trailed publication by weeks.
- `DXN.opening_date` corrected to `2026-06`, the month scheduled commercial
  service began, matching how the field is used elsewhere. The aerodrome licence
  (6 March 2026) and the Phase 1 inauguration (28 March 2026) carried no
  passengers.
- The conservation tripwire names its likelier cause. Symmetry breaks when an
  unmapped city label drops one endpoint of its pairs, not only when a refactor
  breaks the endpoint split; the failure message, `METHODOLOGY.md` and the tests
  now say so. An unmapped label whose directions happen to balance still passes,
  which is recorded in the check's docstring.
- `DATA_QUALITY.md` states what each named falsification test measures.
  `distinct-airports-not-merged` reads all-time presence, so it cannot flag an
  airport that merely stops appearing in new months.
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

- `NMB` (Daman Airport) as an airport entity, with `assumptions/NMB-001.md`.
  DGCA's July 2026 workbook introduced a `DAMAN` label when scheduled civil
  traffic began there; left unmapped it also broke the endpoint conservation
  tripwire, because only the Delhi end of the one route was attributed.
- Carrier float precision is now a BLOCKING validation check, so a restatement
  reds the refresh that would publish it rather than the one after.
- `REVISIONS.md` covers all five published tables, not just the two airport
  layers, and counts rows whose non-passenger columns moved. The load-factor
  rewrite would have restated 2,721 published rows with the log reporting
  "no changes". `diff_layer` now refuses a non-unique key rather than emitting a
  cartesian product of invented changes.
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
