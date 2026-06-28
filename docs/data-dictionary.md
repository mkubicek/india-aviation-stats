# Data dictionary

Every published file is a **single-cadence layer**: one airport (or airline) is
one entity, and one file has one time grain. Schema versions live in
`data/processed/metadata.json` (`layers.<name>.schema_version`); a breaking
change bumps the version and is recorded in the `schema_changelog`.

`passengers == departures + arrivals` on every airport row, and all passenger
counts are whole-person **integers**. `airport` is a canonical key — an IATA code
when one exists, else a stable `name:<slug>` — never a raw source label.

---

## Layer 1 — `airport_monthly.csv` (canonical core)

Domestic, monthly. The crown-jewel series. **Schema v2.0.**

| column | type | unit | key | notes |
|---|---|---|---|---|
| `year` | int | calendar year | ✓ | |
| `month` | int | 1–12 | ✓ | |
| `airport` | string | canonical key | ✓ | IATA or `name:<slug>` |
| `passengers` | int | persons | | `= departures + arrivals` |
| `departures` | int | persons | | embarked at this airport |
| `arrivals` | int | persons | | disembarked at this airport |

Key: exactly one row per `(airport, year, month)`. Source: DGCA domestic
city-pair workbooks.

## Layer 2 — `airport_international_quarterly.csv`

International, quarterly — the real cadence, no midpoint-month hack. **v1.0.**

| column | type | unit | key | notes |
|---|---|---|---|---|
| `year` | int | calendar year | ✓ | |
| `quarter` | int | 1–4 | ✓ | |
| `airport` | string | canonical key | ✓ | Indian endpoints only |
| `passengers` | int | persons | | `= departures + arrivals` |
| `departures` | int | persons | | |
| `arrivals` | int | persons | | |

Key: one row per `(airport, year, quarter)`. Foreign counterpart cities are
dropped. Source: DGCA international city-pair workbooks.

## Layer 3 — `airport_yearly.csv` (derived convenience view)

Whole-calendar-year totals, **derived** from Layers 1+2 (domestic years need all
12 months; international years all 4 quarters). **v2.0.**

| column | type | unit | key | notes |
|---|---|---|---|---|
| `year` | int | calendar year | ✓ | complete years only |
| `airport` | string | canonical key | ✓ | |
| `category` | string | `domestic`/`international` | ✓ | |
| `passengers` | int | persons | | |

## Layer 4 — `carrier_monthly.csv` (airline operating stats)

Airline-level monthly stats. Airlines **link, not collapse** — a merged brand
keeps its own series (`succeeded_by` in `mappings.yaml`). **v1.0.**

| column | type | unit | key | notes |
|---|---|---|---|---|
| `airline` | string | canonical name | ✓ | spelling canonicalized only |
| `service_type` | string | enum | ✓ | `scheduled_domestic`, `nonscheduled_domestic`, `scheduled_international`, `nonscheduled_international` |
| `year` | int | calendar year | ✓ | |
| `month` | int | 1–12 | ✓ | |
| `aircraft_km` | float | km | | |
| `passengers` | int | persons | | |
| `passenger_km` | float | passenger-km (RPK) | | revenue passenger kilometres |
| `seat_km` | float | seat-km (ASK) | | available seat kilometres |
| `freight_tonnes` | float | tonnes | | |
| `mail_tonnes` | float | tonnes | | |
| `total_tonne_km` | float | tonne-km | | |
| `available_tonne_km` | float | tonne-km | | |
| `passenger_load_factor` | float | percent (0–100) | | |
| `weight_load_factor` | float | percent (0–100) | | DGCA source has rare >100 outliers; surfaced as advisory |

Key: one row per `(airline, service_type, year, month)`. Aggregate "Total" rows
dropped. Source: DGCA domestic carrier workbooks.

---

## Not in the data (by design)

- **`tier`** — not published. The metro/tier bands are a presentation aid (chart
  colours only), not an official classification; see METHODOLOGY. They appear in
  no published CSV.
- **`category` on Layer 1** — constant (`domestic`) once the cadence is split.
