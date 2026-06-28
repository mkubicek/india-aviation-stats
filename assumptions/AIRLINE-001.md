---
type: cleanup-assumption
title: Airline mergers are linked, not collapsed — each brand keeps its own series
category: airline-identity
falsification: airlines-linked-not-collapsed
covers: []
params:
  airlines: [Vistara, Air India, AirAsia India, AIX Connect, Air India Express]
tags: [airline, carrier, link-not-collapse]
---
# Observation

Indian carriers rename and merge: Vistara merged into Air India (2024-25), and
AirAsia India → AIX Connect → Air India Express. Unlike airports (one physical
facility = one entity), an airline brand is a distinct business an analyst may
want to measure on its own — Vistara's standalone history is meaningful even
after the merger.

# Interpretation

Collapsing Vistara into Air India (or AirAsia India into Air India Express) would
destroy exactly the series users come to measure. Airlines are therefore treated
differently from airports: spelling/casing is canonicalized (Airheritage → Air
Heritage), but brand/legal mergers are **linked, not collapsed**.

# Decision

Each airline keeps its own entity in Layer 4 (`carrier_monthly.csv`); the merger
relationship is recorded as `succeeded_by` in `mappings.yaml: airlines`. No
airline brand is merged into its successor.

# Evidence

- Vistara–Air India merger completed Nov 2024 —
  https://en.wikipedia.org/wiki/Vistara
- AirAsia India → AIX Connect → Air India Express —
  https://en.wikipedia.org/wiki/Air_India_Express

# Falsification

`airlines-linked-not-collapsed`: re-open if any of these brands disappears from
`carrier_monthly` (i.e. was collapsed into its successor rather than kept as a
distinct, linked entity).
