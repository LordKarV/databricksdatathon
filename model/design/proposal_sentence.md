# Proposal: sentence-level evidence and merged-record disentangling

Angle: every trust decision is built from individual claim sentences, and each sentence is first assigned
to the entity it describes (this facility, a same-organisation branch, or some other facility) before
anyone asks whether it supports a service. The model is a glass box over small neural atoms: a small
cross-encoder judges what one sentence says, a per-record graph decides whom it is about, and an additive,
calibrated fusion turns the surviving sentences into a probability whose every point can be traced to a
quoted sentence.

## 1. What the data says, and how it changes the seed idea

Measured for this proposal (scripts in the session scratchpad, logic described inline; all on local
parquet, nothing run on Databricks):

- Service mention sentences (8 services, from audit/claims/out/mentions.parquet): 26,041. Only 1,298
  (5.0%) carry any anchor: a self name, a foreign facility name, a sibling branch name, or an other-state or
  other-district place (joined to audit/merge/out/sentences_flagged.parquet on unique_id, field, text). Only
  147 (0.56%) are quarantined by the merge audit's deterministic policy. This is a census, not a sample.
- The known contaminated record "Aravind Eye Hospital" (Hyderabad) has 151 sentences, 5 quarantined. Its
  dialysis sentences ("Dialysis treatment is provided via a 20-bed Dialysis Unit with 10 machines as part
  of the Pradhan Mantri National Dialysis Programme", "Hemodialysis is performed in three units") name no
  facility and no place. The Wockhardt Nagpur record, by contrast, names the other facility in the same
  sentence ("Provides dialysis treatment at Nair Hospital, Mumbai Central"), and the existing quarantine
  already removes it.
- Merged records are the main uncertainty mass, not an edge case: audit/merge/out/q5_service_stdout.txt puts
  481 of 1,046 dialysis-claiming records (46%, Wilson 43-49%) in tier C (record carries merge evidence),
  and the hand check of 20 tier-C dialysis records found attribution uncertain in 11 and likely own in 9
  (9/20, Wilson 26-66%).
- Array order carries some page structure: across 1,236 record-fields with 2+ flagged sentences, flagged-
  flagged adjacencies were 1,319 against 641.2 expected under shuffling (2.06x), but only 539 of 1,236
  record-fields (43.6%, Wilson 40.9-46.4%) exceed chance. Order is a weak, learnable signal, not a rule.
- Evidence re-homing yield is small. In a random 1,500 of the 2,820 quarantined sentences that name a
  foreign facility, the distinctive part of the foreign name (generic words such as hospital, clinic,
  dental removed) exactly or near-exactly matches another record in 333 cases (22.2%, Wilson 20.2-24.4%),
  but most are homonyms ("Navkar Eye Hospital" matched "Navkar Dental Clinic"). Requiring the matched
  record's city to appear in the sentence or name leaves 33 (2.2%, Wilson 1.6-3.1%), and some of those are
  still wrong. Neither "Indira Gandhi Hospital Dwarka" nor "S L Raheja Fortis Mumbai" (the true owners of
  the two known contaminated claims) exists in the dataset.
- Corpus size: 469,498 sentences, 286,694 distinct after normalisation, mean 45 characters. Rule grades
  (audit/claims/out/grades.parquet) put 5,718 of 10,911 (facility, service) rows in "medium", the stratum
  that neither gold v1 (strong, weak, suspect) nor gold v2 (adds no_mention) samples.

Consequences for the seed idea:

1. A sentence-local attribution classifier is ill-posed for 95% of claims: the sentence itself contains no
   evidence about whom it describes. Attribution must be computed in record context. This proposal replaces
   the attribution head of the cross-encoder with a per-record anchor propagation graph (section 3.2),
   and keeps the cross-encoder for support, where the sentence alone does contain the answer.
2. Record-level contamination signals (geo disagreement, name-scope conflict, quarantine share, source
   breadth) are the second line of defence for anonymous contaminated claims like Aravind's, and enter
   the fusion layer as explicit, visible terms.
3. Re-homing stays, but as a conservative provenance feature that explains exclusions ("this sentence is
   about record X, listed separately"), not as a recall engine. Expected gain is at most a few dozen
   sentences; it must not be sold as more.

## 2. System overview

Four layers, all computed offline into Delta except the decision layer and the rendering of explanations.

```
raw facilities (10,088 rows)
  -> sentence table (469k rows: unique_id, field, idx, text)        [evidence]
  -> anchors + cues (ported audit code)                              [evidence]
  -> support atoms e_i (cross-encoder, 4 classes)                    [evidence, neural]
  -> attribution a_i (per-record anchor propagation + calibration)   [evidence, graph]
  -> evidence units (near-duplicate sentences collapsed)             [fusion]
  -> P(offers), interval, contributions; existence; location trust   [fusion]
  -> query -> ranked options + call plan                             [decision, live in App]
  -> cards (WHY, WHY NOT, WHERE, HOW)                                [explanation, live render]
```

## 3. Evidence layer (text to claims)

### 3.1 Sentence table and deterministic annotations

- Explode procedure, equipment, capability and specialties JSON arrays and sentence-split description, using
  the same split as claims/audit.py and model/gold/build_gold_v2.py so keys join exactly.
- Port, do not rewrite, the audit detectors: foreign, sibling and self names with the sub-unit and acronym
  fixes (merge/detect.py; holdout precision 21/30, Wilson 52-83%), other-state and other-district places
  (holdout precision 27/30, Wilson 74-97%), the service lexicon (core topic precision 196/200, Wilson
  95-99%), non-offer cues v2 (34/40, Wilson 71-93%), quantity and prerequisite detectors, and the geo
  verdicts (geo/facility_geo.parquet, geo/merge_signal.parquet).
- Add a rare-token fingerprint per sentence: numbers with units ("20-bed", "10 machines", "1241 beds"),
  acronyms ("IGH", "PMNDP"), and tokens with corpus IDF above a threshold. Fingerprints are what links an
  anonymous sentence to an anchored one from the same source page.

### 3.2 Attribution: per-record anchor propagation

For record r with sentences i = 1..n (n <= 161 in this data; median 38):

Seeds. Y_i is a row over three classes {own, sibling, other}:
- own: sentence names r (self names) or r's own city or locality; also URL-slug self matches.
- sibling: names a branch of the same organisation (has_sibling), or a chain unit in another locality.
- other: names a foreign facility in a direct or relation context, or asserts a location in another state
  or district (the merge audit's quarantine reasons). Credential and scheme contexts (for example
  "empanelled under PMJAY", "MS from AIIMS") are not seeds.
- unanchored: Y_i = [pi_own, pi_sib, pi_oth] scaled by a small prior weight lambda0, with pi set from
  record-level priors (section 4.3 features), so a record with no anchors resolves to "own" by default.

Graph. W_ij = w_cos * max(0, cos(v_i, v_j)) + w_fp * J_idf(i, j) + w_adj * 1[same field, |idx_i - idx_j| = 1],
W_ii = 0, where v are sentence embeddings and J_idf is the IDF-weighted Jaccard of rare-token
fingerprints. S = D^(-1/2) W D^(-1/2).

Propagation (Zhou et al. 2004 label spreading, closed form):

    F = (1 - mu) (I - mu S)^(-1) Y,    K = (1 - mu) (I - mu S)^(-1)

so F_i = sum_j K_ij Y_j. The raw attribution score is the log-ratio
z_i = log(F_i,own + eps) - log(F_i,oth + eps). Because F is linear in Y, the influence of each anchor j on
sentence i is exactly K_ij Y_j; the explanation reports the top anchors by that product.

Calibration. a_i = P(sentence i describes r) =
sigmoid(t0 + t1 z_i + t2 scope_conflict(r, service of i) + t3 q_share(r) + t4 geo_conflict(r) + t5 field_i),
fit on attribution labels (section 5). A parallel output a_i^sib uses the sibling column.

Hyperparameters (w_cos, w_fp, w_adj, mu, lambda0, eps) are tuned on dev attribution labels by grid search,
not by hand. If w_adj goes to 0 under tuning, the 2.06x contiguity effect was not useful and that is
reported.

Why not a neural pairwise "same source" model: it would need pair labels we do not have and would hide the
reason; cosine plus fingerprints plus adjacency is three numbers a judge can read. Upgrade path: replace
cosine with a learned bilinear similarity if dev attribution AUROC plateaus below the gate in section 6.

### 3.3 Support: sentence cross-encoder

Task: given (service hypothesis h_s, sentence x_i, field), predict one of
- OFFERS: asserts that the described entity currently provides s ("Hemodialysis is performed in three units").
- RELATED: a prerequisite or adjacent capability only ("Nephrology department", "AV fistula surgery" for
  dialysis, "Labour room" for emergency C-section).
- NON_OFFER: mentions s without offering it: negation, referral elsewhere, planned or future, one-off camp,
  past, staff credential, directory or insurance-package listing.
- UNRELATED.

Hypotheses are fixed definitions, one per service, for example h_dialysis = "The facility provides
haemodialysis or peritoneal dialysis to patients", h_csection = "The facility performs emergency caesarean
sections".

Model: a 22M-parameter NLI-pretrained cross-encoder (cross-encoder/nli-deberta-v3-xsmall, MiniLM-L6 as the
fallback), input "[h_s] [SEP] [field]: [x_i]", max length 96 tokens, 4-way softmax, temperature-scaled on
dev. Training: about 20,000 sentence labels (teacher, section 5), class-weighted cross-entropy, 3 epochs,
lr 3e-5, batch 32, groups split as in section 5.4. Output: e_i = p_i(OFFERS), r_i = p_i(RELATED),
n_i = p_i(NON_OFFER).

Candidates scored: all 26,041 lexicon mentions plus a recall set: for each service, sentences in the top
2,000 by embedding cosine to h_s that the lexicon missed ("renal replacement therapy", "kidney care unit").
About 45,000 pairs in total.

Fallbacks, decided by measurement on human-labelled sentences, not by preference:
- If Hugging Face weights cannot reach Databricks compute (outbound internet is restricted, not tested),
  use an embedding probe: multinomial logistic regression on [v_i, v_i * v_h] with gte-large-en
  embeddings from ai_query. Fully inside Databricks.
- If neither student beats the audit's non-offer cues plus lexicon (the rule baseline) on macro-F1 with a
  paired bootstrap interval excluding 0, ship the rules and say so.

### 3.4 Re-homing (conservative)

For a sentence with an "other" seed naming entity k: link to record r' if (1) the distinctive name core of
k matches r' at ratio >= 95, (2) r' city or district appears in the sentence or in k, (3) r' facility type
is compatible with s, and (4) r' is not in r's duplicate group. The sentence then enters r' as evidence with
a_i' = a_i(other) * 0.8 (the 0.8 is a fixed discount for link uncertainty, shown on the card). Measured
upper bound: 2.2% of quarantined foreign-name sentences pass (1) and (2). Its main value is the WHY NOT
text on r's card.

## 4. Fusion layer (claims and signals to calibrated probabilities)

### 4.1 Evidence units

Within record r and service s, cluster the scored sentences with cos(v_i, v_j) >= 0.92 or equal normalised
text (the dataset repeats "Dialysis" across fields and sources). Each unit u keeps the member with the
highest a_i * e_i as its quote, and records the set of fields F_u its members span.

Unit strength: s_u = a_u * e_u * w_field(u), where w_field is a small learned per-field weight vector
(procedure, equipment, capability, description; specialties only via the RELATED channel).

### 4.2 Rank-discounted additive evidence

Sort units by strength, s_(1) >= s_(2) >= ...; evidence mass

    E_fs = sum_k gamma^(k-1) * s_(k),    gamma = 0.5 (tuned on dev in {0.3, 0.5, 0.7})

The first strong sentence counts fully, the second half, the third a quarter. This handles redundant
copies without a dependency model and keeps each unit's contribution exact: c_(k) = beta_E * gamma^(k-1) * s_(k).

### 4.3 Pair probability

    logit P(Y_fs = 1) = b_s + b_type(f) + beta_E E_fs + beta_F (n_fields_eff - 1)
                        + beta_R R_fs + beta_Q q_fs - beta_N N_fs
                        - beta_C C_f - beta_K kappa(f, s) + beta_X X_fs + beta_O O_f

- n_fields_eff: distinct fields among units with a_u e_u >= 0.5 (corroboration; gold v1 strong stratum,
  2+ fields plus prerequisite, was 10/12 confirmed, Wilson 55-95%).
- R_fs: prerequisite support, max over sentences of a_i r_i for the service's prerequisites
  (nephrology for dialysis; obstetrics, theatre and anaesthesia for C-section; and so on).
- q_fs: specificity, 1 if a unit carries a quantity ("10 machines", "20-bed unit").
- N_fs: non-offer mass, sum of a_i n_i.
- C_f: record contamination, a fixed linear index of q_share, geo_conflict and the source-breadth bins
  from merge/out/analyze_stdout.txt (contamination rate rises from 4.2% at 0-2 URLs to 59.6% at 30+).
- kappa(f, s): name-scope conflict (an eye, dental, IVF, lab or skin-named record claiming s). It is a
  feature, not a rule: 17 of 30 sampled single-specialty-named records with such claims were legitimate
  (merge q3_sample).
- X_fs: external list match (government dialysis centre list, SNCU list, PMJAY specialty empanelment)
  when research/ or external/ produces verified lists; 0 otherwise.
- O_f: own-domain or official source present (provenance URL classes).
- b_type: facility-type offsets (hospital, clinic, nursing home, lab), shared across services.

Estimation: L2-regularised logistic regression, pooled over services with per-service intercepts, sign
constraints on coefficients whose direction is known (beta_E, beta_F, beta_R, beta_Q, beta_X, beta_O >= 0;
beta_N, beta_C, beta_K >= 0 as penalties), fit on dev gold labels. Eleven slopes plus intercepts against
roughly 90 dev labels today is tight; the label plan (section 5) raises this, and the bootstrap interval
below is how the tightness is shown instead of hidden.

Calibration: the model is already a logistic; check reliability on cross-validated dev predictions and
apply isotonic recalibration only if ECE improves out of fold.

Per-pair uncertainty: refit the fusion model on B = 200 bootstrap resamples of the dev labels; report the
5th-95th percentile of P_fs as the interval shown to users. This interval reflects label scarcity, which is
the dominant source of uncertainty now.

### 4.4 Existence trust

There are almost no negative existence labels (every gold v1 pair returned "exists: yes"), so this is a
transparent checklist, not a learned model: own domain matches name, phone present and not a directory
number shared across 3+ cities (348 such numbers in identity/out_q4c.txt), official, government or news
URL present, duplicate group size, recent page update. Output tier (high, medium, low) with the checklist
shown. It enters ranking only as a tie-break and as a warning, never as a probability we cannot calibrate.

### 4.5 Location trust

Choose the facility point from {stated city, PIN centroid, coordinates} by the geo audit's state_verdict
and d_pin_km: all agree and d_pin_km <= 10 -> coordinates, radius 2 km; odd one out is the coordinates ->
PIN centroid, radius = PIN office spread; all differ -> PIN centroid, location flagged uncertain. L_f =
P(true site within 10 km of the chosen point), set per tier from the geo hand checks
(geo/hand_check_verdicts.csv, 40 rows) and the gold location_matches field, with Wilson intervals.

## 5. Labels, training and leakage control

### 5.1 Label sources, in order of authority

1. Gold pair labels (web verification): model/gold v1 (36 pairs) and v2 (140 pairs), 176 total, split dev
   89 and test 87 by duplicate cluster, chains excluded, test frozen. Labels: confirmed, contradicted,
   no_info, location mismatch. Training and discrimination metrics use confirmed = 1 and contradicted = 0;
   no_info is not a negative and is reported separately as "unverifiable".
   Gap to close: add 120 pairs from the "medium" grade stratum (5,718 rows, the largest and currently
   unsampled) and 40 from chain sites, using the same build_gold_v2.py split rules.
2. Human sentence labels: 600 sentences, double-annotated by two team members with the 4 support classes
   and 3 attribution classes, sampled 50% from tier-C records, 25% from records with anonymous service
   sentences next to anchored other-entity sentences, 25% random. Report Cohen's kappa. Reuse existing
   hand labels as dev only (merge/handcheck q5_tierC_dialysis, q1/q2 holdouts, identity/labels), because
   the audit rules were tuned on them.
3. Teacher labels (training only, never evaluation): databricks-gpt-oss-120b and
   databricks-qwen3-next-80b-a3b-instruct through ai_query with strict JSON schemas.
   - Attribution task, one call per record: input is the identity card (name, city, PIN, type, own domain),
     URL slugs, and all sentences numbered. Output: a list of entities (name, place, evidence sentence ids)
     and an entity id or "generic" per sentence. This is a different question from "does it offer
     dialysis", which llama-3-3-70b answered "yes, confidence 1" on both contaminated records.
   - Support task, batched per (record, service): category per listed sentence id.
   - Verification: every cited id must exist; every entity name must appear verbatim in a cited sentence or
     URL slug; malformed or unverifiable outputs are dropped. Labels where the two teachers agree get
     weight 1, one abstains 0.5, conflicts go to the human queue (the most informative items).
   - Caps: pilot 60 records; then at most 1,500 records for attribution (oversampling tier C and
     geo_conflict) and about 6,000 (record, service) bundles for support, in batches of 500 per day,
     cached by sentence hash, stopped on the first quota warning.
4. Weak labels: verified external lists, when they appear, as positives with match uncertainty. They feed
   the X_fs feature or a separate evaluation, never both for the same rows.

### 5.2 Teacher gate

Before scaling, measure each teacher on 200 human attribution labels and 200 human support labels. Scale only
if accuracy >= 0.80 with Wilson lower bound >= 0.70. Otherwise train attribution calibration (t0..t5) on
human labels only (feasible: 6 parameters) and treat teacher output as one more feature.

### 5.3 Training stages

1. Rules-only v0 (no neural parts): e_i from lexicon plus cue flags, a_i from quarantine. This is baseline
   B1 and the always-shippable fallback.
2. Attribution graph plus calibration (section 3.2) on teacher and human attribution labels.
3. Support student (section 3.3) on teacher support labels plus human labels from the train groups.
4. Fusion fit on dev gold, bootstrap intervals, then a single evaluation on the test split.

### 5.4 Leakage control

- Split unit is a group: the union of identity grp_strong duplicate clusters, shared source_content_id
  (1,324 records share one with another record), and verbatim-shared normalised sentences
  (identity/out/shared_xcity_sentences.csv). All copies of a sentence land in one split.
- Gold test pairs and their groups are excluded from teacher prompts, student training, threshold tuning
  and hyperparameter search. The test set is hashed and frozen before stage 2.
- Teacher prompts never include web evidence, so the student cannot learn from verification text.
- Audit detectors were tuned on their own handcheck samples, so those samples are dev, not test.
- Hyperparameters (graph weights, gamma, thresholds) are tuned with grouped cross-validation on dev.

## 6. Evaluation: metrics, baselines and gates

All metrics carry 95% intervals: Wilson for proportions, group bootstrap (1,000 resamples over duplicate
groups) for AUROC, Brier, ECE and differences.

| Level | Metric | Baselines it must beat |
| --- | --- | --- |
| Sentence support | macro-F1 on human sentences; precision of OFFERS | B-rule: lexicon plus non-offer cues v2; zero-shot NLI; teacher |
| Sentence attribution | AUROC and accuracy on human attribution labels in merged records; recall of "other" among anonymous sentences | B-quarantine: deterministic merge policy |
| Pair trust | AUROC, Brier, log loss, ECE (10 bins) on test gold; precision at P >= 0.7 | B0 any mention; B1 rule grade (strong 0.9, medium 0.6, weak 0.3); B2 ai_query yes/no with self-confidence; ablations without attribution and without fusion contamination terms |
| Location | accuracy of the chosen point within 10 km on geo hand checks plus gold | stated coordinates as given |
| Recommendation | on 40 fixed (service, location) queries across 8 services and rural and urban districts: top-1 confirmed rate, share of top-3 cited sentences a human judges to be about another facility, abstention correctness | B-RAG: keyword or vector match plus distance sort |

Gates and honesty rules:
- A component ships only if it beats its baseline with a paired bootstrap interval excluding 0. With 87
  test pairs an AUROC interval is roughly +/- 0.08 wide; differences smaller than that are reported as
  "not distinguishable", not as wins.
- The headline served-evidence metric is the harmful misattribution rate in cited sentences of top-3
  recommendations (target: below 5%, measured with Wilson interval). For reference, 11 of 30 merge q1
  holdout hits were harmful misattributions before quarantine (Wilson 22-55%).
- The test split is scored once. Every number in the App's model card comes from that run's output file.

## 7. Decision layer (query to ranked options or plan)

Input: service s, a location (PIN, city, district or coordinates), and a mode (patient now, planner).

1. Resolve the location with geo/resolve_input.py logic (PIN directory robust centroids, district and
   office names with aliases); if ambiguous (5 of 40 resolver tests were), show the choices instead of
   guessing.
2. Candidates: facilities with P_fs >= 0.15 within radius R_s (defaults: emergency C-section and trauma 60
   km, dialysis 50 km, NICU and MRI 100 km, cardiac surgery and burns 300 km), widening in steps until 3
   candidates have P_fs >= 0.5 or 2 R_s is reached. Duplicate groups are collapsed to one candidate.
3. Distance: d_f = 1.3 * haversine(query, chosen point). The 1.3 road factor is an assumption, not a
   measurement, and is labelled as such. Location uncertainty adds the location radius to d_f.
4. Utility: U_f = P_fs * L_f * exp(-d_f / D_s), with D_s a stated policy knob (emergency C-section and
   trauma 30 km; dialysis 25 km because it is three trips a week; NICU 60 km; MRI 100 km; cardiac surgery
   and burns 250 km). Rank by U_f.
5. Call plan: order the top candidates by U_f and report
   P(at least one of the first k works) = 1 - prod_{j <= k} (1 - P_j L_j),
   stopping at k where it reaches 0.9 or at k = 5. Independence is assumed across collapsed groups and
   stated on screen; chain siblings are listed as one entry for this computation.
6. Trade-off line: show the nearest candidate with P_fs >= 0.8 next to the top-U candidate whenever they
   differ ("B is 14 km further and 0.86 likely against 0.41 for A").
7. Abstain when no candidate has P_fs >= 0.5 within 2 R_s: say there is no well-evidenced option, list
   the weak ones with their evidence, and recommend calling before travelling.
8. Planner mode: per district, expected count of facilities offering s within R_s, sum of P_fs, and
   P(none) = prod (1 - P_fs) computed exactly as a Poisson-binomial, joined to NFHS-5 district indicators
   through geo/district_nfhs_map.csv, ranked by gap.

## 8. Explanation layer (WHY and HOW)

### 8.1 Recommendation card (community health worker view)

- Headline: "Likely offers dialysis: 82% (range 70-90%)". The range is the bootstrap interval from 4.3.
- WHY it offers: up to 3 evidence units, each with the verbatim sentence, the field it came from, its
  attribution a_u, support e_u and its points c_(k) on a 0-100 scale converted from log-odds. Prerequisite
  and specificity terms are shown as their own lines.
- WHY NOT or caution: excluded sentences with the reason, for example "Not counted: this sentence is about
  another facility. It shares '20-bed' and 'PMNDP' with sentence 31, 'Listed as a Delhi Government
  Hospital...'" (the top K_ij Y_j anchors), plus non-offer sentences, contamination and name-scope
  penalties as negative points, and re-homed links.
- WHERE: which of city, PIN and coordinates agree, and the radius used.
- WHY THIS ONE: the U_f decomposition (likelihood, location trust, distance) and the trade-off line.
- Sources: the record's source URLs grouped by class (official, government, aggregator). The dataset does
  not map sentences to URLs, so the card says "one of these pages" rather than inventing a citation.
- Plain-language mode: templated sentences in English or Hindi with numbers inserted by code. No LLM
  rewrites the card.

### 8.2 HOW page (judges)

Pipeline diagram, the coefficient table with bootstrap intervals, reliability plot, the metric table from
section 6 with baselines and ablations, the teacher gate results, and two worked failures (Aravind, Wockhardt)
showing each layer's output on the real rows.

### 8.3 Faithfulness by construction

- The card reads the same Delta rows the ranking reads; nothing is regenerated at display time.
- Additivity test in the build: for every (facility, service), b + sum of displayed contributions equals
  the logit of the displayed P within 1e-6; the build fails otherwise.
- Leave-one-out test: for 200 random pairs, drop the top unit, rerun the real fusion code, and check that
  the change in logit equals the change implied by the rank-discounted sum (the remaining units move up
  one rank, which the card notes).
- Attribution reasons are the exact K_ij Y_j terms from the propagation, not a separate explainer.
- The neural atom's output is a category for one sentence a reader can check by reading it; atom
  precision is measured against human labels and printed on the HOW page. Optional token highlighting uses
  occlusion through the actual student, so it is also computed, not narrated.

## 9. What is unique compared with a RAG chatbot plus distance sort

- Attribution comes before entailment. A RAG system retrieves "Dialysis unit of 20 beds" and answers yes;
  this system first asks whose unit it is, using the whole record, because 95% of claims cannot answer
  that on their own.
- Negative evidence is first-class: excluded sentences, non-offer mentions and contamination appear with
  their points, so users see why a claim was discounted.
- Probabilities are calibrated on web-verified labels with per-pair intervals; LLM self-confidence is never
  used, and no LLM sits on the trust path at query time.
- Explanations are exact decompositions of the score (rank-discounted additive evidence, linear label
  propagation), not summaries written after the fact.
- The output is a call plan with a stated success probability and a visible distance-versus-evidence
  trade-off, and the system abstains when evidence is weak.
- Re-homing gives provenance across records ("this sentence describes record X").

## 10. Deployment on Free Edition

Offline, Databricks serverless notebooks or jobs on CPU (writes need the build-phase permissions; this
design created nothing):
1. Sentence table, anchors and cues (port audit code) -> Delta.
2. Embeddings for about 287k distinct normalised sentences: bge-small in the notebook if weights can be
   loaded, else gte-large-en via ai_query (about 3.5M tokens, cached by hash).
3. Teacher labelling within the caps in 5.1.
4. Student training on CPU (about 20k short pairs; estimated well under an hour, not run) and inference
   on about 45k pairs.
5. Label propagation per record (at most 161 x 161 matrices, numpy), fusion fit, 200 bootstraps.
6. Delta tables: sentence_evidence (one row per scored sentence: a, e, class, unit id, rank, contribution,
   exclusion reason, top anchors), facility_service_trust (P, interval, contribution vector), facility_location,
   facility_existence, rehome_links, model_card (metrics JSON with intervals).

Live in the App (Streamlit or FastAPI on 2 vCPU, 6 GB): load the compact tables once through the SQL
warehouse (about 80k trust rows and the evidence rows, tens of MB), resolve the location in memory against
19.5k PIN centroids, vectorised haversine over at most 10k points, utility, call plan, card rendering. No
model inference at query time. Optional ai_query only to parse a free-text query into (service, location),
with dropdowns as the fallback.

## 11. GPU

Not needed. The student is 22M parameters on short inputs and trains on CPU. A one-off GPU job (A10)
could train a larger student (deberta-v3-base) as an ablation, but GPU access is unverified, needs LinkedIn
verification, and one forum report describes quota exhaustion after about 5 minutes. Nothing in the
pipeline or the demo depends on it; if it runs, only its output scores land in Delta.

## 12. Risks

- Teacher partitions may be poor (the same model family missed contamination under a different question).
  Mitigation: the gate in 5.2 and a human-only fallback.
- Label scarcity: 87 test pairs give wide intervals; no_info labels shrink the usable set further.
  Mitigation: the medium and chain additions, intervals on everything, pooled constrained fusion.
- Weights for the student may not download on Databricks compute. Mitigation: the embedding probe.
- Daily quota exhaustion stops compute for the day. Mitigation: caching, caps, batches of 500.
- No sentence-to-URL alignment, so citations are to the record's URL set, not a page.
- Anonymous contamination with no anchors and no fingerprints (pure generic sentences) is invisible to the
  graph; only record-level terms (C_f, kappa) catch it, which penalises the whole record including its
  true claims.
- Chain siblings are a policy question (is "the chain's dialysis unit in the same city" a yes?). Proposal:
  count sibling evidence at a learned discount and name the branch on the card. Gold excludes chains, so
  this is not yet measured.
- The call plan assumes independence; correlated errors inside a merged record are only partly handled by
  collapsing duplicate groups.
- Road distance is approximated; rural travel time can be much worse than 1.3 x straight line.

## 13. Weekend build order

Friday night
1. Sentence table, anchors, cues and rare-token fingerprints from the audit code; Delta write. Compute B0
   and B1 so there is a shippable answer from hour one.
2. Freeze the test split hash. Start the web verification sprint for the medium and chain additions and the
   600-sentence human annotation; these run in parallel all weekend.

Saturday
3. Embeddings and the attribution graph with deterministic seeds; tune graph weights on dev attribution
   labels; compare with B-quarantine.
4. Teacher pilot on 60 records; apply the gate; scale within caps if it passes.
5. Fusion v1 using rule-based e_i plus graph a_i; bootstrap intervals; write facility_service_trust.
6. App skeleton: location resolver, ranking, call plan and cards reading the v1 tables.

Sunday
7. Train the support student on CPU; evaluate against rules, zero-shot NLI and teacher on human
   sentences; adopt only if it wins.
8. Recall expansion and re-homing links; fusion v2 and calibration on dev.
9. Single test-set evaluation; model card; additivity and leave-one-out tests in the build.
10. HOW page, the two worked failures, persona demo scripts (Bihar health worker, Maharashtra NGO
    coordinator, district planner), a notebook fallback for judges, and an App restart before judging.

Simplest version that works: steps 1, 3, 5 and 6 without any neural model. Everything after that has to
earn its place on held-out labels.
