# Re-freeze of the model v2 export (2026-11-21)

Reason: the independent check (check/CHECK.md) found three export and contract blockers. The model was not refit:
A_platt with Platt a 0.5020 and c 1.4983, thresholds unchanged. No TEST label had been revealed to the modelling
side, so re-freezing before the opening is within protocol. Only TEST ids from test_sample.json were read.

| | old | new |
| --- | --- | --- |
| model_version | 4412c4731e1c21ef057bdac876d17b42d1da3fa27e5c5907615cfbcced327410 | eed29abe3b7d857800e31103e702da866299739f7d19d13375585bf7dbf1d69a |
| test_predictions.parquet sha256 | 32fc27c594216143470b3cd1f99fdb2f87930deeffe3872f03875ce473ae8db4 | 1b85f4c81afd936a057d9349247c716f7fa65091931d51e30ccdcef83f6e3ff4 |

model_version changed because export.py is one of the hashed code files.

## What changed

- B2: export.py drops the 12 exclude_review records with common/eligibility.py eligible_facilities, the app's rule.
  The table went from 358,524 to 358,092 rows; the 432 dropped rows were 3 LIKELY, 33 UNLIKELY and 396
  NO_SERVICE_TEXT. None of the 12 is a TEST facility or in a TEST leakage group. The app reads no other derived/v2
  table.
- B3: lo/hi are unchanged. Their meaning (the Wilson 95% interval of the observed confirmed rate among DEV pairs in
  the same score bin, so p need not lie inside it) is now in model_card.json (`field_descriptions`, `intervals`)
  and derived/v2/README.md. contracts_v2.py now checks that lo <= hi, both are in [0, 1], and each row carries its
  bin's lo/hi from `calibration_by_score_bin`.
- B1: bands are unchanged. contracts_v2.py expects LIKELY / CALL_FIRST / NO_SERVICE_TEXT / UNLIKELY. The app
  mapping is in derived/v2/README.md; app/ was not edited (issue #63).
- contracts_v2.py reads the real schema. contributions is parsed from JSON. The `logit` column requirement is
  dropped: MODEL_SPEC 5.4 ties the displayed terms to the shipped logit, which is logit(p), so the check is
  base + sum(points) / (20 / ln 2) = logit(p). A second UNLIKELY rule (C = 2 with T <= 1) is recognised by its c2
  term. not_observable is judged per (facility, service, family). A crashing check now reports fail and no longer
  stops the checks after it.
- model_card.json also gains `band_thresholds` (p, P_L and P_E gates) and `eligibility`.

## Checks (all re-run on the new export)

- export.py: additivity after the JSON round trip on all rows (1e-9) and evidence-id resolution, both asserted.
- contracts_v2.py: 12 of 12 pass, 0 not run (contracts_v2_refreeze_stdout.txt). The selftest passes.
- freeze.py: the same 150 pairs in the same order; `shasum -a 256` equals test_predictions.sha256.
- Old against new: on all 358,092 kept rows p, lo, hi, p_location, p_exists, base, band, overlays and
  contributions are identical. On the 150 TEST rows p and band are identical; only model_version differs.

## Named examples, as they now stand

- Wockhardt Nagpur dialysis: LIKELY, p 0.897, PLACE_UNCLEAR. P_L is 0.705, so PLACE_UNCLEAR comes from the
  stated-city and name-place votes (-1), not from P_L < 0.7. The Nair Hospital sentences are rejected; two
  own-unit sentences carry it. MODEL_SPEC 4.9, 4.10, 4.11, 5.2, 5.3 and 8 now say this.
- Aravind "Hyderabad": still LIKELY for no service. Dialysis is CALL_FIRST at p 0.476, held back by s1, w_silent
  and P_L 0.394. MODEL_SPEC now names the website term as well.
- Sadar Hospital Gopalganj dialysis: LIKELY, p 0.898, P_L 0.716, matching CHECK.md. CHECK.md does not mention its
  PLACE_UNCLEAR overlay (PIN vote -1). No other doc names this case.

Not changed: check/CHECK.md, which keeps the old hashes as the checker's record, and the v1 stories in viz/model/ and
viz/STORYBOOK.md, which are labelled with the v1 model hash.
