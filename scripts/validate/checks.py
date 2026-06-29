"""Mechanical validation checks over the published canonical tables.

Each check returns a list of :class:`Finding`. Severity:
  - ``BLOCKING``  — a structural invariant; a failure should red CI.
  - ``TRIPWIRE``  — true by construction; only catches a future refactor that
                    breaks it (honestly labelled, not a correctness proof).
  - ``ADVISORY``  — visibility only, never blocks.

The headline check is the month-grain overlap-classification gate (``overlap.py``):
it refuses to silently sum two concurrent source labels into one airport unless a
human has declared the merge.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

from metrics import CONSERVATION_RATIO_BAND, SCHEDULED_DOMESTIC

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
    per = monthly.groupby(["year", "month"]).agg(
        dep=("departures", "sum"), arr=("arrivals", "sum")
    )
    broken = per[per["dep"] != per["arr"]]
    if len(broken):
        return [_fail("conservation.tripwire", "TRIPWIRE",
                      f"{len(broken)} month(s) where sum(departures) != sum(arrivals) "
                      "— a refactor broke the symmetric endpoint split")]
    return [_ok("conservation.tripwire", "TRIPWIRE",
               "per month sum(departures) == sum(arrivals) "
               "(true by construction; tripwire only)")]


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
    neg_cols = [c for c in CARRIER_METRICS if c in carrier.columns and (carrier[c] < 0).any()]
    if neg_cols:
        out.append(_warn("carrier.negative_metrics",
                         f"negative values in carrier metrics: {neg_cols}"))
    if len([f for f in out if f.status != "pass"]) == 0:
        out.append(_ok("carrier.value_domain", "ADVISORY",
                       "load factors in 0-100, metrics non-negative"))
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
    (notably 2017) diverge a few percent — a ±10% band tolerates that without
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
