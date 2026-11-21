# Proposal: evidence fusion with learned source reliability

Angle: every piece of evidence about a facility (a sentence type, a structured field, an external list, a
location source) is a noisy witness. We learn how often each kind of witness is right, from how witnesses
agree across 9,959 facilities, anchor that with a small web-checked gold set, and add the weights up. The
sum of weights is the score, so the explanation shown to the user is the computation itself.

Status: design only. Nothing here has been built or run except the measurements cited, which come from the
audit outputs listed in each section or from read-only duckdb queries over those files.

## 1. What the data forces on the design

These measured facts decide most of the architecture. Each one changes something in the seed idea.

1. Sentences carry no per-sentence provenance. `source_urls` is a record-level list (median 8 URLs,
   90th percentile 50; audit/provenance/q1_results.json). So a reliability table of the form "capability
   sentences from research-paper sources are right X%" cannot be estimated directly: we never know which
   URL a sentence came from. What we can measure is record context, and it is strongly predictive.
   Records with fewer than 3 distinct URLs have a contamination rate of 4.2%; 3 to 7 URLs 8.4%; 8 to 14
   URLs 22.3%; 15 to 29 URLs 41.5%; 30 or more URLs 59.6% (audit/merge/out/analyze_stdout.txt, Q4,
   denominator 9,959 records). Design consequence: source reliability is learned per evidence type and
   per record merge-risk bucket, not per URL.

2. Fields are not independent witnesses. Procedure, capability and equipment lists were extracted by
   one LLM from one page bundle. For dialysis, 53% of facilities with a clean procedure mention also have
   a capability mention (375/704) versus 2.1% of those without (193/9,255); this lift is partly true
   signal and partly shared extraction, and the two cannot be separated without labels. Treating each
   field as an independent Dawid-Skene annotator would double count. Design consequence: fields are
   collapsed into one ordinal "text family" variable, and families are chosen so that conditional
   independence is plausible (Section 4.2).

3. A constant voter is a prior, not evidence. An IPHS rule such as "a district hospital must offer
   dialysis" votes yes for every district hospital, whatever the truth, so its likelihood ratio is 1 and
   Dawid-Skene cannot learn its accuracy. Design consequence: policy standards enter as a class prior by
   facility level, with the realisation rate learned from the data (Section 4.2.4). Coverage is small:
   by name regex, 57 records look like district or civil hospitals, 14 sub-divisional, 7 CHC, 11 PHC and
   187 medical colleges; `operatorTypeId` is public for 469 of 9,970 rows.

4. LLM confidence is not trust. ai_query with llama-3-3-70b answered "offers dialysis, confidence 1" for
   both known contaminated records. Design consequence: no LLM output is ever used as a trust score. An
   LLM may be used once, offline, as a sentence-role classifier, and its accuracy is measured and enters
   the reliability table like any other witness.

5. Contamination can be self-consistent. "Wockhardt Hospital Nagpur" (3ac5ae50) has PIN 400078 and
   coordinates in Mumbai Suburban, so the geo audit marks it `state_verdict = all_agree` and
   `geo_conflict = False`. Its dialysis grade in audit/claims/out/grades.parquet is "strong" with 3 own
   fields, yet 2 of its 4 dialysis sentences say "Provides dialysis treatment at Nair Hospital, Mumbai
   Central". Its record has q_share 0.22 and shares source content with other records. Only the name and
   the stated city ("Nagpur") dissent. Design consequence: the name-embedded place is a location witness,
   and a sentence naming another facility is removed from the facility's own evidence before scoring.
   The rule grade alone gets this case wrong.

6. Rule cues vary widely in precision, and we have hand-check numbers for them
   (audit/claims/out/handcheck_summary.json): core topic match 196/200 (Wilson 95% 0.95 to 0.99);
   non-offer cue v2 34/40 (0.71 to 0.93); "names another facility" cue v3 9/40 (0.12 to 0.38);
   cross-state place cue 8/14 (0.33 to 0.79). Design consequence: these hand-check precisions become an
   external check on the learned reliability table (Section 8.4), and the weakest cue (named-other, 9/40)
   is the main target for a better sentence-role classifier.

7. Internal corroboration predicts web truth, with tiny n (audit/ground_truth, 36 pairs). Strong stratum:
   10/12 confirmed (0.55 to 0.95), 0/12 contradicted (0.00 to 0.24). Weak stratum: 1/12 confirmed (0.01
   to 0.35), 3/12 contradicted, 8/12 no_info. Suspect stratum: 4/12 confirmed (0.14 to 0.61), 4/12
   contradicted. Design consequence: the gold target is "publicly verifiable that this facility offers
   it", no_info is a real outcome to model, and the 36 pairs are too few to test on. They become dev
   data; a new test sample is drawn after the model is frozen (Section 7).

8. Location witnesses disagree in a measurable pattern. Of 9,970 records, 9,451 have stated state, PIN
   state and coordinate state all agreeing; when exactly one disagrees, it is the coordinates 91 times,
   the stated state 45 times and the PIN 15 times (audit/geo/facility_geo_stats.json). Of the 9,451
   all-agree records, 1,097 have a stated city that matches neither the PIN district nor the nearest
   post office. Design consequence: location is inferred by truth discovery over several witnesses, with
   learned witness reliability, and it produces a probability, not a single point.

## 2. Architecture at a glance

```
raw facilities.parquet (10,088 rows) + audit outputs + external lists
        |
 [1 Evidence]  sentence -> claim atom (facility, service, field, role, ownership, place, text, id)
        |      family values per (facility, service); location witnesses per facility
        |
 [2 Fusion]    three latent variables per facility f and service s:
        |        Y_fs  offers service s          (semi-supervised Dawid-Skene + additive prior)
        |        E_f   exists and operates       (same machinery, smaller)
        |        D_f   true district / point     (truth discovery over location witnesses)
        |      -> calibrated p, interval [p_lo, p_hi], label, per-term contributions
        |
 [3 Decision]  query (service, place) -> candidate set -> P(success) x distance discount
        |      -> ranked options, a backup plan, or an explicit "no verified option within R"
        |
 [4 Explanation] per card: quoted sentences, rejected sentences, points waterfall, location witnesses
                 global: reliability table, prior shape plots, decision formula, metrics with CIs
```

Everything in layers 1 and 2 is precomputed into Delta tables. The App computes layer 3 live and renders
layer 4 from stored contributions. No model inference and no LLM call is needed at query time.

Unit of analysis: pair i = (f, s), f over 9,959 facilities after exact unique_id dedup, s over 8
services (dialysis, emergency C-section, NICU, cardiac surgery, MRI, burns, trauma, ICU). That is 79,672
pairs, of which 9,588 have at least one clean text mention (measured on audit/claims/out/mentions.parquet
excluding foreign, named-other and non-offer sentences). The service list extends by adding lexicon rows.

## 3. Evidence layer (text to claims)

### 3.1 Claim atoms

One row per (facility, service, sentence) with:

- `sentence_id` = (unique_id, field, idx), matching audit/merge/out/sentence_decisions.parquet, and the
  verbatim text. Every claim shown in the App is this string, looked up by id.
- `field` in {procedure, capability, equipment, specialties, description}.
- `service_match`: lexicon hit (topic precision 196/200 on the 8 services) plus PM-JAY HBP procedure
  names (HBP 2.1: 1,669 procedure codes, e.g. MG072A haemodialysis, SO057A caesarean delivery, BM001A to D
  burns) as extra synonyms. Recall check: embed the 288,493 unique claim strings once (local
  multilingual-e5-small or the hosted databricks-gte-large-en, offline) and hand-review the top 200
  non-lexicon neighbours of each service centroid; add true synonyms to the lexicon. The lexicon, not
  the embedding, decides the match, so the match is inspectable.
- `role` in {offer, equipment_or_unit, staff_or_department, quantity, referral_or_negation,
  future_or_camp, list_or_directory, hedge}: from the claims audit cues (mentions.parquet columns
  negation, referral, future, camp, parttime, staff, directory, is_list, qty, hedge, nonoffer).
- `ownership` in {own_anchored, unnamed, other_named, foreign_place, quarantined}: own_anchored when the
  sentence names the facility itself (33,581 such sentences exist, merge audit Q5), quarantined from
  sentence_decisions (9,506 of 469,498 sentences, 2.0%), other_named and foreign_place from the cue
  columns.
- `specificity`: names a unit ("Dialysis Unit"), states a quantity ("12 machines"), or is generic.

Optional offline upgrade (Section 12): a sentence-role classifier for the 26,041 service-mention
sentences that answers "does this sentence describe facility NAME, a different named facility, a
doctor's credential, or a referral?". Its output replaces the named-other cue only if it beats 9/40 on a
hand-labelled sentence set.

### 3.2 Family values per pair

Families are groups of evidence that come from the same extraction act. Within a family, values are
ordinal and mutually exclusive, so a family casts exactly one vote per pair.

| family | values (ordinal) | source |
| --- | --- | --- |
| T text_own | 0 none; 1 list or specialty-name only; 2 one own sentence, one field; 3 two or more own sentences, one field; 4 two or more fields; 5 two or more fields plus a unit or quantity | claim atoms with ownership in {own_anchored, unnamed}, role in {offer, equipment_or_unit, quantity} |
| C contamination | 0 no foreign support; 1 foreign support alongside own; 2 only foreign or quarantined support | ownership in {other_named, foreign_place, quarantined} |
| N negation | 0 none; 1 a non-offer, referral or future sentence about s | role in {referral_or_negation, future_or_camp} |
| S scope | 0 consistent; 1 facility category conflicts with s (eye, dental, IVF, lab claiming dialysis, cardiac surgery, NICU) | claims audit scope_conflict, name and facilityTypeId |
| P prerequisites | 0, 1, 2+ clinical prerequisites present (nephrology and dialysis machine for dialysis; obstetrics, operating theatre, anaesthesia for C-section; and so on) | grades.parquet pre_* flags |
| X external | 1 on list; 0 in list scope but absent; abstain outside scope | OSM, NIN directory, NHP 2015 specializations, PMNDP dialysis and SNCU lists when acquired |
| R sentence-role model (optional) | 0, 1, 2 own-offer sentences confirmed by the classifier | offline classifier, Section 12 |

Two context variables are not votes:

- merge-risk bucket g in {low, mid, high}: low = no quarantined sentence and fewer than 8 distinct URLs;
  high = q_share >= 0.10 or 30+ URLs or shared source_content_id; mid otherwise. Inputs from
  audit/merge/out/record_scores.parquet. A separate flag marks records whose lists hit the 50-item cap
  (1,789 of 9,970 rows), because "no mention" means less there.
- prior features x_f (Section 4.2.4).

Location witnesses per facility: PIN centroid district, coordinate district, stated city (resolved
through the PIN directory with homonym handling; 16 district names exist in more than one state),
stated state, place token in the facility name, address lines, PINs found in text, cities in source URLs,
and OSM match coordinates when available. Each witness reports a district (and a point where it has one).

Existence witnesses per facility: own website domain matches name; official phone unique versus shared
by 3+ cities (348 such numbers, e.g. one proptiger number on 87 records, identity out_q4c); number of
distinct source_ids; page recency; OSM or NIN match within 1 km with fuzzy name >= 90; non-facility flags
(veterinary 13, pharmacy 12, scale audit).

## 4. Fusion layer (claims to calibrated probabilities)

### 4.1 Latent variables

- Y_fs in {0, 1}: facility f offers service s, in the sense "a public web check would confirm it".
- E_f in {0, 1}: f is a real, operating facility (not a directory artefact, not a duplicate shell).
- D_f: the district (with a point) where f actually is.

They are fitted separately and combined in the decision layer. Fitting them jointly is possible but
would make the explanation harder to read for little expected gain.

### 4.2 Service model: semi-supervised hierarchical Dawid-Skene with an additive prior

#### 4.2.1 Generative model

For pair i = (f, s) with families k = 1..K, observed value v_ik (or abstain), bucket g = g(f):

```
P(Y_i = 1 | x_f)                    = sigmoid(eta_s(x_f))                      (prior, Section 4.2.4)
P(v_ik = v | Y_i = c, g, s)         = theta[k, s, g, c](v)                     (witness reliability)
families conditionally independent given (Y_i, g, s)
```

Posterior log-odds, which is the score:

```
z_i = eta_s(x_f) + sum over non-abstaining k of  w[k, s, g](v_ik)
w[k, s, g](v) = log theta[k, s, g, 1](v) - log theta[k, s, g, 0](v)          (weight of evidence)
q_i = sigmoid(z_i)
```

This is a naive-Bayes form, so the posterior is exactly additive in log-odds. Each w is a learned
likelihood ratio with a plain reading: "evidence of this kind appears X times more often at facilities
that offer the service than at those that do not, on records of this merge-risk level".

#### 4.2.2 Estimation (EM with gold clamping)

```
init     q_i from majority vote of families, or from the claims audit grade
repeat
  E-step q_i = sigmoid(z_i)            for unlabelled pairs
         q_i = y_i                      for gold pairs in the training folds (clamped)
  M-step theta[k,s,g,c](v) = ( sum_i r_ic 1[v_ik = v] + a * m[k,g,c](v) )
                             / ( sum_i r_ic 1[v_ik != abstain] + a )
         with r_i1 = q_i, r_i0 = 1 - q_i
         m[k,g,c] = the same estimate pooled over all services (hierarchical shrinkage)
         a = pseudo-count, default 20, tuned on dev folds
         monotone projection: for ordinal families T, P, R, X force w(v) non-decreasing in v,
         and for C, N, S force w(v) non-increasing (pool-adjacent-violators on w, weighted by counts)
         refit eta_s on targets q_i (Section 4.2.4)
until max |delta theta| < 1e-4 or 200 iterations; 10 random restarts, keep highest likelihood
```

Why each piece:

- Gold clamping turns unsupervised DS into a semi-supervised one. With only 3 to 5 roughly independent
  families, DS is barely identifiable (Kruskal needs 3 conditionally independent views), so a few hundred
  anchored pairs fix the label-switching and degenerate solutions; the 9,588 mention pairs plus 70,000
  no-mention pairs then reduce variance.
- Hierarchical shrinkage lets sparse services borrow strength. C-section has only 23 "strong" pairs and
  burns 229 mention pairs in total; their theta shrink toward the pooled value unless their data
  disagree.
- Monotone projection keeps the scorecard sane: more own evidence never lowers the score, and more
  contamination never raises it. It is also what makes "what would raise this score" answerable.
- Per-bucket theta is the core of the angle: the same "two fields plus a quantity" pattern earns a
  smaller weight on a high-merge-risk record, because those records disagree with the other families
  more often. The App shows this as "weight reduced because this record merges 34 web sources".

#### 4.2.3 Positive-unlabelled external lists inside DS

An official list (PMNDP dialysis centres, SNCU list, NIN services column, OSM healthcare:speciality) is
complete only for its scope. Family X is coded 1 = on list, 0 = in scope but absent, abstain = out of
scope (a state or facility type the list does not cover). Then

```
theta[X, s, g, 1](1) = c_list        (the list's coverage, Elkan-Noto label frequency)
theta[X, s, g, 0](1) = e_list        (false listing rate, Beta(1, 50) prior)
```

EM learns c_list from agreement with the other families, so "absent from the list" lowers the score by
log((1 - c_list) / (1 - e_list)), which is small when the list is known to be incomplete. This is PU
learning without a separate model. No list is in /Users/karthikvattem/projects/datathon/external yet;
until one is, family X abstains everywhere and the system still runs.

#### 4.2.4 The prior: policy standards plus an additive context model

```
eta_s(x) = b_s + h_level,s(level) + h_type,s(facility_type) + h_beds,s(beds_bin)
              + h_doc,s(doctors_bin) + h_breadth,s(n_specialties_bin) + h_aff,s(affiliation)
```

- level in {district hospital, sub-divisional, CHC, PHC, medical college, none} from name and operator.
  h_level carries a Beta prior centred on the IPHS 2022 expectation: for a service marked essential at
  that level (haemodialysis and caesarean section at DH), prior mean 0.8 with strength 10 pseudo-pairs;
  EM then learns the realised rate. A district hospital with no web evidence for dialysis thus gets
  "policy says it should have dialysis; in our data such facilities are confirmed about R% of the
  time", never a silent yes.
- The other terms are binned shape functions (missing values get their own bin), monotone where the
  direction is clinically obvious (beds up, more likely for ICU, NICU, cardiac surgery).
- Fitted as an Explainable Boosting Machine with interactions off, or as a binned logistic regression if
  the `interpret` package is unavailable. Both are GAMs: each term is a lookup table, displayed as a
  bar.
- Prior features are deliberately disjoint from the vote families, so P(Y | x) times P(votes | Y) is a
  proper Bayes combination rather than double counting. The one known overlap (specialties breadth and
  prerequisite flags both come from the specialties list) is checked on gold (Section 8.4).

The prior does two jobs. It sinks claims that do not fit the facility (12 eye hospitals and 2 dental
clinics claim dialysis; claims audit coherence.json) and it surfaces large facilities that probably
offer a service but say little online. It never creates a recommendation by itself: the decision layer
requires at least one cited own sentence for "Likely" (Section 5.4).

#### 4.2.5 Cross-fitting and leakage control inside the fit

Gold pairs are split into 5 folds grouped by state and by chain or duplicate component (identity audit
official_domain and official_phone components, strong duplicate groups). For fold j, EM runs with folds
other than j clamped and fold j unlabelled, and z for fold j is taken from that fit. Calibration and
evaluation use only these out-of-fold scores.

### 4.3 Existence model

Same machinery, one latent E_f, families from Section 3.2 (domain identity, phone uniqueness, source
multiplicity, recency, OSM/NIN match, non-facility flags), prior by facility type. Gold: the `exists`
field of the web checks (31 yes, 5 unclear of 36, so far). Expected outcome: p_exist is high for most
records and the model mainly flags directory artefacts and shells. Strong duplicate groups (rule R5,
precision 27/32, recall 27/31 on 47 hand-labelled groups, identity out_eval_dup.txt) are collapsed for
display only: one card, "also listed as", evidence not pooled, because pooling across a wrong merge is
exactly the contamination we are trying to remove.

### 4.4 Location model: truth discovery over witnesses

For facility f, let C_f be the distinct districts reported by its witnesses j (Section 3.2). Each witness
type has reliability r_j (probability it reports the true district).

```
P(D_f = d)  proportional to  prior(d) * product over witnesses j of
                             [ r_j if d_j = d  else  (1 - r_j) / (|C_f| - 1) ]
r_j = sum_f P(D_f = d_jf) / (number of facilities where j reports)        (M-step)
```

- Initialise r_j from the odd-one-out counts (coordinates least reliable at state level: 91 odd-one-out
  versus 45 for stated state and 15 for PIN).
- The point location is the coordinates if they fall inside the most probable district and within the
  PIN cloud spread, else the PIN centroid, else the city centroid.
- Output: best district and point, location trust P(D_f = best), and an alternative district and point
  when its probability is >= 0.15.
- Validation: the 40 hand verdicts in audit/geo/hand_check_verdicts.csv and the `location_matches` field
  of the web checks.

Worked case: Wockhardt Hospital Nagpur has PIN, coordinates and text in Mumbai and name plus stated city
in Nagpur. With name-place reliability above coordinate reliability, the posterior is split; location
trust lands near 0.5 and the card says "We are not sure where this is: name and city say Nagpur, PIN and
map point say Mumbai". The system does not pretend to resolve it.

### 4.5 Calibration, interval and label

- Calibration: p_i = sigmoid(alpha * z_i + beta), fitted on out-of-fold gold scores, weighted by inverse
  inclusion probability of the gold sample. A linear map in log-odds keeps the score additive, so every
  displayed contribution is alpha * w and the base is alpha * eta + beta. Isotonic regression is not used
  for the shipped score because it breaks additivity and overfits at n around 250; it is run as a
  diagnostic only.
- Interval: draw theta from its Dirichlet posterior (counts plus pseudo-counts) and (alpha, beta) from a
  bootstrap of the gold set, 200 draws, recompute p_i; [p_lo, p_hi] = 5th and 95th percentiles. Rare
  evidence patterns and sparse services get wide intervals automatically.
- Label with a precision guarantee (Learn-then-Test, fixed-sequence testing): on a decreasing grid of
  thresholds t, test H_t "precision of {p_lo >= t} is below 0.90" with a one-sided Clopper-Pearson bound
  at delta = 0.10 on the weighted calibration set; t1 is the last threshold before the first failure.
  "Likely offers" = p_lo >= t1; "Unlikely" = p_hi <= t0 (t0 chosen the same way for negative predictive
  value); everything else is "Unverified". The guarantee holds only under exchangeability with the gold
  sampling design, which is why the gold sample has known inclusion probabilities. With about 250 gold
  pairs the guarantee may only be reachable at a high t1; then fewer pairs are labelled Likely and the
  App says so.

### 4.6 Output tables of the fusion layer

- `pair_scores`: (unique_id, service, z, p, p_lo, p_hi, label, contributions JSON with one entry per
  term: term name, value, points, cited sentence_ids, rejected sentence_ids).
- `reliability`: (family, value, service, bucket, P(v | offers), P(v | not), weight, n_fired, 90% band).
- `prior_shapes`: (service, term, bin, contribution).
- `facility_location`: (unique_id, best district and point, trust, alternative district and point,
  witness table JSON).
- `facility_existence`: (unique_id, p_exist, contributions JSON).

## 5. Decision layer (query to ranked options or plan)

### 5.1 Query resolution

- Service: dropdown plus lexicon match on free text (English plus Hindi and Marathi synonyms stored in
  the lexicon table). No LLM is required; ai_query may be offered for free-text parsing with the parsed
  result shown for confirmation.
- Place: a 6-digit PIN maps to its centroid and district (19,584 PINs in the directory); a district or
  city name maps through the directory, and an ambiguous name (16 district names span more than one
  state) asks the user to pick; coordinates or browser location are used as given. The resolution and
  its radius are shown ("Using PIN 824101, Aurangabad district, Bihar").

### 5.2 Success probability per candidate

```
P_succ(f) = p_service(f, s) * p_exist(f) * sum_d P(D_f = d) * 1[dist(u, point_d) <= R_s]
E_dist(f) = sum_d P(D_f = d) * dist(u, point_d)
```

The product assumes the three are independent given the evidence; that is an approximation and is
stated on the HOW page. Distances are great-circle kilometres times 1.3 as a road factor; the factor is a
documented constant, not a measured one.

### 5.3 Ranking and plan

```
U(f) = P_succ(f) * exp( - E_dist(f) / D_s )
```

D_s is a per-service travel tolerance, a policy knob set with domain input and shown in the UI. Proposed
defaults: dialysis 15 km (three sessions a week), emergency C-section 30 km and trauma 30 km (time
critical), NICU 50 km, MRI 75 km, burns 100 km, cardiac surgery 150 km (planned). R_s starts at 25 km and
expands to 50, 100, 200 km until at least 3 non-Unlikely candidates exist.

Outputs:

- Ranked list by U, with each option's label, p and interval, distance, and location trust.
- Pareto view: options not dominated on (P_succ, distance), so a user can trade a nearer Unverified
  option against a farther Likely one with both numbers visible.
- Plan: the top option plus two backups, and P(at least one works) = 1 - product of (1 - P_succ) over
  the plan, assuming independent failures. For emergencies the plan puts the nearest Likely option first
  and adds the phone number and "call ahead" prompt for each.

### 5.4 Abstention rules

- "Likely" requires at least one cited own sentence (T >= 2) and location trust >= 0.7. A pair whose
  score comes mostly from the prior is shown as "Unverified, may offer this, call to confirm" with the
  prior terms named.
- If no Likely option exists within 200 km, the App says so in one sentence and lists the best
  Unverified options, never presenting them as verified.

### 5.5 Planner mode

For a district planner or NGO coordinator: per district and service, expected verified providers
E_d = sum over facilities within 50 km of the district centroid of P_succ, with the interval from the
same posterior draws, joined to the relevant NFHS-5 indicator (701 of 706 NFHS districts are matched,
audit/geo/district_assign_stats.json). Districts with E_d below 1 are listed as candidate gaps, sorted by
the indicator, with the caveat that low web presence (common for public facilities) looks like a gap.

## 6. Explanation layer

### 6.1 Per recommendation (what the community health worker sees)

One card per option, top to bottom:

1. Plain answer: "Likely offers dialysis. 12 km away. We are fairly sure of the location."
2. Why we think it offers it: the 1 to 3 highest-weight own sentences verbatim, each tagged with its
   field and a link to the record's source URLs, for example `[procedure] "Operates a state-of-the-art
   Artificial Kidney Dialysis Unit with dedicated machines"`.
3. What we ignored: sentences dropped as describing another facility or place, for example `"Provides
   dialysis treatment at Nair Hospital, Mumbai Central" - ignored, names a different hospital`.
4. Where it is: the location witnesses that agree and disagree.
5. How sure: the band in words ("between 70 and 90 in 100 facilities with evidence like this offered the
   service when we checked") and the call-ahead number.

### 6.2 Per recommendation (what the judge sees, one click deeper)

A points waterfall, with points = (20 / ln 2) times the calibrated contribution, so 20 points doubles
the odds:

```
base rate, private hospital, 150 beds, dialysis             -31
text: two fields plus a named unit (3 own sentences)        +52
prerequisites: nephrology and dialysis machine               +14
contamination: none                                           +3
merge risk: low (5 source URLs), full weight                  0 (shown as a note)
-------------------------------------------------------------------
total +38 points  ->  p = 0.79  (band 0.66 to 0.88)  ->  Likely
```

The numbers above are illustrative; the shipped card reads them from `pair_scores.contributions`. Each
row links to the reliability-table row it came from ("text value 5 on low-risk records: seen at 41% of
confirmed providers and 0.8% of non-providers, n = 312").

### 6.3 Global explanation (HOW we decided)

- Reliability table: one row per family value per bucket, with P(v | offers), P(v | not), weight and
  n. This is the sentence the angle promises, in its estimable form: "a dialysis claim backed by two
  fields and a named unit, on a record built from fewer than 8 web sources, comes from a confirmed
  provider X% of the time; on a record built from 30 or more sources, Y%".
- Prior shape plots per service.
- The decision formula with D_s values and the road factor.
- Evaluation with denominators and intervals, the baselines, and the known failure cases.

### 6.4 Why the explanation is faithful

- The score is the sum of the displayed terms. A unit test asserts, for all 79,672 pairs, that base plus
  contributions equals the stored logit to 1e-9 and that the stored p equals sigmoid of it.
- The weights displayed are the theta used in scoring, read from the same table.
- Deletion check: setting one family to abstain and rescoring changes the logit by exactly its displayed
  contribution (true by construction, tested anyway). For the text family, which aggregates sentences,
  the card also shows the exact counterfactual "without these sentences, p would be 0.31", computed and
  stored offline.
- Every quoted sentence string-matches the raw parquet row it cites; a test fails the build otherwise.
- Text on the card comes from templates filled with stored numbers. No LLM writes a rationale.

## 7. Labels, splits and leakage

### 7.1 Where labels come from

- Gold pairs (target Y): the existing 36 web-checked pairs plus a new sample of about 220 drawn with the
  same protocol as audit/ground_truth/web_*.json (public name, city and service only, at most 4 lookups
  per pair, about 1 request per second per site), labelled confirmed, contradicted or no_info, with the
  evidence URL. The new sample is drawn after the evidence layer and families are frozen (the claims
  audit already writes audit/claims/out/FROZEN; the model adds a code hash).
- Sampling design: 60% stratified by service and by decile of the frozen model's p, 40% uniform random
  over the 9,588 mention pairs, with recorded inclusion probabilities so that population precision and
  calibration can be estimated by inverse-probability weighting.
- Target definitions: primary binary target confirmed versus not confirmed (no_info counts as not
  confirmed, the conservative choice that matches "show evidence"); secondary target confirmed versus
  contradicted, no_info excluded. Both are reported.
- Location gold: `location_matches` of the web checks plus the 40 geo hand verdicts.
- Sentence-role gold: 300 hand-labelled service sentences (own offer, other facility, credential,
  referral, list), used only if the optional role classifier is built.
- Weak and silver labels: none are used as training targets for the end score. External lists are
  witnesses (family X), not labels.

### 7.2 Splits

- The 36 v1 pairs were drawn from strata defined by the same cues the model uses, so they are dev only.
- New gold: 5 folds grouped by state and by chain or duplicate component; one fold (about 45 pairs) is
  the sealed test fold, touched once; the other four are used for cross-fitted EM, calibration and
  hyperparameter choice (pseudo-count a, bucket edges, monotone constraints on or off).
- Query-level test set: 60 (service, place) queries fixed before evaluation, 30 sampled at random from
  district headquarters PINs weighted toward low-coverage states (Bihar, Jharkhand, Odisha, Assam among
  them), 30 from the user personas. The top 3 of every system are pooled and web-checked (TREC-style
  pooling), so every system is judged on the same labelled set.

### 7.3 Leakage rules

- No feature uses a web-check URL or verdict.
- A list used as a witness is never used to evaluate; one list (for example NHP 2015 specializations) is
  held out for a positive-recall check.
- Sibling branches and duplicates never straddle folds.
- Any change to families or lexicon after looking at test labels moves those labels to dev.

## 8. Evaluation

### 8.1 Pair-level metrics (sealed test fold plus weighted cross-fitted estimates)

AUROC and AUPRC (bootstrap 95% CI), Brier score and log loss, expected calibration error with 5 bins
(and a reliability plot), precision of the Likely label and negative predictive value of the Unlikely
label (Wilson 95%), and coverage (share of pairs that get Likely or Unlikely rather than Unverified).

### 8.2 Query-level metrics

Success@1 and success@3 (the option offers the service and is at the stated location, by web check),
P(at least one plan option works) predicted versus observed, and median extra distance versus the nearest
any-mention facility. Paired comparison between systems on the same queries with McNemar's test.

### 8.3 Baselines the model must beat

| id | baseline | why |
| --- | --- | --- |
| B0 | any keyword mention, sort by distance | the typical RAG plus distance-sort answer |
| B1 | claims audit grade (strong, medium, weak) then distance | our own rule system; Wockhardt-type failures |
| B2 | ai_query LLM yes/no with self-reported confidence | known to fail on contamination |
| B3 | majority vote over families, equal weights | tests whether learned reliability adds anything |
| B4 | logistic scorecard on the same features, gold only | tests whether the unlabelled pairs add anything |

Acceptance rules, fixed before the test fold is opened: AUPRC at least 0.05 above B1 and B3; not worse
than B4 beyond its CI; ECE at most 0.08; lower Wilson bound of Likely precision at least 0.80;
success@1 at least 10 points above B0. If B4 matches the fused model, we ship B4's simpler fit but keep
the DS reliability table as the global explanation only if its weights agree with B4's in sign and rank.

### 8.4 Checks of the reliability table itself

- Agreement with hand checks: the learned weights must agree with measured cue precisions, for example
  the non-offer family should imply a low P(offers) consistent with 34/40, and the named-other cue,
  hand-measured at 9/40, should earn little weight unless confirmed by the role model.
- Stratum check: mean p over the v1 strong pairs should be close to 10/12 and over the weak pairs close
  to 1/12 (dev only, wide intervals).
- Leave-one-family-out: refit without family k, predict family k's positive votes; a family that the
  others cannot predict at all is either independent signal or noise, and the table says which.
- Residual dependence: on gold, within each Y class, the correlation between families T and P; a large
  value means double counting and triggers merging them into one family.

## 9. Accuracy levers, in expected order of gain

1. Remove foreign evidence before scoring (ownership filter). The suspect stratum contradicted 4/12;
   Wockhardt is graded strong by the rule only because of Nair Hospital sentences.
2. Anchor EM with about 250 gold pairs and calibrate on them. Without gold, DS on 3 to 5 families is
   barely identifiable.
3. The facility-type and level prior (scope conflicts, policy priors).
4. Merge-risk-conditional reliability (contamination 4.2% versus 59.6% across URL-count bins).
5. Location truth discovery including the name-embedded place, propagated into P_succ.
6. External witnesses (OSM, NIN, PMNDP, SNCU lists) as PU family X, the only truly independent view.
7. Hierarchical pooling across services for burns and C-section.
8. A better sentence-role classifier for the named-other case (current cue 9/40).
9. Monotone constraints, mainly for stability on sparse cells.

## 10. What is different from a RAG chatbot plus distance sort

- Trust comes from agreement structure across 9,959 records and a gold anchor, not from an LLM's
  self-reported confidence, which we measured to be 1.0 on contaminated records.
- The same sentence counts for less on a heavily merged record, and the card says so.
- The explanation is the model: an additive weight-of-evidence score whose terms are the displayed
  points, with a global reliability table that is checked against hand-measured cue precision.
- Location is inferred with a probability, and a location conflict lowers the ranking instead of being
  hidden behind one map pin.
- Evidence we rejected is shown, with the reason.
- Policy standards are used as priors with a learned realisation rate, so "should have" never reads as
  "has".
- The output is a plan with a stated chance that at least one option works, and an explicit "no verified
  option" when that is the truth.
- Labels carry a finite-sample precision guarantee tied to a documented sampling design.

## 11. Deployment on Databricks Free Edition

Offline (project venv for duckdb and pandas; a separate venv for `interpret` if used; at most one
serverless notebook run for the Delta writes):

- Build claim atoms and families from the audit outputs, fit DS, the prior, location and existence
  models, calibration and posterior draws. The EM over 79,672 pairs with 6 families is a few numpy array
  passes per iteration; expected seconds to minutes on a laptop CPU (not yet measured).
- Write Delta tables to one Unity Catalog schema: claims (about 26,000 service-sentence rows plus their
  ids), pair_scores (79,672 rows), reliability (a few thousand rows), prior_shapes, facility_location and
  facility_existence (9,959 each), pin_lookup (19,584 PINs), district_lookup, lexicon, metrics. Total
  well under 200 MB.

Live in the App (Streamlit or Dash, 2 vCPU, 6 GB):

- At startup, read the tables through the SQL warehouse (2X-Small) into pandas; about 80,000 score rows
  and 26,000 sentences fit easily in memory.
- Per query: resolve place, vectorised haversine over at most 9,959 facilities, compute P_succ, U, the
  Pareto set and the plan, then render cards from stored contributions. All of this is arithmetic on
  in-memory frames.
- No GPU, no model serving endpoint, no ai_query in the default path. The warehouse is touched once per
  App start, which keeps the daily fair-usage quota safe.
- Judges must be workspace users; the App auto-stops after 24 hours, so the demo plan includes a restart.

## 12. GPU: not needed; one optional offline job

The core model is EM plus a GAM and runs on CPU. A GPU job helps only for the optional sentence-role
classifier: run a zero-shot NLI model (MoritzLaurer/deberta-v3-large-zeroshot-v2.0, 435M parameters) or
fine-tune deberta-v3-small on the 26,041 service sentences (or all 288,493 unique claim strings for a
larger service vocabulary), with the hypothesis "This sentence describes services offered at NAME".
Output goes to a Delta table and becomes family R. Two cheaper routes exist: the same model on laptop CPU
for 26,041 sentences (estimated an hour or so, unverified), or batched ai_query with a hosted chat model
on Free Edition as a classifier. GPU training on Free Edition is unverified (LinkedIn identity step not
done). Whatever produces family R, it enters the model only if it beats 9/40 on the 300-sentence gold set,
and the demo never depends on it.

## 13. Risks

- Residual dependence between families makes posteriors overconfident. Mitigation: family collapsing,
  calibration on gold, the residual-dependence check, and merging families that fail it.
- EM finds a degenerate solution. Mitigation: gold clamping, informative pseudo-counts, monotone
  projection, restarts, and comparison against B3 and B4.
- The gold set stays small (about 250), so intervals are wide and the precision guarantee may only hold
  for a small Likely set. We report the coverage honestly rather than relax the guarantee.
- Target mismatch: "publicly verifiable" is not "actually offers". Public facilities with little web
  presence will score low; the App phrases this as "little public evidence", and the policy prior and
  government lists partly offset it.
- Self-consistent contamination (all witnesses copied from one wrong page) defeats truth discovery; the
  Wockhardt case survives only because the name dissents.
- Straight-line distance with a fixed road factor misjudges hilly and riverine districts.
- The per-service tolerance D_s is a value judgement. It is shown and adjustable, not hidden.
- Free Edition quota exhaustion during the demo; mitigated by reading tables once per App start.
- External lists may not be obtainable in time (data.gov.in and pmjay.gov.in refused connections during
  research); the model runs without family X.

## 14. Weekend build order

Saturday

1. Claim atoms and family values from mentions.parquet, sentence_decisions.parquet, grades.parquet and
   record_scores.parquet; merge-risk buckets; unit tests on the Wockhardt and Aravind records (foreign
   sentences dropped, scope conflict fires).
2. DS EM in numpy with hierarchical shrinkage and monotone projection; first reliability table; compare
   against hand-check cue precisions and the v1 strata.
3. Freeze families and lexicon; draw the new gold sample with inclusion probabilities; start the web
   checks in parallel (agent-assisted, human-reviewed).
4. Location truth discovery and existence model; validate on the 40 geo hand verdicts.
5. Prior GAM per service with the IPHS level term.

Sunday

6. Clamp gold, cross-fit, calibrate, posterior draws, Learn-then-Test thresholds; write pair_scores and
   the other tables (local parquet first, then Delta).
7. Decision layer and App reading local parquet; then switch to the warehouse.
8. Evaluation: pair-level on the sealed fold, query-level on 60 pooled queries, baselines B0 to B4.
9. Explanation UI: cards, waterfall, HOW page with reliability table and metrics; faithfulness tests.
10. Demo scripts for three personas: a CHW in rural Bihar (dialysis by PIN), an NGO coordinator in
    Maharashtra (NICU plan with backups), a district planner (C-section gap view).

Cut order if behind: optional role classifier, planner mode, external family X, the GAM prior (fall back
to a facility-type-by-level prior table), posterior draws (fall back to a bootstrap of calibration only).

## Appendix: two worked cases

Aravind Eye Hospital (b8a5401f): city Hyderabad, PIN 110002 (Delhi), coordinates 1,871 km from the PIN
centroid, `state_verdict = all_differ_or_split`. Dialysis grade "weak" with scope_conflict. Expected model
behaviour: family S fires (eye hospital claiming dialysis), family C fires if the Delhi government
hospital sentence is quarantined, the prior for an eye hospital and dialysis is low, location trust is
split three ways. Result: Unlikely or Unverified, never Likely, with the card naming all three locations.
Compare B2, where the LLM said yes with confidence 1.

Wockhardt Hospital Nagpur (3ac5ae50): rule grade "strong" for dialysis. After the ownership filter, the
two Nair Hospital sentences move to family C (value 1, foreign support alongside own), leaving "In-house
dialysis units" and the concessional pricing sentence as own evidence (T = 4). The record is in the high
merge-risk bucket (q_share 0.22, shared content), so T = 4 earns the high-bucket weight, and location
trust is near 0.5 (Nagpur versus Mumbai). Expected result: Unverified with both candidate locations shown,
where B1 would have ranked it as a strong dialysis option for a Mumbai query.
