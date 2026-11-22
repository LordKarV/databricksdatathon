# Training labels for Witness Ledger v2 (final, with v3 DEV)

Built 2026-11-21 by `labels.py` in this folder. Every number below comes from `out/stats.json`,
`out/c_estimates.parquet` or a query on the tables in `out/`, all written by that script. No model was fitted. All
gold labels are agent-labelled, not human-checked.

Rebuild: `/Users/karthikvattem/projects/datathon/.venv-viz/bin/python labels.py` (about 1 minute). There is no test
file in this folder; the checks are asserts in `main()`, and the build fails if any of them fails:
- the MODEL_SPEC 3.2 target rule on y_S;
- no gold facility is missing from derived/v2; every v3 pair has 0 < inclusion_prob <= 1;
- zero overlap with v3 TEST, by facility and by leakage group, in `gold_dev_pairs`, `gold_dev_facility` and
  `pu_labels` (checked inside `drop_blocked`, and re-checked by hand after the run: 0 and 0 in all three tables);
- every gold trauma_care row is v3_dev, and no pre-v3 row is trauma_care;
- `fold5` equals the hash of the leakage group in gold and PU, and no leakage group in a gold fold appears in another
  fold of the PU table;
- PU rows unique per (list, service, facility), positive weights > 0, and every column the cross-fit plan names exists
  in `facility_features.parquet`.

## What changed in this build

1. v3 DEV ingested: 300 pairs from `model/gold/v3/dev_labels.json`. The service id is read from `service_id` and the
   verdict from `service`. `inclusion_prob` is carried through as `pi` (and `ipw` = 1 / pi). The 75 double-labelled
   pairs carry the second label in `second_service`, `second_exists`, `second_location` (agreement on the service
   verdict 0.907, 68 of 75). `batch` is `v3_dev_<batch>`.
2. Old trauma labels remapped: every v1, v2 and e2e pair whose service was `trauma_emergency` (the old rubric asked
   about 24x7 emergency care) is now `emergency_24x7` (6 v1, 20 v2, 21 e2e). `service_raw` keeps the old key.
   trauma_care gold comes only from v3 DEV (34 pairs).
3. TEST exclusion: the 150 facilities in `model/gold/v3/test_sample.json` (ids only; no TEST label file was opened)
   sit in 150 leakage groups, which hold 209 facilities. All 209 are listed in `out/test_blocked_facilities.parquet`
   and removed from every training table:

   | table | rows removed | facilities removed |
   | --- | --- | --- |
   | gold_dev_pairs | 0 | 0 |
   | gold_dev_facility (gold, geo and cleaning hand checks) | 0 | 0 |
   | pu_labels | 1,237 | 197 |

   Gold removed nothing because the TEST draw already excluded earlier gold and v3 DEV facilities and groups
   (`model/gold/v3/README.md`). The PU removal is what keeps the list labels clean of TEST.
4. New column `y_S_cc` (headline target): confirmed 1, contradicted 0, no_info missing. `y_S` keeps the MODEL_SPEC 3.2
   rule (searched and nothing = 0, never searched missing) for the sensitivity analysis.

## Outputs (out/)

| file | rows | grain |
| --- | --- | --- |
| gold_dev_pairs.parquet | 601 (597 primary) | one gold DEV (facility, service) pair: y_S_cc, y_S, y_L, y_E, y_E_strict, stratum, pi, ipw, leakage group, state, fold5, second labeller |
| gold_dev_facility.parquet | 630 (629 facilities) | location and existence labels per facility and source, for P_L and P_E |
| pu_labels.parquet | 21,500 | one (list, service, facility) inside the list's scope: positive, unlabeled or excluded_expired, weight, citation |
| c_estimates.parquet | 182 | label frequency c per (list, service, anchor); rows with `used` = True are the values to fit with |
| crossfit_plan.parquet | 95 | one (service, label family): what each fit must drop, ablate, or treat as scope |
| test_blocked_facilities.parquet | 209 | TEST facilities and their leakage-group mates; `is_test_facility` marks the 150 |
| stats.json, build_stdout.txt | | counts quoted here |

`fold5` = sha256("labels-v2:" + leakage_group_id) mod 5, the same in every table, so a leakage group never spans two
folds. `state` is `state_final` from derived/v1, for held-out-state CV.

## 1. Gold DEV labels

Sources, all DEV:
- v1: 36 pairs (`audit/ground_truth/web_{1,2,3}.json`).
- v2: 140 pairs (`model/gold/labels_p1..p7.json`). `split_orig` keeps the old splits.json value for disclosure only.
- e2e: 125 benchmark pairs (`labels_e1..e3.json`), drawn from top benchmark answers, so no inclusion probability.
- v3 DEV: 300 pairs, stratified sample with known inclusion probability per cell.

Four (facility, service) pairs were labelled in both e2e and v3 DEV (e2e_081, e2e_132, e2e_024, e2e_013). The v3 row
is primary (`VERSION_RANK`: v3_dev > v2 > v1 > e2e); the e2e row stays with `primary` = False. No duplicate disagrees
on y_S (`dup_conflict` 0). Use `primary` rows only: 597.

Targets:
- `y_S_cc` (headline): confirmed 1, contradicted 0, no_info missing.
- `y_S` (MODEL_SPEC 3.2, sensitivity): confirmed 1; contradicted 0; no_info with an evidence URL 0; no_info with no
  URL missing.
- `y_L`: location_ok yes 1, no 0, unclear missing.
- `y_E`: exists yes 1; no, or unclear with a URL, 0; never searched missing. `y_E_strict`: yes 1, no 0.

Counts per service (primary rows):

| service | pairs | v1 / v2 / e2e / v3 | confirmed | contradicted | no_info | y_S 1 / 0 / missing | y_L 1 / 0 | public pairs | states | groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| burn_care | 72 | 0 / 20 / 18 / 34 | 15 | 7 | 50 | 15 / 34 / 23 | 41 / 5 | 9 | 18 | 67 |
| cardiac_surgery | 77 | 6 / 20 / 16 / 35 | 26 | 12 | 39 | 26 / 37 / 14 | 54 / 2 | 10 | 23 | 73 |
| dialysis | 79 | 6 / 20 / 18 / 35 | 28 | 4 | 47 | 28 / 43 / 8 | 54 / 6 | 12 | 27 | 77 |
| emergency_24x7 | 81 | 6 / 20 / 21 / 34 | 18 | 8 | 55 | 18 / 37 / 26 | 47 / 5 | 10 | 25 | 80 |
| emergency_csection | 82 | 6 / 20 / 22 / 34 | 20 | 7 | 55 | 20 / 53 / 9 | 51 / 7 | 10 | 20 | 79 |
| mri | 68 | 6 / 20 / 7 / 35 | 16 | 5 | 47 | 16 / 32 / 20 | 40 / 3 | 13 | 23 | 68 |
| nicu | 80 | 6 / 20 / 19 / 35 | 21 | 4 | 55 | 21 / 34 / 25 | 43 / 5 | 7 | 25 | 78 |
| stemi_thrombolysis | 24 | 0 / 0 / 0 / 24 | 14 | 2 | 8 | 14 / 10 / 0 | 16 / 0 | 1 | 14 | 21 |
| trauma_care | 34 | 0 / 0 / 0 / 34 | 10 | 4 | 20 | 10 / 22 / 2 | 22 / 1 | 4 | 14 | 33 |
| total | 597 | 36 / 140 / 121 / 300 | 168 | 53 | 376 | 168 / 302 / 127 | 368 / 34 | 76 | 33 distinct | 524 distinct |

So the headline metric has 221 decided pairs (168 confirmed, 53 contradicted); the sensitivity rule has 470.

By operator (operator from `facility_attributes.parquet`, primary rows):

| operator | confirmed | contradicted | no_info | y_S 1 / 0 / missing |
| --- | --- | --- | --- | --- |
| private | 137 | 49 | 291 | 137 / 242 / 98 |
| public | 28 | 3 | 45 | 28 / 30 / 18 |
| unknown | 3 | 1 | 40 | 3 / 30 / 11 |

Public facilities have 3 contradicted pairs in total (2 v1, 1 v2) and none from v3 DEV (13 confirmed, 0 contradicted,
13 no_info among 26 public v3 pairs). Any confirmed-vs-contradicted AUROC for public facilities therefore rests on 3
negatives and is close to undefined; the sensitivity rule has 30 public negatives, almost all "searched, found
nothing". Report this plainly rather than a public AUROC.

By version, confirmed / contradicted / no_info: v1 15 / 7 / 14, v2 31 / 4 / 105, e2e 15 / 15 / 91, v3 DEV
107 / 27 / 166. By stratum: strong 62 / 4 / 58, weak 31 / 14 / 79, suspect 29 / 10 / 76, no_mention 31 / 10 / 72,
e2e_pool 15 / 15 / 91. Labeller confidence: low 332, medium 180, high 85.

Inclusion weights: v3 DEV has `pi` on all 300 pairs; v1 and v2 have the older stratum pi (5 / pool); e2e has none.
On the 134 decided v3 DEV pairs the Kish effective n under 1 / pi is 43.2. By service (n, n_eff): burn_care 15, 10.5;
cardiac_surgery 20, 11.5; dialysis 15, 6.7; emergency_24x7 16, 5.9; emergency_csection 11, 7.7; mri 13, 6.3; nicu 14,
7.8; stemi_thrombolysis 16, 9.6; trauma_care 14, 8.1. Weighted metrics need intervals that reflect these n_eff.

The 27 services outside these 9 have no gold labels; for them the only labels are the PU lists in section 2.

`gold_cites_list` is True on 13 primary pairs whose evidence URLs include an official-list site. For those the gold
label and the list features read the same source (section 3).

Facility labels (`gold_dev_facility.parquet`): 575 gold facilities (first labelled pair per facility, order v3_dev,
v2, v1, e2e; no facility has conflicting y_L or y_E across pairs), plus 29 `geo_hand_check` and 26
`cleaning_hand_check` rows (a hand-check row is dropped when the facility already has a gold y_L).

| source | y_L 1 | y_L 0 | y_L missing |
| --- | --- | --- | --- |
| gold_dev | 354 | 34 | 187 |
| geo_hand_check | 27 | 2 | 0 |
| cleaning_hand_check | 22 | 4 | 0 |

Gold y_E per facility: 394 ones, 47 zeros, 134 missing. All 47 zeros are "unclear and searched"; no pair says
exists = no, so `y_E_strict` still has no negatives. The 47 clear the 15-negative bar of MODEL_SPEC 3.3 only under the
lenient rule, and an "unclear" existence verdict is weak evidence of non-existence.

## 2. Positive-unlabeled labels from official lists

Unchanged in method: matches, thresholds and scopes come from `model/v2/assemble/external.x_lists`, run unchanged.
In scope and stated = positive; in scope and silent = unlabeled; outside scope = not written (never a negative).
Positive weight = match precision x witness value (1.0 strong, 0.5 NMC support course). LaQshya certificates that
expired before 2026-11-21 are `excluded_expired` (weight 0). Rows for the 209 TEST-blocked facilities are removed.

| family | service | positive | weight | unlabeled | expired |
| --- | --- | --- | --- | --- | --- |
| nabh | emergency_csection, institutional_delivery, high_risk_pregnancy (OBG) | 855 each | 833.62 | 160 | |
| nabh | cardiac_surgery, cath_lab_angioplasty, stemi_thrombolysis (CAR) | 510 each | 497.25 | 505 | |
| nabh | kidney_transplant | 472 | 460.20 | 543 | |
| nabh | dialysis | 463 | 451.42 | 552 | |
| nabh | chemotherapy, radiotherapy, surgical_oncology (ONC) | 314 each | 306.15 | 701 | |
| nabh | emergency_24x7, trauma_care (EMD) | 283 each | 275.92 | 732 | |
| eraktkosh | blood_bank | 343 | 274.40 | 5,105 | |
| mohfw_tcf | trauma_care | 15 | 14.25 | 342 | |
| laqshya | emergency_csection | 9 | 7.65 | 111 | 25 |
| laqshya | institutional_delivery | 9 | 7.65 | 106 | 30 |
| pmndp_goa | dialysis | 1 | 1.00 | 1 | |
| nmc | 32 services: trauma_care and orthopaedic_trauma_surgery 60; icu, nicu, picu, ventilator_support, emergency_csection, institutional_delivery, high_risk_pregnancy, safe_abortion_mtp, paediatric_inpatient 59; cataract_surgery, eye_emergency 55; ct_scan, mri, ultrasound 53; de_addiction, psychiatric_care 47; tb_care 41; stemi_thrombolysis 31; emergency_24x7, cardiac_surgery, cath_lab_angioplasty 21; kidney_transplant 20; neurosurgery, stroke_care 17; radiotherapy 16; burn_care 15; dialysis 13; surgical_oncology, blood_bank 8; chemotherapy 4 | see stats.json | | |

Positive facilities by state: NABH 1,015 in 29 states, e-RaktKosh 343 in 30, NMC 62 in 22, MoHFW 15 in 10, LaQshya 12
in 7, PMNDP 1 in 1.

The trauma_care PU labels (NABH EMD, MoHFW, NMC) are list labels, not old gold labels, so the trauma remap does not
touch them. If "trauma_care trained only on v3 labels" is meant to cover list labels too, drop those rows in the fit.

### Label frequency c (Elkan and Noto)

Same rule as before (`MIN_POS_FOR_C` = 10; anchors gold, web_AB, text_T4; then pooled over the list; then the
documented prior 0.5 [0.1, 0.9]). With v3 DEV the gold anchor now qualifies more often. Values used:

| family | service | anchor | k / n | c [95% CI] |
| --- | --- | --- | --- | --- |
| nabh | emergency_csection | web_AB | 30/31 | 0.968 [0.838, 0.994] |
| nabh | institutional_delivery | web_AB | 100/107 | 0.935 [0.871, 0.968] |
| nabh | high_risk_pregnancy | web_AB | 55/60 | 0.917 [0.819, 0.964] |
| nabh | cardiac_surgery | web_AB | 110/123 | 0.894 [0.828, 0.937] |
| nabh | cath_lab_angioplasty | web_AB | 112/126 | 0.889 [0.822, 0.933] |
| nabh | radiotherapy | web_AB | 42/48 | 0.875 [0.753, 0.941] |
| nabh | kidney_transplant | web_AB | 40/47 | 0.851 [0.723, 0.926] |
| nabh | chemotherapy | web_AB | 66/87 | 0.759 [0.659, 0.836] |
| nabh | dialysis | web_AB | 135/199 | 0.678 [0.611, 0.739] |
| nabh | surgical_oncology | web_AB | 78/121 | 0.645 [0.556, 0.724] |
| nabh | emergency_24x7 | gold | 5/10 | 0.500 [0.237, 0.763] |
| nabh | trauma_care | web_AB | 81/220 | 0.368 [0.307, 0.434] |
| nabh | stemi_thrombolysis | gold, pooled over NABH | 30/39 | 0.769 [0.617, 0.874] |
| eraktkosh | blood_bank | web_AB | 89/280 | 0.318 [0.266, 0.375] |
| mohfw_tcf | trauma_care | web_AB | 1/11 | 0.091 [0.016, 0.377] |
| nmc | icu | web_AB | 16/17 | 0.941 [0.730, 0.990] |
| nmc | mri | text_T4 | 9/10 | 0.900 [0.596, 0.982] |
| nmc | ct_scan | text_T4 | 15/18 | 0.833 [0.608, 0.942] |
| nmc | ultrasound | text_T4 | 9/11 | 0.818 [0.523, 0.949] |
| nmc | emergency_24x7 | web_AB | 8/20 | 0.400 [0.219, 0.613] |
| nmc | blood_bank | web_AB | 0/16 | 0.000 [0.000, 0.194] |
| nmc | the other 26 services | gold, pooled over NMC | 10/18 | 0.556 [0.337, 0.754] |
| laqshya | emergency_csection, institutional_delivery | documented prior | not estimable | 0.5 [0.1, 0.9] |
| pmndp_goa | dialysis | documented prior | not estimable | 0.5 [0.1, 0.9] |

None of the anchors is a random sample of positives, so every c is conditional on its anchor. NMC blood_bank and
MoHFW trauma_care have c near 0: use them as rare high-precision positives, not as PU training labels. LaQshya and
PMNDP c are stated guesses.

## 3. Cross-fitting plan

`crossfit_plan.parquet`: 95 rows, one per (service, label family): 50 list rows, 9 gold rows (now including
emergency_24x7, stemi_thrombolysis and v3-only trauma_care) and 36 facility-head rows. The drop, ablate and scope rules
are unchanged from the previous build:

| label family | drop | ablate | scope |
| --- | --- | --- | --- |
| nabh | X rows source_key nabh, every service; d_nabh_service_code, d_nabh_listed, d_nabh_full_accreditation; x_any_list, obs_X | k_text_nabh | d_nabh_listed |
| nmc | X rows source_key nmc; d_nmc_course_strong; x_any_list, obs_X | none | none |
| laqshya | X rows source_key laqshya; d_laqshya_ot_valid, d_laqshya_ot_ever, d_laqshya_labour_room; x_any_list, obs_X | none | operator_public, g_public_level, g_iphs_prior, g_iphs_essential |
| mohfw_tcf | X rows source_key mohfw_tcf; d_mohfw_trauma_centre; x_any_list, obs_X | none | operator_public, g_type_hospital |
| eraktkosh | X rows source_key eraktkosh; d_erk_blood_centre_on_site, d_erk_nearest_km; x_any_list, obs_X | none | g_type_hospital |
| pmndp_goa | X rows source_key pmndp_goa; x_any_list, obs_X | none | operator_public |
| gold_web_check (9 services) | b_loc_conf, b_coord_pin_km; R rows if the reader was trained on gold | e_site_alive, e_identity_conf, e_web_hours_found, e_web_service, e_web_cell, e_web_negated, e_web_24x7_emergency, web_state, obs_W, c_n_urls, c_log2_n_urls, c_share_social, b_website_other_org | none |
| location and existence (facility) | b_loc_conf, b_coord_pin_km | d_nabh_listed, f_osm_match, f_osm_conflict | none |

Folds: use `fold5` (grouped by leakage group, identical across gold, PU and facility tables; asserted), and
held-out `state` where a list allows it. The TEST-blocked facilities are absent from all three tables, so no fold
can train on a TEST facility or its group. Fit code that reads other per-facility data (features, witnesses) for
training rows should take its rows from these tables or exclude `test_blocked_facilities.parquet` itself.

## Not run and limits

- Labels are agent-labelled, not human-checked. v3 double labelling agrees on 68 of 75 service verdicts (0.907).
- No hand check of list-to-service meaning beyond match precision.
- Public facilities have 3 contradicted pairs, so confirmed-vs-contradicted ranking ability on public facilities
  cannot be measured from these labels.
- e2e pairs have no inclusion probability; v1 and v2 pi are the older per-stratum values, not on the v3 frame.
- trauma_care and stemi_thrombolysis gold exist only in v3 DEV (14 and 16 decided pairs).
- No Databricks run. Numbers from the earlier builds (v1 labels, the 301-pair build) are history.

## Not in the repository

`out/pu_labels.parquet` (21500 rows, sha256 fd68d7368444f789a84b770349857f72e1db1fd4e52192c5457378903d6c47d3) is built by `labels.py` from the restricted official lists under `data/external/`, which are not redistributed, so the file is not committed. The frozen model v2 does not need it at run time.
