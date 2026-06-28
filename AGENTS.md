# Agents — Conventions & Chart Styleguide

Pipeline behaviour, data classification, and chart generation follow the rules
here. For data definitions see [METHODOLOGY.md](METHODOLOGY.md).

## Pipeline

```
fetch.py → normalize.py → clean.py → validate/ → chart.py
```

1. **fetch.py** — Download DGCA workbooks + refresh `sources_manifest.csv`
2. **normalize.py** — Parse Excel → aggregated CSVs (PASSENEGER fix, month/airline map)
3. **clean.py** — Entity dedup + cadence split → published layers in `data/processed/`
4. **validate/** — `python -m validate [--assumptions --revisions]`: blocking gate
   (overlap, cadence, schema, definitional) + assumptions ledger + reverse gate +
   revision log → `validation_report.json`, `DATA_QUALITY.md`, `REVISIONS.md`
5. **chart.py** — Passenger race + "Who's Rising" newcomers chart → `charts/`

Each step is idempotent and re-runnable. Run validate with `PYTHONPATH=scripts`.

## Conventions

- `mappings.yaml` drives all classification — edit mappings, not code
- Resolution is 100% table-driven (entity tables + validity windows +
  `airport_aliases`); a high-volume unmapped domestic label is surfaced as an
  advisory, never silently kept as a raw code
- Every non-trivial cleanup decision is a falsifiable `assumptions/<id>.md` file
- Raw data is gitignored; only processed CSVs and charts are committed
- IATA codes uppercase (DEL, BOM); airport names title case; airline names as
  branded (IndiGo, not INDIGO); financial years as "FY2024-25"

## Charts

Charts serve the data — keep them purist:

- **No editorial overlays.** A chart shows only what is in the published layers;
  every mark/label must be verifiable against the dataset. Do **not** caption or
  annotate data that isn't there yet (e.g. an "airport X awaited" note for an
  airport with zero rows). The data-driven path already covers "watch this airport
  rise": `find_risers()` auto-includes any newcomer once it has qualifying rows, so
  a new airport surfaces on its own once DGCA publishes it. **No airport is
  special-cased or gilded** (not even a future flagship) — every line uses the
  shared palette.
- **No employer/legal disclaimer on charts.** It lives in the **README only**.
  Chart surfaces stay clean: title, axes, legend, and the attribution line —
  nothing else.

**Both charts source Layer 1** (domestic monthly) so they never mix cadences.

**Dark theme:** background `#0d1117`, text white, subtle `#94a3b8`, grid `#334155`
dashed alpha 0.2. **Attribution line** (bottom-right, `ax.transAxes` so
`bbox_inches="tight"` works):

```
{repo_url} | Data: DGCA (as of {data_date}) | Generated {today}
```

`data_date` from `data/processed/metadata.json`; `repo_url` from
`GITHUB_REPOSITORY` or `git remote`.

**Highlight colours** (`mappings.yaml: airport_colors` / `airline_colors`):
DEL `#f72585` · BOM `#4cc9f0` · BLR `#4ade80` · HYD `#a78bfa`
· MAA `#fb923c` · CCU `#f87171`; IndiGo `#3b82f6` · Air India `#f72585` · SpiceJet
`#fbbf24` · Akasa `#fb923c` · Vistara `#a78bfa`. Tier bands (presentation only):
Metro `#3b82f6`, Tier 1 `#14b8a6`, Tier 2 `#22c55e`, Tier 3 `#94a3b8`, Greenfield
`#fbbf24`.

**GIF frames:** 300 ms/frame (last 3000 ms), fixed x/y limits across frames, bar
labels never clipped.

## CI / GitHub Actions

- **Schedule:** monthly (5th, 08:00 UTC); GIFs only on schedule or manual dispatch
- **Cache:** raw data as `data/raw.tar.zst`, refreshed by `cache-keepalive.yml`
- **Soft timeout:** `DOWNLOAD_TIMEOUT=600` stops new downloads before job timeout
- **Stale-data governance:** a blocking validation failure keeps the last-good
  published data and opens a `data-quality` issue rather than shipping a bad merge
