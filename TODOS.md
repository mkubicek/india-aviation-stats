# TODOS

Deferred work after the `0.1.0` observed-data release. Priority: P1 is the next
best product-quality improvement, P2 is useful when practical, and P3 is
optional expansion.

## P1

### Data Dictionary

- Add `docs/data-dictionary.md` describing each processed CSV column, units, and
  domestic versus international source cadence.
- Link it from the README processed-data table.

### Contributor Workflow

- Add a compact contributor section covering setup, pipeline commands, tests,
  and how to update `mappings.yaml`.
- Keep the current per-script commands for `0.1.0`; consider a unified CLI only
  if contributors find the script sequence confusing.

## P2

### Validation Hardening

- Add checks for unmapped high-volume uppercase source city names.
- Keep validation advisory so source changes remain visible without blocking
  chart regeneration unnecessarily.

### Additional Observed-Data Charts

- Consider one or two more charts only if they use the current processed data
  directly and can be explained without forecasts.
- Good candidates: domestic recovery by airport, metro share over time, or
  domestic carrier passenger trends.

## P3

### Forecasting Branch

- Keep forecast, GDP, milestone, and report work off `main` until the
  methodology, code, caveats, and tests are aligned.
- If reintroduced, publish it as a separate versioned methodology rather than
  mixing it into the observed-data MVP.
