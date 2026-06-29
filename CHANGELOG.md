# Changelog

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
