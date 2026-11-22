# Model selection on DEV (final refit, v3 labels)

All numbers come from selection.py on grouped 5-fold out-of-fold predictions (column fold5, leakage groups).
Labels are agent-labelled, not human-checked. Intervals: 95% group bootstrap over leakage groups (2,000).
TEST facilities and every member of their leakage groups are absent from every training table (asserted in
prep_labels.py, run_b.py and run_c.py). trauma_care PU list rows were dropped; trauma_care trains on v3 gold only.

## Headline: confirmed vs contradicted (n = 221, 168 confirmed)

| candidate | n (pos) | log loss | AUROC | Brier | ECE | LL minus A (cluster SE) | IPW v3 LL / AUROC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 221 (168) | 0.723 [0.598, 0.861] | 0.804 [0.725, 0.869] | 0.234 [0.195, 0.276] | 0.230 [0.185, 0.291] | - | 0.719 / 0.765 |
| A_platt | 221 (168) | 0.427 [0.352, 0.515] | 0.800 [0.720, 0.867] | 0.132 [0.105, 0.164] | 0.044 [0.027, 0.103] | -0.296 (0.059) | 0.489 / 0.761 |
| B | 221 (168) | 0.451 [0.353, 0.560] | 0.813 [0.742, 0.879] | 0.143 [0.109, 0.178] | 0.074 [0.041, 0.134] | -0.272 (0.067) | 0.409 / 0.877 |
| B_platt | 221 (168) | 0.432 [0.355, 0.518] | 0.812 [0.741, 0.879] | 0.138 [0.110, 0.170] | 0.053 [0.025, 0.108] | -0.291 (0.067) | 0.417 / 0.874 |
| C | 221 (168) | 0.461 [0.386, 0.551] | 0.766 [0.683, 0.841] | 0.146 [0.118, 0.178] | 0.043 [0.025, 0.106] | -0.261 (0.072) | 0.436 / 0.817 |
| C3_resid | 221 (168) | 0.390 [0.295, 0.506] | 0.833 [0.756, 0.903] | 0.110 [0.082, 0.142] | 0.037 [0.025, 0.094] | -0.333 (0.072) | 0.460 / 0.747 |
| C0_gold | 221 (168) | 0.370 [0.290, 0.468] | 0.838 [0.758, 0.904] | 0.107 [0.081, 0.138] | 0.056 [0.029, 0.098] | -0.353 (0.070) | 0.417 / 0.762 |
| C1_shift | 221 (168) | 0.461 [0.380, 0.556] | 0.766 [0.683, 0.842] | 0.145 [0.116, 0.178] | 0.073 [0.031, 0.116] | -0.262 (0.072) | 0.442 / 0.816 |
| base_rate | 221 (168) | 0.557 [0.490, 0.630] | 0.413 [0.328, 0.505] | 0.184 [0.154, 0.217] | 0.068 [0.035, 0.125] | -0.166 (0.079) | 0.557 / 0.360 |

IPW v3 column: v3 DEV pairs only (134 decided, 107 confirmed), weighted by 1/pi; Kish effective n 43.2. v1/v2 weights are on another frame and e2e has none, so they are not mixed in.

Selection steps (replace the incumbent only if LL diff <= -1 cluster SE):

- A_platt vs A: diff -0.2961, SE 0.0588, 95% [-0.4126, -0.1844] -> replaces
- B vs A_platt: diff +0.0239, SE 0.0350, 95% [-0.0456, +0.0927] -> does not replace
- B_platt vs A_platt: diff +0.0052, SE 0.0257, 95% [-0.0477, +0.0558] -> does not replace
- C vs A_platt: diff +0.0347, SE 0.0274, 95% [-0.0190, +0.0859] -> does not replace

**Selected: A_platt.**

## Sensitivity: MODEL_SPEC 3.2 rule (searched and nothing = 0; n = 470, 168 positive)

| candidate | n (pos) | log loss | AUROC | Brier | ECE | LL minus A (cluster SE) | IPW v3 LL / AUROC |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | 470 (168) | 0.747 [0.653, 0.850] | 0.727 [0.678, 0.774] | 0.234 [0.206, 0.262] | 0.176 [0.137, 0.215] | - | 0.670 / 0.762 |
| A_platt | 470 (168) | 0.581 [0.541, 0.621] | 0.726 [0.677, 0.773] | 0.197 [0.180, 0.215] | 0.032 [0.019, 0.077] | -0.166 (0.036) | 0.529 / 0.760 |
| B | 470 (168) | 0.630 [0.559, 0.705] | 0.734 [0.685, 0.781] | 0.204 [0.182, 0.228] | 0.076 [0.050, 0.120] | -0.117 (0.041) | 0.459 / 0.840 |
| B_platt | 470 (168) | 0.586 [0.546, 0.628] | 0.731 [0.682, 0.779] | 0.199 [0.183, 0.217] | 0.042 [0.028, 0.092] | -0.161 (0.043) | 0.489 / 0.839 |
| C | 470 (168) | 0.589 [0.551, 0.632] | 0.718 [0.668, 0.762] | 0.200 [0.184, 0.218] | 0.020 [0.018, 0.075] | -0.158 (0.047) | 0.506 / 0.826 |
| C3_resid | 470 (168) | 0.571 [0.518, 0.631] | 0.759 [0.713, 0.802] | 0.192 [0.172, 0.214] | 0.044 [0.027, 0.093] | -0.176 (0.041) | 0.489 / 0.818 |
| C0_gold | 470 (168) | 0.553 [0.506, 0.605] | 0.768 [0.721, 0.813] | 0.186 [0.167, 0.207] | 0.032 [0.020, 0.085] | -0.193 (0.042) | 0.475 / 0.828 |
| C1_shift | 470 (168) | 0.609 [0.556, 0.668] | 0.719 [0.669, 0.762] | 0.204 [0.185, 0.226] | 0.074 [0.042, 0.112] | -0.138 (0.047) | 0.489 / 0.831 |
| base_rate | 470 (168) | 0.654 [0.627, 0.680] | 0.453 [0.399, 0.509] | 0.231 [0.218, 0.243] | 0.049 [0.025, 0.095] | -0.093 (0.052) | 0.633 / 0.445 |

Selection steps:

- A_platt vs A: diff -0.1661, SE 0.0364 -> replaces
- B vs A_platt: diff +0.0491, SE 0.0267 -> does not replace
- B_platt vs A_platt: diff +0.0054, SE 0.0145 -> does not replace
- C vs A_platt: diff +0.0083, SE 0.0181 -> does not replace

Sensitivity selects A_platt (same as the headline).

## Public vs private (headline labels)

| operator | n | confirmed | contradicted | candidate | log loss | AUROC | Brier | ECE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| public | 31 | 28 | 3 | A | 1.030 [0.683, 1.422] | 0.417 [0.107, 0.800] | 0.358 [0.236, 0.489] | 0.435 [0.294, 0.594] |
| public | 31 | 28 | 3 | A_platt | 0.436 [0.237, 0.696] | 0.393 [0.071, 0.800] | 0.127 [0.059, 0.214] | 0.199 [0.119, 0.309] |
| private | 186 | 137 | 49 | A | 0.680 [0.540, 0.826] | 0.828 [0.754, 0.893] | 0.216 [0.172, 0.260] | 0.210 [0.157, 0.272] |
| private | 186 | 137 | 49 | A_platt | 0.430 [0.346, 0.519] | 0.825 [0.749, 0.892] | 0.135 [0.105, 0.168] | 0.071 [0.028, 0.114] |
| unknown | 4 | 3 | 1 | A | 0.321 [0.085, 0.564] | 1.000 [1.000, 1.000] | 0.097 [0.010, 0.196] | 0.250 [0.080, 0.421] |
| unknown | 4 | 3 | 1 | A_platt | 0.232 [0.119, 0.405] | 1.000 [1.000, 1.000] | 0.052 [0.013, 0.118] | 0.198 [0.112, 0.325] |

Public facilities have 3 contradicted pairs against 28 confirmed. With so few negatives the public AUROC interval is too wide to show any ranking ability: the score has no demonstrated ranking ability for public facilities.

## Per service: selected model vs a text-only rule

Text-only rule: confirmation rate by 1[T >= 2] fitted on the other four folds. 'beats' = LL diff <= -1 SE.

| service | n | conf | contra | LL selected | LL text | diff (SE) | AUROC selected | AUROC of T | beats text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| burn_care | 22 | 15 | 7 | 0.620 | 0.676 | -0.056 (0.130) | 0.629 | 0.643 | no |
| cardiac_surgery | 38 | 26 | 12 | 0.512 | 0.564 | -0.052 (0.071) | 0.804 | 0.712 | no |
| dialysis | 32 | 28 | 4 | 0.243 | 0.389 | -0.147 (0.053) | 0.920 | 0.737 | yes |
| emergency_24x7 | 26 | 18 | 8 | 0.444 | 0.556 | -0.111 (0.092) | 0.847 | 0.729 | yes |
| emergency_csection | 27 | 20 | 7 | 0.327 | 0.575 | -0.248 (0.066) | 0.950 | 0.646 | yes |
| mri | 21 | 16 | 5 | 0.528 | 0.574 | -0.046 (0.082) | 0.562 | 0.481 | no |
| nicu | 25 | 21 | 4 | 0.275 | 0.430 | -0.155 (0.080) | 0.976 | 0.762 | yes |
| stemi_thrombolysis | 16 | 14 | 2 | 0.505 | 0.443 | +0.062 (0.093) | 0.929 | 0.643 | no |
| trauma_care | 14 | 10 | 4 | 0.505 | 0.590 | -0.086 (0.166) | 0.875 | 0.600 | no |

The selected model beats the text-only rule by at least one SE on 4 of 9 services.

## Location head

443 labelled facilities (40 not at the stated place). Prior scorecard: log loss 0.210 [0.153, 0.274], AUROC 0.895 [0.830, 0.946]. EBM (fit_pl.py refit, fold5 OOF): log loss 0.231 [0.173, 0.293], AUROC 0.847 [0.769, 0.914]. Paired LL diff +0.0206 (SE 0.0153). Shipped: A_prior.
Existence head: prior-only (decision), expert settings, not learned.

## Badge thresholds (DEV OOF of the selected model)

t_L = 0.3686 (chosen on DEV), t_U = 0.2000 (fallback). LIKELY on DEV: 102/120 confirmed, Wilson [0.7753, 0.903]. UNLIKELY on DEV: 7/7 contradicted, Wilson [0.6457, 1.0].
A fallback applies when fewer than 20 DEV pairs lie beyond a threshold meeting precision 0.85 (t_L) or NPV 0.90 (t_U).

## Conformal top-k (alpha 0.10, DEV OOF)

| urgency | queries | k | coverage | Wilson 95% | random-order coverage at k | median query size |
| --- | --- | --- | --- | --- | --- | --- |
| emergency | 27 | 2 | 1.000 | [0.875, 1.000] | 0.974 | 2 |
| planned | 20 | 2 | 0.950 | [0.764, 0.991] | 0.965 | 3 |

Pseudo-queries are (service, state) groups of decided DEV pairs with at least one confirmed pair; real queries rank many more candidates, so k here is a lower bound on what a live query needs. Queries with no confirmed pair are excluded (counted in select.json).

## Shipped and frozen

- Service head: A_platt = candidate A prior scorecard with one Platt step fitted on all 221 decided DEV pairs
  (a = 0.5020, c = 1.4983). Every contribution is a times the prior contribution, so the card stays additive.
  P_S therefore means "chance a decisive web check confirms the service", not "chance a call finds it".
- Location head: A prior scorecard (the EBM refit did not beat it). Existence head: prior-only.
- C ran (fold5 CV only, about 2.5 minutes per label view); its no-web and held-out-state variants were skipped for time.
  C3_resid and C0_gold have lower OOF log loss than A_platt, but they are ablations outside the pre-set order and were
  not used for selection.
- model_version eed29abe3b7d857800e31103e702da866299739f7d19d13375585bf7dbf1d69a (sha256 of params_A.json, the Platt
  and threshold values, and the code files listed in export.py).
- TEST: 150 pairs written to model/v2/test_predictions.parquet, sha256
  1b85f4c81afd936a057d9349247c716f7fa65091931d51e30ccdcef83f6e3ff4. TEST labels were not opened.
- Re-frozen before the opening to fix three export blockers; no refit, no p or band changed. See REFREEZE.md.
