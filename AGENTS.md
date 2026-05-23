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
- Example: "Scheduled commercial passengers at Indian airports | Log-log GDP regression"

### General Rules

- No overlapping elements — clear spacing between axes, labels, legends
- Legends: outside chart area (`bbox_to_anchor`) or inline labels
- Year axes: always show every year with explicit `xticks`
- Partial years: exclude incomplete years from annual charts
- Chart filenames: descriptive names (e.g., `gdp_flights_correlation.png`)

---

## Animated Charts (GIFs)

- Date label: consistent position, monospace font
- Frame rate: 300 ms per frame, last frame 3000 ms pause
- Fixed axes: lock x/y limits across all frames
- National total counter: top-right corner, formatted with commas
- Circle sizes: proportional to passenger volume (sqrt scale for area)
- New airports: appear at opening date with fade-in effect

---

## Pipeline

```
download.py → process.py → validate.py → project.py → milestones.py → chart.py → report.py
```

1. **download.py** — Fetch data from World Bank API, DGCA/MoCA sources
2. **process.py** — Parse, merge, aggregate → `data/processed/`
3. **validate.py** — Plausibility checks + `check_milestone_stability` → `warnings.log`
4. **project.py** — GDP regression (emits `cov_params`) + passenger projections → `projection.json` (schema v1)
5. **milestones.py** — Monte Carlo inverse prediction from `projection.json` + `milestones.yaml` → `milestones.json` (schema v1)
6. **chart.py** — Generate milestones table (hero) + correlation + projection + GIF map → `charts/`
7. **report.py** — Monthly delta report with milestones section → `reports/`, writes monthly snapshot under `data/processed/snapshots/monthly/`

Each step is idempotent and can be re-run independently.

---

## Conventions

- `mappings.yaml` drives all classification — edit mappings, not code
- Unknown values → "Other" bucket + logged to `warnings.log`
- `validate.py` cross-checks against `reference.yaml`
- `warnings.log` is unified: unmapped values + plausibility checks
- Raw data not committed (gitignored), only processed CSVs and charts
- Charts regenerated on every pipeline run via GitHub Actions
- Financial year labelling: "FY2024-25" format for Indian data

---

## CI / GitHub Actions

- **Schedule:** Monthly (5th of each month at 08:00 UTC)
- **Cache:** Raw data cached between runs, keyed by `scripts/download.py` hash
- **Incremental downloads:** `download.py` uses `If-Modified-Since` to skip
  unchanged files
- **Soft timeout:** `DOWNLOAD_TIMEOUT=600` (10 min) stops new downloads before
  job timeout
- **GIF generation:** Only on 5th of month or manual dispatch (`--skip-gifs`
  flag on other runs)

### Story cadence ≠ CI cadence

The monthly CI schedule is infrastructure: it keeps the pipeline fresh, catches
data-source breakage early, and regenerates charts so the README never goes
stale. The *story* is annual-centric because the regression's load-bearing
inputs (World Bank `IS.AIR.PSGR`, `NY.GDP.PCAP.PP.CD`, DGCA annual totals)
update annually. `check_milestone_stability` runs every pipeline invocation
but only flags drift versus **release snapshots** (annual DGCA release or the
planned v1.1 IMF WEO release cadence), not monthly-to-monthly noise.

---

## Map Specifics (Animated Airport Map)

- **Base map:** Natural Earth or datameet/maps GeoJSON (NO Mapbox)
- **Projection:** Suitable for India (Lambert Conformal Conic or Mercator crop)
- **Airport circles:** `sqrt(passengers)` scaling for perceptual area accuracy
- **Color:** By tier (see Tier Palette above)
- **Animation timeline:** 2015 → 2025 (actual) → 2030 → 2035 → 2040 (projected)
- **Greenfield airports:** Appear at `opening_date` with gold pulsing effect
- **Counter:** National total in top-right, formatted in millions
  (e.g., "340M passengers")
