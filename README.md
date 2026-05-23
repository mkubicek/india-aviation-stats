# India Aviation Stats

Open-source analytics dashboard visualising India's airport expansion boom,
passenger growth, and the GDP-to-flights correlation.

> **Disclaimer:** This is a personal open-source project. Views and analysis
> are my own and do not represent Flughafen Zürich AG, Noida International
> Airport, or any affiliated entity.

---

## The Chart Story

### 1. GDP–Flights Correlation (*the why*)

India's air traffic tracks GDP per capita with remarkable consistency (R² > 0.9).
As incomes rise, flying shifts from luxury to norm — the same S-curve seen in
China (2005–2020) and Southeast Asia. At ~$10,000 GDP per capita PPP, India is
at the inflection point.

### 2. National Passenger Projection (*the how much*)

Using the GDP–flights regression and IMF growth forecasts, we project India's
annual passenger traffic from today's ~340 million to 750M+ by 2040. The model
uses log-log OLS regression — standard in aviation economics — with confidence
bands derived from historical variance.

### 3. Passenger Race (*the momentum*)

An animated bar race tracks the top airports by scheduled domestic passengers
on a trailing 12-month basis. The current source coverage supports continuous
monthly frames from Mar 2016 through Mar 2026.

![India airport passenger race](charts/airport_passenger_race.gif)

### 4. Animated Airport Map (*the where*)

An animated map showing every Indian airport as a circle sized by passenger
volume, coloured by tier. Watch the network grow from 2015 through 2025
(actual data) to 2040 (projected), with greenfield airports like Noida (NIA)
and Navi Mumbai (NMIA) appearing at their opening dates.

### 5. Airport Rankings (*the movers*)

A bump chart tracks the current top 10 airports across complete DGCA source
years. Incomplete annual years are left as visible gaps so rankings are not
over-interpreted when a source workbook is missing.

![India's top airport rankings over time](charts/airport_rankings.png)

---

## Key Numbers (FY2024-25)

| Metric | Value |
|--------|-------|
| Total passengers | ~340.7M |
| Delhi IGI | 79.25M |
| Flights per capita | ~0.13 |
| GDP per capita (PPP) | ~$10,000 |
| Operational fleet | ~750 aircraft |
| Record single day | 505,000 domestic pax (17 Nov 2024) |

---

## Data Sources

| Source | What | Access |
|--------|------|--------|
| [World Bank Open Data](https://data.worldbank.org/) | GDP, population, air passengers | Free API |
| [DGCA](https://www.dgca.gov.in/) | Airport-wise passengers, carrier traffic, international country/city/carrier stats | Public Excel |
| [MoCA](https://www.civilaviation.gov.in/) | Daily summaries (optional snapshot ingestion) | Public HTML / Internet Archive |

> **Note on GDP projections (v1):** post-2025 GDP uses log-linear extrapolation
> from the last 10 years of observed India GDP per capita (PPP). IMF WEO
> integration is a planned v1.1 upgrade; see
> [METHODOLOGY.md Known Limitations](METHODOLOGY.md#known-limitations).

---

## Pipeline

```
download.py → process.py → validate.py → project.py → milestones.py → chart.py → report.py
```

Full refresh on annual DGCA release. Monthly CI (GitHub Actions) runs the
full pipeline as a freshness and infrastructure signal; the underlying story
beats (regression, projection) are annual-centric because the input data
series are annual. Each step is idempotent.

`download.py` now discovers DGCA workbook URLs directly, downloads the raw
source files under `data/raw/aviation/dgca/`, and writes normalized aggregate
CSVs under `data/raw/aviation/aggregated/`. Optional MoCA daily snapshot
ingestion is enabled with `INCLUDE_MCA_DAILY=1`.

See [METHODOLOGY.md](METHODOLOGY.md) for definitions, classifications, and
projection methodology. See [AGENTS.md](AGENTS.md) for chart conventions.

---

## How to cite

If you quote a milestone year or chart from this project in an article,
slide, or paper, please use one of these forms.

**APA:**

> Kubicek, M. (2026). *India Aviation Stats: Operational milestone projections via GDP-flights regression.* Retrieved from https://github.com/mkubicek/india-aviation-stats

**BibTeX:**

```bibtex
@misc{kubicek2026indiaaviation,
  author = {Kubicek, Milan},
  title  = {India Aviation Stats: Operational milestone projections via GDP-flights regression},
  year   = {2026},
  howpublished = {\url{https://github.com/mkubicek/india-aviation-stats}},
  note   = {Open-source project. Updated on IMF WEO and annual DGCA releases.}
}
```

**Fetch the data programmatically:**

```bash
curl -L https://raw.githubusercontent.com/mkubicek/india-aviation-stats/main/data/processed/milestones.json
```

```python
import pandas as pd
import json, urllib.request
url = "https://raw.githubusercontent.com/mkubicek/india-aviation-stats/main/data/processed/milestones.json"
ms = json.loads(urllib.request.urlopen(url).read())
ms["projected"]["india_total_500m"]["p50_year"]  # e.g., 2031
```

The `milestones.json` schema is documented inline in
[`scripts/milestones.py`](scripts/milestones.py). Bands are Monte Carlo
percentiles (p10/p50/p90) over regression + GDP-path uncertainty; they do
**not** include structural-break risk (oil shocks, pandemics, policy
shifts).

---

## Local Development

```bash
# Clone
git clone https://github.com/<your-username>/india-aviation-stats.git
cd india-aviation-stats

# Setup (requires uv — https://docs.astral.sh/uv/)
uv sync

# Run full pipeline
uv run python scripts/download.py
uv run python scripts/process.py
uv run python scripts/validate.py
uv run python scripts/project.py
uv run python scripts/milestones.py
uv run python scripts/chart.py
uv run python scripts/report.py

# Tests
uv run pytest
```

---

## Project Structure

```
india-aviation-stats/
├── AGENTS.md            # Chart styleguide & conventions
├── METHODOLOGY.md       # Data definitions & projection methodology
├── README.md
├── LICENSE              # MIT
├── mappings.yaml        # Airport codes, tiers, airline groups, colors
├── reference.yaml       # Validation reference data
├── scripts/
│   ├── download.py      # Fetch from World Bank, DGCA/MoCA source data
│   ├── ingest_sources.py # Discover, download, and normalize DGCA/MoCA sources
│   ├── process.py       # Parse + aggregate → data/processed/
│   ├── validate.py      # Plausibility checks + milestone stability
│   ├── project.py       # GDP regression + growth projection
│   ├── milestones.py    # Monte Carlo inverse prediction → milestones.json
│   ├── chart.py         # Generate charts → charts/
│   └── report.py        # Monthly delta report
├── data/
│   ├── raw/             # Downloaded source files (gitignored)
│   └── processed/       # Aggregated CSVs + projection.json + milestones.json
│       └── snapshots/   # Release + monthly snapshots for drift checks
├── milestones.yaml      # Projected milestone thresholds config
├── tests/               # pytest unit tests
├── charts/              # Generated PNGs and GIFs
├── reports/             # Monthly markdown reports
├── .github/workflows/
│   ├── update.yml       # Monthly CI pipeline
│   └── cache-keepalive.yml # Raw-data cache TTL refresh
└── pyproject.toml       # uv-managed dependencies
```

---

## License

MIT — see [LICENSE](LICENSE).
