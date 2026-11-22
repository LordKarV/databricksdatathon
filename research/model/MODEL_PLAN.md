# Model plan: explainable service-availability scoring

Date: 2026-11-21. Scope: which models the facility finder should use, a CPU prototype of the
highest-priority one trained on the best verified external label source, and how it ships on
Databricks Free Edition. Paths are relative to ROOT = /Users/karthikvattem/projects/datathon.

## Starting point

A full scoring stack already exists in ROOT/model (Witness Ledger, ROOT/model/MODEL_SPEC.md). It
has a rule-based evidence layer (claim atoms, sentence ownership, echo collapse), an additive
logistic scorecard per (facility, service) fitted on 70-odd web-checked gold pairs, and a decision
layer. Its external-list family X "abstains everywhere today". This plan does not replace that
stack. It answers two questions it left open: can the verified external lists serve as training
labels, and where do they belong in the model?

## Recommended models, in priority order

1. Service-availability scorecard (P_S). An additive logistic model over named VF-only evidence
   terms: text strength T 0-5, prerequisites P, scope conflict S, contamination C, non-offer N,
   facility type, public level, bed, doctor and specialty-breadth bins, and merge bucket. The
   points shown on screen are the computation. External lists enter in two ways. They are direct
   evidence rows, never hidden weights. They also serve as held-out checks of the score. They are
   never both label and feature in the same model. Keep the Witness Ledger P_S, which is fitted on
   web gold, as the ranking score. The NABH-trained variant (prototype below) is a label-scale
   check and a fallback, not the ranker.
2. Registry entity matchers (rules plus rapidfuzz, no learning). These link VF records to NABH,
   NMC, LaQshya, MoHFW TCF, e-RaktKosh and OSM. Hand-checked precision is already 95-97.5%
   (NABH 39/40, TCF 19/20, NMC 19/20). A learned matcher would need pair labels we do not have,
   and it would not clearly beat these numbers. Output: one evidence row per match (list, id,
   status, date, citation URL, match rule, distance).
3. Sentence-attribution classifier ("is this sentence about this facility"). Rules first
   (ROOT/model/proto/evidence). An optional cached LLM classifier via ai_query measured +0.037
   [0.009, 0.076] over the rules on 108 sentences, but ownership changes only 130 of 69,713 pairs.
   It is worth doing only after 1 and 2 ship.
4. Embeddings for query-to-service mapping. Use databricks-gte-large-en through ai_query (verified
   to return 1024 dims). The service list is short and a curated lexicon
   (ROOT/cleaning/claims/lexicon.py) already covers synonyms, so embeddings only map free-text
   user queries ("kidney machine", "operation for baby") onto the service enum. They need one
   precomputed table of service-synonym vectors and no Vector Search endpoint.
5. Translation for Hindi and Marathi. Translate the fixed explanation templates once with a
   foundation chat endpoint, have a speaker review them, and store them as a table. Facility
   quotes stay in their original language with the citation, so no model rewrites the evidence.

## Label sources, ranked

| source | rows usable as labels | what a label means | use |
| --- | --- | --- | --- |
| NABH specialty codes | 1,054 VF facilities with a code among the 7 fetched | facility declared this scope to NABH | prototype training label (below) |
| LaQshya Maternity OT | 49 VF facilities (positive only) | dated government certification | held-out check, evidence row |
| MoHFW trauma care facilities | 20 (positive only) | funded TCF, functional status from 2019 | held-out check, evidence row |
| NMC DM Nephrology | 16 (positive only) | PG department approved | held-out check, evidence row |
| web gold, ROOT/model/gold and audit/ground_truth | 52 checked dev pairs for these 4 services | public web confirms the service | external check; the sealed test split was not opened |

NABH is the only list large enough to train on, and it has negatives within the declared-scope
population. All the others are positive-only and small.

## Prototype: NABH weak-label scorecard

Script: ROOT/research/model/train_nabh.py, run with `.venv-ml/bin/python -B` (about 1 minute on a
laptop CPU). Outputs are in ROOT/research/model/out/: metrics.json, scores.parquet (39,836 rows =
9,959 facilities x 4 services), coefficients.csv, track_record.csv and train_stdout.txt.

Design:
- Population: VF facilities accepted by the NABH matcher whose NABH record carries at least one
  of DIA, NPH, OBG, EMD, CAR, ONC or TRN (1,054). Restricting the population this way makes "code
  absent" mean "declared a scope that leaves this out". It is still a noisy negative.
- Label: NABH lists DIA (dialysis), OBG (proxy for C-section), CAR (proxy for cardiac surgery) or
  EMD (trauma and emergency).
- Features: only VF-derived terms from ROOT/model/proto/evidence/pair_features.parquet. No NABH
  field, status or match flag is a feature.
- Split: 70/30 by sha256 of leakage_group_id. Duplicate and chain records share one side, so no
  group appears in both train and test. C (L2) is chosen by grouped 5-fold CV log loss on train
  only.
- Self-check: the script asserts that the stored per-term contributions reproduce the model's test
  probabilities.

Held-out results (350 test facilities per service):

| service (label) | test positives | AUROC | PR-AUC | Brier (base rate) | ECE 5-bin | precision / recall at 0.5 |
| --- | --- | --- | --- | --- | --- | --- |
| dialysis (DIA) | 73 | 0.682 | 0.357 | 0.154 (0.165) | 0.014 | 1.00 / 0.014 (1 flagged) |
| dialysis (DIA or NPH, sensitivity) | 157 | 0.797 | 0.729 | 0.182 (0.248) | 0.059 | 0.71 / 0.73 |
| C-section (OBG) | 279 | 0.619 | 0.848 | 0.158 (0.167) | 0.059 | 0.80 / 1.00 |
| cardiac surgery (CAR) | 186 | 0.760 | 0.784 | 0.199 (0.251) | 0.045 | 0.73 / 0.70 |
| trauma (EMD) | 102 | 0.761 | 0.566 | 0.169 (0.207) | 0.011 | 0.59 / 0.40 |

At a threshold set on train out-of-fold scores to reach precision 0.8: cardiac surgery used 0.63
and got precision 0.786, recall 0.591 on test. For dialysis and trauma, no threshold reached 0.8
on train. For OBG, every threshold reached it, because the base rate is 0.80.

Calibration (track record) on test, as the App would show it. For trauma, of facilities scored
0.6 to 0.8, 22 of 34 (65%, Wilson 48-79%) are on NABH's EMD list. Of those scored 0.0 to 0.2, 17 of
148 (11%) are. For cardiac surgery, the 0.8 to 1.0 bin holds 63 of 78 (81%, Wilson 71-88%).
Dialysis never scores above 0.6: the top bin, 0.4 to 0.6, holds 8 of 20 (40%). The full table is
in out/track_record.csv.

Baselines on the same test rows:
- Rule "VF text has an own claim" (T >= 2): dialysis precision 0.37, recall 0.47; trauma 0.33 /
  0.74; cardiac 0.86 / 0.30; OBG 0.90 / 0.10.
- Witness Ledger P_S (fitted on web gold) against NABH labels: AUROC dialysis 0.678, OBG 0.564,
  CAR 0.738, EMD 0.680. Brier is worse everywhere, as expected, because it targets a different
  quantity.
- TF-IDF over all VF text plus logistic regression (not explainable; a stand-in for "a bigger text
  model"): AUROC dialysis 0.656, DIA or NPH 0.785, OBG 0.755, CAR 0.786, EMD 0.773. That is within
  0.03 of the scorecard except OBG (+0.14).

External checks (facilities outside the NABH training population):
- Web gold dev (52 checked pairs). The NABH-trained model gets AUROC 0.531 pooled, and per service
  0.607 dialysis, 0.630 C-section, 0.625 cardiac and 0.760 trauma (n of 10 to 15 each). Witness
  Ledger P_S scores 0.852 pooled, but that is in-sample, because it was fitted on these labels.
- NMC DM Nephrology, 16 positives: median dialysis p 0.393, against 0.186 for other public
  facilities, AUROC 0.881.
- LaQshya Maternity OT, 49 positives: AUROC 0.553 against other public facilities, so the score
  does not separate certified maternity theatres.
- MoHFW TCF, 20 positives: AUROC 0.698.

What the prototype shows:
1. On its own label the scorecard is well calibrated (ECE 0.011 to 0.059) but only moderately
   discriminative. The largest weights are size and breadth terms (beds 100+, P prerequisites,
   specialty breadth), not service text. It learns "large hospitals declare broad scope", a useful
   prior but not evidence of the service.
2. NABH scope codes and web confirmation measure different things (pooled AUROC 0.53 on web
   gold). NABH codes should not replace the web-gold P_S as the ranking target.
3. The label is the ceiling, not the model. A TF-IDF model over all text gains at most 0.03 AUROC
   (OBG aside), so a fine-tuned transformer has little headroom on these labels.
4. The DIA code looks under-declared. Adding NPH lifts AUROC to 0.797, but nephrology is not
   dialysis. Show it as a separate evidence line ("NABH lists nephrology"), not as a dialysis
   label.

Decision: external lists go into the product as direct, cited evidence rows (family X) with each
list's hand-check precision. They also serve as held-out checks on P_S. The NABH-trained
scorecard ships only as a "regulator scope prior" line, with its track record, for facilities that
have no web-gold-comparable evidence. Or it is dropped if the App runs short of space. Not run: using
the NABH-trained weights as an informative prior for the web-gold fit (n too small to measure on
dev without touching the sealed test).

## Leakage controls

- A list used as the label is never a feature. The prototype uses no NABH field, and VF text that
  mentions "NABH" counts only through generic text terms. Not checked: whether removing those
  sentences changes the scores.
- When P_S is evaluated against a list, that list's evidence row is switched off for the
  evaluation.
- Splits are grouped by leakage group (duplicates, chains, shared phones and domains).
- Thresholds are chosen on train out-of-fold scores, never on test.
- The sealed Witness Ledger test split (model/gold, test) was not opened.

## GPU

A GPU would not help. The data is 10k facilities and about 1k labelled pairs per service. The
scorecard trains in seconds on CPU. The text comparator shows little headroom over it, embeddings
and LLM calls run on foundation endpoints, and Free Edition has no GPU serving or GPU batch
inference (research/gpu/GPU.md). GPU access in this workspace is unverified: `air pools list`
returned FEATURE_DISABLED and no workload has run. The only GPU-shaped job would be fine-tuning a
sentence-attribution encoder, which has 108 labelled sentences today. More labels would help it
more than more compute.

## Deployment on Free Edition

Offline, once per data refresh, on a laptop or a serverless notebook:
1. Upload the scores and evidence tables to a UC volume, then CTAS into Delta. Proposed names,
   none created yet: workspace.vf_ledger.service_scores (unique_id, service, p, z, intercept,
   top_terms, cited_atom_ids, model_hash), workspace.vf_ledger.score_terms (unique_id, service,
   term, points), workspace.vf_ledger.track_record (service, label, bin, n, positives, rate,
   wilson_lo, wilson_hi) and workspace.vf_ledger.list_evidence (unique_id, list, service, status,
   valid_to, source_url, match_rule, hand_check_precision).
2. Claim sentences come from claim_atoms (atom_id, field, text, ownership, role), so every cited
   atom resolves to its original facility text.

At query time, the App (Streamlit or Dash, Medium size) works through the 2X-Small warehouse:
- resolve place, then select candidates within a radius, then join service_scores, list_evidence
  and claim atoms;
- rank with the decision layer's closed form;
- run no model on request, call no GPU and no custom serving endpoint. An optional ai_query for
  query-to-service mapping falls back to the lexicon.

## How the App shows it

For each recommended facility:
- Verdict line: "Likely offers dialysis: 0.43 (moderate)", with the badge from the decision layer.
- Why: up to 3 cited sentences from the facility's own record (field name, quote, link to
  source_urls), then the list evidence rows. For example: "NABH Accredited H-2024-1433, lists
  cardiology (certificate link)", "LaQshya Maternity OT certified, valid to 19/03/2026 (expired)",
  "MoHFW Level II trauma care facility, 2019 status functional".
- How: a points waterfall. The intercept plus each term's points equals the score. Example from
  out/scores.parquet: Palanpur hospital b3b4b4dc, cardiac surgery, test row. Intercept -1.23, beds
  100+ +1.04, two prerequisites +0.99, claims in 2+ fields +0.76, truncated list +0.51, giving
  p = 0.95. The cited sentences are "Offers cardiac surgery as a specialty" (capability) and
  "Offers cardiac surgery" (procedure).
- Track record: "Of facilities scored 0.8 to 1.0 for cardiac care, 63 of 78 (81%) were on NABH's
  cardiology list in a held-out check." Show the label definition next to it, because it is
  NABH's declared scope, not a confirmed service.
- Uncertainty: list absence is never shown as evidence against the service. A score with no cited
  sentence shows "no service text: call first".
- Non-technical view: the verdict, a phone number and one sentence of why. The waterfall stays
  behind "How we decided".

## Rejected or deferred

- Training P_S on NABH codes as ground truth: it measures declared scope and size (web gold AUROC
  0.53).
- Gradient boosting or a neural ranker: not additive, so the points cannot be shown as the
  computation, and the text comparator shows little headroom.
- A fine-tuned transformer on GPU: label-limited, and unverified GPU access.
- A learned entity matcher: rule matchers already reach 95-97.5% hand-checked precision.
- Live LLM scoring or explanations: the LLM gave confidence 1.0 on contaminated records
  (audit/capabilities/CAPABILITIES.md).
- Vector Search: one endpoint, Delta Sync only, and the service enum is short, so a precomputed
  synonym table is enough.
- PMNDP and HMIS as labels: they are state or district level, so they serve as context and need
  only.

## Risks

- Label noise: NABH codes are self-declared, with undocumented meaning. Some codes are broken
  (AMBULANCE returns all rows).
- Population shift: training covers NABH-matched facilities (mostly hospitals). Scores for clinics
  and unmatched records are extrapolation. The App should show the score with the track record of
  the matched population and say so.
- Positive-only checks (LaQshya, TCF, NMC) are small (16 to 49), and LaQshya certificates are
  mostly expired (509 of 2,173 rows valid on 2026-11-21).
- The web gold dev check has n = 10 to 15 per service, so its intervals are wide.
- Licence: NABH and NMC forbid republication. Show per-facility facts with citation only, never a
  bulk download.
- Not pushed to GitHub: this task's rules forbid git, so the orchestrator should push
  research/model/ (the out/ parquet is small, about 1 MB) and leave data/external out.
