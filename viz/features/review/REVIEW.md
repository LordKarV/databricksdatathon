# Adversarial review of the feature study

Scope: everything in /Users/karthikvattem/projects/datathon/viz/features/ as handed over (FEATURES.md,
the six scripts, out/, charts/). Review scripts and outputs are in this folder:

- `recompute.py` / `recompute.json`: independent recomputation of the headline effects from raw
  inputs (own DEV loader, sklearn `roc_auc_score`, own cluster bootstrap, 2,000 resamples).
- `coverage_check.py` / `coverage_check.json`: coverage and denominator checks.
- `cache_before_fix/`: the builder's univariate cache, kept to diff the rerun against.
- `*_rerun_stdout.txt`: logs of the rerun after the fixes.

Verdict scale: PASS (correct as delivered), FIXED (wrong, corrected in this review),
FLAG (correct as computed but needs a caveat that #11 must carry; caveat added to FEATURES.md
where noted), NOT RUN.

## Summary

| # | check | verdict |
| --- | --- | --- |
| 1a | study code reads TEST labels | PASS |
| 1b | feature table carries TEST labels through an input | FIXED (`c_location_score_v1`) |
| 1c | inputs built after TEST was viewed | FLAG (added to FEATURES.md) |
| 2a | gold web check shares sources with features | PASS (measured, disclosed) |
| 2b | list features scored against their own list | PASS (excluded as "direct") |
| 2c | official lists used by the gold labeller | PASS (none except NABH portal, 3 pairs) |
| 2d | "b_loc_conf 0.98 is leakage, not skill" | FIXED (claim not supported as stated) |
| 2e | NABH codes as labels for the services | FLAG (construct, added to FEATURES.md) |
| 3 | 5+ headline univariate effects | PASS (all reproduce to 3 decimals) |
| 4 | coverage numbers and denominators | PASS, one wording FLAG |
| 5 | card phrases | FIXED (4 phrases) |
| 6 | charts | FIXED (3 titles), rest PASS with notes |

## 1. Sealed TEST split

1a. PASS. `labels.gold_dev()` filters `split == "dev"` before any label is used, and every
statistic and model (univariate.py, glassbox.py, charts.py) starts from `gold_dev()`. `_labels()`
does parse the whole label files into a dict (TEST pairs included) but nothing downstream reads a
TEST entry. My own loader (`recompute.py`) filters the pair ids first, so TEST labels never enter
memory. No unique_id is in both splits (0 overlap, checked).

1b. FIXED. `build_features.py` set `c_location_score_v1 = facility_trust.location_score`. In
derived/v1 that column is overwritten with the gold verdict (0.97 true, 0.03 false) for every gold
facility: counted without looking at the values, 56 DEV and 56 TEST facilities have a non-
`unverified` location status (derived/v1/README.md: "Verified by gold (dev or test)"). So
`out/features_pairs.parquet` carried sealed TEST location labels for 56 facilities x 7 services =
392 rows, and the all-pairs Spearman matrix used them. The DEV AUROC of 1.00 was the label itself,
not "rules updated with gold DEV labels" as the catalogue said.
Fix: the column now reads `score_model` (the score before the gold override) from
derived/v1/data_point_scores.parquet; build_features.py, univariate.py, recommend.py and charts.py
were rerun. Results for the corrected column: DEV location AUROC 0.98 [0.94, 1.00] (was 1.00),
DEV service 0.46 [0.30, 0.61] (was 0.58). Every other feature's DEV and location statistics are
bit-identical before and after the rerun (diff of the two caches), so the rerun also reproduces the
builder's numbers. It is still "fitted" (its evidence rates and source reliabilities were updated
with gold DEV) and still dropped. glassbox.py does not use the column and was not rerun.

1c. FLAG. Two inputs were changed after TEST labels existed or had been viewed:
- MODEL_SPEC 4.12: the evidence layer wrote v2 test metrics at 13:50:37, then changed facility.py
  at 13:51:58; "Any model built on evidence outputs needs fresh test labels". model/proto/evidence
  supplies every `a_` feature, the `g_` features and `b_votes_against`, `b_n_source_ids`,
  `b_directory_phone`, `b_no_phone`, `b_coord_shared_3plus`. FEATURES.md did not say this.
- cleaning/geo_identity/s2_facility_location.py was last modified 13:11:56, after all seven
  labels_p*.json files (13:06:43 to 13:09:36). File times do not show the labels were read, only
  that they could have been.
Added a "Inputs that already saw TEST" block to FEATURES.md. #11 cannot claim a clean TEST number
for any model built on these features without fresh labels.

## 2. Leakage

2a. PASS. `labels.evidence_overlap()` matches evidence URL domains to the record's cited source
domains, its crawled own-site domain and "nabh". I checked the one risk in its registrable-domain
shortcut (`x.split(".")[-2:]` turns `kaithal.gov.in` into `gov.in`): no record source domain and
no crawl target domain is a public suffix (gov.in, ac.in, edu.in, co.in, org.in, nic.in: 0 each),
so 43 of 60 is not inflated by suffix collisions. The match is by domain, not by page; the chart 08
title said "a page our features already read" and was reworded (see 6).

2b. PASS. `pu_stats` returns NaN for any feature whose leakage against that label is "direct"
(all `nabh`, `nmc`, `laqshya`, `mohfw` tagged features for the all-lists label; all `nabh` tagged
for NABH codes), and `glassbox.pu_model` asserts no direct feature enters the NABH EBM.
`d_laqshya_ot_valid` (a subset of the label's `d_laqshya_ot_ever`) and `d_nmc_course_any` (a superset
of `d_nmc_course_strong`) are correctly excluded.

2c. PASS. The 89 DEV evidence URLs contain no NMC, e-RaktKosh, LaQshya, MoHFW, OSM or Google Maps
host; official hosts are 3 portal.nabh.co pages, 3 district gov.in sites and 5 college or university
sites.
So `d_nmc_*`, `d_erk_*`, `d_laqshya_*`, `d_mohfw_*` and `f_osm_*` being "none" against gold holds.

2d. FIXED. FEATURES.md finding 7 said `b_loc_conf` scores 0.98 "because the cleaning step was
checked against the v1 web verdicts". s6_eval.py only evaluates (its TRUE_TOWN dict is used to
measure distances, not to set loc_conf), and the effect holds where the v1 verdicts cannot reach
it: on the 37 v2 DEV facilities alone (10 wrong) `b_loc_conf` is 0.97 [0.93, 1.00] and
`b_votes_against` 0.03 [0.00, 0.06]. The honest statement is "not explained by v1; the code was
edited after v2 labels existed and the v2 suspect stratum oversampled far-from-PIN pins, so treat
as tuned and optimistic". Finding 7 and the `b_loc_conf` reason in recommend.py were rewritten.
The leakage level ("fitted") is unchanged.

2e. FLAG. The NABH-code PU label uses department codes as stand-ins: OBG (obstetrics) for
emergency C-section, NPH (nephrology) or DIA for dialysis, EMD for trauma, CAR (cardiology) for
cardiac surgery. Only CAR was called a proxy. The study recommends fitting P_S on these
populations, so P_S would learn "has the department". 714 of the 1,103 C-section pairs in
finding 2 rest on an OBG code alone. Added to FEATURES.md (labels section and fitting advice).

Not leakage but optimistic: the DEV scorecard and EBM features were chosen after the DEV
univariate pass ("one or two features per cluster"), so the out-of-fold AUROC 0.69 / 0.66 does not
cover feature selection. With intervals of [0.54, 0.83] this does not change any conclusion.

## 3. Headline univariate effects, recomputed

Own code (`recompute.py`), gold DEV only, 61 searched pairs, 22 confirmed (matches).

| feature | label | study | review |
| --- | --- | --- | --- |
| a_n_atoms | DEV service | 0.72 [0.58, 0.85] | 0.718 [0.576, 0.849] |
| k_text_nabh | DEV service | 0.69 [0.56, 0.80] | 0.686 [0.558, 0.802] |
| g_n_specialties | DEV service | 0.67 [0.52, 0.80] | 0.672 [0.533, 0.807] |
| c_n_urls | DEV service | 0.66 [0.52, 0.79] | 0.661 [0.517, 0.793] |
| g_type_hospital | DEV service | 0.58 [0.53, 0.64] | 0.577 [0.526, 0.638] |
| c_n_urls | DEV location (52, 12 wrong) | 0.27 | 0.271 [0.120, 0.449] |
| b_votes_against | DEV location | 0.02 [0.00, 0.05] | 0.022 [0.000, 0.050] |
| b_loc_conf | DEV location | 0.98 | 0.978 [0.941, 1.000] |

Point estimates agree to 3 decimals; interval ends differ by up to 0.01 (different resampling
seeds). Verdict PASS. One reading caveat, added to finding 4: the hospital-type interval is narrow
only because 0 of the 6 non-hospital pairs were confirmed (Wilson 0% to 39%) against 22 of 55
hospitals; it rests on 6 pairs.

Also reproduced: NABH DIA or NPH 488 facilities, dialysis mentioned in text for 202 (any claim atom;
201 at text level >= 1); OBG 95 of 890; 1,103 vs 248 for C-section; 58,025 silent pairs follows from
the same table (61,744 pairs at text level 0, 44 of which have a claim atom that was rejected for
ownership, so "the dataset text says nothing" is right to within 44 pairs).

## 4. Coverage and denominators

PASS on every number checked (`coverage_check.json`): 69,713 pairs, 9,959 facilities, 110
features; e_web_service 48.9% have a value and 7.0% non-zero; g_log_beds 25.1%; k_text_nabh
12.5%; a_prereq 30.9%; a_T 11.4%; b_votes_against 20.9%; c_share_social 90.6%; 7 features below
1 in 1,000 (a_negation, c_pagecheck_supported, three LaQshya, MoHFW, e_web_negated). Chart 01
denominators are 9,959 per service and the headline uses the 69,713 total.

FLAG (wording): the builder's summary calls `d_nabh_service_code` "57% of pairs can have a code".
57% is the 4 of 7 services where a code exists; for 35,620 of those 39,836 pairs the facility is
not NABH-coded at all, so the 0 is structural. NABH can speak for 4,216 pairs (6.0% of all pairs).
FEATURES.md and the catalogue do not repeat the 57% claim, so nothing to fix in the files.

## 5. Card phrases

FIXED in catalogue_meta.py (charts and the catalogue regenerated):
- `d_nabh_service_code`: "listed by NABH for {code}" read as a service listing. Now "NABH lists
  its {code} department (a department, not proof of this service)".
- `a_negation`: "refers out or does not offer" overstated the feature, which also fires on camps
  and future plans. Now "a sentence suggests {svc} may not be offered here routinely (referral,
  camp, plan or negation)".
- `c_n_urls`: "N web pages were used to build this listing" claimed provenance the feature does not
  measure (it counts cited URLs). Now "its listing cites N web pages".
- `e_identity_conf`: "its website names this facility and its address" was printed for any level
  0 to 3. Now "its website matches this facility ({conf} confidence)".
PASS for the rest of the 41 kept phrases, including the honest "(not checked)" on `k_text_nabh`
and "(may have expired)" on `d_laqshya_ot_ever`.

## 6. Charts

Viewed: 01, 03, 05, 06, 08, 10, 11, 13 before the fix; all 13 regenerated after it.
FIXED:
- 01: the title said independent sources "speak for" 1,103 C-section facilities; now states that
  714 of them rest only on a NABH OBG code, which names a department.
- 08: title said "a page our features already read"; the overlap is measured by domain. Reworded.
- 12: title said "Even when NABH lists dialysis" for a DIA-or-NPH group and "silence is not
  evidence of absence", which overreads a department code. Reworded.
PASS: every chart has a finding headline, labelled axes, n and denominators, intervals (Wilson or
cluster bootstrap) on rates and AUROCs, small-n notes, alt-text sidecars, no maps or outlines,
and the blue / orange / green / gray palette from viz/style.py.
Notes, not fixed: chart 10's bands are bagging SD (model variance on the same rows), not
held-out-state uncertainty; the stability claim in its title rests on the fold AUROCs 0.75 to 0.77,
not on the bands. Chart 06 colours every dot blue, so colour carries nothing there.

## Not run

- Any statistic on TEST labels (sealed). The 1b check counted gold-overridden rows by split
  without reading their values.
- glassbox.py was not rerun: it does not use the corrected column.
- Whether the cleaning or evidence authors actually read the v2 labels: file times only.
