# Airport-label cleanup audit

How every DGCA domestic source label that was **not** previously mapped got
resolved to a canonical airport. This is the trace behind the `airports:`
table in `mappings.yaml`; anyone can re-check a row against the cited evidence.

## Method

- **Scope:** 107 domestic source labels with no canonical mapping.
- **Research:** one Sonnet agent per label batch — IATA code, opening date,
  and whether the city has more than one airport (web + the raw CSV).
- **Verification:** every new airport, windowed rename, and multi-airport case
  was re-checked by a second, adversarial Sonnet agent told to refute it.
- **Result:** 92 genuinely new airports, 3 windowed renames, 2 multi-airport
  distinct (Rajkot/Hirasar), 10 spelling aliases, 0 unclear.

## Three issues the verification caught

These are why the dataset cleans up the DGCA mess *without* introducing new
errors of its own:

1. **Kalaburagi filed under Kolhapur's IATA code.** The committed table keyed
   Kalaburagi/Gulbarga airport as `KLH`, but `KLH` is *Kolhapur's* IATA code
   (Kalaburagi is `GBI`). Mapping the unmapped `KOLHAPUR` label naively would
   have merged two distinct airports. Fixed: Kalaburagi moved to `GBI`, a
   correct `KLH` created for Kolhapur. They are now separate series.
2. **Ludhiana is two airports under one label.** `LUDHIANA` means the old
   Sahnewal field (`LUH`, UDAN ops ≤ 2025-09) and, from 2026, the new Halwara
   International (`HWR`, the 2026-05 row jumps ~40×). Split with validity
   windows like Goa, so neither airport is erased.
3. **Purnea has two spellings.** `PURNEA` and `PURNIA AIRPORT` are the same
   airport (`PXN`); mapped together rather than counted as two.

## Validation

- Resolver builds with **zero label conflicts** (overlapping windows refuse to build).
- **0 unmapped labels / 0.000% unmapped passengers** in the domestic series.
- Passenger **conservation is exact**: processed total = 2 × raw (each passenger
  counted at both endpoints), zero leakage.

## Full mapping table

`conf` is the verifier/researcher confidence (0–100). Blank window = all-time;
blank conf = spelling alias of an airport already in the table.

| Source label | → Airport | Window | conf |
| --- | --- | --- | --- |
| `AGATTI ISLAND` | **AGX** Agatti Airport | all-time | 95 |
| `AMBIKAPUR` | **AHA** Maa Mahamaya Airport (Darima Airport) | all-time | 90 |
| `AMBIKAPUR AIRPORT` | **AHA** Maa Mahamaya Airport (Darima Airport) | all-time | 90 |
| `ADAMPUR` | **AIP** Adampur Airport (Shri Guru Ravidass Maharaj Ji Airport) | all-time | 95 |
| `AMRAVATI` | **AVR** Amravati Airport (Belora) | all-time | 88 |
| `AMRAVATI AIRPORT` | **AVR** Amravati Airport (Belora) | all-time | 88 |
| `AYODHYA` | **AYJ** Maharishi Valmiki International Airport Ayodhyadham | all-time | 95 |
| `AYODHYA INTERNATIONAL AIRPORT` | **AYJ** Maharishi Valmiki International Airport Ayodhyadham | all-time | 95 |
| `AZAMGARH AIRPORT` | **AZH** Azamgarh Airport | all-time | 95 |
| `BHUJ` | **BHJ** Bhuj Airport (Rudra Mata Airport) | all-time | 98 |
| `BHAVNAGAR` | **BHU** Bhavnagar Airport | all-time | 95 |
| `BIKANER` | **BKB** Bikaner Airport (Nal) | all-time | 95 |
| `MUMBAI MUMBAI` | **BOM** Chhatrapati Shivaji Maharaj International Airport | 2026-01–… | 98 |
| `BATHINDA` | **BUP** Bathinda Airport (Bhatinda Airport / Bhisiana Air Force Station civil enclave) | all-time | 95 |
| `BHATINDA` | **BUP** Bathinda Airport (Bhatinda Airport / Bhisiana Air Force Station civil enclave) | all-time | 95 |
| `CUDDAPAH` | **CDP** Kadapa Airport | all-time | 97 |
| `CUDDAPAH KADAPA` | **CDP** Kadapa Airport | 2026-01–… | 95 |
| `KADAPA` | **CDP** Kadapa Airport | all-time |  |
| `COOCH BEHAR` | **COH** Cooch Behar Airport | all-time | 96 |
| `CHITRAKOOT AIRPORT` | **CWK** Chitrakoot Airport | all-time | 95 |
| `DARBHANGA` | **DBR** Darbhanga Airport | all-time | 95 |
| `DEHRA DUN` | **DED** Jolly Grant Airport | all-time |  |
| `DHARAMSALA` | **DHM** Gaggal Airport | all-time |  |
| `DATIA AIRPORT` | **DPP** Datia Airport | all-time | 95 |
| `GONDIA` | **GDB** Gondia Airport (Birsi Airport) | all-time | 93 |
| `GONDIA AIRPORT` | **GDB** Gondia Airport (Birsi Airport) | all-time | 96 |
| `GWALIOR` | **GWL** Gwalior Airport (Rajmata Vijayaraje Scindia Terminal) | all-time | 98 |
| `GHAZIABAD` | **HDO** Hindon Airport (Civil Enclave, Hindan Air Force Station) | all-time | 90 |
| `HINDON AIRPORT` | **HDO** Hindon Airport (Civil Enclave, Hindan Air Force Station) | all-time | 97 |
| `HOLLONGI AIRPORT ITANAGAR` | **HGI** Hollongi Airport (Donyi Polo) | all-time |  |
| `KHAJURAHO` | **HJR** Khajuraho Airport | all-time | 95 |
| `ALIGARH AIRPORT` | **HRH** Aligarh Airport | all-time | 95 |
| `HIRASAR RAJKOT` | **HSR** Rajkot International Airport (Hirasar) | all-time | 95 |
| `RAJKOT INTERNATIONAL AIRPORT` | **HSR** Rajkot International Airport (Hirasar) | all-time | 95 |
| `HISAR` | **HSS** Maharaja Agrasen Airport (Hisar) | all-time | 95 |
| `HISSAR` | **HSS** Maharaja Agrasen Airport (Hisar) | all-time | 93 |
| `NASHIK` | **ISK** Nashik Airport (Ozar Airport / Gandhinagar Airport) | 2026-01–… | 95 |
| `NASIK` | **ISK** Nashik Airport (Ozar Airport / Gandhinagar Airport) | all-time | 97 |
| `ALLAHABAD` | **IXD** Prayagraj Airport (formerly Allahabad Airport) | all-time | 95 |
| `ALLAHABAD PRAYAGRAJ` | **IXD** Prayagraj Airport (formerly Allahabad Airport) | 2026-01–… | 95 |
| `PRAYAGRAJ` | **IXD** Prayagraj Airport (formerly Allahabad Airport) | all-time | 95 |
| `MANGALORE MANGALURU` | **IXE** Mangalore International Airport | all-time |  |
| `BELGAUM` | **IXG** Belagavi Airport (Belgaum Airport / Sambra Airport) | all-time | 95 |
| `LILABARI` | **IXI** Lilabari Airport (North Lakhimpur Airport) | all-time | 97 |
| `KESHOD` | **IXK** Keshod Airport | all-time | 95 |
| `PATHANKOT` | **IXP** Pathankot Airport | all-time | 95 |
| `PASIGHAT` | **IXT** Pasighat Airport | all-time | 95 |
| `AURANGABAD` | **IXU** Chhatrapati Sambhaji Maharaj Airport | all-time | 99 |
| `JAMSHEDPUR` | **IXW** Sonari Airport | all-time | 97 |
| `BIDAR` | **IXX** Bidar Airport | all-time | 95 |
| `BIDAR AIRPORT KARNATAKA` | **IXX** Bidar Airport | all-time | 95 |
| `KANDLA` | **IXY** Kandla Airport (Gandhidham Airport) | all-time | 95 |
| `JAMNAGAR` | **JGA** Jamnagar Airport (Civil Enclave Govardhanpur) | all-time | 97 |
| `JAGDALPUR` | **JGB** Maa Danteswari Airport | all-time | 95 |
| `JALGAON` | **JLG** Jalgaon Airport | all-time | 95 |
| `JHARSUGUDA` | **JRG** Veer Surendra Sai Airport | all-time | 95 |
| `JAISALMER` | **JSA** Jaisalmer Airport | all-time | 98 |
| `KUSHINAGAR` | **KBK** Kushinagar International Airport | all-time | 90 |
| `KUSHINAGAR INTERNATIONAL AIRPORT` | **KBK** Kushinagar International Airport | all-time | 97 |
| `KURNOOL` | **KJB** Kurnool Airport (Uyyalawada Narasimha Reddy Airport / Orvakal Airport) | all-time | 95 |
| `KALABURAGI KARNATAKA` | **KLH** Chhatrapati Rajaram Maharaj Airport | all-time |  |
| `KOLHAPUR` | **KLH** Chhatrapati Rajaram Maharaj Airport | all-time |  |
| `AJMER` | **KQH** Kishangarh Airport | all-time | 95 |
| `KISHANGARH` | **KQH** Kishangarh Airport | all-time | 95 |
| `LUDHIANA` | **LUH** Sahnewal Airport | all-time | 78 |
| `MUNDRA` | **MDA** Mundra Airport | all-time | 95 |
| `MYSORE` | **MYQ** Mysore Airport (Mandakalli Airport) | all-time | 97 |
| `MORADABAD AIRPORT` | **MZS** Moradabad Mundha Pande Airport | all-time | 95 |
| `NANDED` | **NDC** Nanded Airport (Shri Guru Gobind Singh Ji Airport) | all-time | 97 |
| `MUMBAI NAVI MUMBAI` | **NMIA** Navi Mumbai International Airport | all-time |  |
| `PITHORAGARH` | **NNS** Naini-Saini Airport | all-time | 96 |
| `BILASPUR` | **PAB** Bilasa Devi Kevat Airport | all-time | 95 |
| `PORBANDAR` | **PBD** Porbandar Airport | all-time | 97 |
| `PANTNAGAR` | **PGH** Pantnagar Airport | all-time | 95 |
| `PONDICHERRY` | **PNY** Puducherry Airport | all-time | 95 |
| `PONDICHERRY PUDUCHERRY` | **PNY** Puducherry Airport | all-time | 90 |
| `PUDUCHERRY` | **PNY** Puducherry Airport | all-time | 95 |
| `PURNEA` | **PXN** Purnea Airport | 2025-09–… | 97 |
| `PURNIA AIRPORT` | **PXN** Purnea Airport | all-time | 92 |
| `PAKYONG` | **PYG** Pakyong Airport | all-time |  |
| `REWA` | **REW** Rewa Airport | all-time | 97 |
| `RAJAHMUNDRY` | **RJA** Rajahmundry Airport | all-time | 99 |
| `SHIVAMOGGA` | **RQY** Shivamogga Airport (Rashtrakavi Kuvempu Airport) | all-time | 92 |
| `SHIVAMOGGA AIRPORT` | **RQY** Shivamogga Airport (Rashtrakavi Kuvempu Airport) | all-time | 95 |
| `ROURKELA` | **RRK** Rourkela Airport | all-time | 95 |
| `RUPSI` | **RUP** Rupsi Airport | all-time | 95 |
| `SHIRDI` | **SAG** Shirdi Airport | all-time | 99 |
| `MALVAN` | **SDW** Sindhudurg Airport (Chipi Airport) | all-time | 92 |
| `SINDHUDURG AIRPORT` | **SDW** Sindhudurg Airport (Chipi Airport) | all-time | 93 |
| `SHIMLA` | **SLV** Shimla Airport (Jubbarhatti) | all-time | 92 |
| `SIMLA` | **SLV** Shimla Airport (Jubbarhatti) | all-time | 92 |
| `SHOLAPUR` | **SSE** Solapur Airport | all-time | 97 |
| `SOLAPUR` | **SSE** Solapur Airport | 2026-01–… | 95 |
| `SALEM` | **SXV** Salem Airport | all-time | 95 |
| `TUTICORIN` | **TCR** Thoothukudi Airport (Tuticorin Airport) | all-time | 95 |
| `TEZU` | **TEI** Tezu Airport | all-time | 95 |
| `TEZPUR` | **TEZ** Tezpur Airport (Salonibari) | all-time | 95 |
| `TIRUCHIRAPALLY` | **TRZ** Tiruchirappalli International Airport | all-time |  |
| `UTKELA` | **UKE** Utkela Airport | all-time | 92 |
| `VIDYANAGAR` | **VDY** Jindal Vijayanagar Airport | all-time | 95 |
| `VIJAYAWADA` | **VGA** Vijayawada Airport | all-time | 99 |
| `VIJAYWADA` | **VGA** Vijayawada Airport | all-time | 90 |
| `SHRAVASTI AIRPORT` | **VSV** Shravasti Airport | all-time | 95 |
| `VISHAKHAPATNAM VISAKHAPATNAM` | **VTZ** Visakhapatnam Airport | 2026-01–… | 99 |
| `ZERO AIRPORT` | **ZER** Zero Airport | all-time | 95 |
| `ZIRO` | **ZER** Zero Airport | all-time | 93 |
| `UTTARLAI` | **name:uttarlai** Uttarlai Air Force Station | all-time | 90 |

## Manual corrections (override the automated decision)

| Label | Automated | Corrected to | Why |
| --- | --- | --- | --- |
| `KALABURAGI KARNATAKA` | KLH (alias) | **GBI** | KLH is Kolhapur's IATA, not Kalaburagi's |
| `KOLHAPUR` | KLH (alias) | **KLH** (rebuilt) | KLH freed for its real owner, Kolhapur |
| `LUDHIANA` | LUH (all-time) | **LUH ≤2025-12 / HWR ≥2026-01** | airport changed: Sahnewal → Halwara |
| `PURNEA` | PXN (window 2025-09) | **PXN** (all-time) | same airport as `PURNIA AIRPORT`, no window needed |
