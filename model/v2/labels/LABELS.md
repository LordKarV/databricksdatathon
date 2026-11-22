# Training labels for Witness Ledger v2

Built 2026-11-21 by `labels.py` in this folder. Every number below comes from `out/stats.json`, `out/c_estimates.parquet`
or a query on the tables in `out/`, all written by that script. No model was fitted. `model/gold/v3/` does not exist,
so there are no v3 DEV labels. The script opens only `model/gold/v3/dev_labels.json`, picks it up on a rerun, and
never opens any other v3 file.

Rebuild: `/Users/karthikvattem/projects/datathon/.venv-viz/bin/python labels.py` (about 1 minute). The script asserts
the MODEL_SPEC 3.2 target rule, that no gold facility is missing from derived/v2, that PU rows are unique per
(list, service, facility), that positive weights are > 0, and that every column the cross-fit plan names exists in
`facility_features.parquet`.

## Outputs (out/)

| file | rows | grain |
| --- | --- | --- |
| gold_dev_pairs.parquet | 301 | one gold DEV (facility, service) pair: y_S, y_L, y_E, y_E_strict, status fields, stratum, leakage group, state, fold5, ipw, second labeller |
| gold_dev_facility.parquet | 346 (345 facilities) | location and existence labels per facility and source, for P_L and P_E |
| pu_labels.parquet | 22,737 | one (list, service, facility) inside the list's scope: positive, unlabeled or excluded_expired, weight, citation |
| c_estimates.parquet | 177 | label frequency c per (list, service, anchor); rows with `used` = True are the values to fit with |
| crossfit_plan.parquet | 93 | one (service, label family): what each fit must drop, ablate, or treat as scope |
| stats.json, build_stdout.txt | | counts quoted here |

`fold5` = sha256("labels-v2:" + leakage_group_id) mod 5. It is the same in every table, so a leakage group never
spans two folds and gold, PU and facility fits line up. `state` is `state_final` from derived/v1, for held-out-state
CV.

## 1. Gold DEV labels

Sources, all DEV under MODEL_SPEC 3.1 change 5, since every one of them has already been read:
- v1: 36 pairs (`audit/ground_truth/web_{1,2,3}.json`, metadata in `sample.json`).
- v2: 140 pairs (`model/gold/labels_p1..p7.json`, metadata in `sample_v2.json`). `split_orig` keeps the old
  splits.json value (88 test, 88 dev across v1 and v2) for disclosure only. Every row has `split` = dev.
- e2e: 125 benchmark pairs labelled by `labels_e1..e3.json` (pool in `model/proto/decision/e2e_pairs_to_label.json`).
  They were drawn from the top answers of the benchmark methods, not from strata, so they have no inclusion
  probability (`pi`, `ipw` NaN, `stratum` = e2e_pool). The fit step decides whether to weight them or leave them out
  of the IPW metrics.
- Second labeller (`labels_o1..o2.json`, 30 v2 pairs): stored as `second_service`, `second_exists` and
  `second_location`. They are not used as labels.

No (facility, service) pair is labelled twice across v1, v2 and e2e (`primary` is True for all 301, and
`dup_conflict` is 0). The v1 service key `trauma_emergency` maps to `trauma_care`, its taxonomy alias.

Targets:
- `y_S` (MODEL_SPEC 3.2): confirmed 1. Contradicted 0. no_info with at least one evidence URL 0 (searched, found
  nothing). no_info with no URL is missing (never searched). P_S therefore means "chance a public web check confirms".
- `y_L`: location_ok yes 1, no 0. unclear is missing, because an unclear place is not evidence of a wrong place.
- `y_E`: exists yes 1. no, or unclear with at least one URL, 0. Never searched is missing. This mirrors the y_S rule
  and the prototype's `existence_rows`. `y_E_strict` (yes 1, no 0) is also stored. No gold pair says exists = no, so
  `y_E_strict` has no negatives.

Counts per service (pos / neg is y_S; contradicted is a subset of neg):

| service | pairs | v1 / v2 / e2e | y_S pos | y_S neg | contradicted | y_S missing | y_L 1 / 0 | states | leakage groups |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| burn_care | 39 | 0 / 20 / 19 | 5 | 12 | 2 | 22 | 11 / 5 | 16 | 37 |
| cardiac_surgery | 43 | 6 / 20 / 17 | 13 | 17 | 6 | 13 | 23 / 2 | 19 | 41 |
| dialysis | 45 | 6 / 20 / 19 | 14 | 25 | 3 | 6 | 25 / 5 | 21 | 44 |
| emergency_csection | 48 | 6 / 20 / 22 | 9 | 30 | 7 | 9 | 24 / 7 | 19 | 47 |
| mri | 33 | 6 / 20 / 7 | 6 | 12 | 2 | 15 | 16 / 3 | 21 | 33 |
| nicu | 46 | 6 / 20 / 20 | 8 | 22 | 3 | 16 | 23 / 4 | 24 | 46 |
| trauma_care | 47 | 6 / 20 / 21 | 7 | 15 | 3 | 25 | 16 / 5 | 21 | 46 |
| total | 301 | 36 / 140 / 125 | 62 | 133 | 26 | 106 | 138 / 31 | 33 distinct | 274 distinct |

By version, y_S pos / neg / missing: v1 15 / 20 / 1, v2 31 / 51 / 58, e2e 16 / 62 / 47. By stratum: strong
24 / 12 / 11, weak 6 / 24 / 17, suspect 11 / 21 / 15, no_mention 5 / 14 / 16, e2e_pool 16 / 62 / 47. Labeller
confidence: low 173, medium 105, high 23.

The 29 other services have no gold labels at all. For them the only labels are the PU lists in section 2.

`gold_cites_list` is True on 9 pairs whose evidence URLs include an official-list site (all of them portal.nabh.co).
For those 9 pairs the gold label and the NABH features read the same list. Section 3 says how to handle them.

Facility labels (`gold_dev_facility.parquet`): 290 gold facilities (the first labelled pair per facility, in the
order v3_dev, v2, v1, e2e; no facility has conflicting y_L or y_E across its pairs), plus the two location hand
checks the prototype P_L fit used: 30 `geo_hand_check` (the verdict for the source behind p1) and 26
`cleaning_hand_check`. A hand-check row is dropped when the facility already has a gold y_L.

| source | y_L 1 | y_L 0 | y_L missing |
| --- | --- | --- | --- |
| gold_dev | 131 | 31 | 128 |
| geo_hand_check | 28 | 2 | 0 |
| cleaning_hand_check | 22 | 4 | 0 |

Gold y_E per facility: 163 ones, 10 zeros (unclear and searched), 117 missing. That is still under the 15 negatives
MODEL_SPEC 3.3 asks for before P_E is fitted, so P_E stays prior-only.

## 2. Positive-unlabeled labels from official lists

The list matches, thresholds and scopes are the ones `model/v2/assemble/external.x_lists` used to build family X.
The function is imported and run unchanged, so labels and features cannot disagree about who matched or who is in
scope.

- In scope: the list covers that kind of facility (the assemble step's `absent` or `present`). Positive = in scope and
  the list states the fact. Unlabeled = in scope and the list says nothing. Outside scope (`not_observable`) is
  excluded and not written: absence from a list is never a negative, and a facility the list cannot see is not even
  unlabeled.
- Positive weight = the list's hand-checked match precision x the witness value from assemble: 1.0 for a strong fact,
  0.5 for an NMC support course. Unlabeled rows have weight 1. `match_k` and `match_n` carry the counts for intervals.
- Each positive row carries its citation: `evidence_id`, `evidence_url`, `quote`, `value_text` and `fetched_date`.
  Only matched facilities appear, one fact per row. No list is copied whole; NABH rows hold the matched facility's
  acc_no and certificate URL only.

| label family | services | scope (who can be unlabeled) | match precision |
| --- | --- | --- | --- |
| nabh | DIA to dialysis; NPH to dialysis, kidney_transplant; TRN to kidney_transplant; OBG to emergency_csection, institutional_delivery, high_risk_pregnancy; EMD to emergency_24x7, trauma_care; CAR to cardiac_surgery, cath_lab_angioplasty, stemi_thrombolysis (proxy); ONC to chemotherapy, radiotherapy, surgical_oncology | the 1,054 NABH-matched facilities with at least one fetched specialty code | 39/40 |
| nmc | 32 services (strong or support PG course, assemble map extended from external/nmc_colleges/join.py) | NMC-matched colleges (81) | 19/20 |
| laqshya | valid Maternity OT certificate to emergency_csection; valid Labour Room certificate to institutional_delivery | public CHC, SDH, DH or MC by name, or matched | 17/20 (3 more plausible) |
| mohfw_tcf | trauma_care | public hospitals, or matched | 19/20 |
| eraktkosh | blood_bank (the prerequisite rows for four other services are features, not labels) | hospitals, or matched | 16/20 strict |
| pmndp_goa | dialysis | public facilities in Goa | 1/1 (recall 1/8) |

A LaQshya certificate that expired before 2026-11-21 is coded `excluded_expired` (weight 0): the list stated the
fact once, so the facility is neither a clean positive nor unlabeled. That covers 35 rows for C-section and 41 for
delivery. Re-coding them as positives with weight 0.5 x precision is a one-line change if the fit wants them.

Counts (positives, summed positive weight, unlabeled):

| family | service | positive | weight | unlabeled |
| --- | --- | --- | --- | --- |
| nabh | emergency_csection, institutional_delivery, high_risk_pregnancy (OBG) | 890 each | 867.75 | 164 |
| nabh | cardiac_surgery, cath_lab_angioplasty, stemi_thrombolysis (CAR) | 531 each | 517.72 | 523 |
| nabh | kidney_transplant | 497 | 484.58 | 557 |
| nabh | dialysis | 488 | 475.80 | 566 |
| nabh | chemotherapy, radiotherapy, surgical_oncology (ONC) | 332 each | 323.70 | 722 |
| nabh | emergency_24x7, trauma_care (EMD) | 297 each | 289.58 | 757 |
| eraktkosh | blood_bank | 365 | 292.00 | 5,280 |
| mohfw_tcf | trauma_care | 20 | 19.00 | 418 |
| laqshya | emergency_csection | 14 | 11.90 | 130 |
| laqshya | institutional_delivery | 13 | 11.05 | 125 |
| pmndp_goa | dialysis | 1 | 1.00 | 1 |
| nmc | orthopaedic_trauma_surgery 70, trauma_care 70, emergency_csection 69, institutional_delivery 69, high_risk_pregnancy 69, safe_abortion_mtp 69, icu 69, ventilator_support 69, nicu 68, picu 68, paediatric_inpatient 68, cataract_surgery 64, eye_emergency 64, ct_scan 62, mri 62, ultrasound 62, de_addiction 51, psychiatric_care 51, tb_care 44, stemi_thrombolysis 40, cardiac_surgery 26, cath_lab_angioplasty 26, emergency_24x7 26, kidney_transplant 23, neurosurgery 23, stroke_care 23, radiotherapy 21, burn_care 19, dialysis 16, blood_bank 10, surgical_oncology 9, chemotherapy 6 | see stats.json | 81 minus positives |

Positive facilities by state: NABH 1,054 facilities in 29 states, e-RaktKosh 365 in 30, NMC 72 in 23, MoHFW 20 in
12, LaQshya 18 in 10, PMNDP 1 in 1. Held-out-state CV is possible for NABH and e-RaktKosh. For MoHFW, LaQshya and
PMNDP it is not, and grouped folds are the most those lists allow.

### Label frequency c (Elkan and Noto)

c = P(list positive | the service is offered, facility in the list's scope). Under SCAR, P(offered | x) =
P(list positive | x) / c inside the scope. c folds in both list coverage and match recall. It is estimated as k/n
with a 95% Wilson interval on three anchor sets of known positives:
- `gold`: gold DEV pairs with y_S = 1. `gold_no_list_url` drops the 9 pairs that cite a list site; it gave the same
  k and n everywhere.
- `web_AB`: pairs whose own website has a cell A or B service quote (QA 13/13 and 3/3). This anchor does not use the
  lists.
- `text_T4`: pairs with own-text level T >= 4. This anchor does not use the lists either.

Rule, fixed before reading the results (`MIN_POS_FOR_C` = 10): use the first anchor with n >= 10 in the order gold,
web_AB, text_T4 for the service. If none qualifies, use the list's pooled estimate in the same order. If that fails
too, use the documented prior c = 0.5 [0.1, 0.9], a deliberately wide guess with no data behind it.

Gold gives n >= 10 only for NABH pooled over services: 6/10, c = 0.60 [0.31, 0.83]. By service it gives cardiac 2/2,
C-section 3/4 and trauma 1/4. For NMC gold gives 5/8 pooled, and for LaQshya 0/2 and MoHFW 1/1. Those are too few
to use, so web_AB or text_T4 carries most of the estimates:

| family | service | anchor | k / n | c [95% CI] |
| --- | --- | --- | --- | --- |
| nabh | emergency_csection | web_AB | 31/32 | 0.969 [0.843, 0.995] |
| nabh | institutional_delivery | web_AB | 106/113 | 0.938 [0.878, 0.970] |
| nabh | high_risk_pregnancy | web_AB | 56/61 | 0.918 [0.822, 0.965] |
| nabh | cardiac_surgery | web_AB | 111/125 | 0.888 [0.821, 0.932] |
| nabh | radiotherapy | web_AB | 42/48 | 0.875 [0.753, 0.941] |
| nabh | cath_lab_angioplasty | web_AB | 115/132 | 0.871 [0.803, 0.918] |
| nabh | kidney_transplant | web_AB | 42/49 | 0.857 [0.733, 0.929] |
| nabh | chemotherapy | web_AB | 68/89 | 0.764 [0.666, 0.840] |
| nabh | dialysis | web_AB | 143/207 | 0.691 [0.625, 0.750] |
| nabh | surgical_oncology | web_AB | 81/124 | 0.653 [0.566, 0.731] |
| nabh | trauma_care | web_AB | 84/228 | 0.368 [0.309, 0.433] |
| nabh | emergency_24x7 | web_AB | 140/407 | 0.344 [0.300, 0.391] |
| nabh | stemi_thrombolysis | gold, pooled over NABH | 6/10 | 0.600 [0.313, 0.832] |
| eraktkosh | blood_bank | web_AB | 92/296 | 0.311 [0.261, 0.366] |
| mohfw_tcf | trauma_care | web_AB | 1/18 | 0.056 [0.010, 0.258] |
| nmc | mri | text_T4 | 12/13 | 0.923 [0.667, 0.986] |
| nmc | icu | web_AB | 16/18 | 0.889 [0.672, 0.969] |
| nmc | ultrasound | text_T4 | 13/15 | 0.867 [0.621, 0.963] |
| nmc | ct_scan | text_T4 | 17/20 | 0.850 [0.640, 0.948] |
| nmc | emergency_24x7 | web_AB | 9/22 | 0.409 [0.233, 0.613] |
| nmc | neurosurgery | web_AB | 3/10 | 0.300 [0.108, 0.603] |
| nmc | blood_bank | web_AB | 0/18 | 0.000 [0.000, 0.176] |
| nmc | the other 25 services | web_AB, pooled over NMC | 65/129 | 0.504 [0.419, 0.589] |
| laqshya | emergency_csection, institutional_delivery | documented prior | not estimable (anchors n = 2, 3, 1) | 0.5 [0.1, 0.9] |
| pmndp_goa | dialysis | documented prior | not estimable | 0.5 [0.1, 0.9] |

What these mean for the fit:
- None of the anchors is a random sample of positives. Web and text anchors lean toward large private hospitals with
  rich sites and listings, so they probably overstate c for NABH and understate it for lists of public facilities.
  Every c is conditional on its anchor, and the `anchor` column says which one was used.
- NMC blood_bank (0/18) and MoHFW trauma_care (1/18) have c near 0. A PU fit on them would claim almost every
  facility offers the service. Use them as rare high-precision positives (for an evaluation of precision at the top),
  not as PU training labels. The MoHFW list is 196 facilities nationwide, and its "12th plan: supported" rows were not
  functional as of 2019 (see `value_text`).
- LaQshya and PMNDP are not estimable. Their prior is a stated guess, and any metric that depends on it must say so.

## 3. Cross-fitting plan

`crossfit_plan.parquet` has one row per (service, label family): 50 list rows, 7 gold rows and 36 facility-head rows
(the facility head is service-independent; the rows repeat it per service for joins). Columns: `drop_witness_rows`,
`drop_columns` (must not enter the fit), `ablate_columns` (may enter, but the fit must also be reported without
them), `scope_columns` (they define the list's scope, so they are near-constant within it; allowed, not
discriminative). The leakage grades come from `viz/features/features_catalogue.csv`
(direct, fitted, shared, selection, design), extended to the v2 columns.

| label family | drop | ablate | scope |
| --- | --- | --- | --- |
| nabh | X rows with source_key nabh for every service (pooled fits included); d_nabh_service_code, d_nabh_listed, d_nabh_full_accreditation; x_any_list, obs_X | k_text_nabh (record text says NABH; FEATURES.md "shared") | d_nabh_listed |
| nmc | X rows source_key nmc; d_nmc_course_strong; x_any_list, obs_X | none | none |
| laqshya | X rows source_key laqshya; d_laqshya_ot_valid, d_laqshya_ot_ever, d_laqshya_labour_room; x_any_list, obs_X | none | operator_public, g_public_level, g_iphs_prior, g_iphs_essential |
| mohfw_tcf | X rows source_key mohfw_tcf; d_mohfw_trauma_centre; x_any_list, obs_X | none | operator_public, g_type_hospital |
| eraktkosh | X rows source_key eraktkosh (including its prerequisite rows); d_erk_blood_centre_on_site, d_erk_nearest_km; x_any_list, obs_X | none | g_type_hospital |
| pmndp_goa | X rows source_key pmndp_goa; x_any_list, obs_X | none | operator_public |
| gold_web_check (7 services) | b_loc_conf, b_coord_pin_km (tuned on gold); R rows if the issue #50 reader was trained on gold pairs | website and cited-source columns: e_site_alive, e_identity_conf, e_web_hours_found, e_web_service, e_web_cell, e_web_negated, e_web_24x7_emergency, web_state, obs_W, c_n_urls, c_log2_n_urls, c_share_social, b_website_other_org (FEATURES.md: 43 of 60 gold evidence URLs overlap the feature pages) | none |
| location and existence (facility) | b_loc_conf, b_coord_pin_km | d_nabh_listed, f_osm_match, f_osm_conflict (matcher gates, "selection") | none |

Rules behind the table:
- A list used as the label is dropped as a source, not only for its own service. NABH NPH, for example, feeds
  dialysis and kidney_transplant, and a pooled EBM with service as a term would otherwise see the label through a
  sibling service. Other lists' X rows stay as features. `x_any_list` and `obs_X` aggregate every list, so they are
  dropped, or rebuilt without the label list.
- For gold fits the official lists stay as features (MODEL_SPEC 3.1: a list used as X is never an evaluation label).
  On the 9 `gold_cites_list` pairs the labeller read the NABH portal, so the NABH-feature weight should also be
  reported with those pairs removed.
- Text families T, C, N, S, P and D are graded "design" against gold, because the gold strata were drawn on the rule
  grade. They are not dropped, but stratum IPW (`ipw`) is needed for any rate-type metric on v1 and v2 pairs.
- Folds: use `fold5`, which groups by leakage group, and where a list allows it hold out by `state`. Gold has 33
  states. NABH and e-RaktKosh positives span 29 and 30 states.

## Not run and limits

- No hand check of the list-to-service meaning beyond match precision. NABH codes are self-declared departments,
  CAR to stemi_thrombolysis is a proxy, and the NMC extension to 32 services is assemble's unchecked mapping.
  Positive weights carry match precision only, not meaning precision.
- c intervals are Wilson on anchor counts. They do not include the anchors' own error (web cell A/B is 16/16 in QA)
  or the selection bias described above.
- Gold y_E has 10 negatives (none strict), y_S has 62 positives across 7 services, and 29 services have no gold.
  Labels are still the bottleneck, as in v1.
- The e2e pairs have no inclusion probability, and the fit step must decide how to weight them.
- No Databricks run.
