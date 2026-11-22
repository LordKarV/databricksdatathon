# Candidate D: scorecard with reader soft counts (issue #79)

Run 2026-11-21 with `python model/v2/fit_reader/fit.py` (about 1 minute, CPU). Every number below is
in `out/metrics.json`, `out/params.json` or `out/oof_predictions.parquet`, written by that script.
The script reads `model/v2/labels/out/` (gold DEV and PU labels) and `derived/v2/`. It never opens
`model/gold/`.

## Result

**The reader adds nothing detectable on gold DEV.** No variant with reader soft counts beats the
same scorecard without them: every paired difference in out-of-fold log loss has a 95% interval
that includes zero. Recommendation: do not select candidate D.

A second result matters more than the first: **none of these scorecards is clearly better than
predicting the base rate.** The baseline's out-of-fold log loss is 0.621 against 0.631 for the
training-fold base rate; the interval of that difference includes zero. AUROC is about 0.63.

Gold DEV pairs with a y_S label: 195 (62 positive, base rate 0.318), 7 services, grouped 5-fold by
`fold5`. Intervals: 2,000-replicate bootstrap over leakage groups, seed 79. Unweighted.

| Model | Log loss (95% CI) | AUROC (95% CI) | Brier | ECE (5 bins) | Log loss minus B_like (95% CI) |
|---|---|---|---|---|---|
| base rate of the training folds | 0.631 (0.574 to 0.686) | not meaningful | 0.219 | 0.063 | +0.010 (-0.044 to 0.063) |
| B_like, gold only | 0.621 (0.547 to 0.695) | 0.631 (0.553 to 0.713) | 0.218 | 0.090 | reference |
| D_replace, gold only | 0.611 (0.541 to 0.686) | 0.636 (0.554 to 0.714) | 0.213 | 0.095 | -0.010 (-0.041 to 0.023) |
| D_augment, gold only | 0.619 (0.546 to 0.694) | 0.638 (0.556 to 0.714) | 0.217 | 0.078 | -0.002 (-0.024 to 0.021) |
| D_augment_offers_only, gold only | 0.613 (0.538 to 0.688) | 0.649 (0.569 to 0.724) | 0.215 | 0.081 | -0.008 (-0.033 to 0.019) |
| B_like, PU prior | 0.619 (0.545 to 0.694) | 0.630 (0.550 to 0.710) | 0.217 | 0.089 | -0.003 (-0.009 to 0.004) |
| D_replace, PU prior | 0.609 (0.538 to 0.686) | 0.641 (0.558 to 0.721) | 0.213 | 0.087 | -0.012 (-0.039 to 0.017) |
| D_augment, PU prior | 0.615 (0.542 to 0.691) | 0.642 (0.563 to 0.720) | 0.215 | 0.087 | -0.007 (-0.026 to 0.015) |
| D_augment_offers_only, PU prior | 0.609 (0.536 to 0.685) | 0.652 (0.573 to 0.728) | 0.213 | 0.080 | -0.012 (-0.033 to 0.012) |

The reader variants are nominally lower by about 0.01 log loss. With 195 pairs that is well inside
the noise, and eight variants were compared, so the best of them is not evidence of anything.
Leaving out p_about_this (offers only) is at least as good as using it, which agrees with the hand
check in `model/reader/README.md` (the reader's "not about this facility" flags were right in 8 of
34 cases).

### Public and other facilities

| Group | Pairs (positive) | Model | Log loss (95% CI) | AUROC (95% CI) | ECE |
|---|---|---|---|---|---|
| public | 34 (15) | base rate | 0.725 (0.582 to 0.863) | not meaningful | 0.123 |
| public | 34 (15) | B_like, gold only | 0.754 (0.626 to 0.893) | 0.521 (0.312 to 0.704) | 0.128 |
| public | 34 (15) | D_replace, PU prior | 0.740 (0.598 to 0.898) | 0.547 (0.324 to 0.747) | 0.138 |
| private or unknown | 161 (47) | base rate | 0.611 (0.553 to 0.671) | not meaningful | 0.081 |
| private or unknown | 161 (47) | B_like, gold only | 0.593 (0.514 to 0.678) | 0.651 (0.561 to 0.736) | 0.104 |
| private or unknown | 161 (47) | D_replace, PU prior | 0.582 (0.503 to 0.666) | 0.653 (0.565 to 0.738) | 0.102 |

For public facilities every model is nominally worse than the base rate and ranks at chance
(AUROC 0.52 to 0.56, intervals 0.31 to 0.75). 34 pairs is too few to conclude more than "no
evidence the scorecard works for public facilities". Mean prediction tracks the observed rate in
both groups (public 0.42 predicted against 0.44 observed; other 0.30 against 0.29), because the
model has a `public` term.

## What was fitted

Logistic scorecard, all terms 0/1 indicators, so a score is `base + sum of weights of the terms
that are on`. The script asserts that identity on every fit (largest error 1.3e-15).

- Service intercepts (7).
- Own-text family T: `t1..t5` = 1[a_T >= v], weights >= 0.
- Reader soft count s = sum over the pair's echo units of the largest p_about_this x p_offers in
  the unit. Terms `r1..r3` = 1[s >= 0.5], 1[s >= 1.5], 1[s >= 3], weights >= 0. The steps were
  fixed before any fit and not tuned. The offers-only ablation uses p_offers alone.
- `prereq` (>= 0), `c1` contamination, `n1` negation, `s1` scope conflict (all <= 0), `trunc`,
  `x_on` (>= 0), `x_absent`, `public`, `hospital`, `beds_hi` (free).
- Fairness coding: a missing or not-observable input is 0 and contributes nothing.
- MAP fit, Gaussian prior, sign bounds, L-BFGS-B. Prior sds 1.5 (weights), 5 (intercepts): assumed,
  not tuned.
- "PU prior": stage 1 fits "is on the list" on 22,140 PU rows (NABH, NMC without blood_bank,
  LaQshya, e-RaktKosh; the lists LABELS.md says are not usable are left out), with list terms
  dropped and the held-out fold's leakage groups removed. Its evidence weights become the prior
  means (sd 1.0) of the gold fit. It moved log loss by 0.003.

Variants: B_like (T only), D_replace (reader instead of T), D_augment (both), and D_augment with
the offers-only soft count; each with and without the PU prior.

Full-data weights for B_like, gold only: t1 0.82, t2 to t4 0 (at the bound), t5 0.68, prereq 0.50,
s1 -1.09, hospital 0.90, public 0.68, beds_hi 0.56, x_on 0 (at the bound). That is: beyond "any
own text" and "the strongest level", the text level carries no fitted signal here, and being on an
official list carries none.

## Limits

- **B_like is my reimplementation, not candidate B.** `model/v2/fit_scorecard/` did not exist when
  this ran, so there is no paired comparison with the real B. `out/oof_predictions.parquet` has
  `pair_id` and `fold5`; the comparison is one merge once B's file exists. B has about 60 terms;
  this has 15 to 18.
- Not weighted by inclusion probability (the 125 e2e pairs have none), so these are not population
  rates.
- 66 of the 195 pairs have no reader score at all (no scored sentence for the service); their soft
  count is 0.
- The reader was trained on rule-derived weak labels, not on gold pairs, so it is not dropped
  under the cross-fit plan; but its labels come from the same rules that build family T, so the
  two are not independent witnesses.
- y_S counts "searched, nothing found" as 0. The models predict that label, not "offers the
  service".
- The web-evidence columns were left out (the cross-fit plan marks them "ablate" for gold fits).
  A model with them would likely score better on this label, and be closer to circular.
- No Platt step, no posterior draws, no thresholds, no scores for the full corpus: not worth
  building for a candidate that should not be selected.
- No TEST data was read.
