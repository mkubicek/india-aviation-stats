# India Aviation Stats

Open-source analytics dashboard visualising India's airport expansion boom,
passenger growth, and the GDP-to-flights correlation.

> **Disclaimer:** This is a personal open-source project. Views and analysis
> are my own and do not represent Flughafen Zürich AG, Noida International
> Airport, or any affiliated entity.

---

## The Three-Chart Story

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

### 3. Animated Airport Map (*the where*)

An animated map showing every Indian airport as a circle sized by passenger
volume, coloured by tier. Watch the network grow from 2015 through 2025
(actual data) to 2040 (projected), with greenfield airports like Noida (NIA)
and Navi Mumbai (NMIA) appearing at their opening dates.

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
| [Vonter/india-aviation-traffic](https://github.com/Vonter/india-aviation-traffic) | Airport-wise passengers, carrier data (primary) | Public GitHub |
| [World Bank Open Data](https://data.worldbank.org/) | GDP, population, air passengers | Free API |
| [IMF WEO](https://www.imf.org/en/Publications/WEO) | GDP projections to 2029 | Free download |
| [DGCA](https://www.dgca.gov.in/) | City-pair traffic, carrier stats | Public Excel |

---

## Pipeline

```
download.py → process.py → validate.py → project.py → chart.py → report.py
```

Automated monthly via GitHub Actions. Each step is idempotent.

See [METHODOLOGY.md](METHODOLOGY.md) for definitions, classifications, and
projection methodology. See [AGENTS.md](AGENTS.md) for chart conventions.

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
uv run python scripts/chart.py
uv run python scripts/report.py
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
│   ├── download.py      # Fetch from World Bank, Vonter, IMF
│   ├── process.py       # Parse + aggregate → data/processed/
│   ├── validate.py      # Plausibility checks
│   ├── project.py       # GDP regression + growth projection
│   ├── chart.py         # Generate charts → charts/
│   └── report.py        # Monthly delta report
├── data/
│   ├── raw/             # Downloaded source files (gitignored)
│   └── processed/       # Aggregated CSVs + projection.json
├── charts/              # Generated PNGs and GIFs
├── reports/             # Monthly markdown reports
├── .github/workflows/
│   └── update.yml       # Monthly CI pipeline
└── pyproject.toml       # uv-managed dependencies
```

---

## License

MIT — see [LICENSE](LICENSE).
