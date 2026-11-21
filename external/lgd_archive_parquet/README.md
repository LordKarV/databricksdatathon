# LGD daily archive (Parquet mirror)

Local Government Directory (LGD, Ministry of Panchayati Raj) entities as daily
Parquet snapshots, mirrored by ramSeraph/opendata. We use the geography subset:
states, districts, sub-districts, blocks, villages, PIN-to-village,
PIN-to-urban-local-body and urban-local-body-to-district coverage.

## Source

- Index: https://ramseraph.github.io/opendata/lgd/data/metadata.json (JSON list of
  every dataset with file URL, sha256, row count and observed date). Fetched
  2026-11-21, `published_at` 2026-11-21T09:45:34Z.
- Landing page: https://ramseraph.github.io/opendata/lgd/
- Upstream: https://lgdirectory.gov.in/ (the mirror exists because the original
  site puts reports behind captcha forms).
- Collection code: https://github.com/ramSeraph/opendata/tree/master/lgd

Files fetched (all observed on 2026-11-19, sha256 verified against the index):

| dataset | rows | bytes |
|---|---|---|
| states | 36 | 2,495 |
| districts | 790 | 10,426 |
| subdistricts | 7,112 | 85,255 |
| blocks | 7,343 | 95,386 |
| villages | 677,660 | 7,991,452 |
| pincode_villages | 672,593 | 5,641,170 |
| pincode_urban | 7,307 | 66,170 |
| urban_local_bodies | 5,050 | 93,617 |
| statewise_ulbs_coverage | 35,401 | 489,910 |

Exact file URLs are in `data/external/lgd_archive_parquet/fetch_log.json`
(for example https://ramseraph.github.io/opendata/lgd/data/villages.<sha16>.parquet;
file names are content-addressed and change when the data changes, so always
resolve them through metadata.json). Total on disk 15 MB.

## Licence and terms

- Upstream LGD copyright policy (https://lgdirectory.gov.in/copyRightPolicy.do, read
  2026-11-21): "Material featured on this site may be reproduced free of charge in
  any format or media without requiring specific permission. This is subject to the
  material being reproduced accurately and not being used in a derogatory manner or
  in a misleading context. Where the material is being published or issued to
  others, the source must be prominently acknowledged."
- Upstream terms (https://lgdirectory.gov.in/termsconditions.do): content "should not
  be constructed as a statement of law or used for any legal purposes"; users are
  advised to verify with State Departments; no liability for loss from use.
- Mirror: footer says "Public data collected from Indian government sources." The
  repo's UNLICENSE (https://github.com/ramSeraph/opendata/blob/master/UNLICENSE)
  covers the code the author wrote; GitHub reports the repo licence as "Other"
  (NOASSERTION). The data itself carries no separate mirror licence, so the
  upstream LGD policy is the operative one.
- Verdict: private team repo redistribution is allowed (reproduction free of
  charge, accurately). Public demo use is allowed with a visible credit such as
  "Administrative codes: Local Government Directory, Ministry of Panchayati Raj
  (lgdirectory.gov.in), via ramSeraph/opendata mirror, snapshot 2026-11-19".
  Data files stay gitignored under data/external anyway.

## Fetch

```
.venv/bin/python -I external/lgd_archive_parquet/fetch.py data/external/lgd_archive_parquet
```

Re-runnable: downloads the index, then each dataset in `WANTED`, verifies sha256,
skips files whose hash already matches, pauses 1 s between requests, refuses any
file over 300 MB. Writes metadata.json and fetch_log.json next to the Parquet files.

## Inspection

- No SQL NULLs in any column, but empty strings stand in for missing values:
  `village_census_2011_code` empty or "0" for 36,862 villages (5.4%, villages created
  after 2011); `district_census_2011_code` empty or "0" for 152 of 790 districts
  (districts created after 2011, e.g. the 2022 Andhra Pradesh split);
  `village_name_local` empty for 501,318 villages (74%).
- No duplicate village or district codes. Every PIN is a valid 6-digit code.
- 5,067 of 677,660 villages (0.7%) have no PIN mapping.
- PIN universe: 17,197 PINs in the village mapping, 5,650 in the urban mapping,
  17,869 combined after joining urban bodies to districts. India Post directory
  has 19,586 PINs; 17,821 are in both, 1,765 India Post PINs are absent from LGD
  (the facility PINs in this gap are mostly metro delivery PINs: Kolkata 133,
  Bengaluru Urban 113, Gurugram 65, Chennai 61 facilities), 48 LGD PINs
  are absent from India Post.
- PINs are not district-unique: 1,893 rural PINs span more than one district and
  27 span more than one state (border PINs such as 605014 Kalapet, split between
  Puducherry and Viluppuram; the primary pick for it is Viluppuram, wrong for
  facilities in Kalapet). A PIN gives a candidate district set, not one answer.
- 12 urban local bodies in pincode_urban have no district in
  statewise_ulbs_coverage; 27 ULBs span more than one district.
- Freshness: snapshots observed 2026-11-19, the index regenerates daily. Names
  are current (Ahilyanagar, Chhatrapati Sambhajinagar, Dharashiv, Tirupati and
  Anakapalli districts all present), which is newer than both India Post and
  NFHS-5. The site warns: "A missing record does not by itself establish that an
  entity was deleted."
- Coordinates: none. LGD has codes and names only; geometry must come from a
  polygon source (see external/lgd_district_polygons).

## Join test

Script: `external/lgd_archive_parquet/join_test.py` (self-check in
`test_join_test.py`). Outputs in `data/external/lgd_archive_parquet/derived/`.

Matcher: facility PIN (digits only, must match `[1-9][0-9]{5}`) joined to the
union of PIN-village and PIN-urban-body mappings. Primary district = the district
with urban-body evidence first, then most villages, then lowest code. Checks:
facility state vs LGD state (normalised names plus aliases), facility city vs LGD
district, sub-district and urban body names for that PIN (rapidfuzz
token_set_ratio >= 85), and LGD district vs India Post district for the same PIN
(fuzz.ratio >= 80 or a name in the candidate set).

| metric | value | denominator |
|---|---|---|
| facilities with valid PIN | 9,923 | 10,088 |
| PIN found in LGD | 8,510 (85.8%) | 9,923 valid PINs |
| valid PIN missing from LGD but in India Post | 1,214 | 9,923 |
| matched PIN maps to one district | 7,244 | 8,510 |
| matched PIN maps to 2+ districts | 1,266 | 8,510 |
| state agrees with facility state field | 8,162 (95.9%) | 8,510 |
| city agrees with LGD names for the PIN | 6,770 (79.6%) | 8,510 |
| LGD district agrees with India Post district | 8,121 (95.5%) | 8,503 |

Of the 348 state disagreements, 293 are cases where the facility's state field
is not a state name (city names such as Thane, Navi Mumbai, Chennai; abbreviations
such as "U.p"; empty). 55 name a real
state: 25 are "Andhra Pradesh" for Hyderabad PINs (pre-2014 text), and the rest are
genuine contradictions in the facility record, e.g. "Modern Diagnostic & Research
Centre, Thanabhawan, Muzaffarnagar" with Delhi PIN 110015, "Aarogya Hospital" city
Delhi with Surat PIN 394516, "Sharma Hospital" Kapurthala (Punjab) with Bhiwani
PIN 127029. These are direct inputs for the contamination flags.

The India Post disagreements are mostly renames and new districts
(Ahmednagar/Ahilyanagar, Chittoor/Tirupati, Visakhapatnam/Anakapalli), where LGD
is the current one, plus India Post errors (PIN 799001 Agartala listed under
"Nirmal").

### Hand check, 20 random matched facilities (seed 7)

From `derived/handcheck_facilities.csv`. Verdict = is the LGD primary district right
for this PIN and facility.

| # | facility | city, state | PIN | LGD district | verdict |
|---|---|---|---|---|---|
| 1 | SPOT Hospital | Chennai, TN | 600024 | Chennai | correct |
| 2 | Doctor Diagnostics & Vascular Clinic | Purnea, Bihar | 854301 | Purnia | correct |
| 3 | Global Diagnostic Centre | Raebareli, UP | 201001 | Ghaziabad | PIN mapping correct; facility city contradicts its PIN, flag |
| 4 | Dermadent Skin & Dental Clinic | Hyderabad, Telangana | 500090 | Medchal Malkajgiri | correct |
| 5 | Lall Hospitals | Gurgaon, Haryana | 122001 | Gurugram | correct |
| 6 | Clove Dental | New Delhi, Delhi | 110016 | South East (5 candidates) | ambiguous, India Post says South |
| 7 | Vedic Karma Ayurvedic Hospital | Batala, Punjab | 143505 | Gurdaspur | correct |
| 8 | United Hospital | Gulbarga, Karnataka | 585102 | Kalaburagi | correct |
| 9 | Lokmanya Hospital (Nigdi) | Nigdi, Maharashtra | 411044 | Pune | correct |
| 10 | A.G Diagnostics | Pune, Maharashtra | 411004 | Pune | correct |
| 11 | Surendra Multispeciality Hospital | Tirupadiripuliyur | 607002 | Cuddalore | correct |
| 12 | Supreme Clinic | Pune, Maharashtra | 411044 | Pune | correct |
| 13 | Sri Raghavendra Hospital | Bangalore, Karnataka | 560057 | Bengaluru Urban | correct |
| 14 | Prudent Dental Clinic | Ahmedabad, Gujarat | 380006 | Ahmedabad | correct |
| 15 | Shah Satnam Ji Speciality Hospital | Sirsa, Haryana | 125055 | Sirsa | correct |
| 16 | Chennai Stone Clinic | Chennai, TN | 600024 | Chennai | correct |
| 17 | Life Imaging Centre | Srinagar, J&K | 190001 | Srinagar | correct |
| 18 | Excel Orthopedic and Kidney Care Hospital | Ahmedabad, Gujarat | 382481 | Ahmedabad | correct |
| 19 | Gupta Multispeciality Hospital | Amritsar, Punjab | 143001 | Amritsar | correct |
| 20 | Sharma Nursing Home | Kanpur, UP | 208002 | Kanpur Nagar | correct |

Precision: 19/20 primary district correct for the PIN; 1/20 ambiguous (Delhi PIN
across 5 districts, tie broken by code). Row 3 shows the PIN mapping exposing a
contradictory facility record rather than an LGD error.

### LGD district to NFHS-5

Name match within state (fuzz.ratio >= 80; WRatio was rejected after it matched
Prayagraj to Agra). 648 of 790 LGD districts (82.0%) match, reaching 642 of 706
NFHS-5 districts (90.9%). 604 matches are exact after normalisation; of the 44
fuzzy matches, 41 were correct by inspection and 3 wrong (Korea to Korba,
Nayagada to Rayagada, Eastern West Khasi Hills to South West Khasi Hills).
Misses are renames (Prayagraj, Mysuru, Gurugram, Belagavi, Kalaburagi) and
post-2019 districts with no NFHS-5 row (Andhra Pradesh 2022 split, Rajasthan 2023,
Ladakh, Sikkim renaming). The Dadra and Nagar Haveli and Daman and Diu state name
did not normalise to the NFHS form. Fix before use: a short rename alias table
and parent-district mapping for new districts (LGD change reports or the census
2011 codes, present for 638 of 790 districts).

## Product role

Geography backbone. It turns a user's PIN or village name into a canonical LGD
district code, gives every facility a candidate district set from its PIN,
flags facilities whose PIN contradicts their stated city or state, and supplies
the district code used to join NFHS-5 need indicators and district polygons.
It cannot place a user on a map (no coordinates) and cannot resolve the 1,214
facility PINs that only India Post knows, so it runs alongside the India Post
directory, not instead of it.

## Ingest plan (Databricks Free Edition)

1. Run fetch.py locally (Databricks compute cannot reach github.io), upload the
   nine Parquet files to a Unity Catalog volume, e.g.
   `/Volumes/workspace/geo/raw/lgd/2026-11-19/`.
2. Create Delta tables `workspace.geo.lgd_states`, `lgd_districts`,
   `lgd_subdistricts`, `lgd_villages`, `lgd_pincode_villages`,
   `lgd_pincode_urban`, `lgd_ulb_coverage` with `CREATE TABLE AS SELECT * FROM
   read_files(...)`, then derived `workspace.geo.pin_district` (from
   join_test.py logic), `workspace.geo.lgd_nfhs_district_map` and a
   `facility_lgd` column set on the facility table.
3. Refresh: manual, once before the demo. The data changes slowly; a weekly
   re-fetch is enough if the project continues.
4. App screens: the search box (PIN or village to district, with "this PIN spans
   N districts" when ambiguous), the facility card evidence panel ("PIN 201001 is
   in Ghaziabad district, LGD; the record says Raebareli"), and the district need
   panel via the NFHS join.

Effort: about 3 hours (upload and tables 1 h, alias table for NFHS renames 1 h,
wiring into the resolver and contamination flags 1 h).
