# IDP NFHS district table (2015-16, 2019-21, 2023-24) with LGD codes

District-level NFHS fact-sheet indicators compiled by the India Data Portal (ISB/Bharti Institute),
with LGD state and district codes. Status: usable. It adds LGD codes and a 2023-24 (NFHS-6) round
to our name-only NFHS-5 table, and it joins to 9,902 of the 10,088 Virtue Foundation facilities.

## Source

- Publisher: India Data Portal, package "National Family Health Survey (NFHS)", organisation
  "IDP organization"; `source_name` Ministry of Health & Family Welfare, extraction page
  https://www.nfhsiips.in/nfhsuser/publication.php (per the resource metadata).
- Catalogue URL given to us: https://ckan.indiadataportal.com/dataset/national-family-health-survey-nfhs.
  On 2026-11-21 this host refused TCP connections on ports 443 and 80 (curl error 7, and the
  same ECONNREFUSED from a remote fetcher), so it is down, not blocked only from here.
- What we actually accessed (same package id 591d88dd-23f4-4b43-8d65-a5e4bc617293):
  - metadata: https://ckandev.indiadataportal.com/api/3/action/package_show?id=national-family-health-survey-nfhs
  - district CSV: https://ckandev.indiadataportal.com/dataset/591d88dd-23f4-4b43-8d65-a5e4bc617293/resource/b8ac1c23-d13f-4a91-aa4c-a056605f9115/download/districtlevel-nfhs.csv
    (302 to a signed Wasabi S3 URL; 1,175,920 bytes, matches the metadata `size`)
  - state CSV: https://ckandev.indiadataportal.com/dataset/591d88dd-23f4-4b43-8d65-a5e4bc617293/resource/2f0e5dfb-7486-44ca-a8ed-faf25550c2b9/download/state-level-nfhs.csv
    (172,918 bytes)
- Freshness (metadata): `data_last_updated` 2026-08-21, `data_retreival_date` 2026-09-10, resource
  `last_modified` 2026-09-20, package `metadata_modified` 2026-11-20. Fetched 2026-11-21T18:52:16Z.
- The "ckandev" host name suggests a staging instance. The content is the live package (same id,
  edited yesterday), but the URL may change; fetch.sh tries the production host first.

## Licence and terms

- Dataset record: `license_id` and `license_title` are empty, `isopen` is false. No licence is
  stated on the record itself.
- Portal-wide copyright policy (https://indiadataportal.com/datausage?view=copyright_policy, text
  read from the page's embedded data on 2026-11-21), quoted:
  - "Licensing of all the public and government datasets on the India Data Portal is based on the
    Open Data Commons Attribution License unless mentioned otherwise." (links ODC-BY 1.0)
  - "Reuse of material featured on the portal is authorised, provided the source is acknowledged."
  - "Whenever India Data Portal's material is published or issued to others, the source material
    must be prominently acknowledged. The India Data Portal logo image must be carried by all
    visualisations generated from the portal ... the permission to reproduce this material shall not
    extend to any material identified as being of a third party."
  - "Manipulation of India Data Portal's copyrighted material is prohibited, and such manipulation is
    not permitted for reuse or reproduction."
- Reading: this is a government dataset with no other licence stated, so ODC-BY 1.0 applies by the
  portal default. Keeping a copy in a private team repo: allowed (ODC-BY allows copying and
  redistribution with attribution). Use in a public demo: allowed with attribution to India Data
  Portal and to MoHFW/IIPS NFHS. Two cautions: (1) the logo clause targets "visualisations generated
  from the portal" (their own chart tool); we do not use their tool, but showing "Source: India Data
  Portal (ISB), NFHS fact sheets via MoHFW/IIPS" on any chart is cheap and safe; (2) do not alter
  values and present them as IDP's; derived scores should be labelled as ours. The underlying NFHS
  fact sheets are public MoHFW/IIPS publications. Not legal advice; no one at IDP was asked.

## Fetch steps

```
bash /Users/karthikvattem/projects/datathon/external/idp-nfhs-district/fetch.sh
```
Writes package_show.json, districtlevel-nfhs.csv, state-level-nfhs.csv and FETCHED_AT into
/Users/karthikvattem/projects/datathon/data/external/idp-nfhs-district/. It only follows resource
URLs on the two IDP CKAN hosts, rejects HTML responses, waits 1 s between requests and prints
sha256 sums (district CSV dc9186d6f117...664b on 2026-11-21).

Inspect and join test (reads data/raw and audit/geo, read-only):
```
D=/Users/karthikvattem/projects/datathon/data/external/idp-nfhs-district
/Users/karthikvattem/projects/datathon/.venv/bin/python -I -B \
  /Users/karthikvattem/projects/datathon/external/idp-nfhs-district/inspect_join.py \
  $D/districtlevel-nfhs.csv $D/state-level-nfhs.csv /Users/karthikvattem/projects/datathon/external/idp-nfhs-district
```
Outputs here: inspect_stats.json (every number below), nfhs5_idp_district_map.csv (706-row
crosswalk from our NFHS-5 parquet to LGD codes), handcheck_20.csv. Output in the data dir:
facility_idp_district.csv (facility unique_id to LGD district code).

## Inspection results

- 1,995 rows x 129 columns (id, year, state_name, state_code, district_name, district_code, 123
  indicators). Rows: 2015-16 = 575, 2019-21 = 707, 2023-24 = 713. States/UTs: 34, 36, 33.
- 2023-24 has no rows for Chandigarh, Lakshadweep and Manipur (11 district codes present in 2019-21
  are absent: 044, 252-260, 553). Metadata says Manipur is not covered by NFHS-6. 17 codes are new
  in 2023-24 (districts carved out recently: 6 in Tamil Nadu, 3 in West Bengal, 5 in Arunachal
  Pradesh, 2 in Telangana, Gaurela-Pendra-Marwahi). 694 codes appear in both 2019-21 and 2023-24.
- district_code is blank in 8 rows (Shahdara, Mahe, Yanam across rounds); the script gives them a
  surrogate key "NA-<name>". No duplicate (year, district_code) otherwise, no duplicate names.
- Null rates: 2015-16 has 45 indicators entirely blank, 2023-24 has 30 (NFHS-6 fact sheets carry 93
  of the 123). Among the 93 populated 2023-24 indicators the mean null rate is 5.7%. Key fields in
  2023-24: births_c_section, public_births_c_section, institutional_births, men/women high blood
  sugar (>140), men/women elevated BP all 0% null; private_births_c_section 13.5% null (fewer than
  25 private births, suppressed). Blood sugar and BP are 100% null in 2015-16.
- No percentage cell outside 0-100. births_c_section 2023-24: min 1.0, median 24.7, max 87.3.
- The task brief listed "men_high_blood_sugar_140plus" etc. as key fields: they exist with those
  names. There is no NICU or dialysis indicator; blood sugar and BP are proxies only.
- Metadata caveats worth surfacing in the app: values in parentheses in the fact sheets (25-49
  unweighted cases) are kept as plain numbers with no flag; NFHS-6 results are marked provisional;
  some NFHS-5 values differ between the NFHS-5 and NFHS-6 fact sheets.
- State check: for births_c_section, institutional_births and women_high_blood_sugar_140plus, the
  state "Total" value from the state CSV lies inside the min..max of that state's districts in
  273 of 275 state-year-indicator cases. This is an internal consistency check only. I did not
  compare 2023-24 values to an official NFHS-6 district fact sheet: rchiips.org failed TLS
  verification from both my machine and the remote fetcher, and I found no page confirming an
  official NFHS-6 district release (India/State fact sheets of 29 May 2026 are confirmed in press
  coverage). Treat 2023-24 district values as unverified against the primary source.

## Join test

Step 1, IDP 2019-21 to our NFHS-5 parquet (data/raw/nfhs_5_district_health_indicators.parquet,
706 rows). Within state: exact normalised name (spaces ignored), then rapidfuzz token_sort_ratio
>= 85, then for the rest a value fingerprint (all of births_c_section, institutional_births, men and
women blood sugar >140, women BP, stunting equal within 0.1, unique in state).
- Matched 705 of 706 (99.9%): 611 exact, 30 fuzzy, 64 by values (renames such as Gurgaon to
  Gurugram, Cuttack to Kataka, Warangal Urban to Hanumakonda, Ramanagara to Bengaluru South).
- Value agreement on the 6 shared indicators for the 705 pairs: births_c_section 705/705,
  institutional_births 705/705, women sugar 705/705, men sugar 705/705, stunting 704/704, women BP
  703/705. 703 pairs agree on every compared value. (For the 64 value matches this is true by
  construction, so their precision rests on the name check below.)
- The 2 BP disagreements: Puducherry (IDP 31.1, ours 22.7) and Mahe (IDP 37.7, ours 33.3). Which is
  right is unverified.
- Unmatched: our parquet's "Mizoram / Chandel" row, which duplicates the values of Manipur / Chandel
  exactly (an error in our raw file; the audit already maps Saiha to it). IDP has a real Siaha row
  (C-section 9.5 vs the duplicated 14.9). IDP also has Purba Bardhaman, which our parquet lacks.
- Hand check of 20 pairs (handcheck_20.csv; 7 fuzzy, 7 value, 6 exact, seed 7): 20/20 correct.
  Assam Morigaon = Marigaon; Meghalaya East Jantia Hills = East Jaintia Hills; Andhra Pradesh Sri
  Potti Sriramulu Nello = Sri Potti Sriramulu Nellore; J&K Baramula = Baramulla; Jharkhand Sahibganj
  = Sahebganj; Gujarat Ahmadabad = Ahmedabad; Odisha Jajapur = Jajpur; Jharkhand Purbi Singhbhum =
  East Singhbum; Andhra Pradesh Y.S.R. = Y.S.R. Kadapa; Odisha Sundargarh = Sundaragada; Sikkim West
  District = Gyalshing; Jharkhand Pashchimi Singhbhum = West Singhbhum; Punjab Firozpur = Ferozepur;
  Maharashtra Ahmadnagar = Ahilyanagar; and exact Satna, Gomati, Puducherry, Sindhudurg, Ramgarh,
  Majuli. All 20 also agree on every compared value except Puducherry (5 of 6, the BP case above).
  I also read all 64 value-fingerprint pairs; each is a known rename or respelling.

Step 2, facilities to an IDP 2023-24 district. Facility district comes from the audit's
audit/geo/facility_district.parquet (PIN directory district, 9,970 facilities, 9,961 with a
district). Two routes: (a) the audit's NFHS-5 district through the step 1 crosswalk to an LGD code;
(b) the PIN directory district name matched directly to IDP 2023-24 names in the same state (exact,
fuzzy >= 85, plus 39 hand-written renames in DIR_ALIAS and DIR_ALIAS_ANY). Best code = (b) if found, else (a).
- Denominator 10,088 facilities in data/raw/facilities.parquet. With a 2023-24 IDP row that has a
  births_c_section value: 9,902 (98.2%). Route (b) alone: 9,785; route (a) alone: 9,902.
- Not joined (186 = 10,088 - 9,902): 118 facilities absent from the audit table, 9 with no
  district in the audit (Gujarat 4, Maharashtra 3, Madhya Pradesh 1, no state 1), and 59 in places
  with no 2023-24 data (Chandigarh 46, Manipur 13). For Chandigarh and Manipur the app should fall
  back to the 2019-21 row. The 12 facilities in Shahdara, Mahe and Yanam join through the
  surrogate key because IDP has no LGD code for those three.
- Where both routes give a code (9,785), they agree for 9,708. The 77 disagreements are all
  facilities in districts carved out after NFHS-5 (Chengalpattu, Ranipet, Tirupathur, Tenkasi,
  Kallakurichi, Mayiladuthurai, Alipurduar, Kalimpong, Purba Bardhaman): route (b) gives the new
  district's own NFHS-6 row, route (a) gives the parent. Route (b) is the better answer there.
- Andhra Pradesh: the 2023-24 rows use the 13 pre-2022 districts, so the 12 post-2022 AP districts seen among facilities reach
  data only through the parent (route a). Flag those as "parent district estimate".

Service-claim check: not applicable. This is a need/geography table with no facility or service
list, so it yields no facility-level evidence or training labels.

## Product role

District context for the "why here" part of a recommendation, never evidence about a facility:
- Need badge on the results screen: "C-section rate in this district 2023-24: 24.7% (NFHS-6,
  provisional); 2019-21: x%" for emergency C-section and high-risk delivery; institutional births
  and the public/private C-section split for NGO and planner views; men/women blood sugar >140 and
  BP as weak proxies for dialysis/NCD burden. Always show round, source and "district estimate,
  not facility data".
- Planner screen: rank districts by need vs number of facilities claiming the service.
- The LGD district_code gives a stable key for joining other government tables (HMIS, census,
  LGD boundaries) later, which our name-only NFHS-5 parquet cannot.

## Ingest plan (Databricks Free Edition)

1. Upload districtlevel-nfhs.csv (1.2 MB) and nfhs5_idp_district_map.csv to a Unity Catalog volume,
   e.g. /Volumes/<catalog>/external/raw/idp_nfhs/ (manual upload from a laptop; Databricks compute
   cannot reach indiadataportal.com). Not done: the workspace is read-only for this task.
2. One SQL statement on the 2X-Small warehouse: `CREATE TABLE <catalog>.ref.nfhs_district_lgd AS
   SELECT * FROM read_files(..., format => 'csv', header => true)` keeping district_code as STRING
   (leading zeros), plus a long-format view (year, district_code, indicator, value) for the app.
3. Join to facilities on a precomputed facility_district_lgd table (facility unique_id to
   district_code, built from facility_idp_district.csv or by rerunning the matcher in a notebook).
4. Refresh: manual, when IDP updates (frequency "Quinquennially"; next change expected when official
   NFHS-6 district reports appear). Rerun fetch.sh and compare sha256.
5. App use: the Databricks App reads the table through the SQL warehouse for the need badge and the
   planner view. Citation string stored with each value: "India Data Portal, NFHS district
   dataset (resource b8ac1c23), round <year>".

Effort: about 3 hours (1 upload and table, 1 facility-district table and checks, 1 app wiring and
citation text).
