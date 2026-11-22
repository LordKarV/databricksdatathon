# Candidate A: expert prior-only scorecards v2

Built 2026-11-21 by `prior_a.py` (terms, weights, scores, about 5 s) and `evaluate.py` (gold DEV metrics, about
7 minutes, almost all of it the bootstrap). Every number below comes from `out/params_A.json`,
`out/metrics_A.json`, `out/badges_A.json` or `out/platt_full_A.json`, all written by those two scripts. No weight
of A was fitted to a label. `model/gold/v3/dev_labels.json` and `derived/v2/reader_scores.parquet` do not exist,
so there are no v3 DEV labels and the reader slot R is empty (weight 0, x = 0 everywhere). No v3 file was opened.

## Verdict for the selection step

- Ranking: out-of-fold AUROC 0.771 [0.692, 0.833] on 195 searched gold DEV pairs (62 confirmed, 178 leakage
  groups). The v1 prior-only scorecard B4 had 0.789 [0.692, 0.875] on the old test, so A is in the same place.
- Calibration: A is overconfident. Mean P_S 0.456 against an observed 0.318; ECE 0.178 [0.124, 0.242]; log loss
  0.732 [0.587, 0.912].
- Platt (two parameters, fitted out of fold) passes the one-SE rule of MODEL_SPEC 3.2 under both fold schemes:
  log-loss gain 0.185 (SE 0.065) with grouped folds and 0.188 (SE 0.065) with held-out states. It costs a little
  ranking (AUROC -0.012 [-0.026, -0.002]) and brings ECE to 0.022 to 0.033. The slope is 0.38 on all 195 pairs
  (0.34 to 0.45 across folds), close to the v1 slope of 0.38, so the expert weights are about 2.6 times too
  large on this target.
- Likely: no threshold reaches precision 0.85 on 20 or more dev pairs, so t_L falls back to 0.70 for every
  variant. At the fallback A calls 47 dev pairs Likely and 25 are confirmed: 0.53 [0.39, 0.67]. With Platt the
  Likely band almost empties (5 pairs, 1 confirmed). The precision guarantee of MODEL_SPEC 3.2 is not met by A in
  either form.
- What the new families bought: the website family W carries the gain. Removing W drops AUROC by 0.072
  [0.026, 0.122]. Removing all new families (X, W, O, D, K, public and no-website contamination priors) drops it
  by 0.083 [0.027, 0.142]. The list family X does not help ranking (AUROC -0.003 [-0.031, 0.024] without it) and
  hurts log loss: A without X is better by 0.110 [0.032, 0.205]. The X weights are too large for this target.

## How A is built

`z = base_s + sum_j w_j x_j`, `P = sigmoid(z)`, with `contribution_j = w_j x_j`. There are 90 service terms (36
intercepts and 54 evidence and context terms), 17 location terms and 13 existence terms. `prior_a.py` asserts
`|z - sum of contributions| < 1e-9` on all 358,524 pairs (measured maximum 3.6e-15), again after reloading
`params_A.json` from disk, and for P_L and P_E on all 9,959 facilities. `evaluate.py` asserts it again on the
gold rows and checks that `sigmoid(z)` equals the stored P_S.

Weights are prior means. Where a mean broke a sign or monotonicity constraint, the weight is the constrained
point closest to the means in the prior metric, which is the B4 rule from `model/proto/fusion/fit.py`, solved
here with SLSQP. Two composite constraints:
1. `t2 + tb_high + tp_public + tw_none >= 0`: one more own unit never lowers the score, even on a 30+ URL public
   record with no website.
2. `t1 (1 - 0.893) - trunc0 >= 0`: replacing a specialties-only mention (t1 x = its evidence weight, at most
   0.893) with a text mention never lowers the score. That leaves trunc0 at 0.048 instead of 0.3.

Projected weights: t1 0.40 to 0.448, t2 0.46 to 0.841, trunc0 0.30 to 0.048, tb_high -0.86 to -0.646, tp_public
-0.409 to -0.195, tw_none -0.121 to 0 (at its bound).

### Conversion rule for independent positive witnesses

A list fact, a website quote or an OSM tag states "F offers s" and is true with probability p (match precision
x meaning factor, or the QA cell precision). With only that witness, P(confirmed) = r p + (1 - p) pi0: a true
statement is confirmed at rate r, a false one leaves the pair at the base rate.
`w = logit(r p + (1 - p) pi0) - logit(pi0)`, with pi0 = sigmoid(-2.9) = 0.052 (M1 base) and r = 10.5/13 = 0.808
(v1 strong stratum, 10 of 12 confirmed). Precisions use (k + 0.5) / (n + 1), as M1 did for n1. The largest
weight any single witness can earn is 4.34.

| term | p | weight | source |
| --- | --- | --- | --- |
| x_nabh:service_code (DIA) | 39/40 x 1.0 | +4.17 | NABH match check, two seeds of 20 |
| x_nabh:department (NPH, OBG, EMD, ONC, TRN) | 39/40 x 0.5 | +2.56 | same; FEATURES.md: codes are departments |
| x_nabh:department_proxy (CAR) | 39/40 x 0.25 | +1.72 | same; cardiology for cardiac surgery |
| x_nmc:department / support course | 19/20 x 0.5 / x 0.25 | +2.51 / +1.68 | NMC match check |
| x_laqshya:certificate / expired | 17/20 x 1.0 / x 0.5 | +3.66 / +2.36 | LaQshya match check |
| x_mohfw_tcf:designation | 19/20 x 0.5 | +2.51 | MoHFW match; 12th-plan rows not verified functional |
| x_eraktkosh:service (blood_bank) | 16/20 x 1.0 | +3.50 | e-RaktKosh strict match |
| x_erk_prereq (C-section, trauma, burns, cardiac) | p1 0.9 x 16/20 | +0.72 | prerequisite, not the service |
| x_pmndp_goa:service | 1/1 | +3.38 | PMNDP Goa |
| w_cell_A / B / C / D / E | 13/13, 3/3, 8/14, 5/12, 7/18 | +4.17 / +3.81 / +2.82 / +2.38 / +2.28 | kb/web_evidence/qa/QA.md |
| w_24x7 (emergency_24x7 / trauma, C-section) | 9/10 x 1.0 / x 0.25 | +3.77 / +1.61 | QA 24x7 fact |
| o_emergency / o_speciality | 17/20 x 1.0 / x 0.5 | +3.66 / +2.36 | kb/opendata high tier |

Meaning factors (1.0 the list states the service, 0.5 a department or designation, 0.25 a proxy department or
support course) are expert settings: LABELS.md records that list-to-service meaning was never hand-checked.

One vote per source: within a list only its strongest row counts, and within W only the best website witness.
Lists are independent of each other and of the text, so they add.

Shared pages counted once: `w_overlap = -min(text points t1..t5, website points)`. Text and own website together
earn max(text, website), not the sum, because the record text was extracted from the same web pages (FEATURES.md
finding 5).

### Every other term

| term | weight | derivation |
| --- | --- | --- |
| b_s (36 services) | -2.9 | M1: expert base rate about 5% for a pair with no mention |
| t1..t5 | 0.448, 0.841, 0.8, 1.0, 0.6 | M1 means from the v1 strata (1/12 weak, 10/12 strong), t1 and t2 projected; t1 x = specialty evidence weight when the only mention is a specialties item (kb/taxonomy/specialty_evidence_weights.csv) |
| trunc0 | 0.048 | M1 0.3, projected (constraint 2) |
| d_unit | 0.46 | dataset detail (kb/vf_details, 46/50) counts as one own unit (the t2 step), only when T < 2, because D comes from the same text |
| tb_mid / tb_high | -0.43 / -0.646 | M1 merge audit: contamination 4.2% of records under 3 URLs vs 59.6% at 30+; buckets by URL count (8 to 29, 30+), because v2 has no q_share |
| tp_public | -0.195 | PATTERNS 1: public hospital contamination OR 2.34, as log P(own) at the mid bucket (q 0.376 to 0.585) = -0.409, projected |
| tw_none | 0 | PATTERNS 3: no-website contamination OR 1.34, -0.121, projected to its bound |
| c1 / c2 | -0.51 / -0.5 | M1 (17/25 foreign); the v2 witness rates give 23/34, the same 0.68 |
| n1 | -1.67 | M1, non-offer hand check 34/40 |
| s1 | -2.649 | G_scope hand check: claims at single-focus facilities true 67/111 against own text units 96/100, logit difference. Replaces M1 s1 (-1.5) and type_dentist (-2.0), since v2 S fires for every service outside the focus |
| p1 / p2 | 0.9 / 0.5 | M1; x = value of the strongest and second distinct cue (1 for a text cue, the specialty evidence weight for a specialty cue) |
| w_silent | -1.466 | site observable and silent: log(1 - r_W), r_W = 3,793/4,931 pairs with own text T >= 4 whose site mentions the service (label-free anchor, the same idea as LABELS.md text_T4) |
| k_iphs | 0.5 x IPHS expectation (0 / 0.5 / 1) | M1 iphs_essential, now for 36 services, public facilities with a known level only |
| type, level, beds, breadth, scale_contradiction | M1 means | M1 expert (type_clinic -0.5, type_other -1, level_dh 0.5, level_mc 1, level_phc -1, beds_lt30 -0.5, beds_100p 0.5, breadth -0.3 / +0.3, scale_contradiction -0.5); doctor-count terms dropped, because v2 has no doctor count |
| r_reader | 0 | slot for the issue #50 reader; its weight is to come from the reader's own validation, never from gold |

M1 terms with mean 0 are omitted (g_mid, g_high, public, the service deviations); level_chc is kept at 0. Not added,
as PATTERNS.md says: the off-focus flag, year established, the anomaly score.

Fairness coding. Website, list and OSM terms fire only when present. Not observable contributes 0 (no
attributable site, a facility type the list does not cover, not matched). Absent from a list contributes 0.
Only a website that is observable and silent costs points (w_silent); a facility with no website is never
charged for it. Public facilities get the IPHS prior instead (K, observable for 176 public facilities).

Location head P_L: the M1 location means (b_loc 0.8, votes v_pin 1.4, v_name 1.4, v_city 1.0, v_coords 0.7,
v_state 0.7, source and flag terms), plus NABH list match +0.713 (PATTERNS 4, drift OR 0.49), PM-JAY text -0.464
(drift OR 1.59, the weak drift risk), no website -0.412 (PATTERNS 3, drift OR 1.51) and an OSM same-name point
elsewhere -0.330 (log(1 - 4.5/16)). b_loc_conf and b_coord_pin_km are not used (tuned on gold, cross-fit drop).

Existence head P_E: the M1 existence means (b_ex 1.0 and the website, phone, source, recency, pharmacy,
duplicate and shared-coordinate terms), plus OSM or Wikidata high tier +2.06 and medium +1.37 (17/20, 7/10) and
the NABH list match +3.61 (39/40), all with r = 1 against base P_E 0.731. The display phone and phone_class now
come from one source, so "no phone" fires only when no number is shown.

## Results on gold DEV

All intervals are 95%: 2,000-replicate cluster bootstrap over leakage groups, Wilson for proportions. A has no
fitted parameter, so its out-of-fold predictions are its predictions under any fold scheme. The only fitted
variant is Platt, fitted on the training folds of `fold5` (leakage groups) or of held-out states (states hashed
into 5 folds of 25 to 77 pairs and 4 to 9 states). Pairs: v1 35, v2 82, e2e 78. Per service: burns 17 (5
confirmed), cardiac surgery 30 (13), dialysis 39 (14), C-section 39 (9), MRI 18 (6), NICU 30 (8), trauma 22 (7).

### P_S, all 195 pairs

| variant | log loss | AUROC | Brier | ECE | minus A: log loss | minus A: AUROC |
| --- | --- | --- | --- | --- | --- | --- |
| A | 0.732 [0.587, 0.912] | 0.771 [0.692, 0.833] | 0.223 [0.183, 0.269] | 0.178 [0.124, 0.242] | | |
| A + Platt, grouped folds | 0.546 [0.478, 0.618] | 0.758 [0.678, 0.823] | 0.184 [0.156, 0.214] | 0.022 [0.026, 0.106] | -0.185 [-0.320, -0.068] | -0.012 [-0.026, -0.002] |
| A + Platt, held-out states | 0.544 [0.477, 0.615] | 0.762 [0.682, 0.826] | 0.183 [0.155, 0.212] | 0.033 [0.026, 0.107] | -0.188 [-0.320, -0.070] | -0.009 [-0.018, -0.001] |
| without X (lists) | 0.622 [0.520, 0.739] | 0.768 [0.696, 0.829] | 0.209 | 0.143 | -0.110 [-0.205, -0.032] | -0.003 [-0.031, 0.024] |
| without W (website) | 0.760 [0.635, 0.914] | 0.698 [0.617, 0.771] | 0.245 | 0.159 | +0.028 [-0.045, 0.099] | -0.072 [-0.122, -0.026] |
| without the gold_web_check ablate set (W, tb_mid, tb_high, tw_none) | 0.819 [0.683, 0.986] | 0.700 [0.618, 0.774] | 0.259 | 0.188 | +0.087 [0.009, 0.165] | -0.070 [-0.124, -0.022] |
| without P | 0.638 [0.510, 0.789] | 0.768 [0.691, 0.830] | 0.196 | 0.121 | -0.093 [-0.157, -0.030] | -0.003 [-0.020, 0.015] |
| without context | 0.697 [0.561, 0.855] | 0.740 [0.659, 0.807] | 0.215 | 0.151 | -0.035 [-0.097, 0.023] | -0.031 [-0.052, -0.010] |
| without contamination priors | 0.783 [0.626, 0.973] | 0.773 [0.697, 0.836] | 0.235 | 0.211 | +0.051 [0.023, 0.080] | +0.003 [-0.007, 0.012] |
| without K (IPHS) | 0.731 | 0.767 [0.687, 0.830] | 0.222 | 0.182 | -0.001 [-0.014, 0.013] | -0.004 [-0.012, 0.003] |
| without S | 0.737 | 0.767 | 0.224 | 0.180 | +0.005 [0.002, 0.011] | -0.003 [-0.009, 0.000] |
| without D | 0.733 | 0.770 | 0.223 | 0.177 | +0.002 [0.000, 0.005] | -0.001 [-0.004, 0.000] |
| without specialty weights (t1 x = 1) | 0.731 | 0.771 | 0.223 | 0.179 | -0.000 [-0.002, 0.001] | +0.001 [0.000, 0.003] |
| without O | identical | | | | 0 | 0 |
| new families off (no X, W, O, D, K, tp_public, tw_none) | 0.661 [0.573, 0.758] | 0.687 [0.605, 0.762] | 0.231 | 0.136 | -0.071 [-0.208, 0.047] | -0.083 [-0.142, -0.027] |

Ablations zero the family's contributions and do not re-project. O fires on no gold pair, so its ablation is
untested. The website ablation is the one the cross-fit plan asks for: the website and cited-source columns read
the same pages as the gold check (43 of 60 gold evidence URLs overlap), so the W gain is optimistic.

### Public and private facilities

| subset | n (confirmed) | A log loss | A AUROC | A ECE | Platt (grouped) log loss | Platt AUROC |
| --- | --- | --- | --- | --- | --- | --- |
| public (operator_public = 1) | 34 (15) | 0.912 [0.513, 1.460] | 0.670 [0.434, 0.856] | 0.216 [0.114, 0.392] | 0.693 [0.518, 0.883] | 0.628 [0.389, 0.826] |
| private | 146 (46) | 0.691 [0.520, 0.890] | 0.797 [0.717, 0.868] | 0.178 [0.111, 0.247] | 0.529 [0.448, 0.613] | 0.786 [0.703, 0.862] |
| operator unknown | 15 (1) | 0.726 | 0.714 [0.462, 0.929] | 0.316 | 0.383 | 0.786 |

On public facilities A ranks no better than chance within its interval, and the new families do not help there:
without them public AUROC is 0.663 [0.413, 0.852], log loss 0.707. W costs public pairs on average (mean W
contribution -0.29 among confirmed public pairs, from the silent-site penalty on the few public facilities with a
site). On all 358,524 pairs the mean W contribution is -0.13 logit for public and -0.52 for private facilities,
and the IPHS prior adds +0.13 on average to public pairs. Private ranking is where A works.

Other cuts: v1 and v2 pairs (117, 46 confirmed) AUROC 0.757 [0.660, 0.842]; e2e pairs (78, 16) 0.816 [0.705,
0.914]; IPW on v1 and v2 (ESS 41.6) AUROC 0.729 [0.557, 0.880], ECE 0.211 [0.111, 0.358]. Without the 9 pairs
whose labeller read the NABH portal: AUROC 0.770 [0.696, 0.837], and dropping X there still improves log loss by
0.116 [0.033, 0.214].

### Thresholds and badges (MODEL_SPEC 3.2)

| variant | t_L | Likely n, confirmed, precision [Wilson] | t_U | Unlikely n, NPV [Wilson] |
| --- | --- | --- | --- | --- |
| A | 0.70 (fallback) | 47, 25, 0.53 [0.39, 0.67] | 0.130 | 62, 0.90 [0.80, 0.95] |
| A + Platt, grouped | 0.70 (fallback) | 5, 1, 0.20 [0.04, 0.62] | 0.156 | 50, 0.92 [0.81, 0.97] |
| A + Platt, held-out states | 0.70 (fallback) | 6, 2, 0.33 [0.10, 0.70] | 0.172 | 60, 0.90 [0.80, 0.95] |

Eligibility is P_L >= 0.7, P_E >= 0.7 and T >= 2. For A, precision among eligible pairs is 33/73 at P_S >= 0.3,
29/61 at 0.5, 24/41 at 0.8 and 13/21 at 0.9: it never reaches 0.85. t_U was chosen and measured on the same dev
pairs, so its NPV is optimistic. Gold badges under A: Likely 47 (25 confirmed), Call first 51 (15), No service
text 35 (16), Unlikely 62 (6).

Under A's thresholds the 358,524 pairs get Likely 7,483, Call first 10,101, No service text 24,639 and Unlikely
316,301 (public: Likely 500 of 16,884). The most Likely pairs are ICU (987), emergency 24x7 (933) and trauma (601).
After Platt on all 195 pairs (a = 0.3837, c = -0.7884, `out/platt_full_A.json`) the maximum P_S is 0.932 and 463
pairs would be Likely at the 0.70 fallback. Not implemented in the badge counts: the "C = 2 with T <= 1" Unlikely
rule and the PLACE UNCLEAR overlay.

### Location and existence heads

| head | labels | AUROC | log loss | ECE | at P >= 0.7 |
| --- | --- | --- | --- | --- | --- |
| P_L, all facility labels | 218 (37 wrong) | 0.866 [0.795, 0.924] | 0.358 [0.258, 0.477] | 0.052 [0.027, 0.111] | 164 of 179 right, 0.92 [0.87, 0.95] |
| P_L, gold DEV only | 162 (31) | 0.928 [0.845, 0.988] | 0.343 [0.215, 0.493] | 0.113 [0.076, 0.161] | |
| P_L, public / private | 36 (9) / 169 (27) | 0.848 [0.708, 0.966] / 0.854 [0.757, 0.928] | 0.537 / 0.345 | 0.164 / 0.042 | |
| P_E, gold DEV | 173 (10 no or unclear) | 0.700 [0.489, 0.881] | 0.232 [0.120, 0.372] | 0.027 [0.015, 0.064] | 163 of 173, 0.94 [0.90, 0.97] |
| P_E, public / private | 33 (2) / 125 (7) | 0.887 / 0.636 | 0.191 / 0.249 | | |

Cross-fit ablation (the matcher-gate columns): P_L without the NABH and OSM-conflict terms changes AUROC by +0.002
[-0.012, 0.017] and log loss by -0.011 [-0.027, 0.003]. P_E without the NABH and OSM terms loses 0.049 AUROC
[-0.204, 0.104]. With 10 negatives, none of the P_E figures supports a claim.

### Per-family contributions on gold (mean logit, confirmed vs not confirmed)

| family | pairs with a non-zero value (of 195) | confirmed | not confirmed |
| --- | --- | --- | --- |
| T text | 146 | +1.74 | +1.16 |
| W website (with overlap and silent) | 110 | +0.52 | -0.30 |
| P prerequisites | 156 | +0.96 | +0.75 |
| context | 156 | +0.75 | +0.35 |
| X lists | 34 | +0.51 | +0.30 |
| K IPHS | 28 | +0.11 | +0.05 |
| contamination priors | 92 | -0.37 | -0.23 |
| S scope | 12 | 0 | -0.24 |
| C contamination | 14 | -0.09 | -0.05 |
| D details | 1 | | |
| N, O, R | 0 | | |

The full table, split by public and private and for all pairs, is in `metrics_A.json` (`family_contrib_gold`,
`family_contrib_all_pairs`).

## Leakage and process disclosures

- A uses no label in any weight. The only data-derived constant is r_W, read from the witnesses with no label.
  The Platt variant is fitted only on training folds of gold DEV. No list is a label anywhere in this candidate,
  so the list cross-fit drops do not apply. X stays a feature for the gold evaluation, as LABELS.md section 3
  says.
- Before writing the new priors I printed DEV cross-tabulations of 14 columns against y_S (a_T, obs_W,
  e_web_cell, obs_X, web_state, operator_public, a_prereq, obs_K, g_iphs_prior, obs_O, d_any_detail,
  a_scope_conflict, a_contamination, g_type_hospital). The conversion rule and the rates come from named QA and
  match checks, not from those tables, but the choice to add a silent-website penalty was made after seeing them
  (site observable but silent: 9 confirmed of 59; no site: 23 of 78). That makes w_silent informed by DEV.
- The text-family priors are M1's, which were written after v2 dev notes were read (MODEL_SPEC 4.12), and the
  r = 10/12 rate is from v1 strata, which are DEV.
- The eligible-pair Likely and Unlikely rates are measured on the same pairs the thresholds were chosen on.
- No Databricks run. No git.

## Not run and limits

- Not run: a re-projected ablation (ablations zero contributions only), intervals on the weights (A has no
  posterior), the "C = 2 with T <= 1" Unlikely rule, the PLACE UNCLEAR overlay, any metric for the 29 services
  without gold labels, any metric on PU list labels.
- O fires on no gold pair, and D on one. Their weights are untested.
- Naive Bayes over-counts: list, website and text terms each carry the searchability rate r, so a pair with two
  strong witnesses is pushed toward 1. The Platt slope of 0.38 is the measured size of that over-count.
- Labels remain the bottleneck: 62 confirmed pairs, 34 public pairs, 10 existence negatives.

## Files

- `prior_a.py`: term table with derivations, monotonicity projection, design matrices, scoring of all pairs and
  facilities, additivity assertions.
- `evaluate.py`: gold DEV metrics, Platt out of fold (grouped and held-out states), ablations, thresholds,
  badges, family summaries, P_L and P_E.
- `out/params_A.json`: every term with head, family, prior mean, weight after projection, sign, derivation,
  source and fire count, plus constants and input hashes.
- `out/scores_A.parquet`: 358,524 pairs: z_S, P_S, one column per family sum, T, operator_public, P_L, P_E.
- `out/facility_contrib_A.parquet`: 9,959 facilities, z and P for L and E with every term's contribution.
- `out/contrib_gold_A.parquet`: per-term contributions and x values for the 301 gold pairs.
- `out/oof_A.parquet`: 195 labelled pairs with folds, y_S, and P for A, both Platt variants and every ablation,
  plus the badge. This is the input for the selection step.
- `out/metrics_A.json`, `out/badges_A.json`, `out/platt_full_A.json`.

Rebuild:

```
PY=/Users/karthikvattem/projects/datathon/.venv-viz/bin/python
cd /Users/karthikvattem/projects/datathon/model/v2/fit_prior
$PY prior_a.py && $PY evaluate.py
```
