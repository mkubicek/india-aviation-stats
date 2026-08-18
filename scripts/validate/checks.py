"""Mechanical validation checks over the published canonical tables.

Each check returns a list of :class:`Finding`. Severity:
  - ``BLOCKING``  - a structural invariant; a failure should red CI.
  - ``TRIPWIRE``  - true by construction; only catches a future refactor that
                    breaks it (honestly labelled, not a correctness proof).
  - ``ADVISORY``  - visibility only, never blocks.

The headline check is the month-grain overlap-classification gate (``overlap.py``):
it refuses to silently sum two concurrent source labels into one airport unless a
human has declared the merge.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from metrics import CARRIER_DECIMALS, CONSERVATION_RATIO_BAND, SCHEDULED_DOMESTIC

# Documented per-table schemas (column -> dtype kind). Backs the data dictionary.
EXPECTED_SCHEMAS = {
    "airport_monthly": {
        "year": "int", "month": "int", "airport": "str",
        "passengers": "int", "departures": "int", "arrivals": "int",
    },
    "airport_international_quarterly": {
        "year": "int", "quarter": "int", "airport": "str",
        "passengers": "int", "departures": "int", "arrivals": "int",
    },
    "airport_yearly": {
        "year": "int", "airport": "str", "category": "str", "passengers": "int",
    },
    "domestic_route_monthly": {
        "year": "int", "month": "int", "origin": "str", "destination": "str",
        "passengers": "int",
    },
}


@dataclass(frozen=True)
class Finding:
    check: str
    status: str       # "pass" | "fail" | "warn"
    severity: str     # "BLOCKING" | "TRIPWIRE" | "ADVISORY"
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def _ok(check, severity, message) -> Finding:
    return Finding(check, "pass", severity, message)


def _fail(check, severity, message) -> Finding:
    return Finding(check, "fail", severity, message)


def _warn(check, message) -> Finding:
    return Finding(check, "warn", "ADVISORY", message)


# ── BLOCKING: cadence integrity ──────────────────────────────


def check_cadence(monthly: pd.DataFrame, quarterly: pd.DataFrame | None) -> list[Finding]:
    out = []
    dup = int(monthly.duplicated(["year", "month", "airport"]).sum())
    if dup:
        out.append(_fail("cadence.layer1_unique", "BLOCKING",
                         f"{dup} duplicate (airport, year, month) row(s) in domestic monthly"))
    else:
        out.append(_ok("cadence.layer1_unique", "BLOCKING",
                       "domestic monthly: one row per (airport, year, month)"))
    if "quarter" in monthly.columns:
        out.append(_fail("cadence.layer1_no_quarter", "BLOCKING",
                         "the domestic-monthly table must not carry a quarter column"))

    if quarterly is not None and not quarterly.empty:
        dupq = int(quarterly.duplicated(["year", "quarter", "airport"]).sum())
        if dupq:
            out.append(_fail("cadence.layer2_unique", "BLOCKING",
                             f"{dupq} duplicate (airport, year, quarter) row(s) in international quarterly"))
        else:
            out.append(_ok("cadence.layer2_unique", "BLOCKING",
                           "international quarterly: one row per (airport, year, quarter)"))
        bad_q = sorted(set(quarterly["quarter"]) - {1, 2, 3, 4})
        if bad_q:
            out.append(_fail("cadence.layer2_quarter_domain", "BLOCKING",
                             f"quarterly table quarter out of 1..4: {bad_q}"))
        else:
            out.append(_ok("cadence.layer2_quarter_domain", "BLOCKING",
                           "international quarterly: quarter in 1..4"))
    return out


# ── BLOCKING: definitional invariants ────────────────────────


def check_definitional(df: pd.DataFrame, layer: str) -> list[Finding]:
    out = []
    bad = df[df["passengers"] != df["departures"] + df["arrivals"]]
    if len(bad):
        out.append(_fail(f"definitional.sum.{layer}", "BLOCKING",
                         f"{len(bad)} row(s) where passengers != departures + arrivals"))
    else:
        out.append(_ok(f"definitional.sum.{layer}", "BLOCKING",
                       f"{layer}: passengers == departures + arrivals"))

    neg = df[(df[["passengers", "departures", "arrivals"]] < 0).any(axis=1)]
    if len(neg):
        out.append(_fail(f"definitional.nonneg.{layer}", "BLOCKING",
                         f"{len(neg)} row(s) with a negative passenger value"))
    else:
        out.append(_ok(f"definitional.nonneg.{layer}", "BLOCKING",
                       f"{layer}: all passenger values non-negative"))

    non_int = [c for c in ("passengers", "departures", "arrivals")
               if c in df.columns and not pd.api.types.is_integer_dtype(df[c])]
    if non_int:
        out.append(_fail(f"definitional.int.{layer}", "BLOCKING",
                         f"{layer}: non-integer passenger columns: {non_int}"))
    else:
        out.append(_ok(f"definitional.int.{layer}", "BLOCKING",
                       f"{layer}: passenger columns are integers"))
    return out


# ── BLOCKING: schema conformance ─────────────────────────────


def _dtype_kind(series: pd.Series) -> str:
    if pd.api.types.is_integer_dtype(series):
        return "int"
    if pd.api.types.is_float_dtype(series):
        return "float"
    return "str"


def check_schema(layers: dict[str, pd.DataFrame], metadata: dict) -> list[Finding]:
    out = []
    meta_tables = metadata.get("tables", {})
    for name, expected in EXPECTED_SCHEMAS.items():
        df = layers.get(name)
        if df is None:
            out.append(_fail(f"schema.{name}.present", "BLOCKING", f"missing table {name}"))
            continue
        if list(df.columns) != list(expected):
            out.append(_fail(f"schema.{name}.columns", "BLOCKING",
                             f"{name} columns {list(df.columns)} != expected {list(expected)}"))
            continue
        mism = [c for c, kind in expected.items() if _dtype_kind(df[c]) != kind]
        if mism:
            out.append(_fail(f"schema.{name}.dtypes", "BLOCKING",
                             f"{name} dtype mismatch on {mism}"))
        elif name not in meta_tables or "schema_version" not in meta_tables.get(name, {}):
            out.append(_fail(f"schema.{name}.version", "BLOCKING",
                             f"{name} missing schema_version in metadata.json"))
        else:
            out.append(_ok(f"schema.{name}", "BLOCKING",
                           f"{name}: schema v{meta_tables[name]['schema_version']} conforms"))
    return out


# ── TRIPWIRE: conservation (true by construction) ────────────


def check_conservation_tripwire(monthly: pd.DataFrame) -> list[Finding]:
    """Symmetry holds only when BOTH endpoints of every source pair resolve.

    Named a tripwire because the endpoint split is symmetric by construction,
    but it has a second, likelier cause: an unmapped city label attributes one
    end of its pairs and drops the other, so the month goes asymmetric by the
    pair's directional imbalance. That is how DAMAN (166 pax, 6 imbalance)
    surfaced in July 2026. Check the unmapped-label advisory and clean.py's
    unmapped warning before suspecting a refactor. Note the converse: an
    unmapped label whose directions happen to balance leaves this check green.
    """
    per = monthly.groupby(["year", "month"]).agg(
        dep=("departures", "sum"), arr=("arrivals", "sum")
    )
    broken = per[per["dep"] != per["arr"]]
    if len(broken):
        months = ", ".join(f"{int(y)}-{int(m):02d}" for y, m in broken.index[:3])
        return [_fail("conservation.tripwire", "TRIPWIRE",
                      f"{len(broken)} month(s) where sum(departures) != sum(arrivals) "
                      f"({months}) -  an unmapped city label dropping one endpoint, "
                      "or a refactor that broke the symmetric endpoint split")]
    return [_ok("conservation.tripwire", "TRIPWIRE",
               "per month sum(departures) == sum(arrivals) "
               "(symmetric by construction once every label resolves)")]


# ── carrier monthly: own contract ────────────────────────────


CARRIER_KEY = ["airline", "service_type", "year", "month"]
CARRIER_METRICS = ["aircraft_km", "passengers", "passenger_km", "seat_km",
                   "freight_tonnes", "mail_tonnes", "total_tonne_km", "available_tonne_km"]


def check_carrier(carrier: pd.DataFrame) -> list[Finding]:
    out = []
    dup = int(carrier.duplicated(CARRIER_KEY).sum())
    if dup:
        out.append(_fail("carrier.unique", "BLOCKING",
                         f"{dup} duplicate (airline, service_type, year, month) row(s)"))
    else:
        out.append(_ok("carrier.unique", "BLOCKING",
                       "carrier monthly: one row per (airline, service_type, year, month)"))

    for lf in ("passenger_load_factor", "weight_load_factor"):
        if lf in carrier.columns:
            bad = carrier[(carrier[lf] < 0) | (carrier[lf] > 100)]
            if len(bad):
                out.append(_warn(f"carrier.load_factor.{lf}",
                                 f"{len(bad)} row(s) with {lf} outside 0-100"))

    # Published precision is a contract (metrics.CARRIER_DECIMALS). One workbook
    # leaving a column blank flips the upstream aggregate to object dtype, which
    # disables its float formatting and silently restates published values. The
    # unit test reads the committed file, which in CI is last month's; this runs
    # on the table about to be committed.
    for column in carrier.select_dtypes("float").columns:
        values = carrier[column].dropna()
        loose = values[values.round(CARRIER_DECIMALS) != values]
        if len(loose):
            out.append(_fail(f"carrier.precision.{column}", "BLOCKING",
                             f"{len(loose)} row(s) with {column} beyond "
                             f"{CARRIER_DECIMALS} decimals (e.g. {loose.iloc[0]!r}); "
                             "an upstream dtype change is restating published values"))
    neg_cols = [c for c in CARRIER_METRICS if c in carrier.columns and (carrier[c] < 0).any()]
    if neg_cols:
        out.append(_warn("carrier.negative_metrics",
                         f"negative values in carrier metrics: {neg_cols}"))
    if len([f for f in out if f.status != "pass"]) == 0:
        out.append(_ok("carrier.value_domain", "ADVISORY",
                       f"load factors in 0-100, metrics non-negative, floats at "
                       f"{CARRIER_DECIMALS} decimals"))
    return out


# ── ADVISORY: passenger metric semantics ─────────────────────


def check_metric_semantics(
    monthly: pd.DataFrame, carrier: pd.DataFrame | None
) -> list[Finding]:
    """National airport throughput ≈ 2× scheduled-domestic passengers carried.

    Each domestic journey is one carrier passenger and two airport endpoints
    (a departure + an arrival), so summing the airport layer nationally
    double-counts journeys. This advisory surfaces that conservation relationship
    and guards against ever reusing airport endpoint throughput as a national
    "passengers carried" figure. It is intentionally advisory, not blocking: the
    DGCA city-pair and carrier workbooks are independent, so a few historic months
    (notably 2017) diverge a few percent - a ±10% band tolerates that without
    redding CI on a benign data revision, while still flagging a real layer break.
    """
    check = "semantics.domestic_airport_throughput_vs_carrier"
    if carrier is None or "service_type" not in carrier.columns:
        return []

    throughput = monthly.groupby(["year", "month"])["passengers"].sum()
    sched = carrier[carrier["service_type"] == SCHEDULED_DOMESTIC]
    carried = sched.groupby(["year", "month"])["passengers"].sum()
    common = throughput.index.intersection(carried.index)
    if len(common) == 0:
        return [_warn(check, "no overlapping months between airport and carrier layers")]

    t = throughput.loc[common]
    c = carried.loc[common]
    # carried == 0 with material throughput is itself a conservation break (no
    # domestic passengers carried, yet airport endpoints report movement); flag
    # it rather than dropping it. Only carried > 0 months get a finite ratio.
    zero_carried = sorted(k for k in common if c.loc[k] == 0 and t.loc[k] > 0)
    nonzero = [k for k in common if c.loc[k] > 0]
    if not nonzero:
        return [_warn(check, "no overlapping months with non-zero carrier passengers")]

    low, high = CONSERVATION_RATIO_BAND
    ratio = (t[nonzero] / c[nonzero]).sort_index()
    out_of_band = ratio[(ratio < low) | (ratio > high)]
    worst = float((ratio - 2).abs().max())
    breaks = sorted(out_of_band.index.tolist()) + zero_carried
    if not breaks:
        return [_ok(check, "ADVISORY",
                    f"domestic airport throughput == ~2x scheduled-domestic passengers "
                    f"carried for all {len(nonzero)} overlapping month(s) "
                    f"(max deviation {worst:.3f}); endpoint throughput is not "
                    "national passengers carried")]
    sample = ", ".join(f"{int(y)}-{int(m):02d}" for (y, m) in breaks[:6])
    return [_warn(check,
                  f"{len(breaks)} overlapping month(s) where airport throughput is not "
                  f"~2x scheduled-domestic passengers carried: {sample}"
                  + ("..." if len(breaks) > 6 else ""))]


# ── ADVISORY: coverage continuity ────────────────────────────


def check_coverage(monthly: pd.DataFrame, quarterly: pd.DataFrame | None) -> list[Finding]:
    out = []
    periods = sorted(
        pd.Period(year=int(y), month=int(m), freq="M")
        for y, m in monthly[["year", "month"]].drop_duplicates().itertuples(index=False)
    )
    if periods:
        full = pd.period_range(periods[0], periods[-1], freq="M")
        missing = [str(p) for p in full if p not in set(periods)]
        if missing:
            out.append(_warn("coverage.domestic_months",
                             f"missing {len(missing)} domestic month(s): {', '.join(missing[:6])}"
                             + ("..." if len(missing) > 6 else "")))
    if quarterly is not None and not quarterly.empty:
        yq = set((int(y), int(q)) for y, q in
                 quarterly[["year", "quarter"]].drop_duplicates().itertuples(index=False))
        years = range(min(y for y, _ in yq), max(y for y, _ in yq) + 1)
        full = [(y, q) for y in years for q in (1, 2, 3, 4)]
        first, last = min(yq), max(yq)
        gaps = [f"{y}Q{q}" for (y, q) in full if first <= (y, q) <= last and (y, q) not in yq]
        if gaps:
            out.append(_warn("coverage.intl_quarters",
                             f"missing {len(gaps)} international quarter(s): {', '.join(gaps[:6])}"
                             + ("..." if len(gaps) > 6 else "")))
    return out


# -- route table invariants ----------------------------------


def check_route_source(raw_domestic_path) -> list[Finding]:
    """Advisory visibility on duplicate city-pair rows in the SOURCE workbook.

    DGCA sometimes splits one pair across two rows in the same month (observed
    2015-09 and 2025-12). ``clean.py`` SUMS them, which the monthly totals
    support: the summed month tracks its neighbours while a deduplicated one
    falls well below. This check exists so a future change in that pattern is
    visible instead of silently doubling or halving a month.
    """
    raw = pd.read_csv(raw_domestic_path)
    needed = {"Year", "Month", "City1", "City2"}
    if not needed <= set(raw.columns):
        return [_warn("routes.source_duplicates", "source city-pair columns absent")]
    lo = raw[["City1", "City2"]].min(axis=1)
    hi = raw[["City1", "City2"]].max(axis=1)
    keyed = raw.assign(_lo=lo, _hi=hi)
    dup_mask = keyed.duplicated(["Year", "Month", "_lo", "_hi"], keep=False)
    dup = keyed[dup_mask]
    if dup.empty:
        return [_ok("routes.source_duplicates", "ADVISORY",
                    "no duplicate city-pair rows in the source month-pairs")]
    months = sorted({(int(y), int(m)) for y, m in zip(dup["Year"], dup["Month"])})
    shown = ", ".join(f"{y}-{m:02d}" for y, m in months[:4])
    return [_warn("routes.source_duplicates",
                  f"{len(dup)} duplicate city-pair row(s) across {len(months)} month(s) "
                  f"({shown}); clean.py sums them as partial figures")]


def check_routes(routes: pd.DataFrame, monthly: pd.DataFrame, mappings: dict) -> list[Finding]:
    """Structural invariants of domestic_route_monthly (schema v1.0).

    Severity is honest about what each can catch. Key uniqueness, distinct
    endpoints and canonical endpoints are TRIPWIRE: they hold by construction
    of ``build_domestic_routes`` and only fail if that function is refactored
    wrongly. Endpoint containment is BLOCKING and is a REAL check: the route
    and airport tables are built by two independent attribution rules, so a
    bug in either (double counting, dropped traffic) breaks it.
    """
    out: list[Finding] = []
    if routes.empty:
        return [_fail("routes.present", "BLOCKING",
                      "domestic_route_monthly.csv has no rows")]
    key = ["year", "month", "origin", "destination"]

    dups = int(routes.duplicated(key).sum())
    out.append((_fail if dups else _ok)(
        "routes.key_unique", "TRIPWIRE",
        f"{dups} duplicate (year, month, origin, destination) key(s)"
        if dups else f"{len(routes):,} rows with a unique route-month key"))

    self_pairs = int((routes["origin"] == routes["destination"]).sum())
    out.append((_fail if self_pairs else _ok)(
        "routes.distinct_endpoints", "TRIPWIRE",
        f"{self_pairs} self-pair row(s)" if self_pairs
        else "all rows have distinct origin/destination"))

    known = set((mappings.get("airports") or {}).keys())
    endpoints = set(routes["origin"]) | set(routes["destination"])
    unknown = sorted(endpoints - known)
    out.append((_fail if unknown else _ok)(
        "routes.canonical_endpoints", "TRIPWIRE",
        f"non-canonical endpoint(s): {', '.join(unknown[:5])}" if unknown
        else f"{len(endpoints)} endpoints all canonical mappings.yaml airports"))

    negative = int((routes["passengers"] < 0).sum())
    non_int = 0 if routes["passengers"].dtype.kind == "i" else int(
        (routes["passengers"] % 1 != 0).sum())
    bad_vals = negative + non_int
    out.append((_fail if bad_vals else _ok)(
        "routes.nonneg_int", "BLOCKING",
        f"{negative} negative / {non_int} non-integer passenger value(s)"
        if bad_vals else "passengers are non-negative integers"))

    # Endpoint containment (REAL): airport_monthly attributes every resolved
    # endpoint; the route table additionally requires the counterpart to
    # resolve and differ. So route endpoint sums must never EXCEED airport
    # endpoint sums, for any airport-month. Exceeding means double counting;
    # a shortfall is expected and reported (unmapped counterparts, self-pairs).
    dep = routes.groupby(["year", "month", "origin"])["passengers"].sum()
    arr = routes.groupby(["year", "month", "destination"])["passengers"].sum()
    dep.index.names = arr.index.names = ["year", "month", "airport"]
    m = monthly.set_index(["year", "month", "airport"])[["departures", "arrivals"]]
    joined = m.join(dep.rename("route_dep"), how="outer").join(
        arr.rename("route_arr"), how="outer").fillna(0)
    over_dep = int((joined["route_dep"] > joined["departures"]).sum())
    over_arr = int((joined["route_arr"] > joined["arrivals"]).sum())
    over = over_dep + over_arr
    gap = int((joined["departures"] - joined["route_dep"]).clip(lower=0).sum()
              + (joined["arrivals"] - joined["route_arr"]).clip(lower=0).sum())
    out.append((_fail if over else _ok)(
        "routes.endpoint_containment", "BLOCKING",
        f"{over_dep} departure / {over_arr} arrival airport-month(s) where route "
        "endpoints EXCEED airport endpoints (double counting)" if over else
        f"route endpoints within airport endpoints across {len(joined):,} "
        f"airport-months ({gap:,} pax attributed to airports but not routable)"))

    # Advisory: substantial route history vanishing while both endpoints stay
    # active. Skipped when the latest month looks partially published, which
    # would otherwise flood this with false positives.
    latest = routes.sort_values(["year", "month"]).iloc[-1]
    latest_y, latest_m = int(latest["year"]), int(latest["month"])
    latest_ord = latest_y * 12 + latest_m
    rows_by_month = routes.groupby(["year", "month"]).size()
    prior_counts = rows_by_month[
        [(y, mm) for (y, mm) in rows_by_month.index
         if latest_ord - 12 <= y * 12 + mm < latest_ord]
    ]
    median_prior = float(prior_counts.median()) if len(prior_counts) else 0.0
    latest_rows = int(rows_by_month.loc[(latest_y, latest_m)])
    if median_prior and latest_rows < 0.7 * median_prior:
        out.append(_warn("routes.history_disappearance",
                         f"{latest_y}-{latest_m:02d} looks partially published "
                         f"({latest_rows:,} route rows vs a {median_prior:,.0f} prior-12M "
                         "median); disappearance check skipped"))
        return out

    latest_rows_df = routes[(routes["year"] == latest_y) & (routes["month"] == latest_m)]
    latest_pairs = set(zip(latest_rows_df["origin"], latest_rows_df["destination"]))
    active = set(monthly.loc[(monthly["year"] == latest_y)
                             & (monthly["month"] == latest_m), "airport"])
    ordinals = routes["year"] * 12 + routes["month"]
    prior12 = routes[(ordinals >= latest_ord - 12) & (ordinals < latest_ord)]
    hist = prior12.groupby(["origin", "destination"]).agg(
        months=("passengers", "size"), pax=("passengers", "sum"))
    big = hist[(hist["months"] >= 9) & (hist["pax"] >= 100_000)]
    gone = [p for p in big.index
            if p not in latest_pairs and p[0] in active and p[1] in active]
    if gone:
        out.append(_warn("routes.history_disappearance",
                         f"{len(gone)} substantial route(s) absent in {latest_y}-{latest_m:02d} "
                         f"despite active endpoints (e.g. {gone[0][0]}-{gone[0][1]})"))
    else:
        out.append(_ok("routes.history_disappearance", "ADVISORY",
                       "no substantial route history vanished in the latest month"))
    return out
