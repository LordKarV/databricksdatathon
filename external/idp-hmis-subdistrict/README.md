# HMIS major health indicators, sub-district level (India Data Portal mirror)

Monthly service volumes reported to the MoHFW Health Management Information System, by
sub-district and sector, as republished by the India Data Portal (ISB). We use it as district
context for facility claims (C-sections, newborn care, trauma, burns, cardiac, X-ray, USG).
It has no facility rows and no dialysis items.

## Source

- Package: `health-management-information-system-hmis` (id 5841ceaf-d548-426b-a8b2-19fd57ebaf4c),
  resource "Major Health Indicators Sub-district Level" (id bd560c85-ba92-4364-9e31-7411c93e4989,
  sku mohfw-hmis-sd-mn-fhi). Upstream source: https://hmis.mohfw.gov.in (standard reports).
- Metadata: https://ckandev.indiadataportal.com/api/3/action/package_show?id=health-management-information-system-hmis
- Data: https://ckandev.indiadataportal.com/api/3/action/datastore_search?resource_id=bd560c85-ba92-4364-9e31-7411c93e4989
  (paged, `fields=` subset, `records_format=csv`, 32,000 rows per page, 18 pages, 1 s apart).
- On 2026-11-21 `ckan.indiadataportal.com` refused TCP connections on ports 443 and 80, and the
  resource id in our catalogue (eb0d4fba-...) is "Not found" on the dev host. `ckandev.indiadataportal.com`
  serves the same package with the id above. The public site's `/api/ckan/*` proxy answers
  "Forbidden - untrusted origin" to non-browser calls; we did not try to get around that.
- Metadata says: data_last_updated 17-02-2022, years_covered "2017-18, 2019-20", 739 districts,
  4,493 sub-districts, 286 indicators, full CSV 408,524,822 bytes, metadata_modified 2026-11-20.

## Licence and terms

- CKAN record: `license_id: odc-by`, "Open Data Commons Attribution License",
  http://www.opendefinition.org/licenses/odc-by.
- ODC-BY summary (https://opendatacommons.org/licenses/by/summary/): "You are free: To share: To copy,
  distribute and use the database. To create: To produce works from the database. To adapt: To modify,
  transform and build upon the database. As long as you: Attribute: You must attribute any public use of
  the database, or works produced from the database, in the manner specified in the license. For any use
  or redistribution of the database, or works produced from it, you must make clear to others the license
  of the database and keep intact any notices on the original database."
- IDP copyright policy (https://indiadataportal.com/datausage?view=copyright_policy, read from the page's
  server-rendered data): "Reuse of material featured on the portal is authorised, provided the source is
  acknowledged." It also says "The India Data Portal logo image must be carried by all visualisations
  generated from the portal" and "Manipulation of India Data Portal's copyrighted material is prohibited".
  The logo clause is about visualisations generated on the portal; the manipulation clause reads as
  "do not misrepresent", but it sits awkwardly next to ODC-BY's right to adapt. We read it as: do not
  alter the published numbers and present them as IDP's.
- Verdict: redistribution inside a private team repo is allowed (ODC-BY, keep the licence note).
  Use in a public demo is allowed with attribution, e.g. "Source: MoHFW HMIS via India Data Portal (ISB),
  ODC-BY". Show derived aggregates as ours, not as IDP figures. Not legal advice.

## Fetch

```
python -I external/idp-hmis-subdistrict/fetch.py data/external/idp-hmis-subdistrict
```

Pulls all 547,336 rows but only 40 of 296 columns (ids, geography, sector and the delivery, newborn,
emergency, surgery and imaging counts), 76,285,927 bytes, sha256
2763f46fa7a780b4bf547bd56c15e275c8b017642ca036cd7e829d8330ef5239, about 2 minutes. Column labels for
all 295 indicators are in `package_show.json` (`column_labels`). `--max-pages N` limits a test run.

## Inspection (`inspect_hmis.py`, output in data/external/idp-hmis-subdistrict/profile.json)

- 547,336 rows, 36 states/UTs, 739 district codes, 4,309 distinct sub-district codes. No nulls in the
  40 columns pulled, no negative values.
- Sector has five values that overlap: Public, Private, Total, Rural, Urban (about 109k rows each).
  Total is roughly Public + Private but not exactly: all-period C-sections Public 5,621,960 + Private
  6,381,532 = 12,003,492 vs Total 12,497,726 (Rural + Urban = 12,398,565); SNCU 2,127,989 vs 2,134,602;
  trauma 12,968,646 vs 12,978,023. Never sum across all sectors; use Total for district volume.
- Dates run 2017-01 to 2021-05 with 48 months, not the two fiscal years the metadata states. Only
  Telangana's Nagarkurnool district appears before 2019. 2019-01..2019-12: about 4,306 sub-districts and
  700 districts per month. 2020-01..2021-05: 2,853 sub-district codes and 736 districts per month;
  2020-03, 2021-01..03 are missing.
- 2020 national live births per month are about 1.9x the 2019 figure in almost every state (Bihar 176k vs
  325k; Uttar Pradesh 339k vs 610k). Bihar's 2020 rate would be about 3.9M births a year, which is not
  plausible. Cause unverified; treat 2020 and 2021 as unreliable until explained. The join uses 2019.
- Sub-district code 9999 "Others" holds urban and district-level facilities (e.g. Patna, July 2020:
  "Others" 7,139 institutional deliveries and 1,222 C-sections, every named block 0 to 20 C-sections).
  Several codes are pseudo-units: "Dist Level Facility", "Dhq", "Medical College Hq",
  "Medical College Hospital Calicut", Mumbai wards coded 4173 (Panvel). 21,575 (date, sub-district,
  sector) groups outside 9999 have more than one row.
- `inst_deliv_csec` is "Institutional Deliveries (Including C-Sections)", not C-sections. Use `csec_total`
  ("C-Section Deliveries Performed"). The catalogue entry had this wrong.
- Codes are LGD codes: 737 of 740 (district code, name) pairs exist in the LGD archive, 668 with the same
  spelling (others differ only in spelling, e.g. Bargarh / Baragada). Missing: Mahe, Yanam, Shahdara.
  4,749 of 5,490 (sub-district code, name, district) combinations exist in LGD, 4,464 under the same
  district.
- 155,733 rows are all zero across the 31 count columns. Outliers exist: sncu_inborn_m max 8,382
  (Central Delhi "Others", 2019-11) while the 99.9th percentile is 398.
- Zero does not mean absent. Hyderabad reports 0 burn emergencies for 2019-2021, and Darbhanga (which has
  a medical college) and Dhanbad report 0 SNCU admissions in 2019 and 2020.

## Join test (`join_test.py`, outputs in data/external/idp-hmis-subdistrict/)

HMIS is aggregate, so the join is geographic, not by name:

1. Facility PIN to LGD district, reused from `external/lgd_archive_parquet` (`derived/facility_lgd.parquet`,
   same row order as facilities.parquet; unique_id has 11 duplicates, so rows are joined by position).
2. Fallback: India Post district name to HMIS district name, rapidfuzz `ratio` >= 88 within the state.
3. Sub-district: PIN to LGD villages to sub-district codes present in HMIS for that district; urban PINs
   go to the district's "Others" (9999) bucket.

Results, denominator 10,088 facilities:

- District matched: 9,256 (91.75%): 8,073 by LGD PIN, 1,183 by name fallback, 832 unmatched.
  437 facilities had an LGD district code that is absent in HMIS 2019 (new districts).
- 531 of 700 HMIS 2019 districts contain at least one VF facility.
- Sub-district: 3,615 single sub-district, 1,481 several candidates, 2,238 urban "Others" bucket,
  2,754 none. The sub-district level is weak for city hospitals, which mostly report under "Others".

Hand check of 20 random district matches (seed 11, `handcheck_20.csv`), judged against the
facility's stated city: 17 of 20 correct. The 3 misses are contradictions in the VF record itself, where
the PIN belongs to another district than the stated city: Pooja Hospital, Kapadvanj (PIN 380008,
Ahmedabad, but Kapadvanj is in Kheda); Asian Eye Hospital, "Pune" (PIN 431001, Aurangabad); Shivay
Clinic, "Ahmedabad" (PIN 382450, Botad). Correct: Dental Clinic Sevoke Road / Siliguri to Darjeeling,
City Crown Dental / Haridwar, Aarogya Dental Care / Nagaon, Om Healthcare Center / Bhubaneswar to
Khordha, Indira IVF / Dehradun, OmShree Sidha Hospital / Kottayam, Vasudev Multispeciality / Raipur,
PMC American Hospital / Kota, Royd Nursing Home / Kolkata, Rewati Nursing Home / Dehradun, Jeevana
Kerala Ayurvedic Centre / Pune, Exceldent / Udupi, Jagdish Memorial / Patna, Smile Square Dental /
Ahmedabad, Alliance Multi Speciality / Ichalkaranji to Kolhapur, Shridevi Institute / Tumkur to Tumakuru,
Hyperion Dental / Chandannagar to Hooghly. Sub-district picks are shakier (City Crown Dental, Haridwar
city, was given Bhagwanpur).

Service claims among the 9,256 matched facilities (regex over specialties, procedure, equipment,
capability, description; HMIS 2019 district totals):

| service | claim | do not claim | claim, district Total = 0 | private claim, district Private = 0 |
|---|---|---|---|---|
| C-section | 418 | 8,838 | 0 | 9 |
| NICU / SNCU | 672 | 8,584 | 20 | 443 |
| trauma / emergency | 1,846 | 7,410 | 3 | 1,207 |
| burns | 223 | 9,033 | 4 | 143 |
| cardiac | 3,150 | 6,106 | 62 | 2,152 |
| major surgery | 2,608 | 6,648 | 270 | 2,045 |
| X-ray | 2,282 | 6,974 | 5 | 1,379 |
| ultrasound | 1,900 | 7,356 | 13 | 1,309 |

Districts with HMIS 2019 Total = 0, out of 700: C-section 23, SNCU 68, burns 16, trauma 7.
The "Private = 0" column mostly shows that private facilities under-report to HMIS (Private
SNCU = 0 in 615 of 700 districts), not that the claim is false. These are weak flags, not labels.

## Product role

District context and plausibility check. It cannot confirm that a facility offers a service. It can
say "this district reported N C-sections and M SNCU admissions in 2019 (public sector)" next to a
recommendation, as need/capacity context for the planner view and as a low-weight uncertainty flag when
a claim sits in a district that reports zero. Because zeros are often non-reporting, the flag should
only lower confidence when other evidence is thin, and the app must say so.

## Ingest plan (Databricks Free Edition)

1. Upload `hmis_subdistrict_subset.csv` (76 MB) to a UC volume, e.g.
   `/Volumes/<catalog>/external/raw/idp_hmis/`. No outbound fetch from Databricks is needed.
2. One serverless SQL or notebook step builds `<catalog>.external.hmis_district_2019`: one row per
   (district_code, sector in Public/Private/Total) with annual sums, months reported, and
   `is_zero_<service>` flags; about 2,100 rows. Optionally `hmis_subdistrict_2019` for rural blocks.
   Aggregate by district first; whole-table queries on the raw table were slow before.
3. Join to facilities on the LGD district code from the PIN crosswalk table.
4. Refresh: none needed; the source has not changed since 2022-02-17. Re-run `fetch.py` only if IDP
   publishes newer years.
5. App: facility detail "district context" panel, uncertainty badge on C-section / NICU / burns / trauma
   claims, and the planner's district need view. Cite as "MoHFW HMIS via India Data Portal, ODC-BY".

Effort: about 4 hours (upload, aggregate table, join, panel text), plus about 2 hours if the 2020
doubling has to be explained before 2020 data is used.
