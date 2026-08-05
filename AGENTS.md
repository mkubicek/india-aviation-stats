# Agents: Conventions & Chart Styleguide

Pipeline behaviour, data classification, and chart generation follow the rules
here. For data definitions see [METHODOLOGY.md](METHODOLOGY.md).

## Pipeline

```
fetch.py → normalize.py → clean.py → validate/ → chart.py
```

1. **fetch.py**: Download DGCA workbooks + refresh `sources_manifest.csv`
2. **normalize.py**: Parse Excel → aggregated CSVs (PASSENEGER fix, month/airline map)
3. **clean.py**: Entity dedup + cadence split → published tables in `data/processed/`
4. **validate/**: `python -m validate [--assumptions --revisions]`: blocking gate
   (overlap, cadence, schema, definitional) + assumptions ledger + reverse gate +
   revision log → `validation_report.json`, `DATA_QUALITY.md`, `REVISIONS.md`
5. **chart.py**: Static dashboard charts + summary/manifest JSON → `charts/`

Each step is idempotent and re-runnable. Run validate with `PYTHONPATH=scripts`.

## Conventions

- `mappings.yaml` drives all classification; edit mappings, not code
- Resolution is 100% table-driven (entity tables + validity windows +
  `airport_aliases`); a high-volume unmapped domestic label is surfaced as an
  advisory, never silently kept as a raw code
- **Declaring `variants` on an airport REPLACES its implicit `city`/`name`
  labels.** When adding a first variant to an entry, list the city and airport
  name explicitly too, or they stop resolving (104 entries rely on this
  deliberately, e.g. GOI's "Goa" resolving to GOX per GOA-001, so it is not
  globally checkable; it is a per-edit obligation)
- `airport_monthly` attributes each endpoint independently, so one unmapped
  label never deletes a known counterpart's traffic; `domestic_route_monthly`
  requires both endpoints. Validation asserts route endpoints never exceed
  airport endpoints
- Every non-trivial cleanup decision is a falsifiable `assumptions/<id>.md` file
- Raw data is gitignored; only processed CSVs and charts are committed
- IATA codes uppercase (DEL, BOM); airport names title case; airline names as
  branded (IndiGo, not INDIGO); financial years as "FY2024-25"

## Charts

Charts serve the data. Keep them purist:

- **No editorial overlays.** A chart shows only what is in the published tables;
  every mark/label must be verifiable against the dataset. Do **not** caption or
  annotate data that isn't there yet (e.g. an "airport X awaited" note for an
  airport with zero rows). Newcomers surface through data-derived eligibility in
  `newcomer_airport_ramps()` once they have qualifying rows. **No airport is
  special-cased or gilded** (not even a future flagship); every line uses the
  shared palette.
- **No employer/legal disclaimer on charts.** It lives in the **README only**.
  Chart surfaces stay clean: title, axes, legend, and the attribution line,
  nothing else.
- **Disclose selection and windows; no false completeness.** A chart that shows
  a top-N subset (e.g. the share movers) must state on the chart how many
  entities of the total are shown and name the explicit comparison windows
  (period start–end), so a ~20-bar chart is never read as the full field of 100+
  airports or as ending in the current, unpublished period. Selection sizes and
  window labels are computed from the data, never hardcoded, so they stay correct
  on refresh (`share_movers_subtitle()` in `chart.py`).

Default chart generation creates the six static dashboard charts:

- `india_domestic_demand_pulse.png`
- `top_airport_traffic_trends.png`
- `newcomer_airport_rampup_24m.png`
- `domestic_market_share_gainers.png`
- `international_gateway_share_gainers.png`
- `airport_seasonality_fingerprint.png`

`scripts/noida.py` additionally generates the Noida focus set into
`charts/noida/` and writes `noida.html` (run with `PYTHONPATH=scripts`).
Exhibits whose inputs are not yet published (the route layer, DXN airport rows)
are skipped and appear automatically once the data lands. Never annotate a
chart with data that isn't there.

The optional `airport_passenger_race.gif` is generated only with
`uv run python scripts/chart.py --include-gifs`.

Domestic charts source `airport_monthly.csv`; the international gateway chart
sources `airport_international_quarterly.csv`. Do not mix monthly and quarterly
cadences in one chart.

**Light "manager" theme:** surface `#fcfcfb`, ink `#0b0b0b`, secondary
`#52514e`, muted `#898781`, grid `#e1e0d9` (solid hairline, never dashed),
baseline `#c3c2b7`. The page chrome (`index.html`, `noida.html`) uses the same
tokens on ground `#f9f9f7`.

**Takeaway convention:** the title states the computed finding in one sentence
(numbers computed from the data at generation time, never hardcoded); the
subtitle carries the definition, selection disclosure, and comparison windows;
one plain-language caveat sits bottom-left via `add_footer(..., caveat=...)`.
Titles never editorialise beyond what the plotted table shows.

**Computed reference paths:** a title claim about a trend or counterfactual
path may be drawn as a thin solid MUTED line with an ink label, but only when
computed from the plotted series itself (e.g. the growth-pause chart's
trend-path segment). Never a hand-placed guide line.

**Right-margin padding for end labels** must not fabricate empty periods:
clip x-ticks to the last data point (`clip_xticks_to_data()` in `noida.py`).

**Colour rules:** the categorical palette is the CVD-validated ordered set
blue `#2a78d6` · orange `#eb6834` · aqua `#1baf7a` · yellow `#eda100` ·
magenta `#e87ba4` · green `#008300` · violet `#4a3aa7` · red `#e34948`
(`FALLBACK_COLORS`). Assign hues in fixed order or by fixed entity mapping,
never cycle past the set; fold the tail into de-emphasis gray `#a9a7a0` with
ink labels. Gain/decline is always the diverging pair blue `#2a78d6` / red
`#e34948` (never green/red); sequential/diverging heatmaps put a neutral
`#f0efec` at the midpoint. One y-axis per chart, never a dual-axis plot.
Direct labels are ink (`#0b0b0b`), not the series colour. Every co-occurring
colour set in a chart must pass the CVD validator before it ships; the
`tier_colors` band hues failed adjacent-pair validation as chart series and
stay presentation-only for bands/maps; tier splits inside one chart use
validated categorical slots with a BG-colour hairline edge between stacked
segments. Seasonality above/below-average encoding is red above, blue below,
matching the fingerprint heatmap. Entity hues bind wherever two or more
entities co-occur in one chart; a single-entity exhibit uses `PRIMARY` for
legibility (the title names the entity). Aggregates ("rest of India") take
palette slots, never an entity's hue.

**Generated verdict language:** any published verdict or growth sentence
derives its verb and verdict word from the computed sign (`pct_phrase()`,
`register_entries()` in `noida.py`), never hardcoded, and never asserts a
cause the chart's own caveat rules out. Comparison-window strings name both
endpoints (start AND end period).

**Attribution line** (bottom-right on the figure):

```
{repo_url} | Data: DGCA (as of {data_date}) | Generated {today} | Coverage: {coverage}
```

Do not include a data fingerprint inside chart images. Fingerprints belong in
`charts/manifest.json` and `data/processed/dashboard_summary.json`. `data_date`
comes from `data/processed/metadata.json`; `today` is the chart generation date;
`repo_url` comes from `GITHUB_REPOSITORY` or `git remote`.

**Highlight colours** (`mappings.yaml: airport_colors` / `airline_colors`):
DEL `#2a78d6` · BOM `#eb6834` · BLR `#1baf7a` · HYD `#4a3aa7`
· MAA `#eda100` · CCU `#e87ba4`; IndiGo `#2a78d6` · Air India `#e34948` ·
SpiceJet `#eda100` · Akasa `#eb6834` · Vistara `#4a3aa7`. Tier bands
(presentation only): Metro `#2a78d6`, Tier 1 `#1baf7a`, Tier 2 `#008300`,
Tier 3 `#898781`, Greenfield `#eda100`. Colour follows the entity across every
chart, never its rank in the current view.

**GIF frames:** 300 ms/frame (last 3000 ms), fixed x/y limits across frames, bar
labels never clipped.

## CI / GitHub Actions

- **Schedule:** weekly (Mondays, 08:00 UTC); GIFs only on manual dispatch when
  requested. DGCA publishes a month in the last week of the following month and
  restates older months off-cycle, so weekly catches both within 7 days
- **Cache:** raw data as `data/raw.tar.zst`, restored and re-saved by the weekly
  `update.yml` run itself. A miss only costs download time, not correctness
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
