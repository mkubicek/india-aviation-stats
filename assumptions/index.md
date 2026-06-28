# Assumptions index

Routing table for the cleanup knowledge base (OKF bundle). Verdicts are
recomputed by `validate --assumptions` and shown in `data/processed/DATA_QUALITY.md`;
they are not written back into these files.

| id | title | category | → file |
| --- | --- | --- | --- |
| COK-001 | COCHIN and KOCHI are one airport (COK) — a declared concurrent same-airport merge | deduplication | [COK-001.md](COK-001.md) |
| GOA-001 | Goa is two airports — Dabolim (GOI) and Mopa (GOX) — and the DGCA "GOI" label is Mopa from 2023 | deduplication | [GOA-001.md](GOA-001.md) |
| IXD-001 | Allahabad and Prayagraj are one airport (IXD) — a clean disjoint rename | rename | [IXD-001.md](IXD-001.md) |
| KLH-001 | Kalaburagi is GBI, not KLH — KLH is Kolhapur (the source/table mixed the IATA codes) | deduplication | [KLH-001.md](KLH-001.md) |
| LUH-001 | The "LUDHIANA" label is two airports — Sahnewal (LUH) through 2025, Halwara (HWR) from 2026 | deduplication | [LUH-001.md](LUH-001.md) |
