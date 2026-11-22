# Feature study for the core model (#11)

Every candidate feature for the (facility, service) model, measured three ways: how often it has a
value, how well it separates confirmed from unconfirmed pairs on the gold DEV split, and how well it
separates official-list positives from the rest. Each feature carries its leakage risk, its
redundancy cluster and the sentence a Referral Saathi card would print. The recommended set for #11
is at the end and in `recommended_feature_set.json`.

Grain: 9,959 usable records x 7 core services (dialysis, emergency C-section, NICU, cardiac surgery,
MRI, burn care, trauma) = 69,713 pairs, the same grid as `model/proto/evidence/pair_features.parquet`.
110 candidate features in 9 families. All numbers below come from the scripts in this folder; the
file each input came from is in the `source_file` column of `features_catalogue.csv`.

## What we found

1. For 83% of pairs (58,025 of 69,713) no source says anything about the service: not the dataset
   text, not the facility's website, not an official list, not OpenStreetMap. Trauma is the
   exception (59% silent). Chart 01.
2. Independent sources add facilities the text never mentions. For emergency C-section, 1,103
   facilities have a website, list or OSM signal with no text mention, against 248 the other way
   round; 714 of the 1,103 have nothing but a NABH obstetrics (OBG) code, which says obstetrics, not
   emergency C-section. Chart 01.
3. The text is often silent where NABH lists a matching department. Among 488 facilities NABH lists
   for dialysis or nephrology (DIA or NPH), the dataset text mentions dialysis for 202 (41%); with the
   dialysis code DIA alone it is 100 of 227 (44%). For C-section (OBG) it is 95 of 890 (11%), but OBG
   is the obstetrics department and the text names obstetrics for most of these (796 of 890 in
   external/nabh_accredited/README.md), so this is silence about the C-section, not about the
   department. NABH codes are self-declared departments: read these as text silence, not as proof
   the service exists. Chart 12.
4. On 61 searched DEV pairs (22 confirmed) only 9 of the 75 measurable features have a 95% interval
   that excludes 0.5. The strongest: raw mention count 0.72 [0.58, 0.85], the listing's own NABH claim
   0.69 [0.56, 0.80], specialty breadth 0.67 [0.52, 0.80], cited page count 0.66 [0.52, 0.79],
   hospital type 0.58 [0.53, 0.64] (clinic is its mirror, 0.44). The hospital-type interval is
   narrow only because 6 of the 61 pairs are not hospitals and none of the 6 was confirmed (Wilson
   0% to 39%), so it rests on 6 pairs. Chart 03 shows the 26 largest effects.
5. The gold web check is not independent of the features. In 43 of 60 DEV pairs with an evidence URL
   (72%, Wilson 59% to 81%), the labeller's evidence came from a web domain the record already
   cites, its own website or the NABH portal: 35 from one of the record's own cited source domains,
   26 from the facility's own website, 3 from the NABH portal. The match is by domain, not by page. Website and source features therefore look better on gold than they will on new pairs.
   Chart 08.
6. Location and service need different features. A record built from many web pages is more often
   confirmed for the service (AUROC 0.66) and more often in the wrong place (AUROC 0.27 for "location
   right", 52 DEV facilities, 12 wrong). Location votes against the point separate wrong locations
   almost perfectly (0.02 [0.00, 0.05] for "right"). Chart 06.
7. Location composites. The first version of `c_location_score_v1` scored 1.00 on DEV because it
   was the gold verdict itself: derived/v1 overwrites `facility_trust.location_score` with 0.97 or
   0.03 for every gold facility, 56 DEV and 56 TEST, so that column also carried sealed TEST labels.
   The review replaced it with `score_model` from derived/v1/data_point_scores.parquet (before the
   override), which scores 0.98 [0.95, 1.00]. `b_loc_conf` scores 0.98 [0.94, 1.00] on all 52 DEV
   facilities and 0.97 [0.93, 1.00] on the 37 v2 facilities alone (10 wrong), so the 36 v1 verdicts
   read while the cleaning rules were written do not explain it. It is still not clean:
   cleaning/geo_identity/s2_facility_location.py was last edited at 13:11:56, after every v2 label
   file was written (13:06 to 13:09), and the v2 suspect stratum sampled pins far from their PIN, which
   inflates any location AUROC. Treat both as tuned. Chart 06.
8. The source reliability score from derived/v1 points the wrong way: AUROC 0.35 on official lists
   and 0.41 on DEV. The derived/v1 README already warns that social pages score highest; the
   share of social-media sources is the most negative feature we have (lists 0.34, NABH 0.42,
   DEV 0.43). Charts 04, 13.
9. With 4,216 NABH-coded pairs the glass-box shapes are stable and mostly monotone: written
   prerequisites (ICU, OT, blood bank) add up to 13 points, stated beds up to 25, an own-site
   mention about 12. Held-out-state AUROC 0.75 (folds 0.75 to 0.77) against 0.61 for the text level alone.
   On 61 DEV pairs the same kind of model reaches 0.66 [0.51, 0.80]: wide enough to be compatible
   with anything from chance to good. Charts 09, 10, 11.

## Labels used

| label set | pairs | positives | what it is | file |
| --- | --- | --- | --- | --- |
| Gold DEV, service | 61 searched of 88 DEV pairs | 22 confirmed | web check confirmed the service; never-searched pairs (27) dropped | model/gold/splits.json (split = dev), labels_p*.json, audit/ground_truth/web_*.json |
| Gold DEV, location | 52 facilities | 40 right, 12 wrong | location_ok / location_matches yes vs no | same |
| NABH codes (PU) | 4,216 (1,054 facilities x 4 services, 29 states) | 2,206 | NABH lists DIA/NPH, OBG, EMD or CAR for a NABH-matched facility with at least one fetched code; a missing code is unlabelled, not negative | data/external/nabh_accredited |
| All official lists (PU) | 69,713 | 2,397 | any of NABH code, NMC strong course, LaQshya maternity OT, MoHFW trauma list; MRI has 0 positives and NICU 4 | data/external/nabh_accredited, nmc_colleges, laqshya_master, mohfw_trauma_196 |

The sealed TEST split was never read. This study is stricter than `model/proto/fusion/gold.py`: the
17 v1 pairs that splits.json marks test are left out too, so DEV here is 88 pairs (19 v1, 69 v2).
Test results quoted anywhere come from `model/review/stats/results.json` (test AUROC 0.776 for the
shipped model, 0.789 prior-only). The 40 benchmark queries and their end-to-end labels were not used.

Inputs that already saw TEST (found in review, for #11):
- `model/proto/evidence` (all `a_` features, the `g_` features from pair_features, and the `b_`
  features from facility_features) was changed after its v2 test metrics were written; MODEL_SPEC
  4.12 says any model built on evidence outputs needs fresh test labels. That applies to #11.
- derived/v1 `facility_trust.location_score` and `data_point_scores.score` are gold verdicts for
  gold facilities, TEST included. Never use them as features; `c_location_score_v1` now reads
  `score_model`.
- The cleaning location code was last edited after the v2 label files (DEV and TEST) existed.

NABH codes are departments, not services: OBG (obstetrics) stands for emergency C-section, NPH
(nephrology) or DIA for dialysis, EMD (emergency) for trauma, CAR (cardiology) for cardiac surgery.
A model fitted on them learns "has the matching department", which is a prerequisite, not the
service.

## Method

- Coverage: share of the 69,713 pairs with a value, and share with a non-zero value. Missing means
  the source cannot speak (no NABH code exists for MRI; website features need an attributable site).
- Gold DEV association: AUROC (ties count half), pooled over services, with a 95% cluster bootstrap
  over gold split groups (2,000 resamples). Binary features also get the confirmed-rate difference
  with its bootstrap interval (columns `dev_k1/dev_n1`, `dev_k0/dev_n0`, `dev_rate_diff`). An IPW
  AUROC column reweights by the inverse inclusion probability of the stratified sample. A feature is
  marked too small when fewer than 5 labelled pairs sit away from its most common value.
- PU association: AUROC within service (pairs are compared only within the same service, because
  base rates differ from 297 to 890 positives per service), 95% bootstrap over states (1,000
  resamples for NABH codes, 300 for all lists), and the AUROC in each of 5 folds of held-out states.
  Features from the same list as the label are not scored against it.
- Redundancy: Spearman correlation over all 69,713 pairs, average-linkage clusters on 1 - |rho| cut
  at 0.3. 42 features fall into 16 clusters (chart 07).
- Glass-box fits: an EBM with interactions off on gold DEV (15 features, 50 outer bags,
  min_samples_leaf 3), a sign-constrained L2 logistic scorecard on the same features (500 bootstrap
  refits for intervals), and an EBM on the NABH-code population with service as a term, out-of-fold
  AUROC from 5 folds of held-out states.

## Leakage rules

Each feature is graded against each label source (`leak_*` columns, chart 08):

| level | meaning | example |
| --- | --- | --- |
| direct | the label is read off the same list; never score it against that label | d_nabh_service_code vs NABH codes |
| fitted | weights or rules were fitted or tuned on gold labels | c_location_score_v1, c_source_support, a_grade, b_loc_conf |
| shared | feature and label read the same pages or claim | website and cited-source features vs the gold web check (43 of 60 overlap) |
| selection | the list matcher's gates or the list's scope depend on it | coordinates and PIN (matchers block on PIN or 2 km), public operator (LaQshya, MoHFW) |
| design | the gold sample was stratified on this feature's rule grade | all dataset-claim features vs gold |

All 36 v1 gold pairs were read while the cleaning and evidence rules were written (MODEL_SPEC 4.12),
so every rule-based feature is mildly informed by the 19 v1 pairs still in DEV here.

## Recommended feature set for #11

41 features are kept, 15 are display only, 8 are context only, 46 are dropped. Reasons per feature
are in the `reason` column of `features_catalogue.csv`. The card wording for each is in chart 13.

Service head P_S (16 terms):
- Text: `a_T` (text level 0-5, the representative of its 7-feature cluster), `a_prereq`,
  `a_list_truncated`, `a_contamination` (negative), `a_scope_conflict` (negative, prior only: no DEV
  pair has it).
- Dataset details: `k_text_24x7_any`, `k_text_nabh` (show with the NABH check: "claim not found in
  NABH list" when `d_nabh_listed` = 0).
- Own website: `e_web_service`, `e_web_24x7_emergency` (trauma and C-section). Both are "shared" with
  the gold check, so their DEV numbers are optimistic.
- Web footprint: `c_n_urls` (label it truthfully: records built from many pages are confirmed more
  often), `c_share_social` (negative).
- Type and size: `g_type_hospital`, `g_n_specialties`, `g_log_beds` (missing as its own bin),
  `g_public_level` and `g_iphs_essential` (the IPHS prior and the outside option).

Official-list evidence, family X (7): `d_nabh_service_code`, `d_nabh_full_accreditation`,
`d_nmc_course_strong`, `d_laqshya_ot_valid` with `d_laqshya_ot_ever` as one 3-level term,
`d_mohfw_trauma_centre`, `d_erk_blood_centre_on_site` (a prerequisite for C-section, trauma, burns,
cardiac surgery). A list used as a feature is never used as a label for that pair; with list
evidence present, evaluate on gold only.

Location head P_L (7): `b_votes_against`, `b_coord_pin_km`, `b_city_points_elsewhere`,
`b_copied_geocode`, `f_osm_conflict`, `a_quarantine_share`, and `b_loc_conf` with a disclosure that
it was tuned on the v1 verdicts.

Existence head P_E (7): `d_nabh_listed`, `f_osm_match`, `e_site_alive`, `e_identity_conf` (also the
gate for every website feature), `b_directory_phone`, `b_no_phone`, `b_website_other_org`.

Guards, applied as rules (4): `a_negation`, `e_web_negated`, `b_scale_contradiction`,
`g_type_dentist` folded into scope.

Context only, never evidence about the facility (8): the four NFHS-5 district indicators, MAP travel
time, WorldPop population within 25 km, other VF records within 25 km, distance to the nearest
e-RaktKosh centre. Show them on district planner views, never inside P_S.

Dropped, with the main reasons:
- Redundant: six text counts (`a_any_mention`, `a_n_atoms`, `a_n_fields_own`, `a_n_units_own`,
  `a_m_capability`, `a_grade`) share a cluster with `a_T` (rho 0.82 to 0.998); `b_n_source_ids` and
  `b_merge_bucket` into `c_n_urls`; `g_type_clinic` into `g_type_hospital`; three website variants
  into `e_web_service`.
- Fitted on gold: `a_grade`, `c_location_score_v1`, `c_source_support`, `c_mean_domain_reliability`.
- Too rare or no signal: for example `c_pagecheck_supported` (0.6% coverage), `d_erk_within_10km`
  (true for 95.7%), `b_breadth_exceeds_size` (0.49 to 0.54 everywhere).

What this means for the fit: with about 22 effective DEV positives, #11 cannot estimate 30+ free
weights. Fit the service head on the NABH-code and list populations with held-out states, use DEV
only to check signs and calibration, and keep the expert prior wherever the two disagree. The
list labels measure the matching department (OBG, NPH, EMD, CAR), so a head fitted on them ranks
"has the department"; say so on the card and do not read its output as P(service).
`g_log_beds` is the clearest disagreement (DEV 0.44 [0.25, 0.62] on 38 pairs, NABH 0.69
[0.67, 0.72]); the DEV interval is too wide to overturn the list result.

## Charts

All in `charts/` as .png (2x), .svg and a .txt alt-text sidecar, drawn with `viz/style.py`.

| file | finding |
| --- | --- |
| 01_who_speaks_for_each_service | 83% of pairs have no source; 1,103 C-section facilities have only a non-text source, 714 of them only a NABH OBG code |
| 02_coverage_by_feature | 7 of 110 features fire on fewer than 1 in 1,000 pairs; coverage and non-zero share per feature |
| 03_univariate_dev | 7 of the 26 largest DEV effects clear 0.5 (9 of 75 overall); mention count, NABH claim and specialty breadth lead |
| 04_univariate_nabh_pu | beds, specialty breadth and written prerequisites predict NABH codes; stable across held-out states |
| 05_dev_vs_nabh_agreement | the two label sources agree on direction for 53 of 72 features (r = 0.48) |
| 06_location_label | page count predicts the service up and the location down; the location composites are tuned, not clean |
| 07_correlation_clusters | 42 features in 16 redundancy clusters |
| 08_leakage_map | leakage per feature and label source; 43 of 60 gold evidence URLs overlap the features' pages |
| 09_ebm_shapes_dev | DEV EBM shapes, out-of-fold AUROC 0.66 [0.51, 0.80]: hypotheses only |
| 10_ebm_shapes_nabh_pu | NABH EBM shapes, held-out-state AUROC 0.75 vs 0.61 for text alone |
| 11_scorecard_dev | monotone scorecard, out-of-fold AUROC 0.69 [0.54, 0.83]; 2 of 15 terms clearly above zero |
| 12_nabh_codes_vs_text | when NABH lists dialysis or nephrology the text mentions dialysis for 41% |
| 13_card_phrases | what the card would say for each kept feature, with DEV service, DEV location and NABH AUROC |

## Files

- `build_features.py`: builds `out/features_pairs.parquet` (69,713 x 110 features plus keys, state,
  leakage group).
- `catalogue_meta.py`: definition, source file, expected direction, card phrase and leakage tags per
  feature; `leakage()` grades a feature against each label source. Self-check: run it.
- `labels.py`: gold loader that reads only split = dev pairs, PU labels, evidence overlap. Self-check asserts 61 searched and 22 confirmed.
- `univariate.py`: coverage, DEV and PU AUROCs with intervals, held-out-state folds, redundancy;
  writes `out/univariate.parquet`, `out/spearman.parquet`, `out/univariate_meta.json`. Stage results
  are cached in `out/cache/` (delete it to recompute; a full run takes about 11 minutes).
- `glassbox.py`: EBMs and the monotone scorecard; writes `out/glassbox.json`, `out/scorecard.csv`,
  `out/ebm_dev_shapes.json`, `out/ebm_pu_shapes.json`.
- `recommend.py`: the keep / drop / context decision per feature; writes `features_catalogue.csv`
  (one row per feature, all statistics) and `recommended_feature_set.json`.
- `charts.py`: the 13 charts.

Rebuild from a clean folder:

```
PY=/Users/karthikvattem/projects/datathon/.venv-viz/bin/python
cd /Users/karthikvattem/projects/datathon/viz/features
$PY build_features.py && $PY univariate.py && $PY glassbox.py && $PY recommend.py && $PY charts.py
```

## Not run and limits

- Not run: any metric on gold TEST labels (sealed); the end-to-end benchmark labels; PMNDP dialysis
  centres (only Goa is matchable, 1 of 8 centres matched, so no feature); NABH ICU and imaging codes
  (not fetched, so MRI and NICU have no NABH label); interaction terms in the EBMs (off by request).
- DEV is small: 61 pairs, 22 confirmed. Most DEV intervals are 25 to 30 points wide. Read the
  direction, not the point.
- PU labels are not truth. NABH codes are self-declared and undocumented; lists cover public
  programmes and large private hospitals, so type and size features look stronger on lists than they
  are for small clinics. Within-service AUROC on PU data is a ranking measure, not a calibrated one.
- Spearman correlations are pairwise-complete; for sparse features (for example `g_public_level`,
  public facilities only) they describe a subset.
- Card phrases are templates; the example values in chart 13 are illustrative, not a real record.
- Licences: NABH and NMC facts may be shown per facility with a citation, never redistributed as a
  list (research/DATASETS.md). The feature table stays inside the private repository.

An adversarial review of this study, with the fixes it made, is in `review/REVIEW.md`.
