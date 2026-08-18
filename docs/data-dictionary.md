# Data dictionary

Every published file is a **single-grain table**: one airport (or airline) is
one entity, and one file has one time grain. Schema versions live in
`data/processed/metadata.json` (`tables.<name>.schema_version`); a breaking
change bumps the version and is recorded in the `schema_changelog`.

`passengers == departures + arrivals` on every airport row, and all passenger
counts are whole-person **integers**. `airport` is a canonical key - an IATA code
when one exists, else a stable `name:<slug>` - never a raw source label.

> **Passenger semantics differ by table.** The same column name, `passengers`,
> means **airport endpoint throughput** in the airport tables (each domestic
> journey is counted twice - once as a departure at the origin, once as an arrival
> at the destination) and **passengers carried** in `carrier_monthly.csv` (each
> journey counted once, by the operating airline). For national domestic demand,
> use `carrier_monthly.csv` filtered to `service_type == scheduled_domestic` - not
> a national sum of the airport layer, which double-counts journeys. See
> [METHODOLOGY.md → Passenger metric semantics](../METHODOLOGY.md#passenger-metric-semantics).

---

## `domestic_route_monthly.csv` - directed domestic routes (schema v1.0)

One row per `(year, month, origin, destination)`: directed monthly route
passengers between two Indian airports. Each normalized DGCA city-pair row
splits into `City1 -> City2 = PaxToCity2` and `City2 -> City1 = PaxFromCity2`
(explicit zero directions kept); both endpoints resolve through the
validity-window resolver, and self-pairs are dropped.

| column | type | meaning |
|---|---|---|
| `year` | int | calendar year |
| `month` | int | 1-12 |
| `origin` | str | IATA code of the origin airport (canonical `mappings.yaml` key) |
| `destination` | str | IATA code of the destination airport |
| `passengers` | int | passengers flown origin -> destination that month (segment count) |

`airport_monthly.csv` is derived from these rows (origin side = departures,
destination side = arrivals), so endpoint conservation between the two tables
is exact and enforced by a blocking validation check. Segment semantics: a
connecting itinerary appears once per flown segment; this is not true
origin-destination demand.

## `airport_monthly.csv` - domestic monthly (canonical core)

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

`passengers` here means **airport passenger movements / endpoint throughput**  - 
it equals `departures + arrivals` at the airport. Because each domestic city-pair
passenger is attributed to *both* route endpoints, summing this column across all
airports gives domestic **airport throughput** (~2× journeys), **not** domestic
passengers carried. For national domestic passengers carried, use
`carrier_monthly.csv` with `service_type == scheduled_domestic`.

## `airport_international_quarterly.csv` - international quarterly

International, quarterly - the real cadence, no midpoint-month hack. **v1.0.**

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

`passengers` means **Indian international gateway endpoint traffic**. Foreign
counterpart cities are dropped, so the table represents Indian airport gateway
throughput - not foreign-airport totals and not airline-carried passengers.

## `airport_yearly.csv` (derived convenience view)

Whole-calendar-year totals, **derived** from `airport_monthly.csv` and
`airport_international_quarterly.csv` (domestic years need all 12 months;
international years all 4 quarters). **v2.0.**

| column | type | unit | key | notes |
|---|---|---|---|---|
| `year` | int | calendar year | ✓ | complete years only |
| `airport` | string | canonical key | ✓ | |
| `category` | string | `domestic`/`international` | ✓ | |
| `passengers` | int | persons | | |

## `carrier_monthly.csv` - carrier monthly (airline operating stats)

Airline-level monthly stats. Airlines **link, not collapse** - a merged brand
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
dropped. Source: DGCA domestic carrier workbooks. Every float column is published
rounded to **3 decimals** (`metrics.CARRIER_DECIMALS`), so a value never depends on
how a source workbook stored the cell; `passengers` is a whole number.

`passengers` means **passengers carried** by the airline in that month and service
type - each journey counted once. For national scheduled domestic passenger
demand, sum rows where `service_type == scheduled_domestic`; this is the canonical
national domestic-demand metric (the dashboard's domestic headline). Nationally it
is ~½ of summed airport endpoint throughput.

---

## Not in the data (by design)

- **`tier`** - not published. The metro/tier bands are a presentation aid (chart
  colours only), not an official classification; see METHODOLOGY. They appear in
  no published CSV.
- **`category` on airport_monthly** - constant (`domestic`) once the cadence is split.
