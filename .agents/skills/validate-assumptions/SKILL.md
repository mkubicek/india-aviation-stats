---
name: validate-assumptions
description: Re-test every cleanup assumption in assumptions/ against the current data and report which still hold. Use to check the dataset's cleanup is still correct after a DGCA refresh or a mappings.yaml edit. Includes a --triage mode that drafts cited research skeletons for labels the gate detects but can't classify.
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
are computed output - never written back into the static files):

- `data/processed/DATA_QUALITY.md` - the human-readable verdict table.
- `data/processed/validation_report.json` - `assumptions` + `reverse_gate`.

## Read the verdicts

| verdict | meaning | action |
|---|---|---|
| `HOLDS` | the assumption still matches the data | none |
| `TRIGGERED` | the **data drifted** from the assumption (**BLOCKING**) - note this tests the data, not the world | the cleanup may now be wrong - re-research (see Triage) and update `mappings.yaml` + the file, or the dataset is shipping a bad merge |
| `STALE` | a `recheck_by` date on the file has passed (no file sets one today, so this is latent) | send it through Triage to re-verify the cited evidence |
| `ORPHANED` | the quirk vanished from the data | the file can likely be retired |

These tests are **internal**: they re-check the data against itself (key presence,
month-disjointness, declared merges), not the real-world claim the file is about.
That is by design - the gate must stay deterministic. Re-verifying the *world* (is
this label really that airport?) is Triage's job, below.

**Reverse gate:** the run also fails (BLOCKING) if the mechanical checks surface
an anomaly - a concurrent same-airport merge, or a high-volume unmapped label  - 
that has **no** covering `assumptions/` file. That means a new quirk appeared and
must be either cleaned or documented before the data ships. Nothing weird stays
silent.

## Triage - research what the gate can't classify

The gate is **data-only and deterministic**: it can *detect* an anomaly (a new
label colliding onto an existing airport; a high-volume label that maps to
nothing) but it cannot *decide* whether two labels are one physical airport or
two - that needs world knowledge. Triage is the on-demand, **advisory** bridge.

```bash
PYTHONPATH=scripts uv run python -m validate --triage
```

It reuses the gate's detection to emit, per unclassified label, a research
question and a ready-to-fill OKF skeleton (`data/processed/triage_queue.json`,
gitignored). It makes **no** web or LLM calls itself - that part is your job:

1. For each item, **search the web for counter-evidence** to the obvious reading
   - the IATA code, whether the label is a new airport, a rename/spelling of an
   existing canonical, or a distinct airport sharing a code. Try to *refute* the
   first guess before accepting it.
2. Fill the skeleton's Evidence (1–2 primary citations) and Decision; save it as
   `assumptions/<id>.md` (rename the id to the real IATA code).
3. Get a **human to confirm** - the draft is tagged `NEEDS-HUMAN-REVIEW`; nothing
   is auto-applied.
4. Only then edit `mappings.yaml`, and re-run the gate until it is green.

Triage never blocks (exit 0); the gate stays the pass/fail. It just turns a red
reverse gate into a concrete, citable research task.

## When to use

- After a monthly DGCA refresh (a new label may overlap an existing airport).
- After editing `mappings.yaml` (to confirm no decision was invalidated).
- When the gate reds on an **undocumented quirk** or flags a high-volume unmapped
  label - run `--triage` to turn it into a citable research worklist.
- Before tagging a release.

A non-zero exit means a BLOCKING `TRIGGERED` or an undocumented quirk - do not
publish until it is resolved.
