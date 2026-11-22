# NMC college and course list (nmc_colleges)

Regulator list of every MBBS teaching college in India, with each college's
approved PG and super-specialty courses (MD, MS, DM, MCh, diplomas). An
approved DM Nephrology or MCh CTVS seat means the regulator inspected and
approved that department, so it is independent evidence for the matching
service at the attached teaching hospital.

- Publisher: National Medical Commission (NMC), Government of India
- Page: https://nmc.org.in/page/information-desk-for-students-to-study-in-india-list-of-college-teaching-mbbs
- Endpoints used (JSON, found behind that page):
  - `GET https://nmc.org.in/college-courses/list?page=N&per_page=100` (MBBS list, 9 pages)
  - `GET https://nmc.org.in/college-courses/detail/{college_id}` (one per college, 839 calls)
  - headers `Accept: application/json`, `X-Requested-With: XMLHttpRequest`
- Fetched 2026-11-21, 13:51 to 14:21 local time, about 1.1 s between requests.
- robots.txt (https://nmc.org.in/robots.txt): `User-agent: *` / `Disallow:` (empty, so all allowed).

## Licence and terms

There is no open-data licence. Two pages apply.

https://nmc.org.in/page/disclaimer (section "Disclaimer on Website"):

> National Medical Commission ("NMC") authorizes you to copy any documents
> contained on this Site, which are not the property of third parties,
> provided that such use shall be for non-commercial purposes only by you or
> within your organization. [...] Any other use of materials contained on this
> Site including without limitation, reproduction, distribution, modification,
> adaptation and republication without the written permission of NMC is
> expressly prohibited.

https://nmc.org.in/page/terms-of-use is an old Medical Council of India
template ("(c) 2010 by Medical Council of India and/or its suppliers. All
rights reserved.", Washington State law). It contradicts the disclaimer, which
names Indian law and Delhi courts. We treat the disclaimer as the current terms.

What this means for us (my reading, not legal advice):
- Private team repo, non-commercial datathon: allowed as copying "within your
  organization". The raw files stay in `data/external/` (gitignored) anyway.
- Public demo: showing a short fact with a citation ("NMC lists D.M.
  Nephrology, 2 seats, at this college", link to the NMC page) is low risk.
  Republishing the dump or a modified copy is not allowed without NMC's
  written permission. If the demo is public, do not offer the table for
  download; show per-facility facts and link to NMC.

Contact fields (email, mobile, landline, fax, contacts) are dropped by
`fetch.py` before saving. Some are personal gmail addresses and we do not need them.

## Files

Scripts (this directory):
- `fetch.py`: `.venv/bin/python -I external/nmc_colleges/fetch.py data/external/nmc_colleges` (about 30 min, resumable)
- `join.py`: `.venv/bin/python -I external/nmc_colleges/join.py data/external/nmc_colleges .` (inspection, matcher, service labels)
- `test_join.py`: self-check for the name gate, `.venv/bin/python -I external/nmc_colleges/test_join.py`

Data (`data/external/nmc_colleges/`, 7.0 MB total):
- `list.json` (839 MBBS rows), `details.jsonl` (839 colleges with courses)
- `nmc_colleges.parquet` (839 rows), `nmc_courses.parquet` (11,148 rows)
- `nmc_service_labels.parquet` (college x service x tier), `nmc_vf_matches.parquet` (81 pairs)
- `join_stats.json` (all numbers below)

## Inspection

- 839 colleges in 34 states/UTs; 447 Government, 391 Private, 1 Trust. MBBS seats total 140,664 (matches the API's `total_seats`).
- 11,148 course rows: MD 6,400, MS 2,405, MBBS 839, DM 640, MCh 580, Diploma 284. No course row has 0 or null seats.
- Freshness: `updated_date` is 2026-11-04 for 802 of 839 rows, latest 2026-11-16. Recognition text covers academic year 2026-27.
- Null rates (detail): pincode 27.8%, lop_date 30.9%, city 3.0%, website 1.4%, university 0.4%, remarks 97%.
- Usable PIN: 606 have a 6-digit PIN (after falling back to a PIN inside the address), 599 of those are in the India Post directory.
- PIN contradicts the state in 2 rows: Sundarlal Patwa Govt. Medical College (Madhya Pradesh, PIN 770020 is Odisha) and VSS Institute, Burla (Odisha, PIN 221508 is Uttar Pradesh).
- State spelling "Chattisgarh" (NMC) vs "Chhattisgarh" (India Post); normalized in `state_key`.
- Missing: AIIMS, JIPMER, PGIMER, SGPGI, Nizam's and other Institutes of National Importance are not in this list. Courses are listed per college, not per attached hospital, and there are no bed counts or coordinates.

## Join test against facilities.parquet

Matcher (`join.py:match`):
1. Normalize names (lowercase, `&` to `and`, AIIMS/govt/instt/hosp expansions, drop stop words). VF names containing ayurved, homoeo, dental, unani, siddha, nursing, veterinary, physiotherapy or pharmacy are skipped, since NMC lists allopathic MBBS colleges only.
2. Geo gate: if the NMC PIN has a centroid (audit/geo/pin_centroids.parquet), candidates are VF rows with the same PIN or within 10 km (VF coordinates or VF PIN centroid). Otherwise the candidates are VF rows in the same state, and the name bar rises to WRatio 95.
3. Name gate: WRatio >= 88, plus the "core" tokens (name minus generic words such as medical, college, hospital, government, and minus both records' city words) must agree (ratio >= 88 or one contained in the other). If one side has a distinctive name and the other only a place ("Jakir Hossain Medical College, Burdwan" vs "Burdwan Medical College"), the pair is rejected. A second route accepts exact PIN plus one full name contained in the other (VF names often carry the street address).

Results (denominator: 839 NMC colleges):
- 79 colleges matched (9.4%) to 81 VF rows (81 pairs; 2 colleges match two duplicate VF rows each).
- On the VF side, 163 rows have a medical-college-style name (excluding dental/AYUSH/nursing); 75 of them are matched. Most of the 88 unmatched are institutions absent from the NMC list (8 AIIMS rows, SCTIMST, Nizam's, SGPGI, PGIMER Bhubaneswar, corporate hospitals named "Institute of Medical Sciences") or attached-hospital names (e.g. "Shri Maharaja Gulab Singh Hospital, Government Medical College Jammu").
- The low match rate means the VF dataset contains few medical colleges, not that the matcher misses them.

Hand check of 20 random matched colleges (seed 7), judged on name, PIN and city:

| # | NMC college | VF record | Verdict |
|---|---|---|---|
| 1 | Prakash Institute of Medical Sciences & Research, Sangli | Prakash Institute of Medical Sciences & Research, Islampur 415409 | correct (Islampur is in Sangli district) |
| 2 | Dr. Vasantrao Pawar Med. Col. Hosp. & Research Centre, Nasik | Dr. Vasantrao Pawar Medical College Hospital & Research Center, Nashik | correct |
| 3 | Government Medical College, Purnea | Government Medical College and Hospital, Purnea (PIN 845438, coordinates in Bettiah) | name correct, VF record location wrong (PIN and coordinates are Bettiah, West Champaran) |
| 4 | Believers Church Medical College Hospital, Thiruvalla | same, Thiruvalla 689103 | correct |
| 5 | Tirunelveli Medical College | Government Tirunelveli Medical College and Hospital, Palayamkottai 627011 | correct |
| 6 | Naraina Medical College & Research Centre | same, Kanpur 208020 | correct |
| 7 | Goa Medical College, Panaji | Goa Medical College, Bambolim 403202 | correct |
| 8 | Father Mullers Medical College, Mangalore | Father Muller Medical College, Mangalore | correct |
| 9 | Theni Government Medical College | Government Medical College and Hospital, Theni | correct |
| 10 | Shyam Shah Medical College, Rewa | same | correct |
| 11 | Jawaharlal Nehru Institute of Medical Sciences, Imphal | same | correct |
| 12 | Burdwan Medical College | Burdwan Medical College Burdwan 713104 | correct |
| 13 | Jalpaiguri Government Medical College | ... and Hospital, 735101 | correct |
| 14 | Rajendra Institute of Medical Sciences, Ranchi | same, 834009 | correct |
| 15 | Raiganj Government Medical College & Hospital | same, 733134 | correct (VF coordinates flagged by geo audit, 153 km from PIN) |
| 16 | MKCG Medical College, Berhampur | MKCG Medical College and Hospital, 760004 | correct |
| 17 | Vydehi Institute of Medical Sciences, Bangalore | same, 560066 | correct |
| 18 | Darbhanga Medical College, Laheriasarai | Darbhanga Medical College, 846003 | correct |
| 19 | Silchar Medical College | Silchar Medical College & Hospital, 788014 | correct |
| 20 | Pt. JLN Government Medical College, Chamba | Government Medical College Chamba, 176310 | correct |

Precision: 19/20 clean, 1/20 right name on a VF record whose location belongs to another town.
Across all 81 pairs I also found two merged VF records: "Hi-Tech Medical College & Hospital, Bhubaneswar" carries
the Rourkela campus PIN 769004, and "SRM Medical College Hospital and Research Centre" has city Kattankulathur
(Chennai campus) with the Trichy campus PIN 621105. The NMC list has both campuses of each with separate PINs,
so it is a useful check for this kind of contamination.

### Service evidence vs VF claims

"VF claims" = the facility has a non-"non_offer_only" row for that service in
`audit/claims/out/grades.parquet`. Strong course = a department that runs the
service; support = weaker proxy. Counts are matched colleges.

| Service | NMC course used | NMC colleges with it (all 839) | Matched | VF claims | VF silent |
|---|---|---|---|---|---|
| dialysis | D.M. Nephrology | 76 | 15 | 7 | 8 |
| cardiac surgery | M.Ch. CTVS / Cardio Vascular | 55 | 12 | 9 | 3 |
| cardiac surgery (support) | D.M. Cardiology | 82 | 13 | 3 | 10 |
| NICU | D.M. Neonatology | 35 | 3 | 0 | 3 |
| NICU (support) | M.D. Paediatrics | 454 | 63 | 15 | 48 |
| C-section | M.S./M.D. Obstetrics and Gynaecology | 500 | 67 | 9 | 58 |
| trauma | M.D. Emergency Medicine or M.Ch. Neurosurgery | 230 | 35 | 28 | 7 |
| trauma (support) | M.S. Orthopaedics | 260 | 33 | 29 | 4 |
| MRI (support) | M.D. Radio-diagnosis | 413 | 60 | 24 | 36 |
| burns | M.Ch. Plastic Surgery | 98 | 18 | 5 | 13 |
| ICU | D.M. Critical Care | 36 | 3 | 3 | 0 |
| ICU (support) | M.D. Anaesthesiology | 470 | 64 | 36 | 28 |

The "VF silent" rows are candidate positive labels the VF text missed (for
example 58 matched colleges run an approved OBG PG course but the VF text
does not claim C-section). The "VF claims" rows are corroborated claims. The
course-to-service mapping is a proxy: a PG seat shows the department exists,
not that the service runs 24x7 today.

## Product role

- Evidence: a "Regulator-verified departments" line on each matched facility,
  e.g. "NMC approves D.M. Nephrology (2 seats) here, updated 2026-11-04", with
  the NMC link. Raises confidence for dialysis, cardiac surgery, NICU,
  obstetrics, trauma and burns at teaching hospitals.
- Labels: matched pairs give weak positive labels for the service classifier.
- Data quality: NMC PIN vs VF PIN/coordinates flags merged VF records (Hi-Tech,
  SRM, Purnea above).
- Tier signal: an NMC teaching college is a tertiary referral centre.
- Gap: 760 NMC colleges have no VF record. They could be added as new
  candidate facilities (PIN centroid as location, low location confidence).

## Ingest plan (Databricks Free Edition)

1. Run `fetch.py` and `join.py` locally (Databricks compute cannot reach nmc.org.in).
2. Upload the four parquet files to a Unity Catalog volume, e.g.
   `/Volumes/workspace/external_raw/nmc_colleges/2026-11-21/` (catalog `workspace` is the writable one per audit/capabilities/CAPABILITIES.md; schema and volume names are proposals, not created).
3. Tables: `workspace.external.nmc_colleges`, `workspace.external.nmc_courses`,
   `workspace.external.nmc_service_evidence` (from nmc_service_labels), `workspace.external.nmc_vf_xref` (from nmc_vf_matches, keyed on `unique_id`).
4. Refresh: monthly, or before a demo; NMC updated 802 rows on 2026-11-04.
5. App screens: facility detail / "why this facility" evidence panel (regulator line with citation), and the ranking score as a corroboration feature.

Effort: about 4 hours (upload and tables 1 h, evidence panel wiring 1.5 h, alias list for attached-hospital names and re-check 1.5 h).
