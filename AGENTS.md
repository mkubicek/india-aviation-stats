# Agents — Chart Styleguide & Conventions

All chart generation, data classification, and pipeline behaviour follows
the rules in this file. For data definitions, see [METHODOLOGY.md](METHODOLOGY.md).

## Disclaimer

Every chart must include the following disclaimer in the attribution line:

> This is a personal open-source project. Views and analysis are my own and do
> not represent Flughafen Zürich AG, Noida International Airport, or any
> affiliated entity.

---

## Chart Colors

### Tier Palette

| Tier       | Color   | Hex       |
|------------|---------|-----------|
| Metro      | Blue    | `#3b82f6` |
| Tier 1     | Teal    | `#14b8a6` |
| Tier 2     | Green   | `#22c55e` |
| Tier 3     | Slate   | `#94a3b8` |
| Greenfield | Gold    | `#fbbf24` |

### Highlighted Airport Colors

| Airport | Color   | Hex       |
|---------|---------|-----------|
| DEL     | Pink    | `#f72585` |
| BOM     | Cyan    | `#4cc9f0` |
| NIA     | Gold    | `#fbbf24` |
| BLR     | Green   | `#4ade80` |
| HYD     | Purple  | `#a78bfa` |
| MAA     | Orange  | `#fb923c` |
| CCU     | Red     | `#f87171` |

### Airline Colors

| Airline          | Hex       |
|------------------|-----------|
| IndiGo           | `#3b82f6` |
| Air India Group  | `#f72585` |
| SpiceJet         | `#fbbf24` |
| Akasa Air        | `#fb923c` |
| Vistara          | `#a78bfa` |
| Go First         | `#22c55e` |
| Alliance Air     | `#14b8a6` |

---

## Typography

- **Font:** System sans-serif (matplotlib default)
- **Airport codes:** Always IATA uppercase (DEL, BOM, BLR)
- **Airport names:** Title case (Indira Gandhi International, not INDIRA GANDHI)
- **Airline names:** As branded (IndiGo, not INDIGO; Air India, not AIR INDIA)
- **Indian terms:** Always annotate with English equivalent
  - Example: "Lakh (100,000)" or "Crore (10,000,000)"

---

## Layout

### Dark Theme

- Background: `#0d1117`
- Text: white (`#ffffff`)
- Subtle text: `#94a3b8`
- Grid: `#334155`, dashed, alpha 0.2

### Attribution Line

Single line at bottom-right of every chart:

```
{repo_url} | Data: {sources} (as of {data_date}) | Generated {today}
```

- `data_date` from `data/processed/metadata.json`
- `repo_url` from `GITHUB_REPOSITORY` env var or `git remote`
- **Static charts:** fontsize 8
- **GIF frames:** fontsize 11
- Use `ax.transAxes` coordinates (not `fig.text`) for `bbox_inches="tight"`

### Disclaimer Attribution

On charts where space permits, add a second attribution line:

```
Personal project — views are my own, not those of any employer or affiliate
```

### Definition Line

Below chart title, gray text (`#94a3b8`), explains scope/methodology:
- Example: "Scheduled domestic passenger flows by airport | Trailing 12-month total"

### General Rules

- No overlapping elements — clear spacing between axes, labels, legends
- Legends: outside chart area (`bbox_to_anchor`) or inline labels
- Year axes: always show every year with explicit `xticks`
- Partial years: exclude incomplete years from annual charts
- Chart filenames: descriptive names (e.g., `airport_passenger_race.gif`)

---

## Animated Charts (GIFs)

- Date label: consistent position, monospace font
- Frame rate: 300 ms per frame, last frame 3000 ms pause
- Fixed axes: lock x/y limits across all frames
- National total counter: top-right corner, formatted with commas
- Bar labels must stay inside or just outside the plot without clipping.

---

## Pipeline

```
fetch.py → normalize.py → clean.py → validate/ → chart.py
```

1. **fetch.py** — Download DGCA/MoCA source data + refresh `sources_manifest.csv`
2. **normalize.py** — Parse Excel → aggregated CSVs (PASSENEGER fix, month/airline map)
3. **clean.py** — Entity dedup + cadence split → published layers in `data/processed/`
4. **validate/** — `python -m validate [--assumptions --revisions]`: BLOCKING gate
   (overlap, cadence, schema, definitional) + assumptions ledger + reverse gate +
   revision log → `validation_report.json`, `DATA_QUALITY.md`, `REVISIONS.md`
5. **chart.py** — Passenger race + "Who's Rising" newcomers chart → `charts/`

Each step is idempotent and can be re-run independently. Run validate with
`PYTHONPATH=scripts`.

---

## Conventions

- `mappings.yaml` drives all classification — edit mappings, not code
- Resolution is 100% table-driven (entity tables + validity windows +
  `airport_aliases`); a high-volume unmapped domestic label is surfaced as an
  advisory, never silently kept as a raw code
- Every non-trivial cleanup decision is a falsifiable `assumptions/<id>.md` file
- `warnings.log` contains advisory validation warnings
- Raw data not committed (gitignored), only processed CSVs and charts
- Charts regenerated on every pipeline run via GitHub Actions
- Financial year labelling: "FY2024-25" format for Indian data

---

## CI / GitHub Actions

- **Schedule:** Monthly (5th of each month at 08:00 UTC)
- **Cache:** Raw data cached as `data/raw.tar.zst`, restored before download and
  refreshed by `cache-keepalive.yml`
- **Incremental downloads:** source files are cached locally and freshness is
  preserved by the raw-data archive
- **Soft timeout:** `DOWNLOAD_TIMEOUT=600` (10 min) stops new downloads before
  job timeout
- **GIF generation:** Only on 5th of month or manual dispatch (`--skip-gifs`
  flag on other runs)

### Story cadence != CI cadence

The monthly CI schedule is infrastructure: it keeps the pipeline fresh, catches
data-source breakage early, and regenerates charts so the README never goes
stale. The current story is observed passenger traffic only.
