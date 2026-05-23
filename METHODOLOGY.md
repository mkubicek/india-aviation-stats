# Methodology

Single source of truth for all definitions, classifications, and assumptions
used in this project.

## Disclaimer

> This is a personal open-source project. Views and analysis are my own and do
> not represent Flughafen Zürich AG, Noida International Airport, or any
> affiliated entity.

---

## Data Sources (Priority Order)

### 1. DGCA Monthly and Quarterly Statistics (Primary)

- **Provider:** Directorate General of Civil Aviation, India
- **URL:** <https://www.dgca.gov.in/digigov-portal/>
- **Format:** Public Excel files discovered through the DGCA portal and S3
  source URLs, normalized locally by `scripts/ingest_sources.py`
- **Coverage:** Domestic monthly city-pair and carrier data; international
  quarterly city-pair, country, carrier, and carrier-month tables. 2015–present
- **Access:** Public HTTP GET. No authentication required
- **Update frequency:** Monthly/quarterly (follows DGCA publication cycle)

### 2. World Bank Open Data API

- **Provider:** The World Bank
- **Indicators:**
  - `NY.GDP.PCAP.PP.CD` — GDP per capita, PPP (current international $)
  - `SP.POP.TOTL` — Total population
  - `IS.AIR.PSGR` — Air transport, passengers carried
- **Format:** JSON via REST API
- **Endpoint:** `https://api.worldbank.org/v2/country/IND/indicator/{indicator}?format=json&per_page=100`
- **Access:** Free, no authentication required

### 3. IMF World Economic Outlook (planned, not used in v1)

- **Provider:** International Monetary Fund
- **Dataset:** World Economic Outlook database — GDP projections to 2029
- **Format:** Excel download from imf.org
- **Status in v1:** Not yet ingested. v1 uses log-linear extrapolation from
  observed data. Integrating IMF WEO is tracked as a P1 TODO; see
  `TODOS.md` → "IMF WEO ingestion (or permanent downgrade)".

### 4. MoCA Daily Summaries

- **Provider:** Ministry of Civil Aviation, India
- **URL:** <https://www.civilaviation.gov.in/>
- **Format:** HTML snapshots parsed into `daily.csv`
- **Access:** Public HTML; historical snapshots via Internet Archive CDX API
- **Note:** Optional ingestion because the core projection model uses DGCA
  monthly/quarterly and World Bank annual inputs

### 5. AAI Traffic News (Not Used for Automation)

- **Provider:** Airports Authority of India
- **Format:** PDF (Annexures I–VI with airport-wise detailed data)
- **Access:** OTP-gated since 2025 — **not automatable**
- **Note:** DGCA source workbooks are used for equivalent data

---

## Statistical Population

- **Scope:** All scheduled commercial passenger flights at Indian airports
- **Excludes:** Cargo-only operations, military flights, general aviation,
  helicopter services, charter operations
- **Unit:** Passengers (embarked + disembarked, or as reported by source)

---

## Airport Classification

Airports are classified into tiers based on annual passenger volume. Tier
assignments are defined in `mappings.yaml` and updated when traffic data
warrants reclassification.

### Decision Table

| Annual Passengers | 3-Year CAGR | Classification |
|-------------------|-------------|----------------|
| > 20M             | any         | **Metro**      |
| 5M – 20M         | any         | **Tier 1**     |
| 1M – 5M          | any         | **Tier 2**     |
| < 1M             | any         | **Tier 3**     |
| Not yet open      | N/A         | **Greenfield** (use `mappings.yaml` opening date + phase 1 capacity) |

### Tier Definitions

**Metro** — Top airports by volume (> 20M annual passengers)
- Examples: DEL, BOM, BLR, HYD, MAA, CCU

**Tier 1** — Major airports (5M – 20M annual passengers)
- Examples: GOI, COK, AMD, PNQ, JAI, GAU

**Tier 2** — Growing airports (1M – 5M annual passengers)
- Examples: IXC, VNS, PAT, IXB, LKO, SXR

**Tier 3** — Small and regional airports (< 1M annual passengers)
- Examples: UDAN-enabled small airports, regional connectivity scheme routes

**Greenfield** — Under construction or newly opened
- Examples: NIA (Jewar), NMIA (Navi Mumbai), Bhogapuram

---

## Temporal Alignment

Indian aviation data follows the **Indian financial year** (April – March):
- FY2024-25 = April 2024 through March 2025

World Bank and IMF data use **calendar years** (January – December).

**Alignment approach:**
- For GDP-flights correlation: use calendar year for both (World Bank provides
  calendar-year air passenger data)
- For airport-level analysis: use financial year as reported by DGCA,
  clearly labelled as "FY"
- When merging: FY2024-25 maps to CY2024 (using the starting year of the FY)

---

## Growth Projection Methodology

This is the core analytical innovation of the project: projecting India's
passenger growth using the GDP–flights correlation observed globally and in
India's own history.

### Step 1: Establish Historical Correlation

- Collect 20 years of India data (2005–2025):
  - GDP per capita, PPP (World Bank: `NY.GDP.PCAP.PP.CD`)
  - Air passengers carried (World Bank: `IS.AIR.PSGR`)
  - Total population (World Bank: `SP.POP.TOTL`)
- Derive: `flights_per_capita = passengers / population`
- Fit **log-log OLS regression**: `ln(flights_per_capita) ~ β₀ + β₁ × ln(gdp_per_capita_ppp)`
- Log-log model is standard in aviation economics (constant elasticity)
- Report R², coefficients, standard errors, residuals

### Step 2: Project GDP

- **v1 (current):** Log-linear extrapolation from the last 10 years of observed
  India GDP per capita (PPP), yielding a constant-growth projection through
  2040. This is honest about what the code actually does; IMF WEO integration
  is a planned v1.1 upgrade (see `TODOS.md`).
- **v1.1 target:** IMF WEO forecasts for 2025–2029, linear extrapolation of
  IMF growth rate trend for 2030–2040.
- **Milestone confidence bands:** `milestones.py` samples a correlated ±10%
  triangular perturbation over the post-2029 GDP path for each Monte Carlo
  draw. This bounds GDP-path uncertainty in the band, but it does not
  replace IMF integration; until v1.1, the central path is log-linear.

### Step 3: Derive National Passenger Forecast

- For each projected year, compute implied `flights_per_capita` from regression
- Multiply by UN/World Bank population projection → national passenger total
- Compute **confidence bands** using regression standard error (±2σ)

### Step 4: Distribute to Airports

- Calculate each airport's historical **traffic share** (% of national total)
- **v1 (current):** Share held fixed at the latest observed year.
  `compute_airport_projections` multiplies each projected-year national
  total by that frozen share. Per-airport milestones (BOM/DEL/BLR) ride
  on this share-freeze assumption and inherit the national confidence band.
- **v1.1 target (not yet implemented):** tier-based growth differentials:
  - Tier 2/3 airports historically grow faster than metros (calculate from data)
  - Metros are capacity-constrained; smaller airports benefit from UDAN scheme
  - Compute historical CAGR differential by tier from DGCA source data
  - Tracked as P1 in `TODOS.md` → "Tier-CAGR differentials in
    compute_airport_projections"
- **Consequence for tier-share milestones:** under v1 share-freeze, any
  "Tier N cumulative share > X%" milestone is structurally deterministic
  (shares are constant across projected years). `milestones.py` emits
  such rows with `method: "deterministic"` and either a single year
  (achieved) or `beyond_horizon`. Monte Carlo bands would be fake
  precision and are not emitted.
- **Greenfield airports:** appear at their `opening_date` (from `mappings.yaml`)
  with `phase1_capacity`, then ramp over three years toward phase-1 capacity.

### Step 5: Output

- `projection.json` with:
  - Yearly national totals (historical + projected)
  - Per-airport projections
  - Confidence bands (±2σ)
  - Regression diagnostics (R², coefficients, n)
  - Methodology metadata

---

## Validation Checks

Validation is advisory — warnings are logged but never block the pipeline.

| Check | Threshold | Purpose |
|-------|-----------|---------|
| `check_national_totals` | ±5% vs reference.yaml | Annual passenger comparison |
| `check_airport_totals` | ±10% vs reference.yaml | Major airport comparison |
| `check_growth_rates` | > 50% YoY (excl. COVID) | Flag anomalous spikes |
| `check_tier_consistency` | Tier matches volume | Detect misclassified airports |
| `check_gdp_correlation` | R² > 0.85 | Regression quality gate |
| `check_projection_bounds` | Within 2× historical max | Sanity check projections |
| `check_milestone_stability` | > 1y p50 drift vs prior release snapshot | Methodology-soundness signal |

---

## Known Limitations

1. **Source publication dependency:** Primary DGCA/MoCA source publications may
   have gaps, delays, or workbook layout changes
2. **GDP-flights correlation assumes continuity:** The historical relationship
   may not hold through structural breaks (new aviation policy, oil shocks,
   pandemics)
3. **Airport-level share stability:** Projections assume relatively stable
   traffic share; new airports, airline hub changes, and mergers will shift
   shares
4. **Financial year vs calendar year:** DGCA data uses Indian FY (Apr–Mar),
   World Bank uses CY (Jan–Dec) — see Temporal Alignment section
5. **Fleet orders ≠ airport capacity:** Aircraft orders (IndiGo 500× A320neo,
   Air India 470× mixed) don't map directly to specific airports
6. **Domestic vs international:** Some datasets don't distinguish; total
   passenger figures may mix both
7. **UDAN scheme distortion:** Government-subsidised routes may inflate Tier 3
   numbers beyond what pure market dynamics would produce
8. **COVID disruption (2020–2021):** Excluded from trend calculations but
   affects cumulative metrics
9. **v1 uses log-linear GDP extrapolation, not IMF WEO:** the central GDP
   path in `project.py:project_gdp` is a constant-growth extrapolation from
   the last 10 years of observed data. IMF WEO integration is planned for
   v1.1 (see `TODOS.md` P1). Milestone bands reflect regression + a ±10%
   post-2029 GDP perturbation; they do not model structural-break risk (oil
   shocks, pandemics, policy shifts) or IMF-specific short-term forecast
   revisions.
10. **v1 airport distribution uses frozen shares, not tier-CAGR:**
    `compute_airport_projections` freezes each airport's share of national
    passengers at the latest observed year. Tier-CAGR differentials
    described in Step 4 are v1.1 work (`TODOS.md` P1). Per-airport
    milestones (BOM/DEL/BLR) inherit whatever the national regression
    says under this assumption, scaled by a constant share.

---

## Methodology Changelog

| Date | Version | Change |
|------|---------|--------|
| 2026-04 | 1.0 | Initial methodology: GDP-flights log-log regression, 5-tier airport classification, DGCA/MoCA + World Bank data pipeline |
