# Independent check of model/v2/final before publication

Scope: items 1 to 6 of the check task. Code: `check.py` in this folder (my own code, it does not import the fit
code). Raw output: `check_stdout.txt`, `out.json`. `validation/contracts_v2.py` output: `contracts_v2_stdout.txt`.
Nothing in the model or in derived/v2 was changed. TEST labels were not opened or searched for; only the TEST ids
in `model/gold/v3/test_sample.json` were read.

Labels are agent-labelled, not human-checked.

## Verdict

| item | result |
| --- | --- |
| 1 TEST overlap with training rows | PASS |
| 2 no gold TEST verdict or data_point_scores.score in features or fitting | PASS (one disclosure note) |
| 3 selection table recomputed from the OOF files | PASS |
| 4 contract | FAIL: 2 failures in my own checks, plus contracts_v2.py fails |
| 5 faithfulness, 3 cases | mixed: contributions are traceable, but Wockhardt dialysis is now LIKELY |
| 6 sha256 of test_predictions.parquet | PASS |

Blockers, details below:

- B1. The bands are `LIKELY / UNLIKELY / CALL_FIRST / NO_SERVICE_TEXT`. `app/packs/build_packs.py` (`apply_bands`)
  raises `ValueError` on any band outside `likely / not_verified / unlikely`, and contracts_v2.py uses the same
  set. As published, the app pack build fails the moment it reads this table.
- B2. The 12 `exclude_review` records (derived/v1/record_trust) are scored: 432 rows, 3 of them LIKELY. The
  contract says they must not be scored at all. None of them is a TEST facility.
- B3. `lo <= p <= hi` fails on 22,370 of 358,524 rows (6.2%), and on 46 of the 150 frozen TEST rows. lo/hi
  are the Wilson interval of the DEV score bin's record, and p can fall outside its own bin's interval
  (17,671 rows have p < lo, 4,699 have p > hi; the largest gaps are 0.075 and 0.064).

B1 and B2 are export or contract problems, not model problems. Fixing them changes the table, which means
model_version and the frozen test_predictions sha256 have to be redone. Whether that is allowed after the freeze is
the team's decision; I fixed nothing.

## 1. TEST overlap: PASS

150 TEST pairs, 150 facilities, 150 leakage groups (from derived/v2/facility_features.parquet), 209 facilities
in those groups. My recomputed set equals `labels/out/test_blocked_facilities.parquet`.

I checked every training table against those facilities, both by unique_id and by leakage_group_id (taken from
the facility_features map, and from the table's own column where it has one). Zero hits in all 14:

- labels_cc and labels_sens: gold_dev_pairs (597), gold_dev_facility (630), pu_labels (20,059)
- labels/out: gold_dev_pairs with all 601 rows, and pu_labels (21,500)
- oof_selected (221 rows, the Platt fit rows)
- PL oof (2,658 rows)
- B and C OOF for both views (pair ids mapped to facilities)

Existence is prior-only, so it has no training rows to check.

## 2. No gold TEST verdict or data_point_scores.score: PASS

- In derived/v1/data_point_scores, 644 rows have `score != score_model`: 141 v1 gold test, 143 v1 gold dev and
  360 emails. On the overridden location and existence facilities, no column of facility_features or
  facility_attributes equals `score` on more than half the rows, and none separates the overridden verdict
  perfectly (AUROC 0 or 1). The same holds for the 56 overridden service_claim pairs against every pair-level
  feature.
- The only code on the derived/v2 path that reads data_point_scores is `viz/features/build_features.py`. It
  reads `score_model`, the value before the override, and only into `c_location_score_v1`, which build.py does
  not copy into derived/v2. No code under model/v2 mentions test_labels or OPENING_LOG, and no TEST labels file
  is read by any of it.
- Disclosure note: 30 of the 221 decided training pairs are old v1/v2 pairs with `split_orig = test`. They are
  not v3 TEST, but they mean any old v1/v2 TEST number is no longer held out. That fits the decision that v1
  numbers are history; the card should not cite them as independent.
- Not checked: whether the hand-check samples behind witness precisions (G_scope, NABH match and others) include
  v3 TEST facilities. Those samples set source precisions, not service labels.

## 3. Selection table recomputed: PASS

I rebuilt A from scores_A.z_S, A_platt with my own per-fold unpenalised logistic fit on fold5, B and B_platt
from B_cc/oof.parquet, and C (C1_platt) from C_cc/ps_oof.parquet. ECE uses 5 equal-count bins. Cluster SE is
over leakage groups. Every number matches SELECT.md to 0.0015 or better:

| candidate | LL | AUROC | Brier | ECE |
| --- | --- | --- | --- | --- |
| A | 0.723 | 0.804 | 0.234 | 0.230 |
| A_platt | 0.427 | 0.800 | 0.132 | 0.044 |
| B | 0.451 | 0.813 | 0.143 | 0.074 |
| B_platt | 0.432 | 0.812 | 0.138 | 0.053 |
| C | 0.461 | 0.766 | 0.146 | 0.043 |

Steps: A_platt vs A -0.2961 (SE 0.0588) replaces; B vs A_platt +0.0239 (0.0350), B_platt +0.0052 (0.0257) and
C +0.0347 (0.0274) do not. Selected: A_platt.

- My Platt fit on all 221 pairs gives a = 0.5020, c = 1.4983, matching select.json.
- n = 221 with 168 confirmed. IPW on v3: 134 pairs, Kish n 43.2.
- Public (31 pairs, 3 contradicted): AUROC 0.393. Private (186 pairs, 49 contradicted): AUROC 0.825. The score
  has no demonstrated ranking ability for public facilities.
- My A_platt OOF differs from oof_selected by at most 1.5e-4, which is solver tolerance.

## 4. Contract: FAIL

My checks:

- PASS:
  - (unique_id, service_id) is unique.
  - The 36 service ids equal the taxonomy.
  - All 9,947 eligible facilities x 36 are present.
  - Additivity, `logit(p) = base + sum(points) / (20/ln 2)`, holds on a seeded 2,000-row sample (max error
    7.1e-15).
  - All 526,348 evidence ids in all rows resolve to witnesses.evidence_id or claim_atoms.atom_id.
  - not_observable contributes 0. 1,467,631 (facility, service, family) triples are not_observable, and none
    of them appears in any contribution list.
  - One model_version, equal to model_card.json and to test_predictions.parquet.
  - The 150 test_predictions rows equal the table's p and band.
- FAIL: the 12 exclude_review records are present (B2).
- FAIL: `lo <= p <= hi` (B3).

`validation/contracts_v2.py` (exit 1):

- pass: v2_keys_unique, v2_coverage.
- fail: v2_excluded_not_scored (B2), v2_probabilities (B3), v2_logit_identity (the table has no `logit`
  column).
- crash: v2_evidence_ids_resolve. `contributions` is a JSON string column (large_string), not
  `list<struct<term, points, evidence_ids>>`, so `pc.list_flatten` fails. The checks after it (bands,
  not_observable, operator, model_version, quotes, restricted lists) never ran, so they are not run, not passed.

The band vocabulary (B1) would also fail check_v2_bands once the run reaches it.

## 5. Faithfulness (3 cases)

Each case lists the p, band and the main contributions, in points.

Wockhardt Hospital Nagpur (3ac5ae50), dialysis:

- p 0.897, band LIKELY, P_L 0.705, PLACE_UNCLEAR.
- Attribution works. The two Nair Hospital, Mumbai Central sentences are rejected (`names_other_facility`) and
  shown as c1 -7.4 with those evidence ids.
- The T ladder still adds +53.5 from two other sentences counted as own units: "Offers dialysis services at
  concessional pricing (Rs. 350 or less per session)" and "In-house dialysis units". The first reads like the
  same Nair Hospital programme.
- It passes the LIKELY gate only because P_L 0.705 is just above 0.7. MODEL_SPEC and the walk-through say
  "Wockhardt dialysis not Likely (P_S 0.54, P_L 0.58)" and "Wockhardt (caught)". That is no longer true: it
  is now LIKELY with a PLACE_UNCLEAR overlay.
- It is LIKELY for 14 of its 36 services.
- The walk-through text must change, or the team must accept this. Not a contract failure.

Aravind Eye Hospital "Hyderabad" (b8a5401f):

- LIKELY for no service (17 CALL_FIRST, 14 UNLIKELY, 5 NO_SERVICE_TEXT). P_L 0.394, PLACE_UNCLEAR.
- For non-eye services, the scope term s1 (-38.4) and w_silent (-21.2, the site does not mention the service)
  offset a full T ladder built from clearly foreign text: "Sushtruta Trauma Centre", "Emergency surgeries for
  head injury", "24x7 Emergency Services with a 50-bed emergency ward".
- emergency_24x7 still sits at p 0.476 (CALL_FIRST), and icu at p 0.648 (CALL_FIRST), so they stay as call
  candidates.
- cataract_surgery is p 0.936 from the website (w_cell_A +60.4), but its band is NO_SERVICE_TEXT because the
  listing text has T < 2.
- The contributions make sense. It is caught by location and scope, as documented, not by attribution.

Public district hospital in Bihar: Sadar Hospital Gopalganj (1abd52f3, level dh), dialysis:

- p 0.898, band LIKELY, P_L 0.716.
- Own-unit sentences: "Two hemodialysis machines in the dialysis room", "Provides hemodialysis treatment" and
  "Affiliated with Apollo Dialysis Private Limited", which fits the PMNDP PPP pattern.
- Contributions: k_iphs +7.2, level_dh +7.2, tp_public -2.8. "Part of Apollo Dialysis Clinics network with
  over 135 clinics" is rejected as an ambiguous reference (c1 -7.4).
- The contributions make sense.
- Two caveats:
  1. Public-facility ranking has no demonstrated ability on DEV (AUROC 0.393, 3 negatives).
  2. With no service text, this hospital still gets p 0.57 to 0.63 for services like radiotherapy and kidney
     transplant. The base logit is about 0, and level_dh / k_iphs add to it. The band is NO_SERVICE_TEXT, so the
     app must show the band, not p, for these rows.

## 6. sha256: PASS

`sha256(test_predictions.parquet)` = 32fc27c594216143470b3cd1f99fdb2f87930deeffe3872f03875ce473ae8db4, equal
to test_predictions.sha256.
