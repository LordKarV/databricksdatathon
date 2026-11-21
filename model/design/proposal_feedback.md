# Ledger: a facility trust model that publishes its own track record

Angle: honest track record and active learning. Written 2026-11-21. Everything below is a design;
nothing in it was trained or evaluated yet. Numbers quoted as measured come from the audit outputs
under /Users/karthikvattem/projects/datathon/audit/ or from small read-only queries over them
(denominators given). Anything not run is marked "not run".

## One paragraph summary

Ledger turns each (facility, service) pair into three calibrated probabilities: the facility
exists, it is where the record says, and it offers the service. Each probability is a Bayesian
logistic regression over a few dozen named evidence features, with expert prior weights that the
labels pull away from as they accumulate. Every score is an exact sum of feature contributions, so
the explanation is the computation. Every confidence band carries a public, prospective track
record in the form "of N pairs we verified in this band, k confirmed, c contradicted, u no public
information", with a 95% interval. Active learning ranks which pairs to verify next by how much the answer would change
for real queries, and the App turns the health worker's normal call-ahead into a label. The model
is judged by one end-to-end number: how often the top recommendation, checked by a human, turns out
to exist, be at the stated place, and offer the service.

## What the data says, and the design choices it forces

- Lexicon matching finds on-topic sentences well: core topic precision 196/200 across 8 services
  (audit/claims/out/handcheck_summary.json). So the hard problem is not "does this sentence mention
  dialysis" but "is this sentence about this facility, at this place".
- Attribution and location are the failure modes. 25.0% of records (2,489 / 9,959) carry at least
  one quarantined foreign-facility sentence (audit/merge/out/analyze_stdout.txt); contamination
  rises with the number of distinct source URLs, from 0.042 (0 to 2 URLs, n=333) to 0.596 (30+
  URLs, n=1,840). 1,492 / 9,970 records have some geo conflict; the PIN centroid is more than 128 km
  from the coordinates for 10% of records (90th percentile, n=9,682).
- Web ground truth v1 (36 pairs) splits by internal evidence stratum: strong 10/12 confirmed
  (Wilson 95% 0.55 to 0.95), 0 contradicted; weak 1/12 confirmed (0.01 to 0.35), 3 contradicted,
  8 no public information; suspect 4/12 confirmed (0.14 to 0.61), 4 contradicted, 4 location
  mismatch. Two consequences: the three outcomes (exists, location, service) fail independently, so
  the model should factor them; and "no public information" is common for weak pairs (8/12), so it
  must be treated as censored, not as negative, and a non-web label channel (phone calls) is needed.
- An LLM judge said "dialysis yes, confidence 1" for both known contaminated records. LLM output is
  therefore allowed only as one feature whose weight is learned and whose value is ablated; it is
  never a label and never a confidence.
- Text is effectively English (11 of 10,088 rows contain Indic script,
  research/discover/ml_resources/CANDIDATES.md), so no Indic text model is needed for evidence.
- Records leak into each other. A union-find over strong duplicate groups, official-domain chain
  groups and shared source_content_id (identity/out/dup_groups.csv, merge/out/record_scores.parquet)
  gives 8,524 groups over 9,959 records; 521 groups have more than one record (1,956 records), the
  largest holds 69. Any split that ignores these groups puts copies of the same text in train and
  test.
- Label budget is the binding constraint. A band's Wilson half-width at p=0.8 is 0.21 with n=12,
  0.14 with n=30, 0.10 with n=60 (computed). A weekend can afford a few hundred verified pairs, so
  the design must spend labels where they change answers, and must show the intervals.

## Layer 1: evidence (text to claim atoms)

Unit of evidence: a claim atom = (unique_id, service, field, item index, sentence text). Built from
the existing audit tables, not re-derived:

1. Candidate sentences: service lexicon (audit/claims/services.py, extended with PM-JAY HBP package
   names such as MG072A Haemodialysis, SO057A Caesarean Delivery, BM001 burns, neonatal care
   packages) over procedure, equipment, capability, description and the specialties enum. Output
   today: audit/claims/out/mentions.parquet, 26,041 sentence rows.
2. Cue tags per sentence (already in mentions.parquet): negation, referral, future, partner,
   part-time, camp, past, hedge, named_other, foreign place, list, staff, directory, quantity,
   nonoffer, specific.
3. Attribution tier per sentence from the merge audit (merge/out/sentence_decisions.parquet and the
   tiering in q5_service_stdout.txt): A self-anchored (names the record's own facility), B clean
   record, C merged record, Q quarantined. Q sentences and nonoffer sentences contribute nothing to
   the service score; they are kept and shown under "evidence we ignored, and why".
4. Prerequisite atoms per service (grades.parquet pre_* columns): nephrology and dialysis machine
   for dialysis; obstetrics, operating theatre, anaesthesia for C-section; paediatrics or
   neonatology and incubator, warmer or ventilator for NICU; and so on.
5. Facility-level atoms for existence and location: website class, phone class, source URL count,
   page recency, PIN, coordinates, PIN centroid, stated city and state, geo verdicts
   (geo/facility_geo.parquet), merge location signals (geo/merge_signal.parquet), scale fields
   (scale/scale_flags.parquet).
6. Optional atom, LLM attribution: one batched ai_query pass over the 26,041 mention sentences with
   a strict schema {offered_here | other_facility | generic_or_nonoffer}, given the record's name,
   city and PIN. Stored as a feature with a learned weight. Shipped only if the grouped-CV ablation
   shows a Brier improvement whose bootstrap interval excludes zero. Not run.

Every atom keeps a pointer (unique_id, field, index) back to the raw text, so every number on a
card can cite the sentence or field it came from.

## Layer 2: fusion (atoms to calibrated probabilities)

### Factorisation

For facility f and service s:

    P_usable(f, s) = P_E(f) * P_L(f) * P_S(f, s)

- P_E: the facility exists and is operating (label: web "exists", call "reached facility").
- P_L: the facility is at its primary location (label: web "location_matches", call "confirmed
  address or landmark").
- P_S: it offers service s, given it exists (label: web "service confirmed or contradicted", call
  "yes or no").

The factorisation matches the verification protocol already used in audit/ground_truth (three
separate fields per pair), so each head gets its own labels and its own track record, and the user
sees which of the three is weak. "no_info" and "unclear" outcomes are censored for the head they
concern and are never coded as 0.

### Each head is a Bayesian logistic regression with informative priors

    logit P_h(i) = b_h + sum_j w_hj * x_ij,      w_h ~ N(mu_h, diag(sigma_h^2))

Fit by MAP with Newton's method (about 30 lines of numpy; no new dependency). The penalty is
(w - mu)' Lambda (w - mu), so with no labels the model equals the expert prior, and each label moves
it. Laplace posterior: w ~ N(w_hat, Sigma), Sigma = inverse Hessian at w_hat.

For pair i: mean logit m_i = x_i' w_hat, variance v_i = x_i' Sigma x_i. Reported probability uses
MacKay's moderated output p_i = sigmoid(m_i / sqrt(1 + pi * v_i / 8)); the 95% credible interval
is sigmoid(m_i +- 1.96 * sqrt(v_i)). A pair whose features are rare (few labels nearby) gets a wide
interval even if its point estimate is high. This is the model's own uncertainty; the band track
record (layer 4) is the empirical check on it.

Sharing across services (P_S only): each service feature appears twice, a shared copy with prior
N(mu_j, 1) and a service-specific copy with prior N(0, 0.5^2). A dialysis label then teaches the
shared weight "two independent fields agree" that NICU also uses, while services can still differ.
About 15 shared + 15 x 8 specific + 8 intercepts + 5 facility-type terms, roughly 150 parameters;
the Hessian is 150 x 150.

Prior means mu are set in log-odds "points" before any test label is seen, written to a dated
config file, and derived from measured audit rates where one exists (examples below). Sign flips
between prior and posterior are not blocked; they are listed on the model card as findings.

### Features

Service head P_S (pair level, mostly grades.parquet columns, after Q and nonoffer removal):

| feature | definition | prior sign | grounding |
| --- | --- | --- | --- |
| log1p(n_own_specific) | attributable, specific mention sentences (tiers A, B, C) | + | |
| n_fields_own (cap 3) | distinct fields among procedure, equipment, capability, description | + | 2+ fields: strong stratum 10/12 confirmed |
| tier_A_any | at least one self-anchored sentence | + | |
| prereq_frac | share of the service's clinical prerequisites present | + | |
| has_qty | a count ("12 dialysis machines", "20-bed NICU") | + | 103 dialysis facilities |
| enum_hit | specialty enum contains the service | + small | 302 cardiac and 484 ICU pairs are enum-only |
| enum_only | enum hit with no text | - | |
| nonoffer_any | negation, referral, camp, future sentence | - | nonoffer_v2 precision 34/40 |
| named_other_share | share of mentions naming another facility | - small | named_other_v3 precision only 9/40, so weak |
| scope_conflict | eye, dental, IVF centre claiming a tertiary service | - | 129 eye centres claim one of 8 services |
| q_share | record share of quarantined sentences | - | |
| url_bin | distinct source URLs bin | - | contamination 0.042 to 0.596 |
| shared_content | source_content_id shared with other records | - | contamination 0.397 vs 0.227 |
| log1p(beds), log1p(doctors), facility type | scale | + | |
| scale_contradiction | e.g. clinic with 100+ beds (20 of 124 clinics with capacity) | - | |
| external_list | on a verified government or registry list for s | + | when research/ produces one |
| llm_attr | optional LLM attribution verdict | learned | ablated |

Existence head P_E (facility level): website class (own domain with name match 6,327 / 7,914, own
domain without match, government portal, directory or host, none 1,602); phone class (mobile 7,113,
landline 1,966, shared across 3+ cities 348, none 495, tollfree, invalid); log distinct source URLs
and source ids; page recency year (present for 3,532 / 9,970); coordinate shared by 3+ distinct
names; OSM (HOTOSM, ODbL) name match within 2 km and NIN directory match when ingested.

Location head P_L (facility level): state_verdict category (all_agree 9,451; odd_one_out coord 91,
stated 45, pin 15; split 9); log1p(d_pin_km); city matches PIN, nearby only, or neither (1,177);
PIN in directory; source URLs spanning several cities (2,138); text naming another postal
district's PIN (92); foreign-city sentence share; a_geo_copy.

### Direct evidence from verification overrides the model for that pair, transparently

A verification report r on pair i adds a likelihood ratio:

    logit P'(i) = logit P_model(i) + sum_r d(t_r) * [ y_r * log(sens_r / (1 - spec_r))
                                                  + (1 - y_r) * log((1 - sens_r) / spec_r) ]
    d(t) = 2 ^ (-age_days / 180)

Web verification by the team gets sens = spec = 0.9 (one confirmation adds log 9 = 2.2 logits).
A health worker's call outcome starts at sens = spec = 0.85 with a Beta(17, 3) prior and is updated
by agreement with web checks and with other reporters (Dawid-Skene EM once a reporter has 5+
overlapping reports). The 180-day half-life encodes that services start and stop. Call outcomes
"no answer" and "wrong number" do not touch P_S; "wrong number" lowers the phone feature, "closed"
is a negative label for P_E. The card shows each report and its log-odds effect, so the override is
part of the same additive explanation.

## Layer 3: decision (query to ranked options or a plan)

Input: service from a fixed menu (synonyms and Hindi labels map to it; no LLM needed) and a
location (PIN, district, city, coordinates, or a place name). Location resolution reuses
audit/geo/resolve_input.py and the robust PIN centroids (19,584 PINs). On the 40 test cases it
resolves 38 with aliases and flags 5 as ambiguous (geo/resolve_stats.json); ambiguous names are
shown to the user as a choice, never silently picked.

Location mixture. Each facility has a primary point (coordinates, or the PIN centroid when
state_verdict marks the coordinates as the odd one out) and, if the two are more than 25 km apart,
an alternate point. The primary point gets weight pi = P_L; the alternate gets 1 - P_L; with no
alternate, the rest is "location unknown" and contributes nothing.

Utility for query q:

    U(f | q) = P_E(f) * P_S(f, s) * [ P_L(f) * g_s(d_primary) + (1 - P_L(f)) * g_s(d_alt) ]
    g_s(d) = exp(-d / d0_s),   d = 1.3 * haversine_km

d0_s is a policy choice, not learned, and is shown on the "how" page: emergency C-section 25 km,
trauma 25, NICU 40, dialysis 30 (three sessions a week), burns 60, MRI 80, cardiac surgery 150. The
1.3 circuity factor is an assumption, labelled as straight-line distance times 1.3, not travel time.
The user can set a hard radius.

Outputs per query:

- Ranked list (top 3 by U), plus the nearest candidate with any mention even if it ranks low, so the
  trade-off is visible ("B is 12 km away but its only evidence is one capability line in a record
  whose PIN is in another state; expected success 0.21", illustrative numbers).
- Call plan: call in rank order; P(at least one of the top 3 confirms) = 1 - prod(1 - P_usable_i),
  where pairs in the same leakage group count once (take the max), since chain branches fail
  together.
- Abstention: if no candidate within the radius has P_usable >= 0.35 (bottom of band C), the answer
  says so, lists the best weak leads as leads, and adds the IPHS default ("haemodialysis and
  caesarean section are essential services at a district hospital") marked as a standard, not
  evidence from this data.
- Planner view: per district, expected count of usable facilities E = sum_i P_usable(i) within d0_s
  of the district centroid, its variance sum p(1-p), next to NFHS indicators
  (births_delivered_by_csection_5y_pct, institutional_birth_5y_pct). Districts with E < 1 and wide
  variance are the ones where verification, not building, is the next action; the planner gets the
  active-learning queue filtered to that district.

## Layer 4: explanation (what the user and the judges see)

Per recommendation card (all values read from the scored row, nothing generated). The numbers in
the examples below are illustrative placeholders showing the format, not results:

1. Verdict line: "Probably offers dialysis (band B). Exists 0.96 x at this address 0.83 x offers
   dialysis 0.88 = 0.70."
2. Quoted evidence: the top 3 attributable sentences, each with field, attribution tier and source
   URL list, then "evidence we ignored" (quarantined, named another facility, nonoffer) with the
   reason.
3. Points table: each feature's contribution w_j * x_ij in log-odds (shown as points, 1 point =
   1 log-odd), the intercept, and the total, which equals the logit. Verification reports appear as
   rows with their date and effect.
4. Track record of the band, per service where n allows, else pooled: "Of 31 pairs we verified that
   scored 0.60 to 0.80, 24 were confirmed (77%, 95% CI 60 to 89%), 3 contradicted, 4 had no public
   information." Before the sealed test is labelled, the card shows the 36-pair dev figures marked
   "design sample, small".
5. Location warnings quoted from fields: "PIN 110002 is in Delhi; coordinates are in Puducherry;
   city says Hyderabad."
6. Ranking reason: "Ranked 1st: 0.70 x exp(-18/30) = 0.38. 2nd: 0.86 x exp(-41/30) = 0.22."
7. What would change the answer: "If a call confirms Facility B, it becomes 1st." Computed by
   re-running U with B's report applied. This is also the active-learning hint: the App puts a
   "most useful call" marker on the pair with the highest acquisition value in this answer.
8. Call-ahead: phone with its class ("shared with facilities in 3+ cities, may be a booking line"),
   and buttons "called: offers it / does not / no answer / wrong number / closed".

Global "how we decided" page for judges: the funnel (10,088 rows, 9,970 well formed, 26,041 mention
sentences, quarantine and cue filtering, candidate pairs per service, scored, banded); the three
heads' weights with posterior 95% intervals and their prior means; label counts by source and
split; reliability diagram and band table on the sealed test; benchmark results against baselines
with paired bootstrap intervals; learning curve; model version changelog.

### Faithfulness, enforced by checks in the build

- assert |b + sum_j contrib_j + sum_r report_effect_r - logit| < 1e-9 for every row before writing.
- Every sentence quoted as supporting evidence exists in claim_atoms with used = true; ignored
  sentences appear only under "ignored".
- The App recomputes rank order from the displayed numbers and refuses to render if it differs.
- Track-record figures are queried from the labels table at render time, never hard-coded.
- If an LLM rephrases a card into Hindi or plain English, every number in its output must appear in
  the structured input; otherwise the template text is shown. Default is templates only.

## Labels: where they come from and how leakage is avoided

Label sources, by trust:

1. Web verification by the team (protocol in audit/ground_truth: name, city and service queries
   only, max 4 lookups per pair, three outcome fields, evidence URLs). Gold for training and test.
2. Call-ahead outcomes from App users. Gold-ish for training after reliability weighting; never in
   the sealed test; reporter identity stored as a salted hash, no personal data.
3. External lists (government dialysis lists, NHP 2015 specializations, HOTOSM, NIN directory):
   features, not labels. If a list were both a feature and a label the score would grade itself.
   The test report includes accuracy on pairs with no external match, to show the model is not
   echoing a list.
4. LLM outputs: feature only.
5. Audit hand checks (sentence-level precisions above): used only to set prior means.

Splits:

- Grouping: every split is by the leakage group defined above (8,524 groups), so duplicate records,
  chain branches sharing a domain and records sharing scraped content never straddle train and
  test.
- Sealed test T: drawn once by a seeded script before any weight is fitted, stratified by service
  (6 demo services) x prior band (4) x region, with known inclusion probabilities; target 120 pairs
  (5 per cell). The sorted ID list and its SHA-256 are written before labelling. T is never used for
  fitting, prior choice, band cut points, d0, or thresholds. Metrics on T are reweighted by stratum
  pool sizes to estimate population values (for example dialysis pools: strong 305, weak 22,
  suspect 140, from ground_truth/sample_stats.json).
- Held-out states H: Bihar, Jharkhand, Odisha, Assam, Chhattisgarh. No pair from H enters training
  or the active-learning queue before submission; T reports H and non-H separately. Bihar has only
  260 facilities and, for example, 19 strong and 18 medium dialysis pairs (measured), so H metrics
  will have wide intervals and are reported as such.
- Dev D: the 36 existing pairs (they informed the stratum design, so they cannot be test) plus all
  active-learning rounds. Model selection (feature set, prior variances) uses 5-fold GroupKFold on D.
- Prospective log: every time a pair is sent for verification or shown on a card, the model version
  and its p at that moment are logged. Track records compare that logged p with the later outcome,
  so they are out-of-sample by construction.

## Active learning: which pairs to verify next

Goal: reduce uncertainty in the answers users will actually see, not uncertainty in general.

1. Query distribution Q: every district centroid (554 districts with facilities) x 8 services,
   weighted uniformly at first, then by logged App query counts; an NFHS need tilt is optional.
2. Exposure: draw S = 200 weight vectors from the Laplace posterior, rank candidates for every query,
   and set e_i = sum_q pi_q * Pr_draws(i in top 2 for q). Only pairs that might be shown matter.
3. Acquisition for pair i:

        a_i = e_i * p_i * (1 - p_i)  +  lambda * 0.5 * log(1 + p_i * (1 - p_i) * v_i)

   The first term is the direct value: users see i and we are unsure about it. The second is the
   exact Laplace information gain about the weights from one label (rank-one update of the
   precision matrix), which is what makes one label improve thousands of unlabelled pairs.
4. Batch: pick greedily; after each pick, apply the Sherman-Morrison update
   Sigma <- Sigma - c Sigma x x' Sigma / (1 + c x' Sigma x), c = p(1-p), and recompute v for the
   rest. This spreads a batch across feature space for free. At most one pair per leakage group per
   batch.
5. Budget split: 70% of each round goes to the acquisition queue (training only), 30% to a random
   audit stream sampled by band with recorded inclusion probabilities. The track record uses T plus
   the audit stream; the acquisition stream, which over-samples hard cases, is reported separately
   with inverse-probability weights and is never mixed into band precision unweighted.
6. In the App, the call plan already asks the health worker to call the top option; the "most useful
   call" marker points at the pair with the highest a_i in that answer when it differs. Each call
   both helps the user today and becomes a label.
7. Refit: a serverless notebook reads labels, refits the three heads (seconds), writes new scores
   with a new model_version, recomputes the queue and the track record.

Experiment that shows "improves with use" honestly: on the labelled pool, replay labels in
acquisition order and in random order, refitting after each 10, and plot Brier on T against labels
used, starting from 0 labels (pure prior). Paired bootstrap over T for the gap. No synthetic
feedback is generated; call outcomes count only if real.

## Evaluation: metrics, baselines, targets

Pair level, on T: Brier score (primary), log loss, AUROC on confirmed vs contradicted, ECE over the
4 bands, band precision with Wilson intervals, coverage at precision >= 0.8. Inter-rater check:
20% of T labelled twice, Cohen's kappa reported; a low kappa caps what any model can show.

End-to-end benchmark B (the headline):

- 40 queries frozen before systems are run: half sampled from NFHS districts weighted by need,
  a quarter persona-driven (rural Bihar PINs, Maharashtra district headquarters for an NGO, a
  district planner's whole district), a quarter metros.
- Pooled judgement as in TREC: run every system, pool the top 2 of each, verify each pooled pair
  once with the web protocol (and a call where possible). Unjudged pairs count as not verified.
- Metrics: TVR@1 = share of queries whose top-1 is verified usable (exists, at location, offers
  service); Unsafe@1 = top-1 contradicted or at the wrong place; TVR any in top 3; abstention
  precision (when the system abstains, no verified option within 2 x d0 in the pool); distance
  regret against the nearest verified option in the pool. Differences by paired bootstrap over
  queries, 10,000 resamples, 95% intervals.
- Baselines: B0 keyword mention + distance sort (the RAG chatbot answer); B1 LLM judge
  (llama-3-3-70b via ai_query, yes with confidence >= 0.8) + distance; B2 audit rule grade
  (strong > medium > weak) + distance; B3 Ledger with prior weights only; B4 Ledger fitted.
- Pass criteria set now: B4 beats B0 and B1 on TVR@1 and on Unsafe@1 with intervals on the
  difference excluding zero; B4 has lower Brier than B3 on T. If a criterion fails it is reported
  as failed.
- Contamination stress test: the share of queries where each system puts a known contaminated or
  suspect-stratum record (for example "Aravind Eye Hospital" with the Delhi dialysis sentence,
  "Wockhardt Hospital Nagpur" with the S L Raheja sentence) at rank 1.
- Ablations on dev CV: drop each feature group, report the Brier change.

Not run: all of the above. Expected cost: about 40 queries x up to 10 pooled pairs, with overlap
perhaps 150 to 250 verifications, plus 120 for T.

## Why this is not a RAG chatbot with a distance sort

- The score is a calibrated, factorised probability whose band carries a prospective,
  out-of-sample track record with intervals; a chatbot shows retrieval similarity or LLM
  self-confidence, which said 1.0 on contaminated records here.
- Attribution and location are modelled explicitly (quarantine tiers, geo verdicts, location
  mixture), which addresses the failures the audit measured; retrieval treats all text as the
  facility's own.
- "No public information" is kept as its own outcome and fed by a non-web channel (calls), instead
  of being read as yes or no.
- Labels are spent by value of information for real queries, and the health worker's call-ahead is
  the labelling step; the system improves with use and shows the learning curve.
- Evaluation is leakage-aware (grouped by duplicates and chains, held-out states, sealed test,
  pooled end-to-end judgements), with pass criteria fixed before results.
- The explanation is the arithmetic: points that sum to the logit, a product of three heads, a
  utility with a stated distance decay.

## Deployment on Free Edition

Precomputed Delta tables (written by serverless notebooks; sizes estimated from current outputs):

| table | grain | rows (approx) |
| --- | --- | --- |
| claim_atoms | sentence x service, with cues, tier, used flag, raw pointer | 26k |
| facility_features | facility, existence and location features, location candidates | 10k |
| pair_scores | pair, p_E, p_L, p_S, intervals, band, contrib_* columns, model_version | 11k |
| labels | pair, source, outcome per head, date, reporter hash, split, inclusion prob | hundreds |
| feedback_events | App call outcomes (append only) | grows |
| prediction_log | pair, model_version, p at time shown or sent | grows |
| track_record | model_version, band, service, n, confirmed, contradicted, no_info, Wilson | small |
| al_queue | pair, a_i, e_i, info gain, reason | 11k |
| model_card | head, feature, prior mean, posterior mean, interval | ~200 |
| benchmark | query, system, rank, pair, judgement | ~500 |

The App (Streamlit, 2 vCPU, 6 GB) loads pair_scores, facility_features and PIN centroids into
memory at start (well under 100 MB) and computes live only: location resolution, haversine to all
candidates for the chosen service (at most 3,606 pairs, trauma), utility, ranking, call plan,
counterfactual re-rank, and card rendering from stored columns. It writes one row per call outcome
to feedback_events through the SQL warehouse. No model endpoint, no GPU, no LLM on the request
path. Refit and queue recompute are a manually triggered serverless notebook (seconds of compute),
which fits the daily quota and the 5-concurrent-task job limit. Judges must be workspace users and
the App auto-stops after 24 h, so the demo script restarts it before judging.

## GPU

Not needed, and the plan does not depend on it. The only candidate use is a one-off fine-tune of a
small NLI cross-encoder (deberta-v3-small, 142M) for sentence attribution, trained on silver labels
(merge tiers plus adjudicated LLM disagreements), scored once over the 26,041 mention sentences and
written to Delta as the llm_attr feature. Lexicon on-topic precision is already 196/200 and the
remaining errors are record-level and location-level, so the expected gain is small; the same
feature can come from one batched ai_query pass on the pay-per-token endpoints. GPU access is unverified
(research/gpu/GPU.md). Run it only if access is confirmed and the CPU version passes its ablation.

## Risks

- Label scarcity: 120 test pairs gives per-band half-widths near 0.15; per-service bands will often
  be too small and fall back to pooled figures, which the card says.
- Selection bias: acquisition over-samples uncertain pairs; handled by the separate random audit
  stream and inverse-probability weights, but the weights are only as good as the logged inclusion
  probabilities.
- Censoring bias: dropping "no_info" from P_S training favours facilities with a web presence; call
  outcomes are the correction, and their absence in the weekend is a known gap.
- Label noise: web checks rely on a small model summarising pages; kappa on the double-labelled
  20% measures it.
- Feedback noise or gaming: per-reporter reliability, one report per reporter per pair per 30 days,
  feedback never in T.
- Drift: services open and close; the 180-day decay is a guess and is stated as one.
- Correlated failures: chain branches share text and fail together; the call-plan probability
  merges same-group pairs, but other correlations remain.
- Distance: straight line times 1.3, not travel time; rivers and hills break it.
- Prior misspecification: expert priors dominate at low n; the B3 vs B4 comparison and sign-flip
  list expose it.
- Phones: 495 records have no phone and 348 share one across 3+ cities, so the call loop cannot
  reach every pair.
- Held-out states slow learning where the persona lives; H is released into the queue after the
  submission freeze.

## Build order for a weekend

Saturday morning
1. Freeze: seeded script draws T (120 pairs) and benchmark B (40 queries); write ID lists and
   SHA-256. Start web labelling of T in parallel (agents, protocol from audit/ground_truth).
2. Build claim_atoms and facility_features from audit tables; leakage groups by union-find.
3. Write prior means config (dated) from audit rates.

Saturday afternoon
4. Three heads: numpy MAP plus Laplace, moderated output, contributions, sum assertion; grouped CV
   on D (36 pairs plus round 1).
5. Baselines B0 to B2 (B1 needs one capped ai_query batch).
6. Active learning rounds 1 and 2: 30 pairs each, 70/30 acquisition and audit split; refit after
   each.

Sunday morning
7. Write the Delta tables; App: query form, ranked cards with points table, band track record,
   call plan, call-ahead buttons writing to feedback_events, planner district view.
8. Run all systems on B, pool top 2, label pooled pairs.

Sunday afternoon
9. Final metrics on T (overall and held-out states) and B with bootstrap intervals, learning curve,
   ablations, contamination stress test; model card page.
10. Demo script: a community health worker in rural Bihar (dialysis near a PIN), an NGO coordinator
    in Maharashtra (NICU across a district), a district planner (C-section coverage gaps and the
    verification queue).

Cut list if time runs out, in this order: LLM attribution feature, planner view, held-out-state
report (keep T overall), second active-learning round. Never cut: sealed test, grouped splits,
three-outcome labels, the sum assertion, intervals on every rate.
