---
name: validate-assumptions
description: Re-test every cleanup assumption in assumptions/ against the current data and report which still hold. Use to check the dataset's cleanup is still correct after a DGCA refresh or a mappings.yaml edit.
---

# validate-assumptions

This repo's cleanup is **falsifiable**: every non-trivial decision (Goa's
two-airport split, the Kalaburagi/Kolhapur IATA fix, the Ludhiana airport flip,
the Cochin/Kochi concurrent merge, the Allahabad→Prayagraj rename) is a static
Open Knowledge Format file in `assumptions/`, each naming a falsification test.
This skill re-runs those tests against the current data.

Harness-agnostic: it is a thin wrapper over the project's own validator. Run it,
read the verdict table, act on anything that is not `HOLDS`.

## Run

```bash
PYTHONPATH=scripts uv run python -m validate --assumptions
```

This re-tests each `assumptions/<id>.md` and regenerates two artifacts (verdicts
are computed output — never written back into the static files):

- `data/processed/DATA_QUALITY.md` — the human-readable verdict table.
- `data/processed/validation_report.json` — `assumptions` + `reverse_gate`.

## Read the verdicts

| verdict | meaning | action |
|---|---|---|
| `HOLDS` | the assumption still matches the data | none |
| `TRIGGERED` | new evidence contradicts it (**BLOCKING**) | the cleanup may now be wrong — re-research and update `mappings.yaml` + the file, or the dataset is shipping a bad merge |
| `STALE` | the recheck date passed | re-verify the cited evidence |
| `ORPHANED` | the quirk vanished from the data | the file can likely be retired |

**Reverse gate:** the run also fails (BLOCKING) if the mechanical checks surface
an anomaly — a concurrent same-airport merge, or a high-volume unmapped label —
that has **no** covering `assumptions/` file. That means a new quirk appeared and
must be either cleaned or documented before the data ships. Nothing weird stays
silent.

## When to use

- After a monthly DGCA refresh (a new label may overlap an existing airport).
- After editing `mappings.yaml` (to confirm no decision was invalidated).
- Before tagging a release.

A non-zero exit means a BLOCKING `TRIGGERED` or an undocumented quirk — do not
publish until it is resolved.
