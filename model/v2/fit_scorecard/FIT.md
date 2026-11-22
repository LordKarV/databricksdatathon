# Candidate B: fitted monotone logistic scorecard for P_S and P_L

Built 2026-11-21 by `fit.py` in this folder (about 8 minutes). Every number below is in `out/results.json`,
`out/params.parquet`, `out/family_summary.parquet` or `out/fit_stdout.txt`, all written by that script, or was
computed from those files. Evaluation uses gold DEV only (`model/v2/labels/out/gold_dev_pairs.parquet`, 195 searched
pairs, 62 confirmed). `model/gold/v3/` does not exist when this ran, so no v3 DEV labels were used, and no v3 file was
looked for or opened. `derived/v2/reader_scores.parquet` does not exist either, so the reader slot (terms r1, r2) is
in the model at its prior and fires on no pair.

Rebuild:
```
PY=/Users/karthikvattem/projects/datathon/.venv-viz/bin/python
cd /Users/karthikvattem/projects/datathon/model/v2/fit_scorecard
$PY design.py && $PY metrics.py     # self-checks
$PY fit.py                          # writes out/
$PY test_fit.py                     # additivity, cross-fit mask, not-observable = 0, folds
```

## Short answer

- The fitted P_S trained on PU list labels plus gold (variant `B`, the one this task specified) has better
  out-of-fold log loss than the prior-only scorecard, 0.683 against 0.860 (paired difference -0.176, cluster SE
  0.074). The gain comes from calibration, not ranking: AUROC falls from 0.740 to 0.694. The prior-only means are
  overconfident (ECE 0.231).
- PU training hurts on gold. The same scorecard fitted on gold alone (`B_gold_only`) has log loss 0.610 and AUROC
  0.740. B minus B_gold_only is +0.073 in log loss (SE 0.045, 95% CI -0.010 to 0.161). The list labels measure "has
  the department". The fit moves weight from text to size (beds_100p +1.52, spec_20p +0.63, while t3 goes to 0 and
  t2 falls to 0.20), and the web check does not reward size that much.
- Platt passes the MODEL_SPEC 3.2 rule (cross-fitted gain 0.092, SE 0.041), with a = 0.343 and c = -0.436. The
  shipped B is therefore `B_platt`: log loss 0.592 [0.532, 0.655], ECE 0.044 [0.032, 0.126], AUROC 0.685
  [0.604, 0.759]. It is well calibrated and close to flat. Only 108 of 358,524 pairs reach P_S 0.70. On gold DEV,
  2 pairs pass the Likely gate at 0.70, and neither was confirmed.
- No threshold reaches 85% precision with 20 pairs beyond it, for any variant, so t_L uses the 0.70 fallback.
  The Likely band is still empty, as in v1. Labels are still the bottleneck: on 62 positives the AUROC interval is
  about 0.15 wide.
- Public facilities: every fitted variant ranks the 34 public gold pairs (15 confirmed) close to chance (AUROC
  0.50 to 0.61, intervals from about 0.3 to 0.8). The prior-only scorecard gets 0.633 [0.407, 0.813]. Fitting buys
  calibration on private facilities and nothing measurable on public ones.
- P_L fitted (AUROC 0.855) does not beat the prior-only location scorecard (0.875). The paired log-loss
  difference is -0.012 with SE 0.024, so under the least-fitted rule the prior-only P_L should ship. P_E is not
  fitted: gold has 10 existence negatives, under the 15 that MODEL_SPEC 3.3 requires.

## Data used

| set | rows | what |
| --- | --- | --- |
| gold DEV, P_S | 195 pairs (62 y_S = 1) in 7 services, 33 states, 178 leakage groups | `gold_dev_pairs.parquet` rows with y_S not missing (never-searched pairs are missing, MODEL_SPEC 3.2) |
| PU, P_S | 22,140 (nabh 13,702; eraktkosh 5,645; nmc 2,511; laqshya 282), merged with gold to 8,642 to 10,812 distinct training rows per fit | `pu_labels.parquet`, positive or unlabeled |
| location labels, P_L | 218 facilities (37 wrong place) | `gold_dev_facility.parquet` y_L not missing, one row per facility |

Left out of PU training, as LABELS.md advises: MoHFW trauma (c = 1/18), NMC blood_bank (c = 0/18), PMNDP Goa
(1 positive) and the 76 expired LaQshya rows. The c value for each (list, service) is the `used` row of
`c_estimates.parquet`. In 15 NMC services the observed positive rate inside the 81-college scope is above c (for
example 69/81 = 0.85 for C-section, against c = 0.504), which SCAR cannot produce. There c is raised to the positive
rate (`c_raised_to_positive_rate` in results.json), which makes those rows say "every college offers it". Their
scope offset absorbs that, so they carry almost no slope information.

## Model

One additive logit per (facility, service). All terms are 0/1 indicators, and the score is
`z = base + sum_j w_j x_j`, where base is the sum of the three intercept terms that fire (b0, b@category, b@service).
`P_S = sigmoid(a z + c)` with the Platt (a, c) above, and every contribution is reported as `a w_j x_j`.
`full_grid` and `test_fit.py` assert that base plus the stored contributions equals the stored score to 1e-9 for all
358,524 pairs (largest error 9.4e-16), for every out-of-fold row, and for the 9,959 P_L scores.

Terms (249 for P_S, `design.py`):
- T: steps t1 to t5 (>= 0), trunc0 (>= 0, with t1 - trunc0 >= 0), and three contamination discounts on own text
  (T >= 2): tx_urls10 and tx_urls30 (record breadth) and tx_public (operator public), all <= 0 (PATTERNS 1 and 5).
- C c1, c2; N n1; S s1: all <= 0. P p1, p2: >= 0.
- X, one term per list and role, all >= 0: NABH service code, department, proxy; NMC strong and support course;
  LaQshya valid and expired; MoHFW; e-RaktKosh service and prerequisite; PMNDP. No list has an "absent" term, so
  absence from a list can never lower a score.
- W, only where an attributable website exists: cells A or B, C, D or E, 24x7 emergency (all >= 0), silent site
  (`obs_W` = absent, <= 0) and negated line (<= 0). With no website, every W column is 0 (not observable contributes
  0). The test checks this on 173,399 website contributions and 8,907 list contributions.
- O OSM tag, D dataset detail (>= 0). K IPHS prior for public facilities with a known level: essential and
  desirable >= 0, "not expected at this level" <= 0. R reader slot (>= 0, empty).
- Context with free sign unless noted: public, operator unknown, hospital, beds (missing, < 30, 100+), specialties
  (< 5, 20+), URLs (< 3, 30+), web_state none and dead, social share >= 0.5 (<= 0), NABH listed, text says NABH,
  service 24x7 text (>= 0), scale contradiction (<= 0). PM-JAY text is used only in P_L, as a drift risk.
- Hierarchy: the intercept and the slopes t2, t4, p1 each get a category deviation (11 categories, sd 1.0 for the
  intercept and 0.5 for slopes) and a service deviation (36 services, sd 0.5). That is additive Gaussian pooling:
  a service deviation is shrunk toward its category, and a category toward the global term.
- Monotone composites for every service: t2 + t2@cat + t2@svc + tx_urls30 + tx_public >= 0 (and the same with
  tx_urls10), and t_d + t_d@cat + t_d@svc >= 0 for t2, t4, p1. One more own unit never lowers the score, even on the
  broadest public record. 223 constraint rows in total.
- PU scope offsets off@nabh, off@nmc, off@laqshya, off@eraktkosh (sd 2.5). They enter only PU rows and never a
  published score. The contribution code asserts that.

Priors: Gaussian, centred on candidate A means. Candidate A had not published parameters when this ran, so the
centres are written in `design.py`. The text, prerequisite, contamination and context means are read unchanged from
`model/proto/fusion/priors_M1.json`. New v2 terms carry a derivation string, mostly hand-check precisions (website
QA 16/16, 8/14, 12/30; list match precisions). The three text discounts are capped (-0.15, -0.30, -0.15 instead of
M1's -0.43 and -0.86) so that the prior means themselves satisfy the monotone constraints. `design.py` asserts that
the means are feasible. If candidate A publishes different centres, the fit should be rerun with them; there is no
command-line switch for that yet (see Not run).

Fit: MAP by Newton with case weights and the proto active-set method (`model/proto/fusion/glm.py`, reused
unchanged). Gold rows have weight 1. A PU positive has weight = match precision x witness value. A PU unlabeled row
has weight 1 and the EM soft target q = (1 - c) f / (1 - c f), where f is the current P(offered | x). This is the
Elkan and Noto label-frequency correction. EM runs until the largest weight change is below 1e-4; it took 29 to 46
iterations in every fit, and every active set converged.

Cross-fitting by label family (`core.pu_design`, checked by `test_fit.py`): on PU rows labelled by list f, every X
column from list f is set to 0, and so is nabh_listed for NABH rows (scope). A list's weight is therefore learned
only from gold rows and from other lists' rows. Gold rows keep all lists as features (MODEL_SPEC 3.1).

## Evaluation protocol

- Grouped 5-fold CV on `fold5` (leakage groups never span folds; this is asserted). Each fold trains on gold and PU
  rows from the other four folds and predicts the held-out gold pairs.
- Held-out states (`state5`): the 33 gold states are assigned to 5 folds, largest first, each to the lightest fold
  (`state_folds` in results.json). PU rows in held-out states are left out of training, and so is any gold or PU row
  that shares a leakage group with a held-out pair (1 or 2 gold pairs and 45 to 361 PU rows per fold).
- Metrics on out-of-fold predictions. 95% intervals are percentile group bootstraps over leakage groups (2,000
  resamples). They do not include refit variance. ECE uses 5 equal-count bins (MODEL_SPEC 4.3). Paired log-loss
  differences come with a cluster SE by leakage group.
- Platt is cross-fitted: it is fitted on 4 folds' out-of-fold z and applied to the fifth.
- IPW metrics (point only) are given for the 117 v1 and v2 pairs. The e2e pairs have no inclusion probability.

## Results for P_S on gold DEV (195 pairs, 62 confirmed)

| variant | CV | log loss | AUROC | Brier | ECE |
| --- | --- | --- | --- | --- | --- |
| A_prior (centres, no fit; reference) | either | 0.860 [0.702, 1.042] | 0.740 [0.662, 0.808] | 0.256 [0.214, 0.301] | 0.231 [0.175, 0.296] |
| B (PU + gold) | group5 | 0.683 [0.568, 0.817] | 0.694 [0.615, 0.766] | 0.220 [0.184, 0.261] | 0.132 [0.079, 0.201] |
| B | state5 | 0.646 [0.541, 0.767] | 0.711 [0.632, 0.782] | 0.211 [0.176, 0.250] | 0.096 [0.060, 0.169] |
| **B_platt (shipped B)** | group5 | 0.592 [0.532, 0.655] | 0.685 [0.604, 0.759] | 0.203 [0.176, 0.230] | 0.044 [0.032, 0.126] |
| B_platt | state5 | 0.586 [0.524, 0.650] | 0.686 [0.606, 0.761] | 0.201 [0.174, 0.228] | 0.069 [0.032, 0.131] |
| B_gold_only (no PU rows) | group5 | 0.610 [0.508, 0.715] | 0.740 [0.668, 0.807] | 0.203 [0.167, 0.239] | 0.103 [0.059, 0.177] |
| B_gold_only | state5 | 0.629 [0.523, 0.743] | 0.724 [0.648, 0.794] | 0.208 [0.171, 0.247] | 0.118 [0.069, 0.185] |
| B_pu_w0.1 (PU at 1/10 weight; post hoc) | group5 | 0.628 [0.527, 0.742] | 0.727 [0.652, 0.797] | 0.207 [0.173, 0.243] | 0.077 [0.046, 0.156] |
| B_pu_w0.1 | state5 | 0.607 [0.512, 0.713] | 0.728 [0.651, 0.798] | 0.202 [0.168, 0.238] | 0.093 [0.051, 0.161] |
| B_no_web (crossfit-plan ablation) | group5 | 0.731 [0.616, 0.858] | 0.644 [0.558, 0.724] | 0.242 [0.202, 0.283] | 0.171 [0.104, 0.234] |
| B_no_k_text_nabh (ablation) | group5 | 0.682 [0.568, 0.814] | 0.694 [0.615, 0.767] | 0.220 [0.183, 0.261] | 0.150 [0.083, 0.208] |
| B_no_list_cited_gold (ablation) | group5 | 0.685 [0.571, 0.820] | 0.692 [0.614, 0.764] | 0.222 [0.185, 0.262] | 0.132 [0.080, 0.202] |

Paired log-loss differences (negative means the first model is better; cluster SE; 95% bootstrap CI):

| comparison | CV | diff | SE | 95% CI |
| --- | --- | --- | --- | --- |
| B - A_prior | group5 | -0.176 | 0.074 | [-0.320, -0.038] |
| B_platt - A_prior | group5 | -0.268 | 0.087 | [-0.444, -0.107] |
| B_gold_only - A_prior | group5 | -0.250 | 0.076 | [-0.402, -0.099] |
| B_pu_w0.1 - A_prior | group5 | -0.231 | 0.070 | [-0.368, -0.100] |
| B - B_gold_only | group5 | +0.073 | 0.045 | [-0.010, 0.161] |
| B_platt - B_gold_only | group5 | -0.018 | 0.039 | [-0.099, 0.053] |
| B_pu_w0.1 - B_gold_only | group5 | +0.018 | 0.032 | [-0.042, 0.079] |
| B - B_no_web | group5 | -0.047 | 0.026 | [-0.100, 0.005] |
| B - A_prior | state5 | -0.214 | 0.077 | [-0.365, -0.074] |
| B_platt - A_prior | state5 | -0.274 | 0.088 | [-0.453, -0.109] |
| B - B_gold_only | state5 | +0.017 | 0.048 | [-0.081, 0.110] |

How to read this:
- Every fitted variant beats the uncalibrated prior on log loss by more than 2 SE, because the prior centres are
  overconfident. That says nothing about the evidence weights. Candidate A's own Platt-calibrated version is the
  fair comparison, and the selection step should run it.
- Among fitted variants, B_platt and B_gold_only are within 0.5 SE of each other on log loss. B_gold_only ranks
  better (AUROC 0.740 against 0.685). The PU labels add no measurable value on gold, and at full weight they cost
  ranking.
- Removing the website columns costs 0.047 log loss (1.8 SE). Those columns read the same pages as the gold web
  check (FEATURES.md finding 5: 43 of 60 evidence URLs overlap), so this gain is an upper bound on what they add on
  new pairs.
- k_text_nabh and the 9 gold pairs that cite the NABH portal change nothing measurable. Without those 9 pairs in
  training, the NABH weights are 0.097 (code) and 0.116 (department), against 0.10 and 0.13 in B.
- IPW (v1 and v2, 117 pairs): AUROC A_prior 0.700, B 0.608, B_platt 0.596, B_gold_only 0.635; log loss 0.731,
  0.858, 0.719, 0.747. Under the stratum weights the fitted models rank worse than the prior.

### Public and private facilities (group5)

| variant | public (34 pairs, 15 confirmed): log loss / AUROC / ECE | private (146, 46): log loss / AUROC / ECE |
| --- | --- | --- |
| A_prior | 0.792 [0.532, 1.077] / 0.633 [0.407, 0.813] / 0.196 | 0.853 [0.661, 1.077] / 0.779 [0.696, 0.854] / 0.252 |
| B | 0.996 [0.672, 1.364] / 0.544 [0.301, 0.733] / 0.244 | 0.642 [0.512, 0.793] / 0.726 [0.641, 0.803] / 0.135 |
| B_platt | 0.749 [0.585, 0.914] / 0.530 [0.274, 0.728] / 0.177 | 0.578 [0.509, 0.654] / 0.713 [0.625, 0.793] / 0.085 |
| B_gold_only | 0.834 [0.634, 1.071] / 0.544 [0.333, 0.737] / 0.243 | 0.594 [0.471, 0.730] / 0.756 [0.673, 0.833] / 0.081 |
| B_no_web | 0.898 [0.604, 1.254] / 0.607 [0.376, 0.787] / 0.194 | 0.731 [0.600, 0.876] / 0.642 [0.549, 0.731] / 0.172 |

The 15 pairs with unknown operator (1 confirmed) are in results.json; with one positive they say nothing. Public
gold pairs are few and wide. The fitted public main effect is +0.81 (B), so the fit does not penalise public records
as a block, and website terms are 0 for them when there is no site. The fitted models still cannot rank within
public facilities: their evidence is mostly text (T fires on 71% of public gold pairs), lists (29%) and IPHS (85%),
and the fit put K weights at 0 (see weights). With per-variant state CV the picture is the same (B_platt public
AUROC 0.558 [0.317, 0.757]).

### Badge thresholds (MODEL_SPEC 3.2) on out-of-fold P_S

Likely gate: P_S >= t and T >= 2 and out-of-fold P_L >= 0.70. 103 gold pairs pass the T and P_L parts. The P_E gate
is not applied, because P_E is candidate A's prior-only head and has no out-of-fold values here.

| variant | t_L | Likely pairs at t_L | precision [Wilson 95%] | t_U | pairs <= t_U | NPV [Wilson 95%] |
| --- | --- | --- | --- | --- | --- | --- |
| B_platt (shipped) | 0.70 fallback | 2 | 0/2 [0.00, 0.66] | 0.240 | 62 | 56/62 = 0.903 [0.805, 0.955] |
| B | 0.70 fallback | 22 | 10/22 = 0.455 [0.269, 0.653] | 0.080 | 52 | 47/52 = 0.904 [0.794, 0.958] |
| B_gold_only | 0.70 fallback | 18 | 8/18 = 0.444 [0.246, 0.663] | 0.190 | 85 | 77/85 = 0.906 [0.825, 0.952] |
| A_prior | 0.70 fallback | 57 | 26/57 = 0.456 [0.334, 0.584] | 0.224 | 52 | 47/52 = 0.904 [0.794, 0.958] |

No variant has a threshold with precision >= 0.85 and 20 pairs beyond it, so t_L falls back to 0.70 everywhere.
Unlikely works: t_U meets NPV >= 0.90 with 52 to 85 pairs for every variant. Precision at a P_S-only cut of 0.50
for B_platt: 11/22 = 0.50 [0.31, 0.69]. Even the top of the fitted score is confirmed half the time, which
matches "chance a public web check confirms".

## Fitted weights (B, full fit on all gold and PU rows)

Selected terms (logit, before the Platt slope a = 0.343). Every term with its prior, derivation, posterior mean,
Laplace sd, 90% interval, at-bound flag and fire counts on gold and PU is in `out/params.parquet`
(`variant`, `head`).

| term | prior mean | B | B_gold_only | fires on gold / PU rows |
| --- | --- | --- | --- | --- |
| t1 / t2 / t3 / t4 / t5 | 0.40 / 0.46 / 0.80 / 1.00 / 0.60 | 0.89 / 0.20 / 0 (bound) / 0.44 / 0.09 | 0.99 / 0 / 0 / 0 / 0.35 | 126 / 111 / 60 / 48 / 28 gold |
| p1 / p2 | 0.90 / 0.50 | 1.10 / 0.16 | 0.36 / 0.54 | 156 / 72 gold |
| c1, c2, tx_urls10, tx_urls30, tx_public | -0.51 .. -0.15 | all 0 (bound) | all 0 | 14, 9, 30, 52, 12 gold |
| n1 / s1 | -1.67 / -1.50 | -1.10 / -0.22 | -1.67 / -1.59 | 0 / 12 gold |
| x_nabh_code / dept / proxy | 1.50 / 1.00 / 0.50 | 0.10 / 0.13 / 0 | 0.59 / 0.21 / 0 | 1 / 10 / 5 gold |
| x_nmc_dept / x_laqshya_valid / x_mohfw / x_erk_prereq | 0.80 / 1.50 / 1.00 / 0.30 | 0.40 / 1.62 / 1.94 / 0.60 | 1.08 / 1.50 / 1.44 / 0.13 | 4 / 0 / 1 / 16 gold |
| w_ab / w_c / w_de / w_silent | 2.00 / 1.27 / 0.50 / -0.30 | 1.57 / 0.78 / 1.13 / -0.36 | 1.53 / 0.69 / 2.06 / -0.56 | 27 / 9 / 9 / 59 gold |
| k_iphs1 / k_iphs05 / k_iphs0 | 0.50 / 0.25 / -0.50 | 0 / 0 / -0.48 | 0.94 / 0.50 / -0.52 | 24 / 4 / 1 gold |
| public / beds_100p / spec_20p / urls_30p | 0 / 0.50 / 0.30 / 0 | 0.81 / 1.52 / 0.63 / 0.41 | 0.30 / 0.26 / 0.03 / 0.11 | 34 / 90 / 99 / 71 gold |
| web_none / nabh_listed / scale_contra | 0 / 0.30 / -0.50 | -0.36 / 0.50 / -1.61 | 0.32 / -0.19 / -0.50 | 30 / 69 / 0 gold |
| b0 | -2.90 | -4.18 | -3.28 | all |

What changed from the prior: PU data moves weight from text depth (t3, t4) and IPHS to facility size (beds 100+,
20+ specialties, 30+ URLs). That is the signature of department-presence labels (FEATURES.md said a head fitted on
lists ranks "has the department"). The contamination discounts all go to 0, so the data does not support the
breadth or public-record penalty on own text. web_none becomes negative in B (-0.36) and positive gold-only (+0.32).
The two label sources disagree, and the data cannot settle it.

Weight intervals: Laplace sd over the free directions, with active constraints held as equalities. 90% =
mean +/- 1.645 sd, not truncated. The truncated-posterior draws of MODEL_SPEC 3.2 were not run (see Not run).

## Per-family contribution summary (out of fold, group5, `out/family_summary.parquet`)

Mean contribution in logit over the 195 gold pairs, for B before Platt (B_platt is 0.343 times these). The last two
columns are the means among confirmed and not confirmed pairs.

| family | share of pairs where it fires | mean | mean if confirmed | mean if not |
| --- | --- | --- | --- | --- |
| context | 1.00 | +1.52 | +1.91 | +1.33 |
| T text | 0.75 | +0.82 | +0.98 | +0.74 |
| P prerequisites | 0.80 | +0.83 | +0.92 | +0.78 |
| W website | 0.60 | +0.20 | +0.53 | +0.05 |
| X lists | 0.17 | +0.12 | +0.14 | +0.11 |
| D details | 0.08 | +0.02 | +0.02 | +0.02 |
| K IPHS | 0.15 | +0.00 | +0.00 | +0.00 |
| S scope | 0.06 | -0.02 | 0.00 | -0.03 |
| C contamination | 0.04 | -0.00 | -0.00 | -0.00 |
| N, O, R | 0 | 0 | 0 | 0 |

W separates confirmed from unconfirmed pairs most clearly (0.53 against 0.05), and it is the family the gold check
shares pages with. Context carries the largest share of every B score. On public pairs (B_platt) W averages -0.01
and X +0.09. On private pairs W averages +0.08 and X +0.04. Lists matter more for public facilities, as PATTERNS 2
predicted.

Worked example (from `out/pair_contributions.parquet`): `dialysis_strong_1`, a confirmed T = 5 pair. Base -2.195,
then beds_100p +0.520, p1 +0.376, t1 +0.307, spec_20p +0.218, t4 +0.151, urls_30p +0.140 and 11 smaller terms, for
z = -0.232 and P_S = 0.442. Base plus the 17 stored contributions equals z (asserted to 1e-9). Size terms outweigh four of the five
text steps here, and that is the main reason to doubt the PU-trained weights.

## Location head P_L (218 facility labels, 37 wrong, grouped 5-fold)

| model | log loss | AUROC | Brier | ECE |
| --- | --- | --- | --- | --- |
| B fitted | 0.351 [0.269, 0.439] | 0.855 [0.788, 0.913] | 0.114 [0.085, 0.144] | 0.068 [0.024, 0.114] |
| B without d_nabh_listed and f_osm_conflict (ablation) | 0.340 [0.263, 0.423] | 0.862 [0.798, 0.918] | 0.111 [0.083, 0.140] | 0.060 [0.022, 0.113] |
| prior only (M1 and PATTERNS centres) | 0.363 [0.264, 0.476] | 0.875 [0.814, 0.928] | 0.114 [0.081, 0.147] | 0.073 [0.024, 0.131] |

B minus prior: -0.012 log loss (SE 0.024, CI -0.060 to 0.031). That is under one SE, so the least-fitted rule keeps
the prior-only P_L. b_loc_conf and b_coord_pin_km are not used (crossfit plan: tuned on gold). Fitted votes (prior
in brackets): PIN 0.93 (1.40), city 0.91 (1.00), name place 0.70 (1.40), coordinates 0.49 (0.70), state 0.36
(0.70), map link 0 at bound (0.50). Copied geocode -1.61, PM-JAY text -0.77 (prior -0.46, PATTERNS 4), breadth -0.36
per doubling of URLs, NABH listed +0.41, and web_none at its bound 0. Full-fit scores and contributions for all
9,959 facilities are in `out/facility_location_*.parquet`.

## Outputs (out/)

| file | rows | content |
| --- | --- | --- |
| oof_predictions.parquet | 2,535 | out-of-fold z, p_s, base and per-family contribution sums per gold pair, variant and scheme (group5, state5), plus y_S, fold, state, leakage group, operator, T, ipw. Variants: A_prior, B, B_platt, B_gold_only, B_pu_w0.1, B_no_web, B_no_k_text_nabh, B_no_list_cited_gold |
| params.parquet | | every term of every variant: prior mean and sd, derivation, posterior mean, Laplace sd, 90% interval, sign, at_bound, dropped, published, fire counts; P_L terms with head = location |
| pair_scores.parquet | 358,524 | shipped B (B with Platt): z, p_s, base, T for every (facility, service) |
| pair_contributions.parquet | 1,836,419 | non-zero contributions (logit and points, 20 points doubles the odds) for every pair |
| facility_location_scores.parquet, facility_location_contributions.parquet | 9,959 | P_L full fit |
| location_oof.parquet | 218 | P_L out-of-fold, fitted, ablated and prior-only |
| family_summary.parquet | | per-family out-of-fold contribution summary, all / public / private, for B, B_platt, A_prior |
| results.json | | all metrics with intervals, paired tests, Platt decision, thresholds, c adjustments, state folds |
| fit_stdout.txt, test_stdout.txt | | run logs |

## Leakage controls applied

- A list is never a feature on rows it labels. PU rows of list f have every list-f X column and the NABH scope
  column zeroed. The check is in `test_fit.py`. x_any_list and obs_X are not used anywhere.
- b_loc_conf and b_coord_pin_km are not used in either head.
- Folds come from `fold5` (leakage group). Held-out leakage groups are removed from gold and PU training in both CV
  schemes, and this is asserted for group5. Nothing is tuned on anything but gold DEV out of fold.
- Website and cited-source columns are "shared" with the gold check. They stay in B and are reported ablated
  (B_no_web).
- The 9 gold pairs that cite the NABH portal are reported removed from training (B_no_list_cited_gold) and from
  evaluation (`without_9_list_cited` in results.json: B log loss 0.670, AUROC 0.700 on 186 pairs).

## Disclosures

- The prior centres in `design.py` were written by this step, after reading LABELS.md, which gives marginal gold
  counts per service. No gold rate enters a centre. They stand in for candidate A, which had not published its
  parameters.
- `B_pu_w0.1` was added after the first run showed B ranking below the prior. It is a disclosed post-hoc variant,
  not a tuned choice. Comparing it with the other variants on the same out-of-fold data selects on DEV.
- The shipped B uses Platt because the pre-registered rule says so. The rule picks a slope of 0.343, which
  compresses every contribution to about a third and leaves the Likely band empty. This is the same failure the v1
  review described (MODEL_SPEC 3.2: a = 0.38, 40 of 40 benchmark queries abstained).
- The intervals come from resampling fixed out-of-fold predictions. They leave out refit variance and the
  uncertainty in c.

## Not run and limits

- Truncated-posterior weight draws (1,000 accepted, MODEL_SPEC 3.2): not run, and the acceptance rate was not
  measured. Only Laplace sds are given.
- Sensitivity to c (refits at c_lo and c_hi from `c_estimates.parquet`): not run.
- A command-line switch to load candidate A's published centres: not built, because they did not exist. Changing
  `design.service_terms` and rerunning is the path.
- An EBM: not in this candidate.
- P_E fit: not run (10 negatives, under the 15 required). The Likely gate here leaves out P_E.
- The 29 services with no gold labels get scores from PU-informed service deviations and the category pooling.
  Nothing evaluates them.
- The reader slot is empty. When `derived/v2/reader_scores.parquet` lands, rerun `model/v2/assemble/build.py`,
  then this script. Terms r1 and r2 will pick it up without code changes.
- No Databricks run.
