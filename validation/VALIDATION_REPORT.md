# Referral Saathi data validation report

Date: 2026-11-21. Scope: every data layer from the Marketplace source table to the app exports, checked by 8
audit areas plus a completeness critic. Every number below comes from a check saved in
`validation/<area>/checks.py` (signature `check_<name>() -> dict`) and re-run by `validation/run_all.py`.

Last full run (`run_all.py --skip-network`, started 21:12 local, `validation/out/scorecard.json`): 251 checks,
122 pass, 88 warn, 20 fail, 21 not run. The critic added 4 more checks (3 fail, 1 warn) in
`validation/critic/out/results.json`.

Short version:

- The original data was never modified, and derived/v1 reproduces from it. Raw sha256 6/6, 345/345 manifest
  aggregates, 456/456 live-warehouse aggregates, 469,498/469,498 claims verbatim at their stated field and
  index, and 0 real differences on a full rebuild.
- What users and judges see has the most problems: the PIN lookup origin, the planner, the How page and
  notebook numbers, and the dashboard tables.
- Some inputs to model #11 have to be fixed before it publishes derived/v2. Gold TEST verdicts are baked into
  `score`, there are no existence negatives, 12 veterinary records are still scored, and a few lexicon
  rules are wrong (QMRT read as MRI, 3D scans read as ultrasound, "plans to" read as an offer).
- The held-out service-claim AUC in derived/v1 (0.826 / 0.819) has no clean negative. Withdraw it or call it
  in-sample.

Out of scope by instruction: derived/v2 and model/v2 contents (being written by #11; only contract checks
were designed for them) and the v3 gold TEST set (never opened).

## 1. Verdict per layer

| layer | verdict | key numbers |
|---|---|---|
| 0. Raw (facilities, India Post, NFHS) | sound | sha256 6/6; manifest aggregates 345/345; live table 456/456 aggregates and 171/171 column fingerprints equal; 10,088 rows = 9,970 well formed + 30 truncated + 88 fragments (upstream CSV breakage, same in the live table) |
| 1a. derived/v1 keys, lineage, rebuild | sound with caveats | 20/20 manifest rows and bytes; 40/40 id columns resolve; 51/52 primary keys unique (1 duplicate in kb opendata); rebuild 14/23 byte-identical, rest differ by float ulps only (max 1.1e-13); 84-94 hard-coded absolute paths block a rebuild elsewhere |
| 1b. derived/v1 claims | sound with caveats | 469,498/469,498 verbatim; 0 missing, 0 extra; 1,728/18,388 description sentences (9.4%) cut at an abbreviation; 372/9,506 other_facility sentences are the record's own place |
| 1c. derived/v1 grades, data_point_scores, sources | sound with caveats | 518,191 points = documented composition; 0 grade/dps inconsistencies; 141 TEST gold verdicts baked into `score`/`status`; 6 C-section false positives from a missing word boundary; 5,652 repeated URLs double-counted |
| 1d. derived/v1 locations | sound with caveats | district vs LGD 9,802/9,946 agree; district sample 29/30; moved-point sample 24/30 (0.63-0.91); 49 stale state_final; 69 facility PINs > 25 km off their polygon (90 facilities) |
| 1e. derived/v1 evaluation.json | broken | held-out service AUC: 0 of 6 test negatives are clean; 17 design-read v1 pairs sit in TEST (41 of 141 test gold points); existence q_ev 0.984 fitted on 60 true and 0 false |
| 2a. kb taxonomy and lexicon | sound with caveats | lexicon precision 37/40 (0.801-0.974); specialty map 39/40 (0.871-0.996); recall about 0.74 (0.47-0.91); QMRT read as MRI (3 facilities); 3D/4D scan read as ultrasound (82 of 101 pairs wrong) |
| 2b. kb web_evidence | sound with caveats | 237,891 quotes, 0 off-page; services 38/60 (0.507-0.744), weighted 0.691; details weighted 0.586 (check fails); 107 hour rows past 24:00; 282 of 312 medium-identity sites rest on the name alone |
| 2c. kb vf_details | sound | 42,036 quote checks, 0 failures; sample 37/40 (0.801-0.974), weighted 0.899; 74 headcount bands stored as staff counts |
| 2d. kb opendata, crawl, pathways | sound with caveats | 15/15 kb tables 0 orphans; OSM 17/20 (0.64-0.95); Wikidata 20/20; 44 OSM objects shared by 2+ records, 9 not explained by a duplicate group |
| 3. Official list matches | sound with caveats | 21/21 README counts reproduce; LaQshya 20/20, NMC 20/20, trauma 19/20; HOT strong about 206-272 of 3,263 wrong (raw-coordinate anchor); NABH 18/20; e-RaktKosh misses 4/10 true pairs |
| 4. Gold labels | sound with caveats | schema 0 bad of 1,324 fields; 0 split leakage by unique_id; URL re-check 22/25 (0.70-0.96); 0 existence negatives in 331 records; 106/213 no_info never searched; service kappa 0.382 |
| 5a. app facts.json | sound with caveats | 44,968 quotes verbatim; 0 exclude_review records; 227 gazetteer PINs dropped; PIN origin points: 486 of 19,484 > 50 km outside their own polygon |
| 5b. app state packs | sound with caveats | rebuilt 21:11 with duplicate-group collapse; 80/80 merged-member quotes resolve to the member's claim text; vet record now 0; same PIN-origin problem as facts; 37-46 rows show a different quote each build |
| 5c. planner | broken | 8 capability rows on veterinary records (3 with p >= 0.71); 633 hospital capabilities at 536 dental clinics; proposed-capability precision 41/50 (0.69-0.90); about 56 non-offer or camp-only citations; 13 NaN districts; bundles the e-RaktKosh bulk directory (5,230 centres) |
| 5d. How page, notebook, dashboard, Genie (critic) | broken | 4 of 17 How-page cells disagree with derived/v1; notebook 3 of 7 saved numbers stale; dashboard `pair_scores` scores the 12 vet records (84 rows) and bands only 2 pairs Likely where the app bands 45 |
| Privacy and licence (public copy, option B) | broken for option B; fine for the private repo | 0 project credentials ever committed; option-B filter would publish 955 distinct provided phone numbers (25 files) and 11 provided-name lists; 72 SVGs and logs bypass the filter |

## 2. Confirmed issues ranked by severity

"Before v2" means the fix, or at least the filter #11 applies, must land before #11 publishes derived/v2,
because #11 reads that input. "Can wait" means it affects v1 grades, the app, the docs or reproducibility,
and should land before the submission video but not before v2.

Each issue lists the area ids it came from (INT integrity, L lineage, RL record loss, CL claims, LOC/MATCH
location, WF web facts, labels L-numbers as LAB, P privacy, CR critic).

### Critical

C1. TEST gold verdicts are baked into the published scores (INT-02). Before v2.
- Count: 141 data points with gold_split = test carry a verified status (location 56, existence 56, service 29;
  125 true, 16 false). `score` differs from `score_model` on all 141. `facility_trust.location_score` carries
  the 0.97/0.03 override for all 56 test locations.
- Examples: any `reason_codes` GOLD_TRUE or GOLD_FALSE row with gold_split = test in
  `derived/v1/data_point_scores.parquet`.
- Root cause: the gold merge writes overrides into the default `score`/`status` columns.
- Affects: model #11 TEST metrics if it reads `score`, `status` or `reason_codes`; any end-to-end app
  evaluation on TEST.
- Fix: #11 reads only `score_model` and `q_ev` and drops gold_split == test rows from training. Then publish
  an override-free default column, with the verdicts in a separate public column.

C2. The derived/v1 held-out evaluation is not held out (LAB-L2, LAB missed). Before v2. This also matters
for the README and the video.
- Count: 17 of 36 design-read v1 pairs are in TEST, and 41 of 141 test gold points come from them
  (service 12/29, location 14/56, existence 15/56). The service_claim test set has 6 negatives: 5 are
  design-read v1 pairs and the 6th (v2_dialysis_suspect_2) says absence was not shown, so 0 of 6 are clean.
  Of 10 test location negatives, 5 do not show the facility is elsewhere (3 rest only on the PIN
  directory, 2 are state-field typos). Without them location AUC moves from 0.770/0.802 to 0.874/0.861.
- Examples: nicu_suspect_2, emergency_csection_weak_2, mri_suspect_1, mri_suspect_2, cardiac_surgery_weak_1,
  v2_emergency_csection_suspect_5, v2_nicu_suspect_5.
- Root cause: s2_gold does not force version v1 to dev; the location label mixes point_ok and fields_ok.
- Affects: derived/v1/evaluation.json and README AUCs; #11 if it reuses the split.
- Fix: force v1 pairs to dev (or evaluate on v2 TEST only) and re-run s4-s7. Withdraw the service_claim
  AUCs (0.826/0.819) or call them in-sample until 10-15 web-checked contradicted TEST pairs exist. Split
  the location label into point_ok and fields_ok.

C3. No existence negatives anywhere, yet every facility is shown as 0.97-0.99 likely to exist (LAB missed).
Before v2.
- Count: exists = no in 0 of 331 label records. 13 labels whose notes say "searched and not found" are coded
  exists = unclear. EXISTS_DEFAULT is fitted on 60 dev true and 0 false (q_ev 0.984).
  `facility_trust.existence_score` ranges 0.970-0.991 over 9,959 records, and app/facts/build.py:163 shows
  it as p_e. `model/proto/fusion/fit.py` existence_rows codes unclear as y = 0, so its "5 dev negatives" are
  5 unclear labels.
- Examples: v2_dialysis_suspect_2, v2_emergency_csection_suspect_4, e2e_039, nicu_weak_2, mri_suspect_1.
- Root cause: the labelling rubric has no "not found" value.
- Affects: model #11 existence head; the app's existence score.
- Fix: add exists = not_found to the rubric and relabel the 13. Code unclear as missing, not 0, in #11.
  Report existence as not evaluable until negatives exist.

C4. The app's PIN lookup puts many PIN origins in the wrong region (LOC missed).
Can wait for v2; must land before the demo.
- Count: of 19,484 exported PIN points (19,295 with a polygon), 2,241 are > 10 km outside their own polygon,
  1,276 > 25 km, 486 > 50 km and 120 > 100 km. 463 of the 486 hold no facility, so a facility-only check
  could not see them. 18 exported PINs carry a state different from their polygon's state.
- Examples: PIN 224172 exported 467 km off; 504346 exported as ANDHRA PRADESH / PRAKASAM (Telangana polygon);
  384316 exported as RAJASTHAN / NAGAUR (Gujarat polygon); 612906 exported as KERALA (Tamil Nadu polygon);
  494114 (Bastar) exported at Raipur.
- Root cause: app/facts/build.py pins() and app/packs/build_packs.py (line 90 area) send pin_gazetteer
  straight into the lookup and the per-PIN top lists. The pin_median and district_median sources are not
  checked against the polygon.
- Affects: the app. A user who types one of these PINs gets facilities from the wrong region.
- Fix: check each gazetteer point against its data.gov.in polygon. When it is > 10 km outside, use the
  polygon's representative point, take district and state from the LGD polygon, and rebuild facts and packs.

### High

H1. Veterinary (exclude_review) records still ship in the planner and the dashboard (INT-01, RL-02, CR).
Before v2 for #11's filter.
- Count: as of the 21:11 rebuild the packs show 0 and facts.json 0. The planner still has 8 capability rows
  on 5 of the 12 records, and 3 of them have p >= 0.71. Dashboard `pair_scores` scores all 12 (84 rows), and
  `geo_facility` counts 885c79f6 as a service claim.
- Examples: 885c79f6 SKS Veterinary Hospital emergency_24x7 p = 0.764; 3701980c Pet Care Pathology Lab
  ecg p = 0.783; 8b8ee908 Prime Animal Care Hospital blood_transfusion p = 0.715.
- Root cause: planner/data_v1.py facilities() (line 72) and the prototype fusion tables do not filter
  trust_level.
- Fix: filter trust_level != 'exclude_review' in planner/data_v1.py and in V1Store. #11 drops the 12 ids;
  contract `v2_excluded_not_scored` fails otherwise. app/itinerary.py _stop() should drop stops whose id is
  not in eng.fid.

H2. The planner gives hospital capabilities to dental clinics (CL missed). Can wait.
- Count: 633 proposed (capability, facility) rows at 536 dental facilities, 623 of them hospital
  capabilities: general_surgery_ot 408, laboratory 80, ct_scan 53 (CBCT), orthopaedics 43 (dentofacial),
  plastic_surgery 20. Each row has p 0.715 or 0.783. Measured precision of proposed citations is 41/50 =
  0.82 (Wilson 0.69-0.90; seed 20261121), and was never measured before.
- Examples: Ganatra's Dental Care general_surgery_ot <- "Dental Surgeon"; Siri Dental Hospital ct_scan
  <- "Cone-beam computed tomography"; Niramaya Multispeciality Dental orthopaedics <- "Dentofacial
  Orthopaedics"; Akeela Dental Care laboratory <- "On-site dental laboratory".
- Root cause: planner/data_v1.py _match has no facility-type scope rule.
- Fix: reuse cleaning/claims/lexicon.py scope_conflict; add dental, CBCT, oral-surgeon and dental-laboratory
  exclusions to capabilities.json; report the precision in planner describe() and re-measure.

H3. The planner cites non-offer sentences as proof, and the "future" cues miss "plans to" (CL-1, CL missed).
Before v2 for the kb cue; the planner fix can wait.
- Count: 74 cited (capability, claim) pairs over 71 sentences carry a kb non-offer cue. Read in full: 26
  absent or planned, 18 camp-only, 4 another capability, 4 unclear, 22 cue false alarms. 12 more use plan
  wording no cue catches. That is about 38 planned or absent and 18 camp-only citations of 48,164. The kb
  future cue also misses these: 13 kb positive pairs over 7 sentences (which #11 reads), and 4 app pairs,
  1 of them resting only on plan sentences.
- Examples: 51c1ed79:capa:8 "blood bank not available"; 28726757:capa:23 "plans to launch a blood bank";
  0c78cad5:capa:10 "Plans to introduce an in-house dialysis unit" (app dialysis strong);
  e0893a32:proc:20 "Plans to introduce angiography..." (app cardiac_surgery moderate).
- Root cause: build_claims computes non-offer cues only for svc_rows; the planner reads claims.nonoffer
  (116 of 172 kb-cued sentences have nonoffer = False).
- Fix: widen the future cue (plans? to introduce|offer|provide|expand|implement|construct|begin, opening
  soon, in the near future) in kb lexicon_src.py and cleaning/claims/lexicon.py; compute cues for every
  sentence; add a test that no cited sentence carries a cue.

H4. The C-section pattern has no left word boundary (CL missed). Can wait (kb already fixed; v1 grades and
the app are wrong).
- Count: 6 sentences, 6 facilities whose only C-section evidence is these. All 6 are in app
  pairs.emergency_csection (2 strong, 3 moderate, 1 weak) and in the planner's comprehensive_emoc at p
  0.60-0.92.
- Examples: dad3fe96 "paediatric section" (strong 0.92); 338be233 "socio-economic sections" (strong 0.91);
  8c0ec23b eye clinic "economic sections"; 80b72174 "IPC sections 312, 316"; 0a77c719 "Prosthetic Section".
- Root cause: cleaning/claims/lexicon.py:35 'c-? ?section' (from audit/claims/services.py:61). kb fixed it
  at kb/taxonomy/lexicon_src.py:289 with an assert at line 395.
- Fix: back-port '\bc-? ?section' and the assert. Rebuild claims, grades, data_point_scores, facts and the
  planner. The same drift affects 9 app pairs in all (cardiac_surgery 1, burns 1, dialysis 1). Generate the
  cleaning patterns from kb lexicon.json, and correct the "copied unchanged" note in lexicon.json.

H5. "Quantum Magnetic Resonance Therapy" is tagged as MRI (CL-2). Before v2.
- Count: 10 kb mri pairs. 3 facilities have MRI only from them, and all 3 are in app pairs.mri at moderate
  (0.78, 0.80, 0.81).
- Examples: abe799fb, cd8b64e1, e7795a4f.
- Root cause: the MRI include in both lexicons matches "magnetic resonance" without an exclusion.
- Fix: exclude 'magnetic resonance therap|QMRT|quantum magnetic' in both lexicons and add an assert.

H6. The How page and the notebook show stale and contradicting numbers (CR). Can wait; must land before
judging.
- Count: 4 of 17 countable REPORT.md cells disagree with derived/v1. Notebook outputs: 3 of 7 saved
  numbers differ from current data.
- Examples: "1,407 / 9,682 more than 50 km" vs 1,367 / 9,869, and the Flagged row two cells later prints
  1,367 / 9,869. "1,114 more than 100 km" vs 1,101. "About 1,405 / 9,959 name another facility" vs 2,489
  in derived/v1, and STORYBOOK says 1,232. "9,961 / 9,970 district and NFHS join" vs 9,934 / 9,959.
  Notebook engine pairs 8,012 vs 7,980 now; services 37 vs 36.
- Root cause: app/howto/build.py:55 table() copies REPORT.md (written 13:41, pre-dedupe denominators)
  verbatim; submission/build_notebook.py:181 embeds it; the notebook outputs were saved before the 21:11
  rebuild.
- Fix: regenerate the numeric cells from derived/v1 in howto/build.py, pick one definition for "names
  another facility", re-execute the notebook after the final export, and keep the critic checks in run_all.

H7. Dashboard and Genie tables come from unaudited prototype sources (CR). Can wait; re-point after v2.
- Count: `pair_scores` and `facility_scores` load from model/proto/fusion/*.parquet and `geo_facility`
  from viz/geography/data/_cache/facilities.parquet (databricks/tables.yaml:473-503). Prototype bands for
  the 7 app services: Unlikely 37,108, Unverified 32,603, Likely 2. The app bands 45 pairs Likely.
- Root cause: databricks/VERIFY.md checked row counts and keys only.
- Affects: what the video's dashboard shows, which can disagree with the app for the same pair.
- Fix: build the UC dashboard tables from derived/v1 (later v2). Add a contract check: content hash equal to
  the source, no exclude_review id, and bands equal to the app's per (unique_id, service).

H8. The public copy and the deploy bundle would publish provided or restricted data (P1, P3, P missed).
Can wait; must land before any public repo or bundle publish.
- Count:
  - Phones: 25 option-B files carry 955 distinct provided numbers.
  - Names: 11 files list >= 20 provided facility names, including viz/journeys/data/plans_best.csv (389).
  - Blind spot: 72 SVGs and the .log/.out files are never read by the filter; 8 SVGs name 28 provided
    facilities.
  - Third-party pages: 22 full pages are public-class, and 3 public files carry Google API key strings.
  - e-RaktKosh: planner/out/planner_v1.json.gz (also in build/deploy_bundle) embeds the bulk directory,
    5,230 centres, 4,873 of them unmatched to VF. The project's licence notes say not to publish the bulk
    table (external/eraktkosh_blood_centres/README.md:25-26).
- Examples: audit/identity/out/shared_phones.csv, audit/identity/verify/v_shared_phones.csv,
  viz/patterns/charts/p6_anomalies.svg, app_design/feasibility/*/sources/android_go.html.
- Fix:
  - tools/data_audit.py: add the provided-phone (>= 5 numbers) and provided-name (>= 20) rules, add .svg to
    MEDIA_EXT and .log/.out to DATA_EXT, then regenerate tools/public_exclude.txt.
  - Delete the saved third-party pages.
  - planner/export_v1.py:42-53 blood(): ship only the 365 matched per-facility facts plus a nearest-centre
    distance.

### Medium

| id | issue | count and examples | root cause | affects | fix | when |
|---|---|---|---|---|---|---|
| M1 (RL-03, INT missed) | Duplicate-group copies take several option slots | Before 21:11: 259/29,839 pack lists, 2,158/137,977 answers (257 inside the top 3); 117 facts pairs; 361 planner rows on 77 non-canonical records. Example: b2db2916 + e93a7ae0 Nemcare, 35 m apart. The 21:11 rebuild collapses groups in facts and packs (#78); planner not verified. 12 same-name pairs within 300 m and 9 shared OSM objects are not grouped | build_packs.top_lists and engine ranked every record although s4_groups.py:2 promises one card per group | app | keep the #78 collapse; apply it in planner/data_v1.py; feed the 21 candidate pairs to s4_groups and check them by hand | can wait |
| M2 (WF-3) | Weak and web-only service quotes are often not offers | 20,218 positive pairs, 5,444 weak; in the 7 model services 4,885 positive, 1,376 weak. Cell A (strong, 2+ pages) 13/18 here vs 13/13 in QA (pooled 26/31). Sense errors: detox -> de_addiction 46 pairs, eye/facial trauma -> trauma_care 13, knee arthroscopy -> cataract_surgery 19 | weak and strong pairs feed one feature (viz/features/build_features.py:276-285) | model #11 | weak pairs as a separate low-weight feature; add the sense exclusions | before v2 |
| M3 (WF-4, WF missed) | Medium site identity is mostly a same-name facility elsewhere; portals accepted | 312 medium sites, 282 have neither PIN nor locality on the site; 240 records attributable only through medium; ivf.net credited to Santasa IVF Mysore at high (staffing:doctors = 600) | build_web_evidence.py site_identity (line 336) attributes a whole site from one page | model #11 web features | require PIN or locality for medium; page-level attribution when the domain does not spell the name; portal deny-list | before v2 |
| M4 (WF-12, WF-6) | NABH feature counts pre-accreditation and doctor-profile pages | 48 of 684 e_web_nabh_claim records (7.0%) have no row valued accredited; 870 detail rows come from doctor-profile URLs, 6 records' NABH claim rests only on them | value and URL scope not filtered | model #11 | filter value_text == 'accredited'; treat /doctor/, /dr-, /team/ pages as staff | before v2 |
| M5 (WF-1, WF missed) | Hour values past 24:00 and dash minute separators | 107 web_hours rows (104 usable, 70 model-visible, 21 records); same 107 rows in the Databricks copy; 29 rows use '09-30 AM'; 10 rows are CV date ranges (1e2e9c0b) | kb/vf_details/patterns.py _mins adds 12 to hh >= 13 pm | model e_web_hours_found; notebook/Genie | keep hh when >= 13; reject hh > 24 or mm > 59; parse 'h-mm am' | before v2 |
| M6 (WF-2) | Shown facility value differs from the quote cited next to it | web 1,128/17,548 (6.4%), vf 442/25,773 (1.7%); 1,090 of the 1,128 are fixable by citing a row with the shown value | best quote chosen independently of the value | Databricks tables, notebook | cite best_fact_id, or a quote whose row carries the value | can wait |
| M7 (MATCH-02, MATCH-03) | HOT and NABH matches anchored on raw VF coordinates that v1 rejected | HOT strong 272/3,263 within 2 km of the raw point but > 25 km from v1; 12/12 sampled wrong (about 206-272 wrong). NABH 57/1,921, 7/10 wrong. Examples: 4b8e2383 SPARSH Bengaluru -> Hassan; ede7be8d Star Hyderabad -> Tenali; 731cbe0f Marwar Jodhpur -> Bikaner | external/hotosm_ind_health_facilities/match.py and external/nabh_accredited/match.py use raw coordinates | model family X witnesses; NABH badges | distance from derived/v1 loc_lat/loc_lon; refuse coord-anchored geo_conflict pairs without PIN or city agreement | before v2 if #11 uses these witnesses |
| M8 (MATCH-01) | e-RaktKosh matcher misses true blood-centre pairs | 4/10 sampled refusals were true (Wilson 0.17-0.69), about 83-335 of 486 | names keep 'blood centre/bank', no abbreviation expansion | blood-bank coverage | strip generic words; accept <= 0.5 km core-name overlap | can wait |
| M9 (LOC-01, LOC-05) | Wrong PIN centres move facilities 50-300 km | 69 facility PINs > 25 km off their polygon, 90 facilities, 34 placed on the bad point; 20 facilities moved by cleaning from within 2 km of their PIN polygon onto a bad centre | s1 PIN point not checked against the polygon | model P_L and distance; app map | replace off-polygon PIN points, re-run s2 | before v2 if P_L uses loc point, else can wait |
| M10 (LOC-02, INT-08) | state_final keeps a stale typed state | 49 records (32 high), 21 Andhra Pradesh -> Telangana; 24 of 371 Hyderabad/Secunderabad records say ANDHRA PRADESH | typed state preferred over point and PIN | app state filter, cards | use the state the point and PIN agree on, keep the typed value in a note | can wait |
| M11 (LOC-04, LOC missed) | City vs coordinates conflicts kept as high | about 22 real conflicts (29 flagged, 7 resolver false alarms); examples ed1ce467 Thalassery, 5cb31fe2 Bengaluru placed in Ballari, f59cbf5c Jabalpur | places.build_layers() never uses the s3 city layer; cleaning/geo_identity/run_all.sh:9 '|| true' hides a failing self-check | model location, app | consult the city layer; remove '|| true' | can wait |
| M12 (CL-5) | other_facility fires on the record's own place under an old or alternate name | 372/9,506 sentences in 148 records; 90 name the record's own district or city; sample 20/20 own location | no alias table (Bijapur/Vijayapura, Poona/Pune); district missing from the own-place set | model q_ev 0.28 instead of 0.95; app "mentions another facility" | alias table, district in own-place set, rebuild claims | before v2 if feasible; else document |
| M13 (CL-3) | '3D/4D/5D scan' tags dental, eye and orthotic scanners as ultrasound | 101 pairs, 82 at dental/eye/prosthetics facilities; 39 facilities have ultrasound only from them | kb lexicon.json ultrasound include | model #11 positives | require an obstetric or ultrasound word, or exclude intraoral, CBCT, OCT | before v2 |
| M14 (LAB-L1) | no_info mixes never-searched and searched-found-nothing | 106/213 primary no_info have 0 URLs; gold_pairs 52-56 of 114 (dev 25-26, test 27-30); 8 no-URL labels did search | no searched flag | model #11 if no_info is coded y = 0 | add label_status (checked/unchecked/name_only) by URL or notes | before v2 |
| M15 (LAB-L3, LAB-L5, LAB-L4) | Verdicts with no web evidence, misattribution coded as contradicted, 3 unsupported verdicts | 14 service verdicts with 0 URLs (13 e2e name-only); 10 location = no from the PIN directory only; 8/26 contradicted rest on misattribution, 3 show no absence; URL re-check 22/25 | rubric | model #11 targets and metrics | flag name_only/dataset_only and exclude from y; misattribution -> attribution label, service no_info; relabel the 3 | before v2 |
| M16 (LAB-L6, LAB-L7) | trauma_emergency gold maps to trauma_care in the taxonomy but to emergency_24x7 in v1; v1 and the model read different verdicts | 26 v1/v2 trauma pairs, 3/7 confirmations rest only on an ED or casualty unit; 20 fields over 10 pairs differ between derived/v1 and the model loader (3 test service verdicts) | two loaders, two mappings | model #11 and v1 report different truths | one adjudicated label per pair read by both; relabel trauma against trauma_care | before v2 |
| M17 (RL-01, CL-4) | 30 real facilities dropped at the raw step, undocumented | 30/10,088 truncated rows (16 hospitals), 88 fragments; e.g. 41d54237 Guardian Multispeciality Warangal, 63c6add2 Oberoi Pathankot, 69f31faf Choithram Netralaya Indore | upstream newline in description (same in the live table) | coverage (about 0.3%) | state the loss in derived/v1/README.md; optional stitching repair | can wait |
| M18 (RL-04) | Coverage gaps in Bihar and Odisha | records per million: India 6.84, Bihar 1.96, Odisha 2.42, Assam 3.44; Odisha csection PINs > 50 km from a candidate 0.829 | source data | app answers in target states | say so in README and video; add matched official lists as fallback candidates | can wait |
| M19 (L4, L5, L6) | Rebuild tied to this machine | 94 absolute-path lines in 68 files; Makefile:2 PY points at a missing .venv-app; zsh shebangs; no pinned requirements; 13/33 inputs git-ignored (not verifiable without git) | hard-coded ROOT/OUT | reproducibility on Databricks or a clone | ROOT from __file__, env-overridable OUT/PY, requirements-pipelines.txt, document export.py/verify.py first | can wait |
| M20 (L1) | Planner file carries NaN districts | 13/9,959 facilities; not strict JSON; app/itinerary.py can raise (not reached in 4,459 plans) | planner/data_v1.py writes pd NaN | app /api/plan | None if pd.isna; json.dump(allow_nan=False) | can wait |
| M21 (L2) | Pack quotes change on every build | 37-46 of 11,505 rows show a different sentence, 123-130 differ in quote or order; scores equal | set iteration order picks between quotes | app quote shown; cache keys | key=lambda p: (len(p), p) | can wait |
| M22 (L missed) | Exports switch to derived/v2 the moment the file appears, with no hash | app/facts/build.py:96, app/packs/build_packs.py:101 | no provenance | app after #11 | rebuild after #11; write the v2 file sha256 into facts meta and pack index; check at start | after v2 |

### Low

| id | issue | count | fix | when |
|---|---|---|---|---|
| CL-6 | kb negation cue fires on "non-surgical", "without surgery" | 17/47 negation-cued pairs | drop the technique phrases from the shared cue | before v2 |
| CL-10 | small lexicon errors (CT Hospital, critical care, psychiatric diagnoses) | 3/40 precision errors | case-sensitive CT, exclusions | before v2 |
| INT-04, RL-05 | repeated (record, URL) rows double-counted in source weights | 5,652/158,444 rows, 1,525 records; max source_support change 0.023 | dedupe in s1_sources.explode() | can wait |
| INT-03 | specialty_map labels spelling variants differently | 10 keys, 4 disagree on a service (9 records) | label per normalized key | can wait |
| INT-05, RL-07 | facts.json drops PINs with no district | 227/19,711 PINs, 202 facilities | keep district null rows | can wait |
| INT-07 | string nulls and placeholder claims | 230 cells; 17 placeholder sentences ('-') | map to None, drop placeholders | can wait |
| INT-08 | invalid PINs kept | 7/9,882 | null with raw_ column | can wait |
| INT-09 | duplicate row in vf_opendata_facts | 1/6,001 (dda3a4d5) | drop_duplicates | can wait |
| INT-10 | orphan llm_hours row; yearEstablished 0, 7, 15 | 1 row; 5/4,761 | regenerate; year < 1700 -> null | can wait |
| CL-8 | description split at Dr., Pvt., Ltd., initials | 1,728/18,388 (9.4%); 1,310 end at 'Dr.'; e.g. 024a75df:desc:2 'Dr.' | protect abbreviations in build_claims.py:44 (shifts every claim_id: rebuild all downstream together) | can wait |
| CL-9 | claim idx is not the raw array position | 43,706 claims, 1,813 records | document or add raw_pos | can wait |
| RL-06 | specialties.n_raw doubled for the 11 duplicated ids | 165/117,964 rows | add the qualify clause to SPEC_SQL (build_claims.py:55-56) | can wait |
| L missed | specialties.parquet row order not reproducible; spec claim ids in model/proto/fusion/features.py:178 depend on it | 117,712 rows move | 'order by 1, 2' in SPEC_SQL | before v2 if #11 uses proto spec ids |
| L3, L7, L8 | float ulps, gzip mtime, no output hashes in MANIFEST or exports | max 1.1e-13; facts.json.gz mtime | PYTHONHASHSEED=0, mtime=0, output_sha256 | can wait |
| LOC-03 | high confidence with 1 km radius on loose agreement | 28/7,762 > 10 km outside own polygon, 3 > 25 km; 106 rest on prefix3 | high only when d <= 10 km and point is directory or consensus | can wait |
| LOC-06 | Agartala facilities carry Telangana district Nirmal | 6 (PIN 799001) | district must exist in the PIN's LGD state | can wait |
| LOC-07 | null district with district_src map_point | 13 | LGD polygon district or district_src none | can wait |
| LOC-08 | external district join tables disagree with v1 | 283 real per table | rebuild from facility_location | can wait |
| RL missed | gold verified-true pairs hidden by the grade test | 2 pairs (e5cd0285 csection, 611ce272 cardiac_surgery) | check status before excluded grade (build_packs.py:79-80, engine.py:111) | can wait |
| INT-06 | planner cites attributed_elsewhere / counter_evidence pairs | 41 rows (q_ev 0.17-0.26) | same grade exclusion in V1Store | can wait |
| CL missed | planner p_one -> p_two on echoed copies of one sentence | 215/9,851 rows | count distinct texts | can wait |
| INT missed | graded pairs with no cited sentence; pack rows with no quote | 18 weak with no cite; 1,019/11,505 pack rows | cite ambiguous sentences; "specialty listed" card | can wait |
| INT missed | facility_location.pin stored as double | 9,882 values (112001.0) | cast to Int64 | can wait |
| WF-7 | phone-support 24x7 lines read as emergency | 44 records rest only on them | scope as helpline | before v2 |
| WF-8 | LinkedIn headcount bands as staff counts | 74/8,014 vf staffing facts | accept 'to', 'up to', 'N+' | before v2 if used |
| WF-9 | unredacted landlines in quotes | 45 fact quotes, 5 identity quotes; 0 mobiles | widen redaction or document | can wait |
| WF missed | mojibake in quotes; implausible counts | 42 quotes; 71 ambulance = 24, 12 unit beds > total | ftfy-style decode at extraction; count noun required | can wait |
| LAB-L8, LAB-L9 | leakage group spans dev/test; unattached no_mention verdicts; non-canonical ids; URLs with spaces | 1 group (00197d6a); 6/62; 4/334; 10/308 | regroup with leakage_group_id; map to canonical | before v2 for the group |
| LAB missed | confirmations citing only the record's own source pages | 15/62 | evidence_independent flag | can wait |
| P2 | doctor-named records show a mobile | 553 records in facts.json (535 with a strict 'Dr' rule); sample 37/40 are clinics named after a doctor | label as the doctor's listed number; keep out of public docs | can wait |
| P4-P7 | username in 384 paths; stale DATA_AUDIT.md; how.json links to a private repo; Databricks host and ids in 18 public-class files | as stated | rewrite in public_copy.sh; point REPO_URL at the repo judges can open | before publish |
| CR | government-named records typed private; Hospital names typed clinic | 5/175; 32; 28 (cue counts, not hand-read) | hand-read before using type/operator as features | before v2 if used |

## 3. False alarms and corrected counts

Each area's findings were re-verified independently. These claims did not hold, or held only at a smaller
or different size:

- New fails after the 21:11 rebuild (6). The exports changed format between runs, so these are not yet
  regressions:
  - integrity `claim_id_fk`, `app_packs_integrity` and record_loss `pack_quotes_cited` flag ids like
    `e93a7ae0:=b2db2916:capa:31`. That is the duplicate-group collapse (#78): the canonical record cites a
    member's claim. I checked all 80 such pack quotes, and 80/80 equal the member claim's text exactly.
  - record_loss `facts_pairs_complete` (45 missing, 13 extra) and integrity `app_facts_integrity` (14 value
    differences, e.g. e93a7ae0 burn_care now strong / verified_true) follow from merging members' pairs. This
    is plausible, but I have not verified it pair by pair.
  - `pack_facility_membership` (8bc216dd not a candidate) is not triaged. The 25 score and 10 likely
    mismatches inside `app_packs_integrity` are not triaged either.
  - The checks need updating to the merged-id format. Until then, read these 6 fails as "format changed".
- spineNeurosurgery -> neurosurgery (CL-7). The counts reproduce (265/687), but the mapping is the
  documented choice, and the model damps it with evidence weight 0.417. Not a defect.
- Planner NaN (L1). The regex found 21 hits, but 8 are "Infinity" inside facility names. The real count is
  13 NaN districts.
- External district tables (LOC-08). 289 became 283: 6 rows have both sides null, and NaN != NaN counted
  them as mismatches.
- High confidence far from the PIN centre (LOC-03). Of the 164 records > 10 km from the centre, only 24 are
  > 10 km outside their PIN polygon; 58 lie inside it.
- City conflicts (LOC-04). 7 of 29 high flags came from the resolver (Mahe enclave, Khanapur TS, Gorantla,
  Kalol x2, Khanpur, Sheikhpura).
- Chain pages (WF-5). 298 of 572 multi-record pairs sit within one duplicate group, where crediting both
  records is correct. Only 274 (1.4%) involve two distinct facilities.
- Doctor bios (WF-6). The auditor's regex ("his ", "her ") was too broad: 1,346 rows and 139 pairs became
  257 and 31. The detail side was larger than reported, though: 870 rows come from doctor-profile URLs.
- Phone 24x7 (WF-7). The upper bound was 102 records. A strict cue gives 44.
- Coming soon (WF-11). "upcoming camps" and "upcoming workshops" are not future services, so 8 pairs became
  2. Chrome menu lines are not errors in themselves.
- Fetch metadata (WF-10). 7,383 target_id and 9,599 fetched_at differences, all on shared files with equal
  text hashes. Quotes are unaffected; no fix needed.
- Unredacted phones (WF-9). All are STD landlines (0 mobiles), so these are facility switchboards, not
  personal numbers.
- "Affects the app" for web facts. No app export reads kb/web_evidence or kb/vf_details. The exposure is
  the 8 Databricks tables and model features.
- `restricted_list_copies` fail. The 131 "NABH" hits in the planner are e-RaktKosh hospital names that
  coincide with NABH names. The real issue is the e-RaktKosh bulk directory (H8). The derived/v2 rows the
  check lists are in flux and were not judged.
- travel_cache.sqlite in the deploy bundle (P7). It holds 0 rows.
- Dropped facilities (RL-01). None of the 30 has a surviving copy under another id (same city, fuzz >= 90,
  same PIN or phone). The loss is real, not double-listed.
- Personal mobiles (P2). In the sample, 40/40 "personal-likely" rows are clinics named after a doctor whose
  number is listed for the business.
- `check_enums` crash. This was a runner ordering artifact; the runner now uses source order, and the check
  passes.
- Two counts were revised up, not down. INT-06 is 41 planner rows, not 37. CL-1 is about 56 wrong or
  camp-only citations, not 29.

## 4. Accuracy estimates with intervals

Intervals are 95% Wilson unless noted. "Exhaustive" means every row was checked.

| layer | measure | this audit | earlier claim | held? |
|---|---|---|---|---|
| claims | verbatim at field and index | 469,498/469,498 (exhaustive) | README: claims are raw items | yes |
| claims | description sentence integrity | 16,660/18,388 = 0.906 whole sentences (exhaustive) | none | not stated before |
| attribution | own_anchored | 19/20 (0.764-0.991) | none | - |
| attribution | unanchored | 20/20 (0.839-1.000) | none | - |
| attribution | ambiguous | 16/20 (0.584-0.919) | none | - |
| attribution | other_facility | 15/20 (0.531-0.888); 372/9,506 are the own place | How page "about 1,405/9,959 records name another facility" | no: derived/v1 gives 2,489, STORYBOOK 1,232 |
| taxonomy | lexicon precision | 37/40 = 0.925 (0.801-0.974) | TAXONOMY v1.1 new-5 95/100 (0.888-0.978) | yes |
| taxonomy | lexicon recall (sentence pairs) | about 0.744 (0.468-0.912); misses 2/40 unmatched | none (REVIEW.md "not run") | first estimate |
| taxonomy | specialty map | 39/40 = 0.975 (0.871-0.996) | fresh v1.1 39/40 (0.871-0.996) | yes |
| taxonomy | positives really offers | 29/30 (0.833-0.994) | REPORT claims-03 34/40 | yes |
| taxonomy | 3D-scan ultrasound alternative | 18/101 correct (exhaustive read) | included as ultrasound | no |
| locations | moved points land in the right place | 24/30 = 0.80 (0.63-0.91) | none | - |
| locations | district | 29/30 (0.83-0.99); 9,802/9,946 agree with LGD (exhaustive) | LGD README 19/20 primary district | yes |
| locations | NFHS join | 9,934/9,959 | How page 9,961/9,970 | no: stale denominator |
| locations | raw point > 50 km from PIN centre | 1,367/9,869 (exhaustive) | How page 1,407/9,682; > 100 km 1,114 | no: 1,367 and 1,101 |
| locations | PIN polygon containment | 12/12 confirmed | pincode_boundaries README 12/12 | yes |
| locations | app PIN origin within 50 km of own polygon | 18,809/19,295 (exhaustive) | not checked before | - |
| matches | OSM (kb/opendata, high) | 17/20 (0.64-0.95) | OPENDATA.md validation 17/20 (0.64-0.95) | yes |
| matches | Wikidata | 20/20 (0.84-1.00) | pooled high 39/42 | yes |
| matches | HOT OSM strong | 18/20 (0.70-0.97); exhaustive raw-anchor test: about 6-8% of 3,263 wrong | README 15/20 (75%) | yes, but the sample misses a systematic error |
| matches | NABH | 18/20 (0.70-0.97); misses 3/10 | README 39/40 (97.5%) | lower; 57 raw-anchor pairs, 7/10 wrong |
| matches | e-RaktKosh | 19/20 (0.76-0.99); misses 4/10 (0.17-0.69) | README 16/20 strict, 18/20 lenient | precision yes; recall not reported before |
| matches | LaQshya, NMC, trauma, PMNDP | 20/20; 20/20; 19/20; 1/1 and 7/7 refusals | NMC 19/20; trauma 19/20; PMNDP 1/1 | yes |
| web facts | quotes on page | 237,891/237,891 (exhaustive) | selfcheck | yes |
| web facts | services | 38/60 (0.507-0.744), weighted 0.691 | QA 36/60, weighted 0.690 (0.459-0.844) | yes |
| web facts | cell A (strong, 2+ pages) | 13/18; pooled with QA 26/31 (0.674-0.929) | QA 13/13 (0.772-1.000), "A and B 16/16" | no (Fisher p = 0.058); do not treat cell A as near-certain |
| web facts | hours | 21/30 (0.521-0.833), weighted 0.724 | QA 22/30, weighted 0.508 | yes (raw) |
| web facts | details | 22/30 (0.556-0.858), weighted 0.586 | QA 21/30, weighted 0.787 | no for the weighted figure (accreditation 3/6, other 1/4) |
| web facts | site identity | 23/30 (0.591-0.882); accepted medium 1/5 | QA accepted 12/15, rejected 11/15 | yes overall; medium tier is weak |
| web facts | WEB_EVIDENCE.md scored round | covered by the 60/30/30 samples above | 37/40 (0.801-0.974) | no as a headline: the larger samples are lower |
| vf facts | extraction precision | 37/40 (0.801-0.974), weighted 0.899; 3 of 50 earlier hand-checked ids gone | VF_DETAILS.md 46/50 (0.81-0.97) | yes |
| labels | verdict supported by a fresh URL re-check | 22/25 = 0.88 (0.70-0.96); quote found 12/15 (0.55-0.93) | none | - |
| labels | double-labelled agreement | service kappa 0.382 (21/30) | none | - |
| labels | held-out service AUC | 0 of 6 negatives clean | derived/v1 README 0.826 / 0.819 (n = 29) | no |
| labels | held-out location AUC | 0.770/0.802, or 0.874/0.861 without the 5 weak negatives | 0.770 / 0.802 | number reproduces; 5 of 10 negatives are weak |
| labels | existence | not evaluable (0 negatives) | q_ev 0.984 | no |
| planner | proposed-capability precision | 41/50 = 0.82 (0.69-0.90) | never measured | first estimate |

## 5. How to re-run

From the repo root, with the project interpreter:

```
.venv-viz/bin/python validation/run_all.py --skip-network          # all areas, no warehouse or web calls
.venv-viz/bin/python validation/run_all.py                         # adds the 6 live-warehouse checks (sql.sh)
.venv-viz/bin/python validation/run_all.py --area integrity,labels  # selected areas
.venv-viz/bin/python validation/contracts_v2.py --selftest          # contract code on a synthetic v2
.venv-viz/bin/python validation/critic/checks.py                    # critic checks on their own
```

- Flags: `--timeout S` per check (default 1200), `--jobs N` areas at once (default 2). A full run with
  `--jobs 3` takes about 11-14 minutes. Exit code 1 when any check fails.
- Outputs: `validation/out/scorecard.json`, `validation/out/scorecard.md` and `validation/out/logs/<area>.log`.
- `run_all.py` discovers every `validation/*/checks.py`, so the critic area joins the next full run.
- `contracts_v2.py` has 12 checks. They return not_run until `derived/v2/facility_service_scores.parquet` and
  `derived/v2/model_card.json` both exist. They check keys, coverage, the 12 excluded ids, probability
  ranges, the logit identity, evidence ids, bands, not-observable terms, operator, model_version, witness
  quotes and restricted lists. The rules are in `validation/README.md`.
- The v2-gated area checks need `RUN_V2=1`: claims `v2_claim_id_contract`, labels
  `derived_v2_gold_contract`, record_loss `v2_contract`.
- Re-run the full suite after #11 publishes, and again after the final `make app-data`.

## 6. What is still unchecked

- No check opens these judge-facing artifacts:
  - submission/referral_saathi.ipynb, beyond the critic's 7 saved numbers;
  - viz/STORYBOOK.md;
  - the Genie room's questions and answers;
  - geo/travel.py (travel times);
  - the WorldPop and MAP travel-time inputs.
- The 6 fails that appeared after the 21:11 export rebuild are only partly triaged (section 3). The pack
  quote ids are verified. The pair changes in facts.json and the pack score/likely mismatches are not.
- derived/v2 and model/v2 contents are not checked by design: 12 contract checks plus 3 gated checks are
  waiting.
- The 6 live-warehouse checks passed in the area runs but were not run in the final `--skip-network` run.
- Recall was not re-read for refused OSM, Wikidata, HOT, NMC and trauma pairs. The 30 hand-judged
  e-RaktKosh pairs were not re-read.
- The vf_details precision of the current version, after its last two fixes, has not been re-measured with a
  fresh sample.
- The "personal-likely" phone tier (553 records) has only a 40-row precision sample. The type and operator
  cues (critic) are counts only, not hand-read.
- 13/33 rebuild inputs could not be confirmed as missing from a fresh clone, because git was not allowed.
- Web steps ran from cached fetches in the final run: labels `url_recheck` (25/30 pages reachable) and
  web_facts `site_liveness`.
- These samples are small, and their intervals are wide: attribution strata n = 20, moved points n = 30,
  matches n = 20. Treat them as first estimates.
- The v3 gold TEST set was not opened, by instruction.
