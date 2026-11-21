# LaQshya certification master data (Labour Room and Maternity OT)

NHSRC (MoHFW) list of public facilities whose Labour Room (LR) or Maternity Operation Theatre (MOT)
has been certified under LaQshya. For us a Maternity OT certificate is dated, third-party evidence that
a facility does caesarean sections, and the validity date tells us how stale that evidence is.

## Source

- Landing page: https://qps.nhsrcindia.org/laqshya/quality-Certification-Status (read 2026-11-21).
  It lists one file, "LaQshya Certification Status", labelled "*Updated till- : 30-09-2026", and the
  Download link points to the file below.
- File accessed: https://qps.nhsrcindia.org/sites/default/files/2026-04/LaQshya_Master_data-08-04-2026.pdf
  HTTP 200, 998,821 bytes, Last-Modified Wed, 08 Apr 2026 11:53:55 GMT, PDF 1.7, 70 pages,
  sha256 b4b84ea39dc210944eb3290b945c113b949c84473685d50e2a8bd7596d26f8bd.
- Freshness: the newest "Date of Result" in the file is 2026-03-25, which fits the 08-04-2026 file name.
  The "updated till 30-09-2026" label on the page does not match the file content; treat the data as
  current to about April 2026.
- robots.txt on qps.nhsrcindia.org returns 403, so no crawl rules could be read. We made 5 requests
  in total, at least 1 s apart, and downloaded only the one linked file.

## Licence and terms

The QPS site footer says "Copyright (c) 2021. Websites managed by NHSRC, Ministry of Health & Family
Welfare, Government Of India" and links to the NHSRC policies.

https://nhsrcindia.org/copyright-policy (read 2026-11-21):

> Material featured on this site may be reproduced free of charge in any format or media without
> requiring specific permission. This is subject to the material being reproduced accurately and not
> being used in a derogatory manner or in a misleading context. Where the material is being published
> or issued to others, the source must be prominently acknowledged.

https://nhsrcindia.org/terms-and-conditions adds that the content "should not be construed as a
statement of law", users should verify with NHSRC, and NHSRC is not liable for loss from use of the data.

What this means for us (our reading, not legal advice):
- Private team repo: allowed. The raw PDF sits in data/external/ (gitignored) anyway; the parsed
  table can be committed with attribution.
- Public demo: allowed, if we reproduce the rows accurately, show "Source: NHSRC LaQshya certification
  status, file dated 08-04-2026" next to any LaQshya fact, and do not overstate it. An expired
  certificate must be shown as expired, not as current certification.

## Fetch and run

```
/Users/karthikvattem/projects/datathon/external/laqshya_master/fetch.sh
```

It downloads the PDF (curl, 300 MB cap), records headers and sha256, converts it with poppler
`pdftotext -layout` (laqshya.txt, for reading) and `pdftotext -tsv` (words.tsv, word boxes), then runs
`parse.py` (to laqshya.parquet) and `join.py` (to the match files and join_stats.json). The downloaded file
is only read by pdftotext and by Python started with -I; nothing from it is executed.
`python -I test_join.py` checks the matcher rules.

Outputs in /Users/karthikvattem/projects/datathon/data/external/laqshya_master/:
laqshya.parquet (2,173 certificate rows), laqshya_facilities.parquet (1,355 facilities, latest validity per
department), laqshya_vf_matches.parquet (66 pairs), join_stats.json, handcheck_sample.csv, join_stdout.txt.

## Parsing

The PDF is an XLSX printout. Column x positions are the same on all 70 pages (state 80, district 163,
type 232, name 261, department 421, Certified 488, Conditionality 534, result date 563, validity 623 pt),
so parse.py assigns words to columns by x. Two layout quirks are handled:
- Wrapped cells are bottom-aligned, so a row owns every word between the previous row's date line and its
  own (for example "Raja Deosharan District Hospital / Jashpur").
- Overflowing text is either glued to the next word ("PradeshEast", "VishakhapatnamSDH"; split at the
  camelCase boundary) or sits in the neighbour column (moved back: name text found in the department
  column, district text found in the type column).

"Certified" vs "Conditional" comes from which of the two columns holds the "Yes". The parser asserts 2,173
rows and contiguous serials 1..2173; it found exactly that, and 2,173 date pairs in the text.

## Inspection

- 2,173 rows, 32 states/UTs, 1,355 distinct (state, district, name).
- Fields: sno, state, district, ftype (DH 1,026, SDH 540, CHC 410, MC 197), name, dept
  (Labour Room 1,229, Maternity OT 902, blank 42), status (Certified 1,642, Conditional 531),
  date_result (2018-08-07 to 2026-03-25), date_validity (2019-08-06 to 2029-03-16), page.
- Blank rates: dept 1.9% (the 42 rows appended at the end, 2132-2173), district 0.05% (1 row, Delhi), all
  others 0%.
- Validity spans: about 3 years for full certification (1,473 rows near 1,095 days), 1 year (656) or
  6 months (22) for conditional or newer certificates.
- Only 509 of 2,173 rows were still valid on 2026-11-21 (Maternity OT 200, Labour Room 272, blank dept 37).
  Most of the file is expired history.
- Errors found:
  - 16 exact duplicate rows. The appended block repeats itself: rows 2132-2142 = 2143-2153, and
    2163-2165 = 2171-2173.
  - 7 rows have a validity date one day before the result date (559, 632, 827, 891, 980, 1477, 1815),
    almost certainly a wrong year.
  - District and name typos: "Vadodra" next to "Vadodara", "Kozikhode", "Civil Hospiral", "Bobblli".
  - Wrong district: row 601 "DH Mandya" is listed under Koppal.
  - The same facility appears under different district spellings or types, for example Srikalahasti
    as DH and as SDH, or Sivaganga next to Sivagangai.
  - New Andhra Pradesh districts (Eluru, Konaseema, Annamaya) do not match older PIN-directory names.

## Join test against the Virtue Foundation facilities

LaQshya has no PIN or coordinates. The matcher (join.py) works in 5 steps:
1. Block on state. VF state comes from cleaning/geo_identity/facility_location.parquet.
2. Normalize names: expand DH, SDH, CHC, MC, DWH and similar, then strip generic words (district,
   hospital, civil, government, medical college, ...) to get the place-like "core" tokens.
3. Accept a pair if the cores agree (rapidfuzz token_sort_ratio >= 88), or if the VF core is a subset of
   the LaQshya core and the only extra LaQshya words are the district name. Either way the place must
   agree: district ratio >= 85, or a core token appears in the VF city. A near-identical full name
   (ratio >= 95) also passes.
4. The VF row must look public: operatorTypeId = public, or a public-hospital word in its name.
5. The facility kinds must be compatible: DH and SDH are interchangeable, but medical college, women and
   child hospital and CHC/PHC are kept apart.

Results:
- 63 of 1,355 LaQshya facilities matched (4.65%), as 66 pairs on 58 VF rows.
- From the VF side, 56 of the 465 rows with operatorTypeId = public matched (12.0%), and 2 VF rows
  tagged private matched (GMERS Gotri and Civil Hospital Barnala, both actually public, so the VF tag
  is wrong).
- The low rate is mostly coverage: VF holds about 469 public rows nationwide, and many of them are AIIMS,
  ESI, PHCs or specialty hospitals that LaQshya does not certify. We have not measured matcher recall
  against a labelled set.
- 3 LaQshya facilities map to 2 VF rows each (VF duplicates such as the two Kanyakumari GMC rows and the
  two Sub District Hospital Karad rows). 8 VF rows are matched by 2 LaQshya entries (duplicate LaQshya
  spellings, for example Theni, Sivaganga/Sivagangai and SSG Hospital under Vadodra and Vadodara).

### Hand check (20-pair random sample, seed 7, handcheck_sample.csv)

| # | LaQshya (district, type, name) | VF name (city) | verdict |
|---|---|---|---|
| 1 | Tenkasi, DH, District HQ Hospital Tenkasi | Government District Headquarters Hospital (Tenkasi) | correct |
| 2 | Nashik, DH, District Hospital nashik | District Hospital, Nashik (Nashik) | correct |
| 3 | Kheda, DH, General Hospital Nadiad | Civil Hospital Nadiad (Nadiad) | plausible: Nadiad's government hospital, but named differently |
| 4 | Amravati, DH, DWH Amravati | District Women Hospital, Amravati | correct |
| 5 | Hailakandi, DH, SK Roy Civil Hospital | SK Roy Civil Hospital (Hailakandi) | correct |
| 6 | Hyderabad, MC, Niloufer Hospital | Niloufer Hospital (Hyderabad) | correct |
| 7 | Ranchi, MC, Rajendra Institute of Medical Sciences | Rajendra Institute of Medical Sciences (Ranchi) | correct |
| 8 | Goalpara, DH, Civil Hospital Goalpara | Goalpara Civil Hospital | correct |
| 9 | Vadodara, DH, SSG Hospital | SSG Hospital (Vadodara) | correct |
| 10 | Chengalpattu, MC, Chengalpattu Medical College & Hospital | Chengalpattu Government Hospital | plausible: the medical college runs the government hospital |
| 11 | Kangra, DH, Zonal Hospital Dharamshala | Zonal Hospital Dharamshala | correct |
| 12 | Thoothukudi, MC, Thoothukudi Medical College | Government Medical College, Thoothukudi | correct |
| 13 | Theni, MC, Theni medical College & Hospital | Government Medical College and Hospital, Theni | correct |
| 14 | Tuticorin, MC, Thoothukudi Medical College | Government Medical College, Thoothukudi | correct (LaQshya duplicate of #12) |
| 15 | South 24 Parganas, MC, Diamond Harbour Government Medical College | Diamond Harbour Government Medical College and Hospital | correct |
| 16 | Champhai, DH, DH Champhai | Champhai District Hospital, Champhai | correct |
| 17 | Dausa, DH, DH Dausa | Government District Hospital Dausa (Dausa; VF district says BARAN) | correct |
| 18 | Mandya, DH, DH Mandya | District Hospital, Mandya (VF district says MANDLA) | correct |
| 19 | Jodhpur, MC, Umaid Hospital | Umaid Hospital (Jodhpur) | correct |
| 20 | Hapur, DH, DISTRICT COMBINED HOSPITAL HAPUR | District Hospital Hapur | plausible: likely the same, not confirmed |

17 correct and 3 plausible, 0 wrong. We also read all 66 pairs and found no clear false match; 4 are in
the plausible group (rows 3, 10 and 20 above, plus Nashik "Civil Hospital", which is the district civil
hospital).

Earlier versions of the matcher produced false matches, and the current rules exist to reject them:
- "Aland TH Gulbarga" matched "Government General Hospital Gulbarga".
- "NMCH Patna" (Nalanda) matched "Patna Medical College".
- "J K Loan Hospital, Kota" matched "Government Medical College Kota".
- "DWH Raebareli" matched "J N Hospital".
- Two private hospitals matched on the city name alone ("New Korba Hospital", "Faridabad Medical Center").

Two pairs were lost to the tighter rules: "Civil Hospiral Udalguri" (a typo) and "Gandhi Nagar" vs
"Gandhinagar" in Jammu.

### C-section evidence vs VF claims

C-section claims come from cleaning/claims/out/grades.parquet, where a claim means a grade of strong,
moderate, weak or tag_only.

| matched LaQshya facilities | n | VF claims C-section | VF silent |
|---|---|---|---|
| with any Maternity OT certificate | 48 | 3 (1 strong, 2 moderate) | 44 (plus 1 graded attributed_elsewhere) |
| Maternity OT certificate valid on 2026-11-21 | 13 | 1 | 12 |
| Labour Room only, no MOT row | 15 | 1 | 14 |

So for 44 matched public facilities, LaQshya is the only evidence of C-section capability we have, and
these are new positive labels with a date. Labour Room only is not evidence that a facility lacks
C-section: the department may simply not have been certified yet.

## Product role

- Evidence: add a "Government quality certification" line to a facility card, for example "LaQshya
  Maternity OT certified 20/03/2023, valid to 19/03/2026 (expired)", with the source citation. Valid
  certificates raise confidence in C-section and high-risk delivery capability; expired ones are shown
  as historical evidence with lower weight.
- Labels: dated positive labels for csection (MOT) and for obstetric or delivery care (LR), to train or
  validate the claims grader on public facilities.
- Coverage is small inside VF (63 facilities). The full list of 1,355 certified public facilities is also
  a candidate list of facilities that are missing from VF for maternity search, but it has no
  coordinates, so it would need geocoding through the LGD/PIN gazetteer first.

## Ingest plan (Databricks Free Edition)

1. Run fetch.sh locally. The app does not need the PDF, because outbound internet from Databricks
   compute is restricted.
2. Upload laqshya.parquet, laqshya_facilities.parquet and laqshya_vf_matches.parquet to a Unity Catalog
   volume, e.g. /Volumes/workspace/external/raw/laqshya/.
3. Create Delta tables:
   - workspace.external.laqshya_certificates (one row per certificate)
   - workspace.external.laqshya_facilities
   - workspace.external.laqshya_vf_match (lq_id, unique_id, scores, match rule)
4. Add a view that joins the certificates to the facility table with is_valid = date_validity >=
   current_date(), so the app never shows an expired certificate as current.
5. Refresh by hand: NHSRC posts a new PDF a few times a year. Re-run fetch.sh with the new URL and
   re-upload. Check the parser's row-count assert first, since the 2,173 total will change.
6. App screens: the facility detail / evidence panel (certificate line plus citation) and the ranking
   explanation for the C-section and high-risk delivery services.

Effort: about 3 hours, covering upload and tables (1 h), the evidence panel and score feature (1.5 h),
and parser maintenance for a new file (0.5 h). It has not been done yet; nothing was written to the
workspace.
