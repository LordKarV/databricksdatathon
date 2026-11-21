# Referral planner: ranking facilities by expected time to actual treatment

Angle: decision-theoretic referral planning. Written 2026-11-21. This is a design. Nothing was
trained or calibrated. Numbers called "measured" come from audit outputs under
/Users/karthikvattem/projects/datathon/audit/ or from two small scripts I ran over them (section 13,
code included so it can be re-run). Every probability used in the worked examples is an
illustrative stratum rate, not a model output, and is labelled as such. "Assumed" marks a
parameter value I chose and did not measure; each one is editable and enters the sensitivity check.

## 1. Summary

The model answers "where should this patient go, and what should they do if that fails". For each
(facility, service) pair it computes a calibrated probability q that a patient who arrives will be
treated, split into three factors (the facility exists, it offers the service, it can take the
patient on arrival), plus a probability distribution over where the facility actually is. For a
query (service, location) it then searches over short referral plans ("try A; if turned away, go to
B; else C") and picks the plan that is best for the patient under a service-specific urgency
profile: probability of treatment within a deadline for trauma and emergency C-section, weekly
travel burden for dialysis, strength of evidence first for elective cardiac surgery. It also says
which single phone call before departure would improve the plan most, and shows the non-dominated
options when the trade-off is a judgement call.

Every number on screen is a term of the computation that produced the ranking:
- q is an additive log-odds model, so its explanation is the exact list of feature contributions,
  each linked to the facility sentences that set the feature;
- the plan's score is a finite sum over branches ("treated at A", "turned away at A, treated at B",
  ...), and the explanation is that ledger;
- "why A before the nearer B" is a closed-form exchange identity evaluated on the same numbers.

An LLM is never asked whether a facility is trustworthy. The measured reason: llama-3-3-70b
returned "offers dialysis: yes, confidence 1" for both known contaminated records.

## 2. What the data says, and what it forces

Measured facts that shape the design (denominators given):

1. Finding the topic is easy; attributing it to the right facility at the right place is hard.
   Core topic precision of the service lexicon is 196/200 (Wilson 95% 0.95 to 0.99,
   audit/claims/out/handcheck_summary.json). Of 9,959 records, 2,489 (25.0%) carry at least one
   quarantined foreign-facility sentence and 1,952 (19.6%) carry a sentence naming another facility
   (audit/merge/out/analyze_stdout.txt). 1,492 of 9,970 records have some geo conflict; the 90th
   percentile coordinate-to-PIN-centroid distance is 128.4 km (n=9,682,
   audit/geo/facility_geo_stats.json).
2. Internal corroboration predicts web confirmation, on tiny n (ground truth v1, 36 pairs). Strong
   stratum: 10/12 confirmed (0.55 to 0.95), 0 contradicted, 2 no information. Weak: 1/12 confirmed
   (0.01 to 0.35), 3 contradicted, 8 no information. Suspect: 4/12 confirmed (0.14 to 0.61),
   4 contradicted, and 4 of 12 with location_matches = "no". The v1 sample has no "medium" stratum,
   yet medium is the largest grade for 7 of 8 services (dialysis 566 of 1,050 pairs, trauma 2,075 of
   3,606; audit/claims/out/stats.json). The biggest block of candidates has no labels at all.
3. The nearest facility that mentions a service is usually not well evidenced. I ran a sweep over
   19,484 PIN centroids (script 13.1). For each centroid and service I took (a) the nearest facility
   with any mention and (b) the nearest facility graded "strong" with no geo conflict.

   | service | pairs | strong and geo-clean | nearest mention not strong-and-clean | nearest mention has geo conflict | median km, nearest any | median km, nearest strong-clean | PINs with no strong-clean within 100 km |
   | --- | --- | --- | --- | --- | --- | --- | --- |
   | dialysis | 1,050 | 305 | 71.9% | 24.4% | 29.6 | 50.7 | 22.4% |
   | emergency C-section | 462 | 20 | 93.6% | 22.5% | 45.4 | 185.1 | 75.5% |
   | NICU | 746 | 106 | 84.8% | 26.3% | 34.1 | 82.9 | 40.2% |
   | cardiac surgery | 974 | 118 | 88.1% | 25.6% | 35.2 | 79.3 | 39.1% |
   | MRI | 960 | 449 | 57.3% | 24.1% | 34.2 | 47.9 | 17.6% |
   | burns | 278 | 51 | 79.1% | 21.8% | 55.4 | 122.9 | 59.7% |
   | trauma | 3,596 | 282 | 93.0% | 28.0% | 18.2 | 56.8 | 24.0% |

   (PIN centroids are unweighted, not population weighted. "Pairs" counts rows with coordinates.)

   Neither naive rule works. "Nearest mention" lands on weak or location-suspect evidence for most
   PINs. "Nearest strong" sends a woman needing an emergency C-section a median 185 km, because the
   deterministic grade requires obstetrics, an operating theatre and anaesthesia all to be named,
   and only 23 of 462 C-section pairs pass. The right answer is a trade-off between distance and
   evidence, which is exactly what an expected-outcome objective computes.
4. Location errors are of three kinds and none can be ignored. Examples I looked up:
   - "Primary Health Centre Marauna": city Supaul, PIN 811107 (Sheikhpura district), coordinates
     24.80 N 85.03 E, which is next to Gaya. Three sources, three places, all in Bihar, so a
     state-level check passes. It shows up 6 minutes from Gaya town in the trauma example below.
   - "Wockhardt Hospital Nagpur": PIN 400078 and coordinates agree with each other (Mumbai
     Suburban, d_pin_km 1.6), so geo_conflict is False; only city_match_pin = False and the named
     other facility in its dialysis sentences give it away. Its deterministic grade is "strong".
   - "Aravind Eye Hospital": city Hyderabad, PIN 110002 (Delhi), coordinates 1,871 km from the PIN
     centroid; state_verdict all_differ_or_split; already capped to "weak" by the scope rule.
   In the geo hand check of 40 conflicting records (audit/geo/hand_check_verdicts.csv) the PIN was
   right in 27/40 (0.52 to 0.80) and the coordinates in 14/40 (0.22 to 0.50). So when sources
   disagree, the PIN should get more weight than the coordinates, and a point estimate is the
   wrong data type: location must be a distribution.
5. Corroboration counts are inflated by copying. Of 573 dialysis facilities with 2+ fields, 154
   have a near-duplicate sentence across fields (ratio 85, audit/claims/out/stats.json
   cross_field_echo). Independent-field counts must be computed after echo removal.
6. Contact data is not always the facility's. 348 records have an official phone shared across 3+
   cities, and one number (from property-portal pages) is the official phone of 85 records
   (audit/identity/out_q4c.txt, out_q4d.txt). A "call first" recommendation must know whether the
   phone number is likely to reach the facility.

## 3. Architecture

```
raw facility text --> [1 evidence] claim atoms with cue, attribution and place tags
                         |
                         v
                  [2 fusion] per (facility, service): p_offer with exact log-odds decomposition
                             per facility: p_exist, location distribution, phone trust
                             per (facility, service): availability prior a
                             q = p_exist * p_offer * a
                         |
user query  -------> [3 decision] resolve location -> candidates -> travel-time distributions
(service, place)                 -> best referral plan under urgency profile
                                 -> value of one phone call -> Pareto options -> robustness
                         |
                         v
                  [4 explanation] plan ledger, "why this order", contributions with quotes,
                                  location evidence, uncertainty band, model card
```

Layers 1 and 2 run offline (Databricks job or laptop) and write Delta tables. Layer 3 runs live in
the App in numpy (under a second per query, section 10). Layer 4 is rendered from layer 2 and 3
outputs only.

## 4. Layer 1: evidence (text to claim atoms)

Unit: a claim atom = (claim_id, unique_id, service, field, item_index, sentence). Built from the
existing audit tables, not re-derived.

1. Candidate sentences: the service lexicon in audit/claims/services.py over procedure, equipment,
   capability, description, plus the specialties enum. Output today:
   audit/claims/out/mentions.parquet, 26,041 sentence rows for 8 services. Extend the vocabulary with
   PM-JAY HBP package names (for example MG072A Haemodialysis, SO057A Caesarean Delivery), listed in
   research/discover/ml_resources/CANDIDATES.md.
2. Cue tags per sentence, already computed: negation, referral, future, partner, part-time, camp,
   past, hedge, named_other, foreign place, list dump, staff, directory, quantity, nonoffer,
   specific. Measured precision decides how each cue is used: nonoffer_v2 34/40 (0.71 to 0.93) is
   good enough to gate; named_other_v3 9/40 (0.12 to 0.38) is only a weak feature.
3. Attribution tier per sentence from the merge audit (merge/out/sentence_decisions.parquet): A
   self-anchored (names the record's own facility), B clean record, C merged record, Q quarantined.
4. Echo removal: within a (facility, service), sentences with rapidfuzz ratio at least 85 across
   fields collapse to one atom that remembers all its fields. Field counts use distinct atoms.
5. Prerequisite atoms per service (the pre_* columns of audit/claims/out/grades.parquet):
   nephrology and dialysis unit or machine; obstetrics, operating theatre, anaesthesia; paediatrics
   or neonatology and incubator, warmer or ventilator; and so on.
6. Facility atoms for existence and location: website and phone class
   (identity/out/existence_signals.csv), coordinates, PIN, stated city and state, the geo verdicts
   (geo/facility_geo.parquet), PINs and cities found in text or source URLs
   (geo/merge_signal.parquet), scale fields (scale/scale_flags.parquet).
7. External atoms when available: a name and district match to a public list (HOTOSM India health
   facilities, NIN geocoded directory, a government dialysis or SNCU list). These are evidence for
   existence and location, and for the service only when the list is service-specific.
8. Optional LLM atom: a strict-JSON ai_query verdict per sentence {offered_here, other_facility,
   generic_or_nonoffer} given name, city and PIN. It is a feature with a learned weight, never a
   label. It ships only if the grouped-CV ablation in section 8 improves Brier with a bootstrap
   interval that excludes zero. Cap: one pass over the medium and weak pairs' sentences (at most
   about 12,000 sentences, batched), not run.

Every atom keeps (unique_id, field, item_index) so every displayed quote is a verbatim substring
of the raw field, which is tested (section 7.4).

## 5. Layer 2: fusion (claims to calibrated probabilities)

### 5.1 What is estimated

For facility i and service s:

```
q_is = P(treated on arrival) = p_exist_i * p_offer_is * a_is
```

- p_exist_i: the facility exists as a distinct operating entity.
- p_offer_is: it offers s, given it exists. This is what web verification labels ("confirmed" or
  "contradicted").
- a_is: it can take this patient on arrival, given it offers s (24x7 cover, beds, a surgeon on
  call). No dataset field labels this; it is a service prior moved by a few features (24x7 cue,
  beds, emergency department). Its values are assumptions, shown as such, and varied in the
  robustness check.
- L_i: a distribution over where the facility is (section 5.5). It does not enter q; it enters
  travel time, because a patient navigating by name and address reaches the real building, and the
  real building is somewhere in this distribution.

The factorisation matches how the ground truth was collected (separate exists, location_matches
and service fields), so each factor gets its own labels and the user sees which one is weak.

### 5.2 p_offer: Bayesian logistic regression with prior weights in points

```
logit p_offer_is = alpha_s + sum_k (beta_k + delta_ks) * x_isk
beta_k  ~ Normal(mu_k, tau_k^2)          shared across services
delta_ks ~ Normal(0, 0.5^2)              service-specific deviation (scale assumed)
```

- mu_k are prior log-odds "points" fixed and dated before any test label is seen. Where an audit
  rate exists it sets the prior (for example strong vs weak confirmation in v1). Otherwise a
  documented judgement. With no labels the model equals the prior; each label moves it.
- Fit: MAP by Newton's method in numpy (scipy and sklearn are not in the shared venv; about 30
  lines). Laplace posterior: w ~ Normal(w_hat, Sigma), Sigma the inverse Hessian at w_hat.
- Pair uncertainty: m = x'w_hat, v = x' Sigma x; 80% interval sigmoid(m +- 1.28 sqrt(v)). Rare
  feature combinations get wide intervals even when the point estimate is high.
- Calibration: Platt scaling on out-of-fold logits, logit p_cal = c0 + c1 * logit p. Platt, not
  isotonic, for two reasons: it needs few labels, and an affine map on the logit keeps the
  explanation additive (contribution_k = c1 * w_k * x_k, intercept c0 + c1 * alpha_s), so the
  decomposition stays exact after calibration.

Hard gates (rules, listed on the model card, not weights):
- non_offer_only (every mention is a negation, referral, camp or future sentence): excluded.
- only Q-tier (quarantined) sentences mention s: excluded, shown as "evidence we ignored".
- scope conflict (eye, dental or IVF centre claiming a tertiary service): p_offer capped at the
  scope-cap value. The audit applies this cap today to 16 dialysis and 4 C-section pairs.

### 5.3 Features of p_offer (all computed from atoms, each with its claim_ids)

| feature | definition | prior sign | why |
| --- | --- | --- | --- |
| log1p(n_specific_own) | specific, attributable mention atoms (tiers A, B, C) | + | core evidence |
| n_fields_distinct (cap 3) | distinct fields among procedure, equipment, capability, description, after echo removal | + | 2+ fields defined the strong stratum, 10/12 confirmed |
| tier_A_any | a sentence names the record's own facility | + | self-anchored |
| prereq_frac | share of the service's prerequisites present | + | clinical consistency |
| has_qty | a count ("12 dialysis machines", "20-bed NICU") | + | specificity; 103 dialysis facilities |
| enum_hit, enum_only | specialty enum names s; enum without any text | +, - | 302 cardiac pairs are enum-only |
| nonoffer_any | at least one nonoffer sentence among others | - | 34/40 precise |
| named_other_share | share of mentions naming another facility | - small | 9/40 precise, so weak |
| q_share | record share of quarantined sentences | - | merge contamination |
| shared_content | source_content_id shared with other records | - | copied text |
| city_pin_mismatch | stated city not in PIN district (city_match_pin False) | - | the Wockhardt Nagpur pattern |
| list_dump_share | share of mentions that are 4+ item lists | - | 273 dialysis list sentences |
| directory_share | "top", "best", "listed", aggregator wording | - | directory pages |
| log1p(beds), log1p(doctors), facility type | scale and type | + | tertiary services need scale |
| scale_contradiction | breadth exceeds size, clinic with 100+ beds | - | at least 572 records flagged breadth_exceeds_size |
| url_class | official domain, government portal, aggregator only | +, +, - | provenance |
| external_service_list | on a service-specific public list | + | when research delivers one |
| llm_attr | optional LLM verdict | learned | ablated |

Roughly 18 shared weights, 8 x 18 service deviations and 8 intercepts, a Hessian of about 170 x 170. The feature list
is kept short on purpose: the label budget is a few hundred pairs.

### 5.4 p_exist and phone trust

p_exist_i is a small logistic model on: website class (own domain with name match 6,327 of 7,914,
none 1,602), phone class (none 495, shared across 3+ cities 348), source URL count, social and page
recency, duplicate or chain membership, geo agreement, an OSM or registry name match within 2 km.
Labels: the web "exists" field. Negatives are rare in v1, so the prior dominates and p_exist acts
mostly as a flag; that is stated on the card.

phone_trust_i = P(the listed number reaches this facility). Prior by phone class (assumed values):
own mobile or landline high, toll-free medium, shared across 3+ cities low, none zero. It is used
only by the value-of-information step.

### 5.5 Location distribution

Candidate points for facility i: the record coordinates, the PIN centroid (audit/geo/
pin_centroids.parquet, with its spread_km_p90), the stated city or district centroid, PINs found in
the record's own text, and an external match point. Each candidate gets support from the sources
that fall within 10 km of it:

```
score_l = sum_j r_j * 1[dist(l, source_j) <= 10 km]        w_l = softmax(score_l)
```

r_j are source reliabilities, fitted on the geo hand labels (40 now; the v2 location labels add
more). The starting values encode the measured fact that the PIN beats the coordinates in
conflicts (27/40 vs 14/40). Output per facility: the weighted points, the displayed point (highest
weight), and location_trust = w of the displayed point. For PHC Marauna the three sources split,
so no point gets high weight, travel time becomes a wide mixture, and the card says "location
unclear: city, PIN and map point are in three different districts".

### 5.6 Availability a_is (assumed, not labelled)

Service-level prior for "can take the patient on arrival, given it offers s", raised by a 24x7 cue
or an emergency department and by bed count. Until call outcomes exist, a is the least grounded
term in q. It is shown as "assumed availability" on every card and varied in the robustness check.

## 6. Layer 3: decision (query to referral plan)

### 6.1 Query and user location

The App resolves PIN, district, city or coordinates with the geo audit's resolver
(audit/geo/resolve_input.py, 40 test cases in resolve_test_cases.csv). The user location is a
distribution too: a PIN is represented by its India Post offices (the directory gives each office's
coordinates), a district by its PINs. Travel times are averaged over these points, so a PIN that
spans 40 km does not pretend to be one point.

### 6.2 Travel time

Primary: the Malaria Atlas Project 2020 motorized friction surface (CC BY 4.0, 1 km grid, an India
clip is about 55 MB, research/discover/geo_access/CANDIDATES.md). Offline, a cost-distance pass
from every PIN centroid gives the minutes to every candidate facility within 300 km straight-line.
I counted those pairs: 7,608,839 (2,593,016 within 150 km) over 19,584 PIN centroids and 4,714
facilities that have at least one non-excluded service pair (script 13.2). That fits one Delta table.

Travel time is a random variable, not a number:

```
t(x, y) ~ LogNormal(log(kappa * m(x, y)), sigma^2)
```

with m the friction-surface minutes, kappa >= 1 a realism factor (the surface assumes optimal speed,
so it understates real time; value assumed, default 1.0, varied up to 1.5), sigma a spread
(assumed). Between two facilities (leg 2 of a plan) the same surface is used from the first
facility's PIN.

Fallback when the matrix lacks a pair: haversine times a circuity factor over a speed by distance
band, with both fitted by regressing friction-surface minutes on haversine km over the matrix. The
fallback is then consistent with the primary and its error is measurable (MAPE against the
surface, not run). Either way the card says "estimated travel time, no live traffic or road
closures".

If the friction surface cannot be obtained in time, the fallback runs with circuity and speed as
assumed values and the label changes to "rough estimate".

### 6.3 Urgency profiles

| profile | services | objective | parameters (assumed defaults, user-editable) |
| --- | --- | --- | --- |
| deadline | trauma, emergency C-section, NICU transfer, burns, emergency ICU | maximise P(treated within D); tie-break by lower E[T] | D = 60 min trauma and C-section, longer for NICU and burns |
| expected time | MRI, non-emergency ICU | minimise E[time to treatment] | turn-away delay tau |
| recurring | dialysis | minimise amortised first-search time plus weekly travel | f sessions per week, horizon H weeks, cost class |
| evidence first | elective cardiac surgery | maximise the lower bound of q subject to travel at most B | budget B |

These defaults are design choices, not clinical standards, and the card shows them ("deadline used:
60 minutes").

### 6.4 Plan value

A plan is an ordered list pi = (i_1, ..., i_K), K at most 3, followed by an outside option O.
Arrival time at the k-th stop:

```
S_1 = t(x, i_1)
S_k = S_(k-1) + tau + t(i_(k-1), i_k)        tau = time lost at a facility that turns you away
```

Probability that stop k is where treatment happens:

```
P_k = q_(i_k) * prod_(m<k) (1 - q_(i_m))          P_fail = prod_(m<=K) (1 - q_(i_m))
```

Objectives:

```
deadline:       V_D(pi)  = sum_k P_k * Pr(S_k <= D)  +  P_fail * q_O * Pr(S_K + tau + t(i_K, O) <= D)
expected time:  E[T](pi) = sum_k P_k * E[S_k]        +  P_fail * (E[S_K] + tau + E[t(i_K, O)] + T_O)
recurring:      J(pi)    = sum_k P_k * (E[S_k] / H + 2 f E[t(x, i_k)])  +  P_fail * J_O
```

Pr(S_k <= D) is computed by Monte Carlo over the location mixture, the user's location points and
the lognormal noise, with R = 1,000 draws and a fixed seed shared by all plans (common random
numbers, so plan differences are not noise and the numbers on screen are reproducible).

The outside option O matters. In the rural Supaul C-section example (13.3) only 3 candidates lie
within 300 minutes; without O every call has zero value and the plan cannot say "if the first try
fails, go to the district hospital". O is the nearest public facility of a type that should provide
s (IPHS lists caesarean section and haemodialysis as essential at district hospitals,
research/discover/ml_resources/CANDIDATES.md), taken from the dataset or an external list, with q_O
from the type prior. It is shown as "not verified in our data".

Correlated evidence: two records in the same shared-content or identity component share copied
text, so their p_offer are not independent. The planner does not chain two members of the same
component, and says so when it skipped one.

### 6.5 Search

Candidates: pairs passing the gates with E[t] within a service-specific maximum, then a dominance
prefilter (drop i if some j has q_j >= q_i and E[t(x, j)] <= E[t(x, i)]) and the top N = 15
remaining by q / E[t]. All ordered plans of length up to 3: 15 + 210 + 2,730 = 2,955 evaluations,
exact. The prototype in 13.3 enumerates plans of length up to 3 over 12 candidates, including the
value-of-information re-optimisation, for 2 queries in 0.37 s wall time of pure Python including data loading (measured with time).

### 6.6 Why A before B: the exchange identity

For the expected-time objective, two stops, symmetric t_AB and the same terminal cost after both, the difference is exactly

```
E[T](A, B) - E[T](B, A) = (t_A - t_B) - (q_A - q_B) * (tau + t_AB)
```

So A first is better when its extra driving (t_A - t_B) is smaller than its success advantage
times the cost of a wasted trip (tau + t_AB). This is the sentence the App prints: "B is 4 minutes
closer, but A is 31 points more likely to treat you, and being turned away costs about 35 minutes,
so going to A first saves about 7 minutes on average". The printed number is computed by the full
plan evaluation, not by the identity; the identity is the human-readable reason and a test checks
that both agree when the terminal costs match.

### 6.7 Value of one phone call

A call to facility j reaches it with probability r_j = phone_trust_j and, if reached, answers
"yes, we can take the patient now" or "no" with sensitivity s1 and specificity s0 (assumed). It is
the only way to learn a_is, which the data cannot. After "yes" and "no":

```
q_j+ = s1 q_j / (s1 q_j + (1 - s0)(1 - q_j))       q_j- = (1 - s1) q_j / ((1 - s1) q_j + s0 (1 - q_j))
P(yes) = s1 q_j + (1 - s0)(1 - q_j)
VOI_j = r_j * [P(yes) V*(q | q_j+) + (1 - P(yes)) V*(q | q_j-)] + (1 - r_j) V*(q) - V*(q)
```

V* is the optimal plan value (re-optimised in each branch). The App recommends calling the j with
the largest VOI_j when it exceeds a minimum (for example 5 minutes or 0.03 in deadline
probability), and shows what the plan becomes after "yes" and after "no". A second call is chosen
greedily after the first answer. Two consequences that make this more than a gimmick:
- The shared property-portal phone number gets r near zero, so the App never says "call first" to
  a number that cannot reach the facility.
- VOI is large where alternatives are spread out and near zero in dense towns. In the prototype a
  call was worth about 26 to 31 expected minutes for dialysis from rural Supaul, and at most 0.04 in
  P(within 60 min) for trauma inside Gaya town (anecdotal, 4 queries, illustrative q).

### 6.8 Non-dominated options

For the first stop, the App computes the Pareto set over (E[t], lower bound of q, cost class:
government or charitable vs private, from operator type). It shows the recommended plan plus the
other non-dominated first stops, each with the one axis on which it wins. Dominated options appear
only on request, each naming the option that dominates it. For evidence-first services this is
the main view.

### 6.9 Robustness

Draw 200 weight vectors from the Laplace posterior (this keeps the correlation between facilities
that share features), together with kappa and a from their assumed ranges, and re-score the top 20
plans. Report P(recommended plan stays best) and the 10th to 90th percentile of its value. Below
0.7 (assumed threshold) the card says "close call between A and B" and leads with the phone call.

### 6.10 District planner outputs (precomputed)

For each district and service, over PIN offices (or WorldPop 2025 population cells if loaded):
- access: mean V*(x), for example P(treated within 60 minutes);
- data gap: EVPI(x) = E over statuses Z ~ q of [V of the best plan knowing Z] - V*(x), the part of
  the access gap that verification would close;
- infrastructure gap: the remainder, which no phone call can fix;
- verification list: facilities ranked by sum over x of VOI_j(x), "verify these 10 facilities and
  expected district access rises the most".
The data gap vs infrastructure gap split is the planner's headline: it separates "we do not know"
from "there is nothing there".

## 7. Layer 4: explanation (what the user and the judges see)

### 7.1 Recommendation card (health worker view)

```
GO TO: Buddha Hospital and Research Institute, Gaya          about 8 min (estimated)
  Chance you are treated there: 0.79 (80% range ...)          [illustrative value]
  CALL FIRST: +91 ...  (number looks like the hospital's own)
  If they cannot take you: Arsh Superspeciality Hospital, 4 min from there
  Last resort: <district hospital>, not verified in our data
WHY THIS PLACE
  Its records say: "Dialysis unit" (equipment), "...nephrology..." (specialties)   [quotes, links]
  Why we trust it: 2 separate fields, nephrology present, location sources agree (within 1 km)
  Concerns: none found  |  or: "the dialysis sentence names another hospital"
WHY NOT THE NEARER ONE
  Arsh is 4 min closer, but its only evidence is one sentence and no nephrology; ...
```

Plain language, one screen, the numbers rounded, the band word next to each probability.

### 7.2 How we decided (judge and coordinator view)

- The plan ledger: one row per branch with its probability, arrival time, and contribution to the
  objective; the rows sum to the plan's score.
- The p_offer decomposition: intercept plus each feature's contribution in points, each row
  expandable to the claim atoms (sentence, field, source URL) that set it.
- The location panel: candidate points on a map with their weights and the sources supporting each.
- Parameters used: D, tau, kappa, a, f, H, with a slider for each and live recomputation. Moving a
  slider and watching the plan change is the strongest evidence that the explanation is the
  computation.
- Robustness: P(plan stays best) and the value range.

### 7.3 Global explanation (model card page)

Feature weights with prior and posterior intervals, sign flips between prior and posterior listed
as findings, the gates, the calibration curve with per-bin Wilson intervals, the evaluation table
of section 8 against every baseline, the urgency profiles and defaults, and the list of assumed
parameters. A "track record by band" table: of N verified pairs in band "likely", k confirmed, c
contradicted, u no information.

### 7.4 Faithfulness, enforced by tests

1. For every stored pair, intercept plus contributions equals the stored calibrated logit
   (absolute error below 1e-9).
2. For every plan shown, the ledger rows sum to the objective returned by the optimiser.
3. The "why A before B" sentence is recomputed with the full evaluator; the test checks it agrees
   with the exchange identity when terminal costs match.
4. Every quote on a card is a verbatim substring of the raw field at (unique_id, field,
   item_index).
5. Fixed seeds: the same query returns the same numbers.
6. If an LLM is used to phrase text (optional, for Hindi), every number in its output must appear in
   the ledger (regex check); otherwise the template text is shown. Default is templates only.

### 7.5 Uncertainty language

Band words come from the calibrated probability and the interval width together: "likely" (p at
least 0.8 and lower bound at least 0.6), "possible", "unlikely", and "not enough evidence" when the
interval is wider than 0.5 regardless of p. Thresholds are fixed before evaluation and the band
track record is shown. Travel times always carry "estimated". The outside option always carries
"not verified in our data".

## 8. Labels, leakage, evaluation

### 8.1 Label sources

| set | size | use |
| --- | --- | --- |
| v1 web ground truth | 36 pairs | development only, frozen; it was seen while designing features |
| v2 blind stratified sample | target 240 pairs: 8 services x 4 strata (strong, medium, weak, suspect) x about 7, random within strata, inclusion probabilities stored | fit (out-of-fold) and headline metrics, weighted back to the population |
| v2 neighbourhoods | 6 query sites (for example Gaya, Supaul, a Maharashtra district town, a metro) x 3 services x the union of candidates any method puts in its top 3 | decision-level evaluation (8.4) |
| geo hand labels | 40 now (audit/geo/hand_check_verdicts.csv) plus v2 location fields | location reliabilities r_j |
| sentence hand labels | audit handchecks (core 200, nonoffer 40, named_other 40, ...) | evidence layer cue precision |
| call outcomes (later) | from the App's "I called, they said yes/no" button | labels for a and phone_trust |

Protocol for web labels (as in v1): confirmed only with a source independent of the record's own
source_urls (official site, government list, news); no_info recorded separately and never coded as
0; labeller blind to the model's q. Web pages for no_info-heavy pairs are a known gap (8 of 12 weak
pairs in v1), so no_info is modelled as censoring for p_offer, with a sensitivity analysis that
codes it as 0.

### 8.2 Leakage controls

- Features never read verification outputs.
- Splits are grouped by connected components of duplicate groups, chain domains, shared phones and
  shared source_content_id (identity and merge audits), and all 8 services of a facility stay in one
  fold. Without this, copied text sits in train and test.
- A second split leaves one region out (for example all of the east) to test geographic transfer.
- Prior points mu_k and band thresholds are written and dated before v2 labelling.
- An external list is either a feature or a label source, never both for the same pair; pairs
  whose web confirmation came from that list are dropped from that list's ablation.
- Evidence URLs that appear in the record's own source_urls do not count as confirmation.

### 8.3 Fusion metrics and baselines

Out-of-fold over v2, inverse-inclusion weighted: Brier score, log loss, AUROC, AUPRC, expected
calibration error with a reliability plot, precision in the "likely" band with a Wilson interval,
contradicted rate in the "likely" band. All with 95% cluster bootstrap intervals (clusters = the
grouping components). Baselines it must beat, compared by paired bootstrap of the difference:

- B0 any mention means yes;
- B1 the audit's deterministic grade (strong, medium, weak mapped to an ordinal score);
- B2 mention count;
- B3 LLM self-reported confidence (ai_query, structured output, run on the v2 test pairs only,
  about 240 calls);
- ablations: without contamination features, without location features, without the LLM atom.

Honest power statement: with 240 labels a Brier difference smaller than a few hundredths may not
be distinguishable from zero. Calibration matters more than ranking here, because the planner
multiplies probabilities; a well-ranked but overconfident q would push the planner into long
detours with too little fallback.

### 8.4 Decision metrics

On the v2 neighbourhoods, where every candidate any method proposes has a web label:
- realised time to treatment and P(within D) of each method's plan, computed with the labelled
  statuses (no_info candidates evaluated twice, as success and as failure, giving a range);
- regret against the oracle plan that knows the statuses;
- first-stop turn-away rate.
Methods: nearest mention; nearest strong grade; a RAG-style top 3 by embedding similarity then
distance; our plan without the location distribution; our plan. Paired bootstrap over query sites.
Six sites is small; the intervals will be wide and are reported as they come out.

Label-free checks over all 19,584 PIN centroids: share of first stops with a geo conflict or a named
other facility in their evidence (the nearest-mention baseline is at 21.8% to 28.0% geo conflict,
section 2), and how often the first stop changes between baselines and our plan.

Travel time: friction-surface minutes against a small sample of known routes is not available
offline; not run. Reported as an estimate everywhere.

## 9. Accuracy levers (largest expected effect first)

1. Spend labels on the medium stratum and where decisions flip. Medium is the biggest block and has
   zero labels. Within the stratified design, the v2 neighbourhood sampling adds the pairs that
   actually decide plans.
2. Attribution features before text features: q_share, city_pin_mismatch, shared_content and the
   location distribution separate the Wockhardt and Marauna cases, which a text-only model cannot.
3. Echo removal before counting fields (154 of 573 dialysis 2+ field facilities have echoes).
4. Hierarchical sharing across services so C-section (23 strong pairs) borrows strength from
   dialysis and MRI.
5. PIN-weighted location in conflicts (27/40 vs 14/40).
6. An outside option and phone trust in the planner, so a bad record costs a bounded detour instead
   of a dead end.
7. External corroboration (HOTOSM, NIN directory, service-specific government lists) as features.
8. Calibrate with Platt on out-of-fold logits; check per-band track records.

## 10. Free Edition deployment

Delta tables in the workspace catalog, written by one offline job:

| table | rows (measured or bound) | content |
| --- | --- | --- |
| claims | 26,041 sentences | atom, field, index, cues, tier, claim_id |
| trust_pairs | 10,880 non-excluded pairs | p_offer, interval, a, q, band, contributions array of (feature, value, weight, points, claim_ids) |
| facility | 9,970 | p_exist, phone_trust, location points and weights, displayed point |
| travel_pin_facility | 7,608,839 within 300 km | PIN, facility, median minutes |
| pins | 19,584 centroids plus offices | user-location points |
| model_card, eval | small | weights, priors, gates, metrics, band track record |
| district_access | districts x services | access, data gap, infrastructure gap, verification list |

The App (Streamlit, pre-installed) loads trust_pairs, facility and pins into memory at start (a few
MB), and fetches the travel rows for the query's PIN from the warehouse (one indexed lookup) or
falls back to haversine. Per query it runs the candidate filter, plan search, VOI, Pareto and 200
robustness draws in numpy. No LLM and no GPU on the critical path; ai_query is optional for parsing
free-text queries into (service, place), always shown back for confirmation, with dropdowns as the
default. Daily quota use: the offline job is one pass; the App issues one small SQL query per user
query.

Judge access: judges must be workspace users; the App auto-stops after 24 h, so restart before
judging, and keep a recorded walkthrough as backup (audit/capabilities/CAPABILITIES.md).

## 11. GPU

Not needed. The fusion model has about 170 parameters and a few hundred labels; a Newton fit of that size is a CPU job (not run yet)
on a CPU. The only plausible GPU job is a one-off cross-encoder or NLI pass for sentence
attribution (does this sentence describe this facility at this place), where the deterministic
named_other cue is weakest (9/40). It would be adopted only if, on held-out sentence labels, it
beats the deterministic attribution and the optional ai_query atom, and its outputs would be one
Delta column. The ai_query route does the same on pay-per-token CPU endpoints without GPU
verification risk, so it comes first. Nothing in the demo depends on a GPU.

## 12. What is different from a RAG chatbot plus distance sort

1. The objective is the patient outcome (deadline probability, expected time, weekly burden), not
   text similarity or distance.
2. A plan with a fallback, not a list: the turn-away risk is priced into the order.
3. The exchange identity gives a one-line, exact reason why a farther facility comes first.
4. Value of information: the model recommends which phone call to make, and knows when a listed
   number cannot reach the facility.
5. Location is a distribution; a record with three disagreeing locations widens its travel time
   instead of placing a facility 6 minutes from Gaya that is in another district.
6. Trust is decided by deterministic, tested features; the LLM is at most one ablated feature.
7. Every probability is an exact sum of cited contributions; every plan score is an exact sum of
   ledger rows; sliders recompute live.
8. The district view separates the data gap (fixable by verification) from the infrastructure gap.
9. Labels are spent where they change decisions, and the band track record is published.

## 13. Measurements and prototype

### 13.1 Nearest-mention sweep (section 2, item 3)

Script run from the session scratchpad over audit/claims/out/grades.parquet,
audit/geo/facility_geo.parquet and audit/geo/pin_centroids.parquet: brute-force haversine nearest
neighbour from each of 19,484 PIN centroids (best_lat, best_lon inside 6 to 38 N, 68 to 98 E, with a
district) to each service's facilities, deduplicated by unique_id. Output is the table in section 2.

### 13.2 Travel matrix size (section 6.2)

Count of (PIN centroid, facility) pairs within 150 and 300 km, for the 4,714 facilities with
coordinates and at least one pair that is not non_offer_only: 2,593,016 and 7,608,839.

### 13.3 Decision-layer prototype

Illustrative q only: strong 11/14 (Laplace-smoothed v1 strong rate), medium 0.5 (no labels),
weak 2/6 (smoothed v1 weak rate among decided pairs), enum-only 0.2, halved when geo_conflict.
Assumed: circuity 1.4, 40 km/h, tau 20 min, failure penalty 240 min. These are not model outputs.

```python
def evaluate(plan, q, T0, Tij, D):
    """Exact sum over branches: returns E[T], P(T <= D), P(all fail)."""
    surv, t, et, pd_ = 1.0, 0.0, 0.0, 0.0
    for k, i in enumerate(plan):
        t += T0[i] if k == 0 else TAU + Tij[plan[k-1], i]
        et += surv * q[i] * t; pd_ += surv * q[i] * (t <= D); surv *= 1 - q[i]
    return et + surv * (t + TAU + M), pd_, surv
# check: q=(1.0, 0.5), T0=(30, 10), Tij=5: plan (1, 0) gives E[T] = 0.5*10 + 0.5*(10+TAU+5), P = 1
```

Results (12 nearest candidates within 300 min, all ordered plans up to length 3, VOI with a perfect
call):

| query | best plan | nearest-only baseline | most valuable call |
| --- | --- | --- | --- |
| dialysis, PIN 823001 Gaya, expected time | Buddha Hospital, then Arsh, then Nirog (Patna): E[T] 35 min, P(all fail) 0.02 | Arsh alone: E[T] 134 min | about 10.6 min saved |
| trauma, PIN 823001 Gaya, deadline 60 min | three Gaya hospitals in order: P(within 60) 0.88 | nearest alone: 0.50 | at most 0.04 gained |
| C-section, PIN 852131 Supaul, deadline 120 min | only 3 candidates; P(within 120) 0.50 | same | 0.00: no alternative within the deadline, which is why the outside option exists |
| dialysis, PIN 852131 Supaul, expected time | three Darbhanga and Muzaffarpur hospitals: E[T] 249 min | nearest alone: E[T] 339 min | about 26 to 31 min saved |

The Gaya trauma candidates included PHC Marauna (6 min away by its coordinates, city Supaul) and
the Supaul dialysis candidates included "Sadar Hospital, Jamshedpur" with a geo conflict: both are
the cases the location distribution is built for. The baseline gaps above depend heavily on the
assumed 240-minute failure penalty and the illustrative q; they show the mechanics, not the size of
the real gain, which section 8.4 measures.

## 14. Risks

- Labels are few and no_info is common (8 of 12 weak pairs in v1). Intervals will be wide; the App
  must show them rather than hide them.
- Availability a is unlabelled. If the assumed values are off, turn-away probabilities are off.
  Mitigation: shown as assumed, varied in robustness, replaced by call outcomes when they exist.
- Travel times are estimates; the friction surface assumes optimal speeds, ignores traffic,
  floods and closures, and the 1 km grid blurs city streets. The mode of transport is unknown.
- Default deadlines and profiles are design choices, not clinical guidance; a clinician should
  review them. The App is decision support and says "call ahead" on every card.
- The outside option may itself not offer the service; it is labelled as unverified.
- The dataset is incomplete (10,088 rows, 9,970 well formed, 9,959 after exact-id dedup); many
  government facilities are missing, so "no option nearby" can be a data artefact. The planner view
  shows it as a gap of our data, not of the district, unless an external list confirms.
- Independence of failures across facilities is assumed except within copied-content components;
  regional events (strikes, floods) correlate failures and are not modelled.
- PIN centroids are not population; until WorldPop is loaded, district access numbers are per PIN
  office, not per person.
- Complexity for judges: the plan ledger and sliders must stay one click away, not on the main card.

## 15. Build order for a weekend

Saturday
1. Morning: claim atom table from the audit outputs (mentions, sentence_decisions, grades,
   echo removal); facility atom table (geo, merge_signal, identity, scale). Tests: quote substring,
   echo collapse.
2. Morning: write and date the prior points table, gates and band thresholds. Start v2 sampling
   frame and blind web labelling (stratified, including medium; neighbourhood sets for 6 sites).
3. Afternoon: decision engine in numpy: evaluate, plan search, exchange identity, VOI, Pareto,
   Monte Carlo with fixed seed; assert tests 7.4 items 2, 3, 5. Haversine fallback first.
4. Evening: location distribution and its fit on the 40 geo labels; friction-surface travel matrix
   job if the raster is in hand, otherwise keep the fallback and label it.

Sunday
5. Morning: fit p_offer and p_exist (MAP plus Laplace, Platt), grouped CV, baselines B0 to B3,
   ablations; freeze the model; band track record.
6. Midday: write the Delta tables; precompute district access, data gap and verification lists.
7. Afternoon: Streamlit App: query form, card, plan ledger, decomposition, location panel,
   sliders, model card page, planner page.
8. Evening: decision evaluation on the 6 neighbourhoods; demo scripts for a health worker in rural
   Bihar, an NGO coordinator in Maharashtra and a district planner; restart the App and record the
   walkthrough.

If time runs short, cut in this order: the planner page, the Pareto view, robustness draws. Never
cut the ledger, the citations or the uncertainty bands.
