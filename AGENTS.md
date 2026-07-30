# Agents — Conventions & Chart Styleguide

Pipeline behaviour, data classification, and chart generation follow the rules
here. For data definitions see [METHODOLOGY.md](METHODOLOGY.md).

## Pipeline

```
fetch.py → normalize.py → clean.py → validate/ → chart.py
```

1. **fetch.py** — Download DGCA workbooks + refresh `sources_manifest.csv`
2. **normalize.py** — Parse Excel → aggregated CSVs (PASSENEGER fix, month/airline map)
3. **clean.py** — Entity dedup + cadence split + directed domestic routes →
   published tables in `data/processed/`
4. **validate/** — `python -m validate [--assumptions --revisions]`: blocking gate
   (overlap, cadence, schema, definitional) + assumptions ledger + reverse gate +
   revision log → `validation_report.json`, `DATA_QUALITY.md`, `REVISIONS.md`
5. **chart.py** — Static dashboard charts + summary/manifest JSON → `charts/`

Each step is idempotent and re-runnable. Run validate with `PYTHONPATH=scripts`.

## Conventions

- `mappings.yaml` drives all classification — edit mappings, not code
- Resolution is 100% table-driven (entity tables + validity windows +
  `airport_aliases`); a high-volume unmapped domestic label is surfaced as an
  advisory, never silently kept as a raw code
- The domestic route layer resolves both endpoints or fails; it never drops an
  unresolved endpoint. Zero-weight directional observations may remain
  published but are excluded from weighted network calculations.
- Every non-trivial cleanup decision is a falsifiable `assumptions/<id>.md` file
- Raw data is gitignored; only processed CSVs and charts are committed
- IATA codes uppercase (DEL, BOM); airport names title case; airline names as
  branded (IndiGo, not INDIGO); financial years as "FY2024-25"

## Charts

Charts serve the data — keep them purist:

- **No editorial overlays.** A chart shows only what is in the published tables;
  every mark/label must be verifiable against the dataset. Do **not** caption or
  annotate data that isn't there yet (e.g. an "airport X awaited" note for an
  airport with zero rows). Newcomers surface through data-derived eligibility in
  `newcomer_airport_ramps()` once they have qualifying rows. **No airport is
  special-cased or gilded** (not even a future flagship) — every line uses the
  shared palette.
- **No employer/legal disclaimer on charts.** It lives in the **README only**.
  Chart surfaces stay clean: title, axes, legend, and the attribution line —
  nothing else.
- **Disclose selection and windows — no false completeness.** A chart that shows
  a top-N subset (e.g. the share movers) must state on the chart how many
  entities of the total are shown and name the explicit comparison windows
  (period start–end), so a ~20-bar chart is never read as the full field of 100+
  airports or as ending in the current, unpublished period. Selection sizes and
  window labels are computed from the data, never hardcoded, so they stay correct
  on refresh (`share_movers_subtitle()` in `chart.py`).

Default chart generation creates nine static artifacts. The first seven are
general dashboard/README charts; the two NIA-focused charts live in the
standalone route-network case study:

- `india_domestic_demand_pulse.png`
- `top_airport_traffic_trends.png`
- `newcomer_airport_rampup_24m.png`
- `domestic_market_share_gainers.png`
- `international_gateway_share_gainers.png`
- `airport_seasonality_fingerprint.png`
- `domestic_network_decentralisation.png`
- `ncr_route_opportunity_frontier.png`
- `dual_airport_network_roles.png`

The optional `airport_passenger_race.gif` is generated only with
`uv run python scripts/chart.py --include-gifs`.

Airport-level domestic charts source `airport_monthly.csv`; route/network charts
source `domestic_route_monthly.csv`; the international gateway chart sources
`airport_international_quarterly.csv`. Do not mix monthly and quarterly cadences
in one chart. Route/network calculations must remain generic and parameterised;
case-study interpretation belongs in the accompanying analysis document. Prefer
transparent volume, persistence, concentration, and effective-destination
metrics over opaque composite scores or fashionable centrality measures.

**Dark theme:** background `#0d1117`, text `#e6edf3`, subtle `#94a3b8`, grid
`#334155` dashed alpha 0.2. **Attribution line** (bottom-right on the figure):

```
{repo_url} | Data: DGCA (as of {data_date}) | Generated {today} | Coverage: {coverage}
```

Do not include a data fingerprint inside chart images. Fingerprints belong in
`charts/manifest.json` and `data/processed/dashboard_summary.json`. `data_date`
comes from `data/processed/metadata.json`; `today` is the chart generation date;
`repo_url` comes from `GITHUB_REPOSITORY` or `git remote`.

**Highlight colours** (`mappings.yaml: airport_colors` / `airline_colors`):
DEL `#f72585` · BOM `#4cc9f0` · BLR `#4ade80` · HYD `#a78bfa`
· MAA `#fb923c` · CCU `#f87171`; IndiGo `#3b82f6` · Air India `#f72585` · SpiceJet
`#fbbf24` · Akasa `#fb923c` · Vistara `#a78bfa`. Tier bands (presentation only):
Metro `#3b82f6`, Tier 1 `#14b8a6`, Tier 2 `#22c55e`, Tier 3 `#94a3b8`, Greenfield
`#fbbf24`.

**GIF frames:** 300 ms/frame (last 3000 ms), fixed x/y limits across frames, bar
labels never clipped.

## CI / GitHub Actions

- **Schedule:** monthly (5th, 08:00 UTC); GIFs only on manual dispatch when requested
- **Cache:** raw data as `data/raw.tar.zst`, refreshed by `cache-keepalive.yml`
- **Soft timeout:** `DOWNLOAD_TIMEOUT=600` stops new downloads before job timeout
- **Stale-data governance:** a blocking validation failure keeps the last-good
  published data and opens a `data-quality` issue rather than shipping a bad merge

## Red Queen Review Loop

This project treats `AGENTS.md`, `METHODOLOGY.md`, `mappings.yaml`, and the `validate/` checks as the project’s evaluator. The evaluator should improve over time, but only at explicit review boundaries.

When a reviewer or contributor proposes a correction, methodological tweak, or better judgment rule:

1. Apply the correction to the current analysis or chart.
2. Decide whether the correction exposes a reusable rule.
3. If reusable, encode it in the narrowest durable place:
   - `METHODOLOGY.md` for definitions, assumptions, statistical choices, and limitations
   - `AGENTS.md` for chart conventions, review behavior, pipeline rules, and agent operating rules
   - `validate/` checks (`python -m validate`) for measurable gates
   - `mappings.yaml` for airport classifications and known entity facts
4. Add or update a validation check when the rule can be tested mechanically.
5. Do not change the rubric mid-review to justify an existing output; finish the review, then update the evaluator for the next round.
