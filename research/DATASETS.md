# Datasets and model report

Date: 2026-11-21. Audience: the team, deciding this weekend what goes into the Databricks App.

Every number below comes from a script run or a page read by the research subagents. Their scripts and
READMEs are under `/Users/karthikvattem/projects/datathon/external/<slug>/`; raw and derived data are
under `/Users/karthikvattem/projects/datathon/data/external/<slug>/` (gitignored). The model work is in
`research/model/` and the GPU notes in `research/gpu/GPU.md`. Nothing has been written to the Databricks
workspace, and nothing has been pushed to GitHub (the research steps were not allowed to run git).

"VF" means the provided Virtue Foundation facility table (10,088 rows). "Match rate" uses the denominator
named in each entry; they differ between datasets. Hand-check precision is on small random samples
(usually 20), so read it as a rough figure, not a measured rate. Recall was not measured for any matcher.

## 1. Recommended datasets, ranked

### Summary

| Rank | Dataset | Role | Licence for a public demo | Match rate | Hand check | Effort |
|---|---|---|---|---|---|---|
| 1 | NABH accredited list | evidence, labels | restricted (per-facility facts only) | 20.7% of 9,970 VF | 39/40 | 3 h |
| 2 | LGD archive (PIN to district) | geography | reproduce freely, credit LGD | 85.8% | 19/20, 1 ambiguous | 3 h |
| 3 | PIN code boundaries (evaluated, not used) | geography, location check | GODL | 61.7% inside stated PIN | 12/12, far flag 4/4 | 3 h |
| 4 | IDP NFHS district (NFHS-5; NFHS-6 provisional evaluated, not used) | need | ODC-BY | 98.2% of facilities | 20/20 | 3 h |
| 5 | MAP travel time to healthcare | travel time | CC BY | 98.6% | 20/20 raster values | 4 h |
| 6 | NMC medical colleges and courses | evidence, labels | restricted (per-facility facts only) | 79/839 colleges | 19/20 | 4 h |
| 7 | e-RaktKosh blood centres | evidence, routing, labels | no licence stated | 388/6,904 centres | 16/20 strict, 18/20 with likely | 4 h |
| 8 | LaQshya certification | evidence, labels (maternity) | NHSRC: reproduce freely, credit | 63/1,355 | 17/20 plus 3 plausible, 0 wrong | 3 h |
| 9 | HOT OSM health facilities | existence and location evidence | ODbL, share-alike | 35.1% | 15/20 (0 wrong among unflagged) | 4 h |
| 10 | MoHFW trauma care facilities (196) | evidence, routing, labels (trauma) | restricted (per-facility facts only) | 20/196 | 19/20 | 4 h |
| 11 | WorldPop R2025A | need (population) | CC BY 4.0 | 98.7% | 18/20 | 3 h |
| 12 | LGD district polygons | geography | CC0 mirror, do not draw as a map | 99.9% | 15/20, 4 wrong due to VF coordinates | 3 h |
| 13 | HMIS sub-district (IDP) (evaluated, not used) | need, district plausibility | ODC-BY | 91.8% district | 17/20 | 4 h |
| 14 | PMNDP dialysis counts | need, weak dialysis flag | NHSRC: reproduce freely, credit | state join 95.7% | Goa 1/1 precision, 1/8 recall | 3 h |

Status on 2026-11-22: four entries were evaluated and are not used by the model or the app. They are HMIS
sub-district (rank 13), the NFHS-6 2023-24 provisional columns (rank 4; the app shows NFHS-5), PIN code boundaries
(rank 3; only the location validation, `validation/location/`, reads it) and NPPMBI burn units
(section 2). What each used source changes in the scores and in the first answer is in
`validation/out/source_impact.csv` (`validation/source_impact.py`).

Total effort if everything is done: 48 h. Ranks 1 to 8 are about 27 h and cover evidence for all the
example services plus geography, need and travel time. Ranks 9 to 14 add corroboration and context.

### Common ingest path on Free Edition

Databricks compute cannot reach any of these hosts, so every dataset follows the same path:

1. Run the existing `fetch` and `join`/`match` scripts on a laptop (already done for all 14; outputs exist).
2. Upload the derived parquet or CSV to a Unity Catalog volume. The reports proposed several different
   names; we suggest one convention: `/Volumes/workspace/external/raw/<slug>/<date>/`, tables in
   `workspace.external.*` for lists and `workspace.geo.*` for geography. None of these exist yet.
3. `CREATE TABLE ... AS SELECT ... FROM read_files(...)` on warehouse 6a2f5637720a2c17.
4. The App reads small precomputed tables only. No polygon maths, raster work or model runs at request time,
   except the optional travel-time Dijkstra (see rank 5).

Workspace writes need the user's go-ahead; all research so far was read-only.

### Rank 1: NABH accredited list (`nabh_accredited`)

- Role: evidence of existence and quality, accreditation tier for ranking, overclaim flags, weak labels.
- Access: POST to `https://nabh.co/wp-admin/admin-ajax.php` (action `get_hospitals`), allowed by robots.txt.
  Full list fetched: 21,615 rows (865 pages). Specialty-filtered lists fetched for DIA 1,743, NPH 3,100,
  OBG 7,571, EMD 1,502, CAR 3,097, ONC 2,041, TRN 636. ICU (12,277 rows) and IMG were not fetched.
- Licence: no open licence. NABH terms (15 Aug 2025) forbid reproduction "for commercial purposes without
  prior written consent". Keep data out of git; in a demo show only per-facility status, acc_no and a link
  to NABH's own certificate PDF. Never offer the list as a download. Demo use is our reading, unverified.
- Join: PIN or 2 km blocking plus rapidfuzz name rules. 2,061 of 9,970 VF facilities matched (20.7%).
  Hand check 39/40 (97.5%); the one error was a long VF name whose place word fired the subset rule.
- What it found: of 1,318 VF rows that mention NABH, only 726 (55.1%) match. In a probe of 20 unmatched
  claimers, 19 had no same-place match, so up to about 45% of VF NABH claims are unsupported by the current
  list. Among claimers with a status, 252 of 705 hold only entry-level "Certified". 185 matches are over
  25 km apart and 302 have a different PIN, which feeds the location-conflict flags.
- Data caveats: the list mixes programmes (acc_no prefix: PESHCO 6,109 and PEH 1,671 entry level, HOS 1,870
  CGHS/ECHS empanelment, H 1,843 full accreditation). Specialty codes look self-declared and some are broken
  (AMBULANCE returns all 21,615 rows). Absence of a code is not a negative.
- Services: dialysis, nephrology, obstetrics, emergency, cardiology, oncology, transplant; ICU and imaging
  available but not fetched.
- App feature: "NABH lists this facility: status, acc_no, certificate link" on the evidence panel; a visible
  accreditation tier (full accreditation > entry-level certification > empanelment > no record);
  "NABH claim not found in the current NABH list" in the data-quality view.
- Ingest: upload `nabh_hco.parquet`, `nabh_hco_specialty.parquet`, `nabh_vf_match.parquet`. Still to do:
  fetch ICU and IMG (`fetch.py OUT spec ICU IMG`), review matches with score below 100 or distance over 25 km.
- Effort: 3 h. Refresh monthly (about 50 min for the full list).

### Rank 2: LGD archive, PIN to district (`lgd_archive_parquet`)

- Role: geography backbone. User PIN or village to a canonical LGD district code; candidate districts per
  facility PIN; the key that joins NFHS, HMIS and district polygons.
- Access: ramSeraph mirror, `https://ramseraph.github.io/opendata/lgd/data/metadata.json`, 9 Parquet files,
  sha256-checked, snapshot 2026-11-19, 15 MB.
- Licence: LGD copyright policy allows reproduction free of charge, accurately and with prominent
  acknowledgement. Fine for the repo and a public demo with the credit "LGD, Ministry of Panchayati Raj, via
  the ramSeraph mirror, snapshot 2026-11-19".
- Join: 8,510 facilities matched by PIN (85.8%). State agrees for 95.9%, city for 79.6%, and LGD district
  agrees with India Post district for 8,121 of 8,503 (95.5%). Hand check 19/20 correct, 1 ambiguous (a Delhi
  PIN spanning 5 districts).
- Caveats: 1,893 rural PINs span 2 or more districts and 27 span 2 states, so the app must say "this PIN
  spans N districts" rather than pick one silently. 1,214 valid facility PINs (mostly metro delivery PINs)
  are missing from LGD, so India Post stays as a fallback. No coordinates. LGD to NFHS-5 name match reaches
  642 of 706 NFHS districts.
- What it found: real record contradictions, for example a Muzaffarnagar centre with a Delhi PIN, which
  feed the contamination flags.
- Services: none (geography only).
- App feature: location search box (PIN or village to district), facility card line such as "PIN 201001 is
  in Ghaziabad per LGD; the record says Raebareli", district key for the need panel.
- Ingest: upload 9 Parquet files; build `pin_district`, `lgd_nfhs_district_map` and facility columns
  `lgd_district_code`, `n_candidate_districts`, `state_conflict`, `city_conflict`.
- Effort: 3 h.

### Rank 3: PIN code boundaries (`pincode_boundaries`)

- Role: location check per facility (inside stated PIN polygon, within 2 km, or N km away); user PIN to a
  polygon and centroid; reverse lookup from a point such as a highway hotspot.
- Access: `https://github.com/ramSeraph/indian_admin_boundaries/releases/download/postal/Datagov_Pincode_Boundaries.parquet`,
  26.6 MB, 19,312 polygons, data.gov.in vintage 09/05/2025 (read via Wayback; the live page returned 503).
- Licence: GODL, read in the Gazette text: use, adapt and publish for commercial and non-commercial purposes
  with attribution. The attribution line is in the README and must appear in the app.
- Join: 9,960 of 9,964 facilities with valid coordinates fall in some polygon. Of 9,598 with a polygon for
  their stated PIN, 5,925 (61.7%) are inside it, 7,264 (75.7%) within 2 km, and 1,047 (10.9%) more than
  100 km away. Hand check: 12/12 inside matches correct; 4/4 points more than 10 km away were real location
  conflicts; 4 points under 1 km outside were boundary jitter. Use a tolerance: flag over 2 km, conflict over
  10 km.
- What it found: the India Post directory centroid is itself wrong for some PINs (422009 Nashik is about
  165 km off), so 33 facilities the audit flagged at over 100 km are false alarms.
- Coverage gaps: 98.6% of India Post PINs; weakest Mizoram 90.9%, Delhi 92.2%, J and K 92.5%.
- Services: none.
- App feature: location-check badge on the facility card citing stated PIN, containing PIN and distance;
  better PIN centroid for user search; planner hotspot lookup.
- Ingest: upload the parquet; precompute `workspace.geo.facility_pin_check` (or upload
  `facility_pin_polygon_check.parquet`). ST functions work on the warehouse (`st_contains` returned true);
  `ST_GeomFromWKB` on this file was not run.
- Effort: 3 h.

### Rank 4: IDP NFHS district table (`idp-nfhs-district`)

- Role: local need. District C-section rate, institutional births, blood sugar and BP for 2015-16, 2019-21
  and 2023-24, keyed by LGD district code.
- Access: India Data Portal CKAN, `ckandev.indiadataportal.com` (the catalogued host refused connections),
  1.2 MB CSV, 1,995 rows x 129 columns.
- Licence: no record-level licence; the portal policy says public datasets are ODC-BY unless stated, reuse
  allowed with acknowledgement. Do not alter their values; label any derived score as ours.
- Join: IDP 2019-21 matched 705 of 706 rows of our raw NFHS-5 parquet, with values agreeing to 0.1 on
  C-section 705/705. Facilities to a 2023-24 district: 9,902 of 10,088 (98.2%). Crosswalk hand check 20/20.
- What it found: our raw NFHS-5 parquet has a wrong "Mizoram / Chandel" row (a duplicate of Manipur
  Chandel) and lacks Purba Bardhaman. This table should replace it.
- Caveats: 2023-24 values are provisional and were not compared against an official NFHS-6 district fact
  sheet (rchiips.org failed TLS). No 2023-24 rows for Chandigarh, Lakshadweep or Manipur. Andhra Pradesh
  2023-24 uses the old 13 districts. No NICU or dialysis indicator; blood sugar and BP are weak proxies.
- Services: C-section and high-risk delivery need; indirect NICU and dialysis proxies.
- App feature: need badge on results ("District C-section rate 2023-24: x% (NFHS-6, provisional)",
  labelled "district estimate, not facility data"); planner district ranking.
- Ingest: upload the CSV and `nfhs5_idp_district_map.csv`; keep `district_code` as STRING.
- Effort: 3 h.

### Rank 5: MAP travel time to healthcare (`map_travel_time_healthcare_2020`)

- Role: travel time. Remoteness of the user location, drive-minute ranking between candidates, a
  coordinate sanity flag, planner drive-time per district.
- Access: Malaria Atlas Project WCS, India clips of 3 layers (motorized time, walking time, friction),
  3 GeoTIFFs of 67 MB each. The global file (about 708 MB) was not fetched.
- Licence: CC BY (Earth Engine catalog says 4.0, the MAP policy page says 3.0). Either way, redistribution
  and demo use are allowed with attribution to Malaria Atlas Project, Weiss et al. 2020, Nature Medicine.
- Join: 9,944 of 10,088 facilities get a value (98.6%). Hand check: 20/20 raster values correct (5/5 also
  matched the server). Coordinates agreed with the stated city or PIN for 18/20.
- Coordinate flag: among facilities with motorized time over 30 min at their own point, 75% (24/32) are
  already flagged by the geo audit. The flag cannot see a facility moved to another city (it gets 0 min).
- Routing check: Dijkstra on the friction surface reproduced MAP's travel time at 12 random points
  (median error 0.0 min, max 1.4 min). Demo from rural Saharsa, Bihar to dialysis-claiming facilities:
  Begusarai 103 km / 156 min, Raiganj 125 km / 157 min, Darbhanga 106 km / 165 min. The top hit in that
  demo was a contaminated record, so routing must run after the geo filters.
- Caveats to show: data is nominally 2019, assumes ideal speed, and measures time to any hospital or
  clinic, not to a facility offering the service.
- Services: all (not service-specific).
- App feature: "nearest clinic of any kind is about X min by road (MAP 2019)"; rank candidates by modelled
  drive minutes with straight-line km alongside; location-suspect badge; planner table.
- Ingest: upload the 3 GeoTIFFs (about 201 MB) and the derived facility, PIN and district tables. For live
  routing, load the 55 MB friction array in the App and run a 301x301 windowed Dijkstra per query ("seconds
  in pure Python" per the report; App latency not measured).
- Effort: 4 h.

### Rank 6: NMC medical colleges and courses (`nmc_colleges`)

- Role: regulator-backed evidence of departments at teaching hospitals; weak positive labels; detects
  merged VF campus records.
- Access: `https://nmc.org.in/college-courses/list` and `/detail/{id}` JSON, robots.txt allows all. 839
  colleges, 11,148 course rows, updated 2026-11-04 for 802 rows.
- Licence: NMC disclaimer allows non-commercial copying "within your organization"; republication needs
  written permission. Short per-facility facts with a link to NMC in a demo look low risk (our reading).
  Contact fields were dropped at fetch time.
- Join: 79 of 839 colleges matched (9.4%) to 81 VF rows; 75 of 163 VF rows with medical-college-style names
  matched. Hand check 19/20; the one bad pair had the right name but a VF location in another district.
- What it found: two merged VF records (Hi-Tech Bhubaneswar carrying the Rourkela campus PIN; SRM
  Kattankulathur with the Trichy campus PIN).
- Service evidence among matched colleges (has course / VF claims / VF silent): DM Nephrology 15/7/8,
  MCh CTVS 12/9/3, DM Neonatology 3/0/3, OBG PG 67/9/58, Emergency Medicine or Neurosurgery 35/28/7,
  Plastic Surgery 18/5/13. A PG seat shows a department exists, not a 24x7 service.
- Gaps: AIIMS, JIPMER, PGIMER and other Institutes of National Importance are not in the list; no
  coordinates, no beds.
- Services: dialysis, cardiac surgery, NICU, C-section, trauma, burns, ICU, MRI (support).
- App feature: "NMC approves D.M. Nephrology (2 seats) here, updated 2026-11-04" with the NMC link; marks a
  tertiary referral centre.
- Ingest: upload the 4 parquet files; tables `nmc_colleges`, `nmc_courses`, `nmc_service_evidence`,
  `nmc_vf_xref`.
- Effort: 4 h.

### Rank 7: e-RaktKosh blood centres (`eraktkosh_blood_centres`)

- Role: blood availability evidence for C-section, trauma and burns; distance to nearest licensed blood
  centre; labels.
- Access: e-RaktKosh portal JSON endpoints (state list plus a 492-cell `/nearest` grid). 6,904 centres
  (5,135 blood banks, 1,769 storage units). Census state codes 1 to 9 are stored as 90+code on the portal.
- Licence: none stated; the terms neither grant nor forbid reuse. Show single-centre facts with a link
  back; do not publish the bulk table. A GODL alternative (NIHFW Blood Bank Directory on AIKosh) exists but
  was not fetched.
- Join: 388 of 6,904 centres matched (5.6%) to 365 VF facilities. Hand check 16/20 correct, 2 likely,
  2 uncertain (80% strict, 90% with likely). In 30 unmatched centres with a VF record within 1 km, 28 were
  truly different facilities.
- What it found: of 688 VF records claiming blood services, 159 (23%) are confirmed by a name match and 83
  have no centre within 5 km. 206 matched facilities have no VF blood claim (new positive labels).
- Caveats: 23.8% of centres lack coordinates; 32 sit on India's centroid (failed geocode); a coordinate
  shared by 3 or more centres should be treated as district level.
- Services: blood bank, storage unit; supports C-section, trauma, burns.
- App feature: blood-centre badge with type, category and a link to the live stock page; ranking features
  `has_blood_centre`, `km_to_nearest_blood_centre`; planner map layer.
- Ingest: upload `erk_centres.parquet` and `erk_vf_matches.parquet`, add a `pulled_on` column.
- Effort: 4 h.

### Rank 8: LaQshya maternity certification (`laqshya_master`)

- Role: dated government quality certificates for labour rooms and maternity OTs; C-section labels for
  public facilities.
- Access: NHSRC PDF `LaQshya_Master_data-08-04-2026.pdf`, 70 pages, 2,173 rows parsed with a row-count
  assert.
- Licence: NHSRC copyright policy allows reproduction free of charge, accurately and with prominent
  acknowledgement. Showing an expired certificate as current would be a "misleading context", so the app
  must show validity.
- Join: 63 of 1,355 facilities matched (4.65%) as 66 pairs; 56 of 465 VF public rows. Hand check 17/20
  correct, 3 plausible, 0 wrong. The low rate reflects how few public facilities VF holds.
- What it found: 48 matched facilities have a Maternity OT certificate; VF claims C-section for 3 and is
  silent on 44. Only 509 of 2,173 rows were valid on 2026-11-21; most of the file is expired history.
- Services: C-section (Maternity OT), labour room, high-risk delivery support.
- App feature: "LaQshya Maternity OT certified 20/03/2023, valid to 19/03/2026 (expired)" with the NHSRC
  citation; a valid MOT certificate raises C-section confidence, an expired one is weaker historical evidence.
- Ingest: upload 3 parquet files; add a view with `is_valid = date_validity >= current_date()`.
- Effort: 3 h.

### Rank 9: HOT OSM health facilities (`hotosm_ind_health_facilities`)

- Role: independent existence and location check for every facility; backup coordinate; map layer of
  nearby facilities VF lacks (government PHCs and CHCs matter for rural users).
- Access: HDX GeoParquet, 14.5 MB, 139,664 features, OSM snapshot 2026-10-09.
- Licence: ODbL 1.0. Every screen showing OSM data needs "(c) OpenStreetMap contributors, ODbL". The
  VF-to-OSM match table is an adapted database, so if the demo is public we must be ready to publish it
  under ODbL; keep it separate from VF data.
- Join: 3,263 strong and 269 weak matches over 10,077 VF ids (35.1%); 2,803 strong with no location
  conflict. Hand check 15/20; all 3 wrong ones carried the `location_conflict` flag, so among unflagged
  matches 0 of 17 were wrong. Weak tier: about 3 of 10 correct, review leads only.
- Caveat: for 747 of 3,260 strong matches the VF coordinate is within 10 m of the OSM point, which suggests
  VF coordinates were geocoded by name search, so agreement is not fully independent evidence. OSM service
  tags are too sparse to rank on (speciality on 287 matched features).
- Services: existence and location for all; weak service hints only.
- App feature: "found in OpenStreetMap 30 m from the listed location" or "same name found 128 km away:
  location unresolved"; map layer with attribution.
- Ingest: upload the parquet and `vf_osm_matches.parquet`.
- Effort: 4 h.

### Rank 10: MoHFW trauma care facilities, 196 (`mohfw_trauma_196`)

- Role: government designation badge for trauma; a highway-oriented public candidate set for the district
  planner; trauma labels.
- Access: Wayback copy of the MoHFW "List of Trauma Care" PDF (the live host did not resolve) plus the 2019
  programme brief for levels and status.
- Licence: MoHFW policy says content "may not be reproduced partially or fully, without due permission".
  Per-facility facts with a citation link are low risk; republishing the list needs permission.
- Join: 20 of 196 accepted (10.2%), all VF public rows; about 4 more look right in the review band
  (unverified). Hand check 19/20; the wrong one was a merged VF record of three Assam towns.
- What it found: VF text under-states trauma at these centres (0 strong trauma grades among the 20;
  2 say nothing about trauma or emergency).
- Caveats: funded is not functional. Of 196, the 2019 brief lists 104 functional and says no 12th-plan TCF
  had become functional (73 rows). No address or coordinates; the 176 unmatched TCFs need geocoding before
  they can be routed to.
- Services: trauma, emergency.
- App feature: "MoHFW-funded Level II Trauma Care Facility (NPPMTBI), 2019 status: functional" with the
  citation, on the trauma result card and as one weighted item in "how we decided".
- Ingest: upload `tcf_196.csv` and `tcf_vf_matches.csv` (under 100 KB each); geocode the 176 unmatched by
  place token with a precision flag.
- Effort: 4 h.

### Rank 11: WorldPop R2025A population grids (`worldpop_r2025a`)

- Role: need. People, women 15-49 and children under 5 within 5, 10 and 25 km of each facility or user point.
- Access: `data.worldpop.org`, 10 GeoTIFFs at 1 km, 158 MB. The 100 m total (742 MB) and the age-sex zip
  (874 MB) were over the cap and skipped.
- Licence: CC BY 4.0. Attribution "Population: WorldPop Global2 R2025A (2025), University of Southampton,
  CC BY 4.0". The release is an alpha that "may change".
- Join: 9,952 of 10,088 facilities on a populated cell (98.7%). Hand check 18/20; the 2 misses are VF
  coordinate errors. The grid also flags facilities in the sea (for example B.M. Birla Heart Research
  Centre, Kolkata placed in the Bay of Bengal).
- Caveat: the nearest-post-office district sums were wrong (Mumbai 903,114 people), so district totals need
  real polygons (rank 12) before use.
- Services: all, as need context (women 15-49 for delivery, under 5 for NICU).
- App feature: "people within 10 km" on the card; people per qualified facility as a tie-break; cheap
  "location doubtful" check.
- Ingest: upload `facility_population.parquet` (about 2 MB). For arbitrary user points, export the
  3.2 M populated cells to a table and sum with a bounding box; not run yet.
- Effort: 3 h, plus about 2 h for district sums once polygons are loaded.

### Rank 12: LGD district polygons (`lgd_district_polygons`)

- Role: point to LGD district (for user coordinates and facility coordinates), an independent second
  location signal, and the polygons WorldPop district sums need.
- Access: ramSeraph release `LGD_Districts.parquet`, 34 MB, 785 districts.
- Licence: mirror is CC0 with an attribution request; upstream government terms unclear. Use for lookups.
  Do not draw these as an India map: they include two PoK districts and are not Survey of India boundaries.
- Join: 9,962 of 9,970 facilities with coordinates get a district (99.9%). Agreement with the PIN-directory
  district is 94.0% for PIN-assigned rows and 7.8% for rows the audit already marked `pin_conflict`.
  Hand check 15/20 right, 1 plausible, 4 wrong; all 4 wrong ones have wrong VF coordinates. NFHS crosswalk
  reaches 696 of 706 NFHS districts.
- Caveats: predates the 2024-12-28 dissolution of 9 Rajasthan districts, which need a parent mapping.
- Services: none.
- App feature: "coordinates fall in X, address says Y" flag on the result card; user point to district.
- Ingest: upload the parquet plus the precomputed `facility_lgd_district.parquet` and NFHS crosswalk; point
  lookups with `ST_Contains` (latency on the 3.3 M-vertex table not measured).
- Effort: 3 h.

### Rank 13: HMIS sub-district service volumes (`idp-hmis-subdistrict`)

- Role: district volumes (C-sections, SNCU admissions, trauma, burns, cardiac emergencies, X-ray, USG) for
  context and the planner; a low-weight plausibility flag.
- Access: IDP CKAN datastore, all 547,336 rows but 40 of 296 columns (76 MB); the full CSV is 409 MB, over
  the cap.
- Licence: ODC-BY with attribution "MoHFW HMIS via India Data Portal (ISB), ODC-BY".
- Join: 9,256 of 10,088 facilities to a district (91.8%). Hand check 17/20; the 3 errors come from VF PINs
  that contradict the stated city. Sub-district assignment is less reliable.
- Caveats: never sum across the 5 overlapping sector values; use 2019 only (2020 live births look about 1.9x
  too high, cause unverified); zeros often mean non-reporting (Hyderabad shows 0 burn emergencies); the
  catalogue's `inst_deliv_csec` is mislabelled, use `csec_total`. No dialysis.
- App feature: "this district reported N C-sections in 2019" next to a recommendation; planner volumes.
  Not to be used as facility labels.
- Ingest: upload the CSV; one SQL step builds `hmis_district_2019` (about 2,100 rows).
- Effort: 4 h.

### Rank 14: PMNDP dialysis counts (`pmndp_counts_and_state_lists`)

- Role: state public dialysis supply next to NFHS need; a weak "likely offers free haemodialysis under
  PMNDP" flag for public district hospitals.
- Access: NHSRC PMNDP table (36 states, 1,994 centres across 751 districts); PMNDP portal used only as a
  cross-check (exact agreement); Goa state PDF (8 centres, 2020).
- Licence: NHSRC allows reproduction with acknowledgement; the PMNDP portal does not, so drop the
  `portal_*` columns before any public demo. The Goa NHM site looks compromised (gambling spam in the
  footer); citing its 8 rows is a judgement call.
- Join: 95.7% of VF rows map to a PMNDP state. Goa facility list: 1 of 8 matched (correct); the other 7
  are absent from VF.
- What it found: VF has 169 public facilities mentioning dialysis against 1,994 PMNDP public centres
  (Bihar 7 vs 94, UP 7 vs 76), so empty VF text at a district hospital must not be read as "no dialysis".
- App feature: state supply panel with NHSRC citation; flag labelled "state programme evidence, not
  confirmed for this facility", medium or low confidence. Proxy list of district hospitals: about 15/20
  look right and it includes blood banks that need filtering.
- Ingest: upload `pmndp_state_counts.csv` (NHSRC columns only) and the Goa CSV.
- Effort: 3 h.

### Attribution lines the app footer needs

- GODL: PIN code boundaries (Department of Posts via data.gov.in, mirror by ramSeraph/Datameet).
- CC BY: Malaria Atlas Project (Weiss et al. 2020); WorldPop Global2 R2025A.
- ODbL: "(c) OpenStreetMap contributors" on every OSM-derived screen.
- ODC-BY: India Data Portal (NFHS, HMIS).
- Source acknowledgement required: LGD (Ministry of Panchayati Raj); NHSRC (LaQshya, PMNDP).
- Per-facility citation links, no bulk display: NABH, NMC, MoHFW trauma list, e-RaktKosh.

## 2. Considered but rejected or unverified

### Not fetched this round (unverified, worth a later look)

These came up in discovery but were not downloaded or tested, so no match rate or licence is confirmed.

| Candidate | Why it might matter | Why not now |
|---|---|---|
| PM-JAY HBP 2.1 procedure master (Bihar SHA PDF) | procedure-to-service vocabulary for the claim lexicon | not parsed; the HBP 2.2 Excel at nha.gov.in returned 403 |
| Jan Sahayak nightly mirror of the PM-JAY empanelled directory | per-hospital empanelment and specialties, the biggest missing label source | not opened; provenance and licence unverified; hospitals.pmjay.gov.in itself is unreachable from our network |
| PM-JAY extract, PLoS ONE 2020 S1 file | same labels, dated | 2020 snapshot, stale |
| Wikidata hospitals and medical colleges in India | CC0 identity crosswalk (website, coordinates, ids) | not queried |
| Archived COVID-19 bed dashboards (Delhi, TN, Telangana) | the only per-facility ICU and ventilator evidence found | not fetched; 2020-21 data |
| AIKosh mirrors: National Hospital Directory with geo code, Blood Bank Directory (GODL), CGHS list, Health Centres 2016, Hospital Directory 2015 | more registry rows; the Blood Bank Directory is a licensed alternative to e-RaktKosh | not fetched; 2015 and 2016 snapshots are stale |
| MusQan certification, NPPMBI burn units (47; evaluated, not used), NCG cancer members, NCDIR HBCR hospitals, NNF fellowship centres, NQAS, Kayakalp 2021-22 | service-specific evidence for paediatrics, burns, oncology, NICU | not fetched; burn units are "scheme-supported", not proof of service; Kayakalp is FY 2021-22 only |
| State insurance lists: Gujarat PMJAY-MA CSV, Telangana Aarogyasri JSON (GitHub copies), Kerala KASP, Haryana PDFs, MJPJAY via Wayback | per-hospital specialty labels for cardiac, dialysis, oncology | not fetched; GitHub copies have unknown provenance; one state each |
| Chain locators: NephroPlus, DCDC, Apollo Dialysis, Aarthi Scans, Mahajan Imaging | positive labels for dialysis and MRI, where no public list exists | not fetched; robots.txt and terms not checked |
| PSA oxygen plant list (MoHFW RTI, 2023) | oxygen evidence | not fetched |
| Road safety: MoRTH Road Accidents 2024, black-spot lists (Dataful), NCRB ADSI | need for the trauma planner | not fetched; Dataful copies are third-party; no machine-readable national black-spot list with coordinates found |
| Routing alternatives: Geofabrik OSM, OSM highways, HOT roads, PMGSY GeoSadak, global hospital travel-time repo | road-network routing | MAP friction surface already reproduces travel time; the travel-time repo has an unverified method and licence |
| Geography alternatives: Census 2011 villages, geoBoundaries, Datameet maps, GeoNames IN, OSM name:hi, IndicXlit, SHRUG | village-name and Devanagari input resolution (GeoNames, IndicXlit) | not fetched; village typo handling is a real gap for the Bihar health-worker case |
| Population alternatives: GHS-POP R2023A, Meta HRSL, Census PCA | population | WorldPop already covers this |
| Need alternatives: Zenodo NFHS explorer, IJMR CKD state table, SRS IMR/MMR, Mission Antyodaya, RHS 2017 | need | IDP NFHS covers district need; CKD table is state level; NFHS-6 district claims unconfirmed |
| NLP models: Databricks-hosted embeddings, multilingual-e5-small, NLI DeBERTa small, zero-shot DeBERTa, MiniLM, bge-m3, SapBERT, IndicTrans2, others | query mapping and claim classification | not benchmarked; the large models (DeBERTa large, bge-m3, e5-base) are likely too slow on CPU, throughput not measured; check `serving-endpoints list` before relying on hosted embeddings |
| IPHS 2022 standards | expected services per facility level | not parsed |

### Rejected

- hospitalsnearme (hobby site, no provenance or licence), Practo scrapes (doctor-level personal data and
  Practo terms), GoMed dataset (unknown provenance): dropped.
- GADM (non-commercial licence), Survey of India and the official LGD portal (on request): weaker than the
  ramSeraph releases. ICD-10-PCS (US procedure coding, low relevance) and SNOMED CT India (on request).
- Railway hospitals (one zonal PDF), NACO ART centres (off-target service), NIN2HFI (no bulk access found).
- PostalGIS PIN boundaries (335 MB, over the cap; release notes say many polygons have no PIN and 8 states
  are missing). The GODL data.gov.in version (rank 3) is used instead.
- Our raw `nfhs_5_district_health_indicators.parquet` as the need source: superseded by IDP NFHS, which
  fixes its duplicated Chandel row and missing Purba Bardhaman.
- Duplicate candidates collapsed: two blood bank directories, two NHP directories, two SHRUG entries, two
  healthsites entries, two CGHS entries, AIKosh LGD villages vs the LGD archive.

### Searched for, not found or not reachable

- No bulk or open API for ABDM HFR/NHRR, PM-JAY empanelment, CGHS/ECHS with specialties, ESIC, MJPJAY,
  TN CMCHIS, Bihar health department lists.
- No national facility-level list for PMNDP dialysis centres, SNCU/NBSU/NICU, FRU/CEmONC, NOTTO transplant
  hospitals, STEMI cath labs, MRI/CT, or CDSCO blood centres. HMIS facility-wise C-sections not reachable.
- No machine-readable bed counts per NMC college.
- Network note: data.gov.in, hospitals.pmjay.gov.in, pmjay.gov.in, cghs, nhrr, esic, hmis, jeevandayee,
  notto, cdsco, main.mohfw.gov.in and others refused or timed out; facility.abdm.gov.in, abdm.gov.in,
  nha.gov.in, pib.gov.in and mohfw.gov.in returned 403. This looks like geo-blocking; an India network path
  or Wayback snapshots are the untested workaround. Details:
  `research/discover/registries/CANDIDATES.md`, `research/discover/geo_access/CANDIDATES.md`.

## 3. GPU verdict

Verdict: available per docs, unverified in our workspace. We do not need it.

- CLI (profile vf): the `air` (AI Runtime, serverless GPU) group exists; `air list` succeeds with no runs;
  `air pools list` returns FEATURE_DISABLED (no reserved GPU pools); `air run` accepts GPU_1xA10,
  GPU_1xH100, GPU_8xH100. No GPU has been attached.
- Docs: Free Edition gives "limited access to AI Runtime" after LinkedIn verification, and "No GPU serving
  endpoints", "No custom models on GPU or batch inference". A Databricks blog (17 Jun 2026) says Free Edition
  "now includes access to GPUs, subject to availability". A community thread reports "quota exceeded" after
  about 5 GPU minutes; no quota is published. No hackathon GPU credits were found.
- Risk: exceeding the fair-use quota shuts down all compute for the day, including the warehouse and Apps.
- What it means for the model: every model in the plan trains on CPU (the NABH scorecard retrains in
  about 1 minute). The TF-IDF comparator gets within 0.03 AUROC of the scorecard except OBG, so the labels,
  not model capacity, are the limit. GPU would matter only for fine-tuning a transformer, which the label
  volume does not support. Serving is batch tables plus CPU code in the App either way.
- To verify, with the user's approval and never on judging day: check for "Verify identity" in the UI, run
  `databricks air run --file research/gpu/verify_gpu.yaml --dry-run -o json -p vf`, then one A10 smoke test
  with no retries. Ask the organisers about GPU credits.

## 4. Model plan and prototype result

### Plan (`research/model/MODEL_PLAN.md`)

1. Service-availability scorecard P_S per (facility, service): additive L2 logistic regression over named
   VF-derived terms (text strength, prerequisites, scope conflict, contamination, non-offer, facility type,
   size bins, merge bucket). Per-term points are stored so intercept + sum of points = logit, which the
   script asserts. Ranking uses the web-checked gold labels (`model/gold`, `audit/ground_truth`).
2. Registry entity matchers: the deterministic rapidfuzz scripts above; each match stores rule, score,
   distance and citation URL. No learning.
3. Sentence-attribution classifier for merged records: rules first, optional cached `ai_query` term
   (+0.037 [0.009, 0.076] over rules on 108 sentences, but it changes only 130 of 69,713 pairs).
4. Query-to-service mapping: precomputed `databricks-gte-large-en` synonym vectors with lexicon fallback;
   not evaluated yet.
5. Template translation (Hindi, Marathi) of fixed strings only; not run, needs human review.

A list is never both a feature and a label in one model, and absence from a list is never a negative.

### Prototype: NABH-label scorecard (`research/model/train_nabh.py`)

Trained on NABH specialty codes as weak labels for the 1,054 NABH-matched facilities, 70/30 split grouped by
leakage group, about 1 minute on CPU, 39,836 batch scores written.

| Service (label) | Test positives / n | AUROC | ECE | Notes |
|---|---|---|---|---|
| Dialysis (DIA) | 73 / 350 | 0.682 | 0.014 | never scores above 0.6; P/R at 0.5 is 1.00/0.014 |
| Dialysis (DIA or NPH) | n/a | 0.797 | n/a | P/R 0.71/0.73 at 0.5; DIA looks under-declared |
| C-section (OBG proxy, base rate 0.80) | 350 | 0.619 | 0.059 | P/R 0.80/1.00 |
| Cardiac (CAR) | 350 | 0.760 | 0.045 | 0.8-1.0 bin: 63/78 (81%, Wilson 71-88%) |
| Trauma (EMD) | 350 | 0.761 | 0.011 | 0.6-0.8 bin: 22/34 (65%) |

Brier beats the base rate for every service. Baseline: the text rule T>=2 gets dialysis P/R 0.37/0.47.

External checks: on the web gold dev set (52 pairs; sealed test not opened) the NABH-trained model scores
pooled AUROC 0.531. On positive-only lists against other public facilities: NMC DM Nephrology (n=16) 0.881,
MoHFW TCF (n=20) 0.698, LaQshya MOT (n=49) 0.553. The Witness Ledger P_S scores 0.852 on web gold dev, but
that figure is in-sample.

Conclusion: the scorecard is calibrated on its own label, but NABH codes measure declared scope and size
(largest weights: beds 100+, prerequisites, specialty breadth), not a web-confirmable service. So:

- The ranker stays the web-gold P_S. Its 0.852 is in-sample on 10-15 pairs per service, so its real
  performance is not yet known; the sealed test should be opened once before the demo.
- The NABH scorecard ships, if at all, as a labelled "regulator scope prior".
- External lists ship as cited evidence rows and as held-out checks.

### How the app shows it

- Verdict badge and p per facility and service, with up to 3 cited facility sentences (field and source URL).
- List evidence lines with their own citations: NABH acc_no and certificate link, NMC course and update
  date, LaQshya validity date (expired shown as expired), TCF level and 2019 status, blood centre badge.
- "How we decided": the points waterfall, which is the actual computation.
- Calibration as a track-record sentence with the label named, for example "of facilities scored 0.8 to 1.0
  for cardiac care, 63 of 78 (81%) were on NABH's CAR list", with Wilson bounds.
- Uncertainty: location-check badge (PIN polygon, OSM, LGD), "What we ignored" for sentences attributed to
  another facility, "not on list" never shown as evidence against.
- District context (NFHS, HMIS, population, drive time) labelled "district estimate, not facility data".
- Risk to manage in the UI: size terms dominate, so the score alone favours big hospitals; text evidence
  must sit next to it.

Deployment: batch only. Scores, terms, track record and list evidence go to Delta tables (proposed
`workspace.vf_ledger.service_scores`, `score_terms`, `track_record`, `list_evidence`, `claim_atoms`). The App
(Medium size) reads them through the warehouse and ranks in closed form. No GPU, no custom serving endpoint,
no live LLM scoring (the LLM gave confidence 1.0 on contaminated records).

## 5. Order of work for the weekend

Saturday morning (needs the user's approval for workspace writes):

1. Create the volume and schemas once (`workspace.external`, `workspace.geo`), using the single naming
   convention in section 1.
2. Upload and CTAS the geography backbone: LGD archive (rank 2), PIN boundaries check table (rank 3),
   IDP NFHS (rank 4). About 9 h of the listed effort, much of it SQL that can run in parallel.
3. Push scripts and READMEs (not `data/external`) to github.com/LordKarV/databricksdatathon; the research
   steps could not run git.

Saturday afternoon:

4. NABH (rank 1): review borderline matches, upload, wire the badge, tier and overclaim flag. Fetch ICU and
   IMG overnight if the ICU service is in scope (about 492 pages for ICU at about 3 s per page).
5. Build the `list_evidence` table from NABH, NMC, LaQshya, TCF and e-RaktKosh matches with match rule,
   citation URL and hand-check precision per list (ranks 6, 7, 8, 10).

Sunday morning:

6. MAP travel time (rank 5): facility, PIN and district tables first; the live Dijkstra only if App latency
   tests well.
7. Batch scores into `service_scores`, `score_terms`, `track_record`; wire the evidence panel, waterfall and
   track-record sentence. Open the sealed web-gold test once and report it honestly.

Sunday afternoon, if time:

8. OSM existence check and map layer (rank 9), WorldPop catchments (rank 11), district polygons (rank 12).
9. HMIS and PMNDP context panels (ranks 13, 14).
10. Footer attribution lines; restart the App before judging (Apps stop 24 h after start).

Skip this weekend: GPU smoke test, transformer fine-tuning, new web scraping behind geo-blocked hosts.
