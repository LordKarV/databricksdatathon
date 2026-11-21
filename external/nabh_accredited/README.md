# NABH accredited healthcare organisations

Join test of the NABH "Find a healthcare organisation" list against the Virtue Foundation (VF)
facility table. Fetched 2026-11-21. Status: usable with effort (licence is the main constraint).

## Source

- Publisher: National Accreditation Board for Hospitals and Healthcare Providers (NABH), a board
  of the Quality Council of India.
- Page: https://nabh.co/find-a-healthcare-organisation/
- Data endpoint (read from https://nabh.co/wp-content/themes/nabh/js/my-map.js, `fetchHospitals`):
  `POST https://nabh.co/wp-admin/admin-ajax.php` with form fields `action=get_hospitals`, `q`,
  `lat`, `long`, `selectedSpecText`, `page`, optional `specialities[]=<CODE>`.
  Response: JSON `{html, pagination:{total_pages,current_page,total_results}, mapData:[{name,lat,lng,address}]}`,
  25 cards per page.
- robots.txt (https://nabh.co/robots.txt) disallows `/wp-admin/` but explicitly allows
  `/wp-admin/admin-ajax.php`.

## Licence and terms

https://nabh.co/terms-and-conditions/ (effective and last updated 15 August 2025), section
"Intellectual Property Rights":

> All content available on this website - including logos, graphics, training manuals,
> documentation formats, and certification material - is the intellectual property of NABH
> and/or QCI unless otherwise indicated. You may not reproduce, distribute, or publish any part
> of this content for commercial purposes without prior written consent from NABH. Misuse may
> lead to legal consequences, including claims of copyright infringement.

No open licence. The restriction is on commercial reproduction. My reading (not legal advice):

- Private team repo: keep the scripts in git; keep the data out (it lives under the gitignored
  `data/external/`). Each teammate can re-run `fetch.py`. Low risk as non-commercial research.
- Public, non-commercial datathon demo: showing derived fields (accreditation status, number,
  link to NABH's own certificate PDF) with attribution to NABH is likely acceptable, but it is
  unverified. Do not republish the full list as a download. If the project goes commercial,
  ask NABH for written consent first.

## Fetch steps

Scripts are in this directory and only read and write paths given as arguments.

```
PY=/Users/karthikvattem/projects/datathon/.venv/bin/python
OUT=/Users/karthikvattem/projects/datathon/data/external/nabh_accredited
$PY -I fetch.py $OUT all                      # 865 pages, about 50 min at the observed 3 s/page
$PY -I fetch.py $OUT counts                   # total_results per specialty code -> spec_counts.json
$PY -I fetch.py $OUT spec DIA EMD TRN ONC NPH CAR OBG   # what was fetched
$PY -I parse.py $OUT                          # -> nabh_hco.parquet, nabh_hco_specialty.parquet
$PY -I match.py $OUT data/raw/facilities.parquet audit/geo/facility_geo.parquet audit/geo/pin_centroids.parquet
```

`fetch.py` sleeps 1 s between requests, retries 3 times, saves gzipped raw JSON per page and
skips pages already on disk, so it resumes. `parse.py` skips any specialty whose pages are
incomplete (ICU was stopped at 16 of 492 pages and is not used). Not fetched: ICU (492 pages),
IMG (166) and the other 30 codes; run `fetch.py ... spec ICU IMG` to add them. Phone numbers
are not kept, because small clinics often list a personal mobile. Signed S3 query strings on the
certificate links are removed.

Raw data on disk: 19 MB in total (6.8 MB for the 865 unfiltered pages).

## What is in it

`nabh_hco.parquet`: 21,615 rows (pagination total on 2026-11-21; it was 21,609 in an earlier
probe, so the list is live). Fields: name, address, pin (6-digit tail of the address), addr_city,
addr_state, acc_no, cert_url, website, status, remarks, badge_class, nomen, prefix, lat, lng.

- acc_no: 21,576 distinct values. 30 rows are exact duplicates (pages shifted while fetching)
  and 370 repeat a (name, address) pair, usually one facility holding two programmes.
- Missing: pin 21.7%, lat/lng 6.6%, website 67.9%, status 2.1% (status comes from the badge
  text, or from "Accredited/Renewed on Nth Edition" remarks).
- status: Certified 8,686, Empaneled 6,827, Accredited 4,127, Renewed 1,508, missing 460,
  typo "Acredited" 7.
- The list mixes programmes, recognisable from the acc_no prefix: PESHCO 6,109 and PEH 1,671
  (entry-level SHCO and hospital certification), HOS 1,870 / EYE / DEN (CGHS and ECHS
  empanelment), H 1,843 (full hospital accreditation), SHCO 1,254, ECO 691 (eye), D 591 (dental),
  AH 469 (Ayush), MIS 421 (imaging), N 255 (nursing excellence), BB 127 (blood bank), LAB 124,
  and others. "Certified" entry level is not the same as full accreditation.
- Freshness: the year in acc_no runs from 2015 to 2026 (2025: 4,084, 2026: 3,410). The list
  shows current holders; expired or withdrawn accreditations are not listed.
- Geography: 39 addresses are in Nepal. 61 coordinates fall outside an India bounding box (one
  lat is 423443). 292 PINs are not in the India Post directory. For the 15,531 rows with both a
  PIN centroid and coordinates, distance from the PIN centroid: median 1.96 km, p90 14.5 km,
  p95 32.2 km, p99 535 km; 1,011 rows are more than 25 km off. Coordinates look geocoded from
  the address and should not override a PIN. Example: "Apex Hospital", address PIN 440014
  (Nagpur), coordinates in Delhi.
- State strings are messy ("Chattisgarh" and "Chhattisgarh", "Orissa" and "Odisha",
  "Select State", "Bangalore" as a state). Goa addresses sometimes carry "Maharashtra".

`nabh_hco_specialty.parquet`: (acc_no, spec_code) for 7 codes. Per-code totals from the site:
DIA 1,743, NPH 3,100, OBG 7,571, EMD 1,502, CAR 3,097, ONC 2,041, TRN 636, ICU 12,277,
IMG 4,140 (all 39 codes are in `spec_counts.json`). What a code means is not documented.
It is probably the specialties the organisation declared, not an audited scope. Some codes
are clearly broken: AMBULANCE returns the whole list (21,615), and HOM (homeopathy) returns
9,198 rows, including "Aarogyam Hospital" and "Aarthi Scans". Only DIA, NPH, OBG, EMD, CAR,
ONC and TRN were fetched. Treat them as weak, self-declared evidence.

## Join test

Left side: the 9,970 VF rows in `audit/geo/facility_geo.parquet` (the cleaned geo table; 1,318
of them mention "NABH" in name or text). Service text comes from `data/raw/facilities.parquet`.

Matcher (`match.py`):
- Names are lower-cased. Parentheticals ("(A Unit of ...)"), possessive "'s" and generic words
  (hospital, clinic, pvt, ltd, centre, care, multispeciality, lab, imaging, ...) are removed,
  and initials are joined ("R. S. Gaur" becomes "rs gaur").
- Blocking: the same 6-digit PIN, or coordinates within 2 km.
- Score: rapidfuzz token_sort_ratio. A name scores 100 if every token of the shorter name (2 or
  more tokens, at least one of 3 or more letters) appears in the longer one.
- Accept: score >= 90, or score >= 80 when the PIN is the same and the points are within
  0.5 km. If the stripped name has one token, WRatio on the raw names must also be >= 85.
  The best NABH row per VF facility is kept.

Results (`match_stats.json`):
- Matched VF facilities: 2,061 of 9,970 (20.7%), to 2,042 distinct NABH rows.
- Of the 1,318 VF rows that mention NABH, 726 matched (55.1%). 592 did not. 1,335 matched rows
  never mention NABH.
- Status of matched rows: Certified 975, Accredited 473, Renewed 305, Empaneled 266, missing 42.
  Among the 726 matched rows that mention NABH (705 with a status), 252 hold only an entry-level "Certified" record
  and 87 only an "Empaneled" one, so a VF claim of "NABH accredited" is often stronger than what
  NABH lists.
- Signs of VF data problems among matches: 185 are more than 25 km from the NABH point despite a
  name and PIN match, 302 have a different PIN, and 260 already carry `geo_conflict` in the
  geo audit.

Unmatched NABH claimers: I searched the whole NABH list by name for 20 random VF rows that
mention NABH but did not match. 19 of 20 had no same-place name match. One ("Nano Hospital"
560076 against "Nano Hospitals" 560078) is a likely miss caused by adjacent PINs. That means
up to about 45% of VF NABH claims are unsupported by the current list. Some of these facilities
may be listed under a legal entity name, or their accreditation may have lapsed, so they are
"not found", not proven false.

### Hand check (40 random accepted matches, two seeds)

Final matcher, seed 7 (`handcheck_sample.csv`), all 20 correct:
1 Udai Omni Hospital Hyderabad = Udai Omni Hospitals Pvt. Ltd. (H-2023-1123);
2 Holy Family Hospital Mumbai 400050 (H-2010-0060);
3 Mehar Hospital Zirakpur 140603 (H-2024-1465; VF point 50 km off);
4 Madhuram Hospital Vadodara (VF PIN 362560 is wrong, points 0.03 km apart);
5 Soni Eye Care Centre Doraha 141421;
6 Dr. Panjabrao Deshmukh Memorial Medical College Amravati 444603 (HOS/2025/E3057);
7 Ruby General Hospital Kolkata 700107 (H-2015-0318);
8 Sukhda Multispeciality Hospital Hisar;
9 Goodwill Hospital and Maternity Home Jalandhar 144007;
10 Metro Umkal Hospital Rewari 123401 (VF point 72 km off);
11 Bajaj Eye Centre Panipat 132103;
12 Mahatma Gandhi Medical College Puducherry (N-2021-0142);
13 Avinash Hospital Dhanbad 826001;
14 Keshav Medical Centre Dehradun 248001;
15 Prabha Eye Hospital Palwal;
16 HCG Manavata Cancer Centre Nashik 422002 (VF point 567 km off);
17 Sree Uthradom Thirunal Hospital Trivandrum 695004;
18 Hi-Tech Emergency Hospital Patna 801503 (H-2026-1824);
19 Aravali Hospital Udaipur 313004;
20 Shree Siddhi Vinayak Hospital/Hospicare Bhilwara 311001.

Final matcher, seed 11 (`handcheck_sample2.csv`), 19 of 20 correct. Wrong: #10 "Venkat Dental
Solution Beta 1, Greater Noida" matched to "Noida Dental Hospital" (D-2025-0473). The long VF
name contains the token "noida", so the subset rule fired. Correct: RG Stone Urology Kolkata,
Miglani Nursing Home Karnal, Central Hospital and Maternity Home Jalandhar, Ujala Cygnus
Central Hospital Haldwani, Apple Dental Specialities Vizianagaram, Medipulse Hospital Jodhpur,
Shri Shyam Hospital Kotputli (VF point 97 km off), Suraj Eye Institute Nagpur, Perfect Tyagi
Hospital Delhi, Malnad Hospital Shimoga, Kamala Dental Thiruvananthapuram, Devi Eye Hospital
Bangalore, Save Sight Centre Delhi, HCG Bharath Hospital Mysore, Zoi Hospitals Attapur,
Patiala Heart Institute, Hooda Hospital Rohtak, Maax Super Speciality Hospital Shimoga, and
GS Multispeciality / G S Hospital Basti (plausible).

Precision on the hand check: 39 of 40 (97.5%). An earlier version of the matcher had three
error classes that the hand check exposed and that are now fixed: initials ("R.R." matching
"R K"), possessives ("Madaan's" producing a token "s") and partial token overlap. The remaining
error mode is a long VF name that contains place words. Recall is not measured.

### Service evidence (matched rows with any of the 7 fetched codes: 1,054)

| code | NABH lists it | VF text also claims it | VF silent | VF claims it, NABH does not list it |
|------|------|------|------|------|
| DIA dialysis | 227 | 100 | 127 | 199 |
| NPH nephrology | 488 | 389 | 99 | 242 |
| OBG obstetrics and gynaecology | 890 | 796 | 94 | 107 |
| EMD emergency | 297 | 253 | 44 | 550 |
| CAR cardiology | 531 | 465 | 66 | 293 |
| ONC oncology | 332 | 264 | 68 | 323 |
| TRN transplant | 127 | 87 | 40 | 184 |

VF claims use regexes over specialties, procedure, capability, description and equipment (see
`SERVICE_RE` in `match.py`; for example EMD also matches "trauma" and "casualty"). Rows where
NABH lists the service and VF agrees are candidate positive labels. "VF silent" rows are
evidence that the VF extraction missed a service. Rows where VF claims the service but NABH
does not list it are not negatives: the NABH codes are self-declared, undocumented and
incomplete.

## Product role

- Evidence: "NABH lists this facility: <status> (<acc_no>), certificate <cert_url>". This is
  a strong existence and quality signal, and it is citable to NABH's own PDF.
- Ranking feature: full accreditation (H, SHCO, ECO, ...) above entry-level certification
  (PESHCO, PEH) above empanelment (HOS, EYE, DEN), and above no record. Show it as an evidence
  tier, not a hidden weight.
- Overclaim check: VF says NABH but there is no match, or the match is only "Certified". Show
  "NABH claim not found in current NABH list".
- Weak labels: per-service agreement (table above) for training or calibrating the claim
  extractor.
- Geo: acc_no is the stable key once matched. NABH coordinates are geocoded and 6.5% are more
  than 25 km from their PIN, so use them only to corroborate.

## Ingest plan (Databricks Free Edition)

1. Locally: run fetch, parse and match. Do not fetch from Databricks, because outbound internet
   is restricted.
2. Upload `nabh_hco.parquet`, `nabh_hco_specialty.parquet` and `nabh_vf_match.parquet` to the
   volume `/Volumes/workspace/external/nabh/` (the `workspace` catalog is writable per
   CAPABILITIES.md).
3. Create the tables `workspace.external.nabh_hco`, `workspace.external.nabh_hco_specialty` and
   `workspace.external.nabh_vf_match` with `CREATE TABLE ... AS SELECT * FROM read_files(...)`.
4. App: the facility detail or "why this facility" panel shows the NABH badge, acc_no and
   certificate link. The ranking screen uses the accreditation tier as a feature. The
   data-quality view shows the overclaim flags.
5. Refresh: re-run monthly (the list is live and many numbers are dated 2025 to 2026). It takes
   about 50 min of polite fetching plus about 30 min per 300 specialty pages.

Effort: about 3 h to finish (fetch ICU and IMG, review borderline matches, upload and create
tables, wire the app panel). About 5 h were spent so far.

## Files

- Scripts: `fetch.py`, `parse.py`, `match.py` (runs `_selfcheck()` asserts on start).
- Data (gitignored): `/Users/karthikvattem/projects/datathon/data/external/nabh_accredited/`
  with `raw/`, `nabh_hco.parquet`, `nabh_hco_specialty.parquet`, `nabh_vf_match.parquet`,
  `nabh_geo_qc.parquet`, `match_stats.json`, `spec_counts.json`, `handcheck_sample*.csv`, and
  `terms.html`.
