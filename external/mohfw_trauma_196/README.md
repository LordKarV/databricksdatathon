# MoHFW trauma care facilities (NPPMTBI, 196 TCFs)

Government list of the 196 hospitals funded as Trauma Care Facilities (TCFs) under the
National Programme for Prevention and Management of Trauma and Burn Injuries (NPPMTBI),
with state and funds allocated. A second MoHFW document (the 2019 programme brief) adds
the level (I/II/III) and a 2019 functionality status per facility.

## Source

| File | URL actually fetched | Notes |
|---|---|---|
| source.pdf (421,544 bytes, 5 pages, sha256 f29d9f7a...ae12ac) | https://web.archive.org/web/20231215043518id_/https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf | "List of 196 Trauma Care Facilities and funds allocated". PDF metadata: title "Microsoft Word - Annexure- I", created 2023-02-08. |
| brief.pdf (742,343 bytes, 14 pages, sha256 fb0deb83...236586) | https://web.archive.org/web/20231113174125id_/https://main.mohfw.gov.in/sites/default/files/Prog%20brief%20Trauma%20component%20.pdf | NPPMTBI programme brief, created 2019-09-25. Annexure-1 unit costs, Annexure-2 status of 116 11th-plan TCFs, Annexure-3 list of 80 12th-plan TCFs with level. |

Original URL https://main.mohfw.gov.in/sites/default/files/List%20of%20Trauma%20Care.pdf
no longer resolves from here (curl: "Could not resolve host: main.mohfw.gov.in",
2026-11-21). The same path on www.mohfw.gov.in returned 404 once and 403 once. Both
files therefore come from the Internet Archive raw snapshots above.

## Licence and terms

MoHFW website policy (archived https://web.archive.org/web/20230922152945/https://main.mohfw.gov.in/website-policies,
read 2026-11-21), "Copyright Policy":

> Contents of this website may not be reproduced partially or fully, without due
> permission from Department of Health and Family Welfare. If referred to as a part of
> another website, the source must be appropriately acknowledged. However, the material
> has to be reproduced accurately and not to be used in a derogatory manner or in a
> misleading context.

"Hyperlink Policy": "We do not object to you linking directly to the information that is
hosted on this website and no prior permission is required for the same."

What this means for us (my reading, not legal advice):
- Private team repo: the PDFs and the parsed CSV sit in data/external/ (gitignored), so
  nothing is redistributed. Keep it that way; commit only the scripts.
- Public demo: reproducing the list "partially or fully" formally needs permission. The
  facts themselves (that hospital X is a government-funded level-II TCF) are public
  government information. Safe pattern: show per-facility facts with a citation link to
  the MoHFW document, do not republish the full table as a download. The document is
  not on data.gov.in under the Government Open Data License as far as I checked (not
  searched exhaustively: unverified).

## Fetch and parse

```sh
sh external/mohfw_trauma_196/fetch.sh            # tries live MoHFW URLs, then Wayback
D=data/external/mohfw_trauma_196
.venv/bin/python -I external/mohfw_trauma_196/parse.py $D/source.pdf $D/brief.pdf $D/tcf_196.csv
.venv/bin/python -I external/mohfw_trauma_196/join.py $D/tcf_196.csv data/raw/facilities.parquet \
  audit/geo/facility_district.parquet data/raw/india_post_pincode_directory.parquet \
  audit/claims/out/grades.parquet $D
```

parse.py needs `pdftotext` (poppler) on PATH. The state column in the PDF is a merged
cell, so states are assigned from hand-coded serial-number ranges (checked against the
brief's state headings); the script asserts serials 1..196 are all present.

## Inspection results

- Rows: 196 of 196 parsed (serials 1..196, no duplicates), 32 states/UTs.
- Fields in the source: S. No., Name of State, Name of TCF, Amount allocated (Rs crore).
  No address, district, PIN, coordinates or level column.
- Derived fields in tcf_196.csv: level_from_amount, plan_from_amount, brief_level,
  brief_status, level (brief level if present, else from amount).
- Null rates: sno, name, state, amount 0%; level_from_amount 0.5% (only Gangtok, Rs
  8.772 cr, matches no unit cost); brief fields 4.1% (8 rows not found in the brief:
  Bilaspur CIMS, Jagdalpur, Jamnagar, Thiruvananthapuram, Kohima, Dimapur, Nizamabad,
  Diamond Harbour).
- Level from amount is reliable: the brief's Annexure-1 gives unit costs L-III 4.775 /
  L-II 9.63 / L-I 15.93 (11th plan) and 4.942 / 10.272 / 17.132 (12th plan); 6.1632 and
  2.9652 are exactly 60% of the 12th-plan L-II and L-III costs. Of 188 rows matched to
  the brief, 185 agree with the amount, Gangtok has no amount level (brief: II), and two
  disagree: Purnia (6.1632, brief says III) and Porbandar (9.63, brief says III).
- Final level counts: I 6, II 74, III 116. Total allocation Rs 1,359.12 cr.
- Status (brief, 2019): 104 "functional", 7 under construction, 4 construction not
  started, 73 12th-plan TCFs with the note "No TCF have become functional", 8 unknown.
- Obvious errors in the source: misspellings (Kishanjanj, Gopalgang, Bogaigaon,
  Dharbhanga, Devangiri, Allhabad, Diamod Harbour, Fazailka, Kiphiri, Namachi); brief
  places Dungarpur (Rajasthan) in "Sabarkantha" (Gujarat) and Leh under J&K; some
  names are only a type plus place ("District Hospital, Gomati"), others only a
  college name ("Doon Medical College & Hospital").
- Freshness: list PDF created 2023-02-08; status data is from 2019. The brief says
  no new TCFs were identified after the 12th plan (2012-17), so the list itself is
  stable, but "funded" does not mean "functional today".

## Join test against facilities.parquet

Matcher (join.py): same state (audit/geo district table, else raw state), a place or
distinctive token from the TCF name must appear in the VF name/city/address (rapidfuzz
ratio >= 88), then name similarity after abbreviation expansion (Govt, Dist, GMCH, DH,
CHC...) with the shared place token removed, mean of token_set and token_sort ratio.
A VF name carrying a token not in the TCF name ("Shree Hospital", "District Hospital
Hapur", "R.R. Hospital") or a place hit only via the PIN-derived district is capped at
70, i.e. sent to review. Accept at >= 80.

- TCFs with any same-state candidate sharing a place token: 155 / 196.
- Accepted matches: 20 / 196 = 10.2%. Review band (60-79): 80 TCFs, mostly wrong
  (private hospitals in the same town); about 4 look right on reading
  (Sub-Divisional Hospital Kharagpur, Doon Hospital Dehradun, SSG Hospital Vadodara,
  and, less sure, Lunglei Civil Hospital for "District Hospital, Lunglei"), which would bring it to about 24 / 196 (12%) after manual
  review (unverified beyond my reading).
- The ceiling is low because the VF data is mostly private: 477 of 10,034 named rows
  have operatorTypeId "public". All 20 accepted VF rows are "public".
- TCF coordinates were approximated from India Post offices whose district or office
  name equals a TCF token: 165 / 196 got a point. This is noisy (Vadodara landed at
  15.59 N; Burdwan used one office), so distances below are diagnostics, not gates.

Hand check of all 20 accepted matches (my judgment from names, city and address):

| # | TCF (state) | VF record (city) | km | Verdict |
|---|---|---|---|---|
| 1 | Agartala Govt. Medical College (Tripura) | Agartala Government Medical College (Agartala) | - | correct |
| 2 | Civil Hospital, Bogaigaon (Assam) | Civil Hospital (Mahabhairab; address line 3 Bongaigaon, description Dhemaji) | - | wrong: merged record of three towns |
| 3 | General Hospital, Ernakulam (Kerala) | General Hospital Ernakulam | 15.9 | correct |
| 4 | District Hospital, Satara (Maharashtra) | District Hospital, Satara | 9.0 | correct |
| 5 | Regional Institute of Medical Sciences, Imphal | Regional Institute of Medical Sciences (Imphal) | 2.5 | correct |
| 6 | District Hospital, Churachandpur (Manipur) | CHURACHANDPUR DISTRICT HOSPITAL | 5.3 | correct |
| 7 | District Hospital Champhai (Mizoram) | Champhai District Hospital, Champhai | 10.1 | correct |
| 8 | Medical College & Hospital, Silchar (Assam) | Silchar Medical College & Hospital | 5.4 | correct |
| 9 | Burdwan Medical College & Hospital (West Bengal) | Burwan Medical College & Hospital, Burdwan | 111.8 | correct (TCF point bad) |
| 10 | GMCH, Kanyakumari (Tamil Nadu) | Kanyakumari Government Medical College Hospital (Nagercoil) | - | correct |
| 11 | North Bengal Medical College & Hospital, Siliguri | North Bengal Medical College and Hospital | 5.0 | correct |
| 12 | GMCH, Tirunelveli (Tamil Nadu) | Government Tirunelveli Medical College and Hospital (Palayamkottai) | 16.2 | correct |
| 13 | Government Medical College & Hospital, Thiruvananthapuram | Government Medical College, Thiruvananthapuram | 115.0 | correct (VF coords wrong, PIN 695009 is Thiruvananthapuram) |
| 14 | Darbhanga Medical College Hospital (Bihar) | Darbhanga Medical College (Laheriasarai) | 31.9 | correct |
| 15 | Govt. Medical College, Goa | Goa Medical College (Bambolim) | - | correct |
| 16 | Govt. General Hospital & Medical College, Kurnool (AP) | Government General Hospital (Kurnool) | 360.4 | correct (VF coords wrong, PIN 518002 is Kurnool) |
| 17 | Murshidabad Medical College (West Bengal) | Murshidabad Medical College & Hospital (Berhampore) | 29.9 | correct |
| 18 | MKCG Medical College, Behrampur (Odisha) | MKCG Medical College and Hospital, Berhampur | - | correct |
| 19 | SCB Medical College, Cuttack (Odisha) | SCB Medical College and Hospital, Cuttack | 1.8 | correct |
| 20 | Chengalpattu Govt. Medical College & Hospital (TN) | Chengalpattu Government Hospital | 5.0 | probably correct (the college's attached hospital) |

Precision on the hand check: 19 / 20 (95%), one merged VF record.

What the VF data claims for the 20 matched TCFs (audit/claims grades for service
"trauma", plus a regex over specialties/procedure/equipment/capability/description):
- grade: medium 10, weak 5, enum_only 3, none 2, strong 0.
- 11 / 20 have an explicit trauma, casualty or accident word; 18 / 20 have at least
  "emergency" (often only the specialty code emergencyMedicine); 2 / 20 (RIMS Imphal,
  Burdwan MCH) say nothing about trauma or emergency.
- So these are positive labels the VF text under-states: no designated TCF was graded
  "strong" by the claims audit.

Outputs (gitignored, in data/external/mohfw_trauma_196/): tcf_196.csv,
tcf_vf_matches.csv (accepted), tcf_vf_candidates.csv (all TCFs with best candidate and
score), join_stats.json.

## Product role

- Evidence: a government designation badge on a VF facility ("MoHFW-funded Level II
  Trauma Care Facility, NPPMTBI; 2019 status: functional"), cited to the MoHFW PDF.
- Routing for trauma queries: the 196 TCFs are a candidate set in their own right, also
  where no VF row exists (176 of them). They need coordinates first (see plan).
- Labels: 20 (about 24 after review) positive trauma labels; small, but useful to
  measure recall of the trauma claim grader on public hospitals.
- Uncertainty to show: funded is not functional; 73 12th-plan TCFs had "no TCF
  functional" in 2019 and nothing newer was found; levels for 8 rows come from the
  amount only.

## Ingest plan for Databricks Free Edition

1. Upload tcf_196.csv and tcf_vf_matches.csv (both under 100 KB) to a Unity Catalog
   volume, e.g. /Volumes/<catalog>/external/raw/mohfw_trauma_196/, from a laptop (the
   workspace cannot reach mohfw.gov.in or archive.org).
2. Tables: `external.mohfw_trauma_tcf` (196 rows: sno, state, name, amount_cr, level,
   brief_status, source_url, source_page) and `external.mohfw_trauma_tcf_vf_link`
   (tcf sno, vf unique_id, score, hand_check verdict). Add the 4 review-band rows after
   a human confirms them.
3. TCF coordinates: geocode the 176 unmatched TCFs from the place token with the PIN
   centroid table (audit/geo/pin_centroids.parquet) or a one-off manual pass; store
   lat/lon with a precision flag ("district centroid").
4. Refresh: none needed (the scheme stopped adding TCFs after 2017); re-run fetch.sh
   only if MoHFW publishes a new status list.
5. App screens: trauma results card (badge, level, 2019 status, citation link) and the
   "how we decided" panel (government designation as one weighted evidence item).

Effort: about 4 hours (upload and tables 1h, geocoding the unmatched TCFs 2h, app badge
and citation 1h).
