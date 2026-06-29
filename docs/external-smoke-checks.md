# External smoke checks

These checks are **not** canonical source ingestion. They are independent scale
checks to detect obvious metric or processing errors. Canonical data remains the
DGCA source data ingested by the pipeline; press/media reports are never used as a
data source (see [METHODOLOGY.md](../METHODOLOGY.md)).

Each check states the *comparable* metric — not just a similar-looking number —
because the same word ("passengers") spans both airport throughput and passengers
carried in this repo.

| Check | Repo value | External reference | Verdict |
|---|---:|---|---|
| April 2026 scheduled-domestic passengers carried | 13,814,816 (~1.381 crore) from `carrier_monthly.csv` | Public report quoting DGCA: April 2026 domestic traffic just over 1.38 crore | Pass |
| May 2026 domestic airport throughput vs passengers carried | 30,779,402 airport throughput = 2 × 15,389,701 carrier passengers carried | Internal cross-layer conservation (`semantics.domestic_airport_throughput_vs_carrier`) | Pass |
| International latest 4Q Indian-gateway throughput | 77,740,037 | Needs periodic DGCA/AAI cross-check when an official comparable table is available | Pending |

The first two checks are what motivated moving the national domestic dashboard
headline from the airport layer (endpoint throughput, ~2× journeys) to the carrier
layer (passengers carried, once per journey): the airport-derived May 2026 figure
of 30,779,402 was exactly twice the carrier figure and roughly twice the
DGCA-reported domestic scale.

## References

- DGCA portal: <https://www.dgca.gov.in/digigov-portal/>
- Times of India, April 2026 DGCA domestic traffic report:
  <https://timesofindia.indiatimes.com/business/india-business/indias-domestic-air-traffic-falls-4-2-in-april-amid-weak-demand-and-rising-costs/articleshow/131423895.cms>
