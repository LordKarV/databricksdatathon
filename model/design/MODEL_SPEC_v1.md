# Model spec v1: Witness Ledger

Status: design contract for the prototype builders. Nothing in this spec has been built or run. Numbers marked
(measured) come from files or queries named next to them; numbers marked (assumption) are policy choices that the
App shows as adjustable knobs; numbers marked (target) are budgets. Paths are absolute unless they are inside a
layer's own output folder.

Root: /Users/karthikvattem/projects/datathon (written ROOT below). Prototype outputs: ROOT/model/proto/{evidence,
fusion,decision,explanation,eval}/. Each layer has its own builder and can be built against the fallback inputs
listed in its section, so the four layers can be built in parallel.

## 1. The system in one paragraph

Every piece of evidence about a facility is a witness: a sentence family, a structured field, a location source, a
phone number. Witness Ledger turns 10,088 web-extracted records into three probabilities per (facility, service):
the facility exists (P_E), it is where we think it is (P_L), and it offers the service (P_S). Each probability is a
Bayesian logistic scorecard, an additive sum of named, sign-constrained weights, so the points a user sees are the
computation itself. The weights have two independent sources that the fit reconciles: a prior learned from how
witnesses agree across all 69,713 (facility, service) pairs (a semi-supervised Dawid-Skene pass), or from
hand-measured audit rates, and a likelihood from web-checked gold pairs. Before any sentence counts, it must be
attributed to this facility. Sentences that name another hospital or another state are removed and shown as
"evidence we ignored". Evidence on heavily merged records earns visibly less weight. The decision layer ranks
options by U = P_E x P_S x (location-weighted distance discount), returns a referral plan with backups and
P(at least one works), and says plainly when no verified option exists. Every card cites the verbatim sentences,
shows a per-band track record ("of 22 facilities we checked with a score like this, 18 were confirmed, 1 was
wrong, 3 had no public information"), and explains in one exact sentence why a farther option outranks a nearer
one. No LLM sits on the trust or explanation path. An LLM appears only as a baseline, which we expect to fail on
contaminated records (measured: confidence 1.0 on both known contaminated records).

## 2. Where each idea came from

The judges picked the witness-weighted evidence fusion proposal (accuracy and explainability lenses) and flagged
its estimation stack as too heavy for a weekend (feasibility lens). This spec keeps its evidence families,
merge-risk conditioning, IPHS-as-prior, name-embedded place witness, rejected-evidence display and reliability
table. It changes the estimator: gold labels decide the weights and Dawid-Skene EM only proposes their prior
means. Learn-then-Test thresholds are dropped in favour of Wilson-bounded band precision.

| idea | from | where in this spec |
| --- | --- | --- |
| evidence families, one vote per family, fields collapsed into T | fusion | 4.4 |
| merge-risk bucket discount (contamination 4.2% at <3 URLs vs 59.6% at 30+) | fusion | 4.4, 5.2 |
| IPHS level as a prior term, never as evidence; prior-only pairs stay Unverified | fusion | 5.2, 6.6 |
| place named in the facility name as a location witness | fusion | 4.6, 5.4 |
| B4 gold-only scorecard as a gate on any agreement-learned gain | fusion | 5.3, 8 |
| 40% uniform sample with inclusion probabilities, no_info counted as not confirmed | fusion, accuracy judge | 5.7 |
| factorised P_E x P_L x P_S, each head trained on its own protocol field | ledger | 5.1 |
| informative priors fixed and dated before labels; prior vs posterior sign flips as findings | ledger | 5.3 |
| per-band prospective track record with three outcomes and Wilson CI | ledger | 7.1, 9 |
| focus-state subgroup report (Bihar, Jharkhand, Odisha, Assam, Chhattisgarh) | ledger | 9.4 |
| App recomputes the rank from displayed numbers, refuses to render on mismatch | ledger | 7.4 |
| "if a call confirms B it ranks first" counterfactual | ledger | 7.2 |
| cross-field echo removal before counting fields (154 of 573 dialysis 2+ field facilities echo) | referral planner | 4.3 |
| location vote priors from geo hand checks (PIN right 27/40, coordinates 14/40 in conflict cases) | referral planner | 5.4 |
| phone trust class, "call first" marker, outside option marked unverified | referral planner | 4.7, 6.6 |
| never two members of one copied-content component in one plan | referral planner | 6.5 |
| exact one-line "why the farther one first" identity | referral planner (adapted to U) | 6.7 |
| near-duplicate evidence units; rank of quotes by specificity | sentence | 4.3 |
| record-level contamination term because 95% of service sentences carry no anchor | sentence | 4.4 (bucket), 5.2 |
| harmful misattribution rate among cited sentences | sentence | 9.3 |
| "one of these pages" citation wording (no sentence-to-URL map exists) | sentence | 7.1 |

Dropped, with the reason: label-spreading attribution graph and NLI student (label-hungry, untestable with our gold
size), availability factor a and deadline objectives (unlabelled numbers inside the headline probability), MAP 2020
friction-surface travel matrix (raster not in the project), Laplace-moderated output (breaks exact additivity),
Learn-then-Test labels (certifies a tiny set at about 250 labels), active learning and the call-ahead feedback loop
(no outcomes would exist before judging).

## 3. Facts the design rests on

- Records: 10,088 rows; 9,959 after unique_id dedup (cleaning/claims/out/build_stats.json). Services in scope: the 7
  in the gold set and the 40 benchmark queries: dialysis, emergency_csection, nicu, cardiac_surgery, mri, burn_care,
  trauma_emergency. ICU claims are used only as prerequisite evidence. Pairs: 9,959 x 7 = 69,713.
- Claims: 469,498 claim sentences in cleaning/claims/out/claims.parquet (capability 231,465, procedure 163,647,
  equipment 55,998, description 18,388). 24,467 carry a service tag. Their attribution: unanchored 23,269 (95.1%),
  own_anchored 955, other_facility 136, ambiguous 107 (build_stats.json). Distinct (facility, service) pairs with at
  least one tagged sentence, 7 services: 7,300; with at least one unanchored or own-anchored non-offer-free
  sentence: 7,244 (measured, duckdb over claims.parquet).
- Merge risk: with the bucket rule in 4.4, records split low 3,281, mid 3,685, high 2,993 (measured over
  audit/merge/out/record_scores.parquet). 1,324 records share a source_content_id. The source_urls list is capped
  at 50 items (1,240 records sit at the cap; measured).
- Cue precision (audit/claims/out/handcheck_summary.json): core topic 196/200; non-offer v2 34/40 (Wilson 0.71 to
  0.93); named-other v3 9/40 (0.12 to 0.38); cross-state place 8/14.
- Location (audit/geo/hand_check_verdicts.csv, 40 conflict cases): PIN correct 27/40 (0.52 to 0.80), coordinates
  correct 14/40 (0.22 to 0.51). cleaning/geo_identity/facility_location.parquet gives one resolved point per record
  with loc_conf high 7,786, medium 521, low 1,147, disputed 505, and an alternative point for 1,529 records
  (measured on the file as of 2026-11-21 13:01; the cleaning workflow may still change it).
- Web gold v1 (36 pairs): strong 10/12 confirmed, weak 1/12 (8 no_info), suspect 4/12. These were read during
  design, so all 36 are dev data.
- Gold v2 (ROOT/model/gold/sample_v2.json): 140 sampled pairs, 5 per (service, stratum) over strong, weak, suspect
  and no_mention, pool sizes recorded in sample_v2_stats.json, split 69 dev / 71 test by sha256 of the duplicate
  cluster (splits.json). None is labelled yet. The design has no medium stratum and excludes chains, which is why
  section 5.7 adds a uniform sample.
- Benchmark: 40 fixed queries in ROOT/model/gold/queries.json (16 rural health worker, 8 NGO, 8 planner, 8 patient
  family; 17 emergency, 10 urgent, 8 scheduled, 5 elective; coverage ok 32, sparse 6, none 2).
- Environment: the project venv has numpy 2.5.5, pandas, duckdb, pyarrow and rapidfuzz, and has no scipy or
  scikit-learn (measured). Everything below is specified so that numpy is enough.

## 4. Layer 1: evidence

### 4.1 Inputs

| input | path | used for |
| --- | --- | --- |
| claim sentences with attribution, cues, services, prereqs, kind, qty | ROOT/cleaning/claims/out/claims.parquet | atoms |
| per-pair rule grade and flags (scope_conflict, risks, pre_*) | ROOT/cleaning/claims/out/grades.parquet | S family, baseline B2 |
| specialties enum per facility | ROOT/cleaning/claims/out/specialties.parquet | T level 1, breadth |
| lexicon (core, related, exclude patterns) | ROOT/cleaning/claims/out/service_lexicon.csv | service match |
| quarantine decision per sentence | ROOT/audit/merge/out/sentence_decisions.parquet | ownership |
| record merge stats (q_share, shared_content, source_urls, phones, type, beds, doctors) | ROOT/audit/merge/out/record_scores.parquet | bucket, context, existence |
| resolved point, alt point, loc_conf, loc_flags, district | ROOT/cleaning/geo_identity/facility_location.parquet | location |
| raw geo checks (d_pin_km, state mismatches, city match, coord_dup_names) | ROOT/audit/geo/facility_geo.parquet | location votes |
| PIN gazetteer and place layers | ROOT/cleaning/geo_identity/pin_gazetteer.parquet, places.py | name-place witness, query resolution |
| existence signals, duplicate groups, chains, shared phones and domains | ROOT/audit/identity/out/*.csv | existence, leakage groups |
| raw text for quote checks | ROOT/data/raw/facilities.parquet | faithfulness test |

Fallback if the cleaning outputs change schema: the builder pins the sha256 of every input file in FROZEN (4.9) and
fails loudly on a missing column. It never silently substitutes.

### 4.2 Claim atoms

One atom per (claim sentence, service) for every sentence tagged with one of the 7 services, plus one atom per
specialties-enum hit (field = specialties, idx = row order in specialties.parquet). Service keys are mapped to the
gold keys (csection -> emergency_csection, burns -> burn_care, trauma -> trauma_emergency).

- ownership, from claims.attribution, sibling_names, places_other_state, places_other_district and the quarantine
  flag: own_anchored | unanchored | sibling | other_facility | other_place | ambiguous | quarantined.
- role, from claims.kind and cues: offer | unit_or_equipment | quantity | staff | list | directory | nonoffer
  (any of cue_negation, cue_referral, cue_future, cue_camp, cue_past, nonoffer) | hedge | research_or_template.
- specificity: unit (names a unit, centre, department or theatre for the service) | quantity (qty_value present) |
  generic.
- counts_as_own = ownership in {own_anchored, unanchored} and role in {offer, unit_or_equipment, quantity}.
- rejected_reason (null when counts_as_own): names_other_facility | other_state_place | other_district_place |
  quarantined_merge | sibling_branch | nonoffer_cue | directory_or_list | staff_only | hedge. Sibling-branch atoms
  are shown on the card under their own heading ("describes another branch of the same group") and do not count.
- attribution_score and support_score: the measured precision of the atom's ownership class and role class, read
  from a lookup table attribution_rates.csv (class, k, n, wilson_lo, wilson_hi, source_file). Seed rows: core topic
  196/200, non-offer v2 34/40 (support 6/40 for nonoffer atoms), named-other v3 9/40. Classes without a hand check
  get null and the evidence builder adds a 100-sentence check (50 unanchored atoms on high-bucket records, 50 on
  low-bucket records) to fill them. These scores order quotes on the card and stratify the misattribution metric.
  They do not enter any logit: the logit uses the family values in 4.4, which keeps the score free of numbers
  that were never fitted.

### 4.3 Evidence units (echo collapse)

Within each (unique_id, service), atoms with counts_as_own are clustered single-link when normalised texts are
equal or rapidfuzz fuzz.ratio >= 85. A cluster is one evidence unit. Its representative is the member with the
highest specificity (unit > quantity > generic), then the longest text. Fields of a unit = the set of fields of its
members, but a unit counts for only one field when computing n_fields_own: its representative's field. This stops
"Provides dialysis treatment" echoed in procedure and capability from counting as two-field corroboration.

### 4.4 Family values per pair (one vote per family)

| family | values | definition |
| --- | --- | --- |
| T text_own | 0 to 5 | 0 none; 1 specialties enum or list/directory only; 2 one own unit; 3 two or more own units, one field; 4 own units in 2+ fields; 5 level 4 plus a unit or quantity |
| C contamination | 0 to 2 | 0 no rejected-for-ownership atom; 1 such atoms alongside T >= 2; 2 such atoms and T <= 1 |
| N non-offer | 0, 1 | any atom with role nonoffer for this service |
| S scope | 0, 1 | grades.scope_conflict (eye, dental, IVF, lab names claiming the service); 0 when no grades row |
| P prerequisites | 0, 1, 2 | count of distinct prerequisite flags for the service found in sentences that are not themselves atoms of this service, capped at 2 |
| X external list | 1, 0, abstain | on list, in list scope but absent, out of scope. No list exists yet, so X abstains everywhere in v1 |
| R role model (optional) | 0 to 2 | own-offer units confirmed by the optional classifier (4.8) |

Context variables (not votes, they condition or offset):

- bucket g: high if q_share >= 0.10 or 30+ source URLs or shared_content; low if q_share = 0 and fewer than 8 URLs;
  mid otherwise.
- list_truncated: the record has a list at the 50-item cap, so "no mention" carries less information.
- facility context: facilityTypeId (hospital 5,610, clinic 3,770, dentist 488, other; measured), operator public,
  public level from name patterns (district or civil hospital, sub-divisional, CHC, PHC, medical college, none),
  iphs_essential = level is DH and the service is marked essential at DH in IPHS 2022 (dialysis, emergency_csection),
  beds bin (missing, <30, 30-99, 100+), doctors bin (missing, <5, 5-19, 20+), specialty breadth bin (<5, 5-19, 20+),
  scale_contradiction (clinic with 100+ beds).

### 4.5 Existence witnesses per facility

website class (own domain matching the name, other domain, none), phone class (mobile, landline, shared by 3+
cities, none) from existence_signals.csv and shared_phones.csv, distinct source_ids bin, page recency present,
coordinate shared with 3+ names (facility_geo.coord_dup_names), non-facility type (pharmacy, farmacy), member of a
strong duplicate group, OSM or NIN match (abstain until a list arrives).

### 4.6 Location witnesses per facility

The cleaning layer's resolved point is the primary candidate (p1) and its alt point, when present, the second (p2).
Each witness votes +1 if it lies within 25 km of p1 (or inside p1's district for district-level witnesses), -1 if it
points elsewhere, 0 if absent: raw coordinates, PIN centroid, stated city centroid (gazetteer office or district
layer), the place token in the facility name (matched to the gazetteer office and district layers; "Wockhardt
Hospital Nagpur" -> Nagpur), stated state, PINs found in text, and the name-matched map point (907 records have one,
cleaning s2_stats.json). Extra flags: copied_geocode, coords_look_wrong, pin_looks_wrong, loc_radius_km.

### 4.7 Leakage groups

Union-find over: identity grp_strong, grp_official_domain, grp_official_phone, chain membership, shared
source_content_id. Phone and domain keys shared across 3+ cities are excluded from the union, because directory
numbers would otherwise chain unrelated facilities into one component (one number appears on 432 records in 167
cities, shared_phones.csv). Output: leakage_group_id per facility. Used by splits (5.7), bootstrap (9.1) and plans
(6.5).

### 4.8 Optional sentence-role classifier (family R, cut first)

One ai_query pass with databricks-gpt-oss-120b, strict JSON, one call per record over its numbered service
sentences: for each sentence, {about_this_facility, about_other_facility, generic, non_offer} plus the id of the
sentence that names the other entity. Verification: cited ids must exist, any named entity must appear verbatim in a
cited sentence. Caps: at most 1,500 records, batches of 250, cached by sha256 of the prompt, stop at the first quota
warning, never on gold test facilities' web evidence (prompts contain only the record's own text). R enters the model
only if it beats the rules on the 100-sentence check (4.2) with a paired Wilson difference whose interval excludes 0.

### 4.9 Outputs (ROOT/model/proto/evidence/)

claim_atoms.parquet, one row per atom:

| column | type | notes |
| --- | --- | --- |
| atom_id | str | claim_id + "|" + service |
| claim_id | str | from claims.parquet, e.g. "3ac5ae50:proc:17"; specialties: uid8 + ":spec:" + row |
| unique_id, field, idx | str, str, int | (unique_id, field, idx) locates the raw array item |
| text | str | verbatim |
| service | str | one of the 7 gold keys |
| ownership, role, specificity | str | 4.2 |
| quarantined | bool | sentence_decisions.quarantine |
| counts_as_own | bool | |
| rejected_reason | str or null | |
| named_entity | str or null | foreign or sibling name, or other place, that caused the rejection |
| unit_id | str | evidence unit; equal for echoes |
| is_unit_rep | bool | |
| qty_value, qty_unit | float, str | |
| attribution_score, support_score | float or null | lookup, 4.2 |
| attribution_n, support_n | int or null | denominators behind the two scores |

pair_features.parquet, one row per (unique_id, service), 69,713 rows: T, C, N, S, P, X, R (null = abstain), bucket,
list_truncated, n_atoms, n_units_own, n_fields_own, n_rejected, cited_atom_ids (up to 3 unit representatives,
ordered by specificity, then field diversity, then support_score), rejected_atom_ids, t_without_cited (the T value
if the cited units are removed, for the stored counterfactual), grade (cleaning grade, for B2 and sampling), and the
facility context columns of 4.4.

facility_features.parquet, 9,959 rows: existence witnesses (4.5), location votes and flags (4.6), p1 and p2
(lat, lon, source, radius_km), district, state, nfhs keys, phone, phone_class, phone_n_cities, website,
leakage_group_id, group_size.

attribution_rates.csv (4.2), lexicon_used.csv (copy of the lexicon rows used), FROZEN.json ({code_sha256,
input_sha256 per file, created_at}). After FROZEN is written, any change to families or lexicon gets a new hash, and
gold labels read before the change move to dev.

### 4.10 Evidence tests (must pass before FROZEN)

- Wockhardt Hospital Nagpur (3ac5ae50): the two Nair Hospital dialysis sentences (proc:17, equi:7) are rejected with
  names_other_facility; capa:24 and equi:43 count as own; C = 1 for dialysis; bucket = high (q_share 0.22, 50 URLs,
  shared content; measured).
- Aravind Eye Hospital (b8a5401f): its 8 dialysis sentences are all unanchored (measured), so T is high for
  dialysis; S = 1; bucket = high. This record shows that sentence-level ownership alone cannot catch contamination,
  and the test documents the gap.
- Every atom's text equals the raw facilities.parquet array item at (unique_id, field, idx).
- Echo collapse: two exact duplicates in different fields give one unit and n_fields_own = 1.

## 5. Layer 2: fusion

### 5.1 Model class (exact)

Three heads, each a Bayesian logistic regression with Gaussian priors and sign constraints, fitted by MAP with an
active-set Newton method, with a Laplace posterior, followed by an affine Platt map in logit space:

```
z_h(i)  = b_h + sum_j w_hj x_hj(i)                      raw logit of head h for unit i
w_hj   ~ N(mu_hj, sd_hj^2)                              prior; mu from M0, M1 or M2 (5.3)
z*_h(i) = a_h z_h(i) + c_h                              Platt, fitted on out-of-fold dev logits; a_h = 1, c_h = 0
                                                        if it does not improve out-of-fold log loss
P_h(i)  = sigmoid(z*_h(i))                              shipped point estimate (no moderation)
contribution_hj(i) = a_h w_hj x_hj(i);  base_h = a_h b_h + c_h     exact: base + sum contributions = z*
points = (20 / ln 2) x contribution                     20 points doubles the odds
```

Heads: service P_S over (facility, service) pairs; existence P_E over facilities; location P_L over facilities.
P_L means "the facility is within 25 km of point p1". The heads are combined only in the decision layer, under a
stated assumption that they are independent given their features.

Fitting: Newton on the penalised log likelihood with case weights (5.7). Any sign-constrained weight that ends on
the wrong side is fixed at 0 and the fit is repeated, at most 10 rounds. Covariance Sigma = inverse Hessian over the
free weights. Intervals: 200 draws of w ~ N(w_hat, Sigma) and of (a, c) from a 200-replicate group bootstrap of the
Platt fit; p_lo and p_hi are the 5th and 95th percentiles of P_h. Random seed fixed at 20261122.

### 5.2 Service head terms

Ordinal families use cumulative step indicators (x = 1[T >= v]), so a sign constraint on each step is a monotone
constraint on the family: more own evidence never lowers the score, more contamination never raises it.

| term | x | sign | service-specific deviation |
| --- | --- | --- | --- |
| b_s | intercept per service | free | yes (7 intercepts) |
| t1 .. t5 | 1[T >= v] | >= 0 | t2 and t4: delta_s ~ N(0, 0.5^2) |
| tb_mid, tb_high | 1[T >= 2] x bucket | <= 0 | no |
| g_mid, g_high | bucket main effect | free | no |
| trunc0 | 1[T = 0 and list_truncated] | >= 0 | no |
| c1, c2 | 1[C >= 1], 1[C >= 2] | <= 0 | no |
| n1 | N | <= 0 | no |
| s1 | S | <= 0 | no |
| p1, p2 | 1[P >= 1], 1[P >= 2] | >= 0 | p1: delta_s ~ N(0, 0.5^2) |
| x_on, x_absent | X = 1, X = 0 (abstain = both 0) | >= 0, <= 0 | no |
| r1, r2 | 1[R >= 1], 1[R >= 2] (optional) | >= 0 | no |
| type_clinic, type_dentist, type_other, public | facility context | free | no |
| level_dh, level_sdh, level_chc, level_phc, level_mc | public level | free | no |
| iphs_essential | DH x (dialysis or emergency_csection) | >= 0 | no |
| beds_*, doctors_*, breadth_* | bins, missing has its own bin | free | no |
| scale_contradiction | clinic with 100+ beds | free | no |

About 45 shared weights plus 7 intercepts and 21 deviations. With about 150 dev labels the priors carry most of the
information for rare terms. That is why prior means are fixed before labels are read (5.3) and why the model card
lists every weight whose posterior differs in sign from its prior.

The terms are grouped on the card into evidence (T, C, N, S, P, X, R and the bucket interactions) and context (the
rest). Context terms alone can never make a pair Likely (6.4).

### 5.3 Prior means: three candidates, chosen on dev only

- M0 gold-only: mu = 0, sd = 2.5 for every slope. This is baseline B5, the plain supervised scorecard.
- M1 expert: mu and sd written to ROOT/model/proto/fusion/priors_M1.json, with a date and sha256, before any v2 label
  is read. Each mu is a log likelihood ratio derived from a named audit rate (for example n1 from non-offer v2 34/40;
  c1 from the named-other and cross-state hand checks; t-steps from the v1 strong and weak strata rates; location
  votes from 27/40 and 14/40), and each sd is at least 0.75. The file records the derivation of every number.
- M2 agreement: mu = the weight of evidence from a semi-supervised hierarchical Dawid-Skene pass over all 69,713
  pairs (5.3.1), with sd = max(0.5, 2 x its posterior sd) to allow for dependence between families.

Selection: grouped 5-fold cross-validation on dev, by leakage group. The shipped prior is the one with the lowest
out-of-fold weighted log loss. M0 is preferred whenever another candidate beats it by less than one standard error,
because the simpler fit is easier to defend. All three are scored on test as ablations in the same single pass.

#### 5.3.1 Dawid-Skene pass (M2 only; time-boxed, cut before the App)

```
P(Y_i = 1)                   = sigmoid(eta_s)                         one intercept per service
P(v_ik = v | Y_i = c, g, s)  = theta[k, s, g, c](v)                   families T, C, N, S, P (X, R if present)
E-step: q_i = posterior of Y_i, clamped to the label for dev gold pairs
M-step: theta[k,s,g,c](v) = (sum_i r_ic 1[v_ik = v] + 20 m[k,g,c](v)) / (sum_i r_ic 1[v_ik observed] + 20)
        r_i1 = q_i, r_i0 = 1 - q_i; m = the same estimate pooled over services
        project w(v) = log theta1(v) - log theta0(v) to be monotone (pool-adjacent-violators, count-weighted)
stop: max |delta theta| < 1e-4 or 200 iterations; 10 restarts, keep the highest likelihood
```

Outputs: the agreement columns of reliability.parquet and the M2 prior means (step weight = w(v) - w(v-1);
bucket interactions from the high and mid minus low difference of w(T >= 2)). The same pass is the global "how often
is this kind of witness right" table even when M2 is not shipped.

### 5.4 Existence and location heads

Existence: terms from 4.5, all M1 priors (own domain >= 0, shared phone <= 0, pharmacy <= 0, coordinate shared by
3+ names <= 0, source multiplicity >= 0). Target: web-check exists = yes vs no or unclear. v1 has 32 yes and 4
unclear (measured over web_1..3.json), so negatives are rare. If the training set has fewer than 15 negatives, the head
ships prior-only (M1, not fitted) and the card says "existence weights are expert settings, not learned".

Location: logit P_L = b + sum_j r_j vote_j + flag terms, one row per facility. Vote weights are >= 0 (agreement
supports p1). Flags copied_geocode, coords_look_wrong and pin_looks_wrong are <= 0. M1 priors come from the geo hand
checks: in conflicts, the PIN vote weighs more than the coordinate vote (27/40 vs 14/40), and the name-place vote
starts equal to the PIN vote. Targets: web-check location_matches (yes = 1, no = 0, unclear dropped), and the 40 geo
hand verdicts mapped to the source behind p1 (listing_coordinates -> coords_ok, postcode_centre -> pin_ok,
address_city_centre -> stated_state_ok and the note). The geo hand verdicts are training-only because their
sampling design is not known. The remaining location mass 1 - P_L is assigned to p2 when p2 exists, otherwise to
"unknown", which earns no utility (6.3). Optional M2 for location: truth discovery over witness districts,
r_j = mean posterior agreement, used only as prior means.

### 5.5 Bands

- Likely: P_S >= t_L and P_L >= 0.7 and P_E >= 0.7 and T >= 2 (at least one cited own unit).
- Unlikely: P_S <= t_U, or C = 2 with T <= 1.
- Unverified: everything else, including every pair whose evidence is context only.
- t_L = the smallest threshold whose out-of-fold dev precision (inverse-probability weighted) is at least 0.85;
  t_U = the largest whose out-of-fold dev NPV is at least 0.90. If dev cannot support the estimate (fewer than 20
  pairs above the threshold), use t_L = 0.70 and t_U = 0.20 (assumption) and say so on the model card. The
  thresholds are frozen with the model.

### 5.6 Labels and targets

- Primary service target: y = 1 if service = confirmed; 0 if contradicted or no_info. P_S therefore means "a public
  check would confirm it". A facility with little web presence scores low, and the card words this as "little
  public evidence", never as "does not offer".
- Secondary: confirmed vs contradicted with no_info dropped; reported, never shipped.
- Usable target (end-to-end and for the product P_E x P_S x P_L): exists = yes and location_matches = yes and service
  = confirmed.
- Web-check protocol: same as ROOT/audit/ground_truth/web_*.json (public name, city and service only, at most 4
  lookups per pair, about 1 request per second per site, no login or paywall). Fields: exists, location_matches,
  service, confidence, evidence_urls, notes, plus two new fields: found_location_text (the address found, geocoded
  later through the gazetteer) and independent_source (true if a confirming URL is not in the record's own
  source_urls). Labellers see name, city, state, PIN and service only. They do not see stratum, quotes or scores.
- Double labelling: the 30 pairs in ROOT/model/gold/overlap_v2.json are labelled twice and Cohen's kappa is reported
  per field.

### 5.7 Splits, weights and leakage rules

Gold sets:

| set | pairs | split | inclusion probability |
| --- | --- | --- | --- |
| v1 | 36 | all dev (seen during design; the 17 that splits.json marks test are excluded from every headline metric) | not used for weighted estimates |
| v2 | 140 | splits.json: 69 dev, 71 test | 5 / pool size of its (service, stratum) cell, sample_v2_stats.json |
| U (new) | 84 (target), 12 per service, uniform over the mention pairs of that service in cleaning grades.parquet, chains included, v1 and v2 facilities excluded | same sha256 rule and salt as splits.json; a new facility whose leakage group already has a member in splits.json inherits that member's split | 12 / pool size of its service |

- Population for weighted estimates: the union of the v2 and U sampling frames. Weight = 1 / (1 - (1 - pi_v2)(1 - pi_U)),
  with pi_v2 computed by applying the build_gold_v2.py stratum rules to the pair and pi_U = 12 / pool size for mention
  pairs. Pairs outside both frames (small facilities with no mention) are outside the population, and the model card
  says so.
- Headline TEST = v2 test (71) + U test (about 42, not yet drawn). Opened once, by one evaluation script, after
  FROZEN, priors_M1.json and the fusion model hash are written. Re-runs are allowed only for bug fixes and are
  logged with the diff.
- Labels are stored in ROOT/model/gold/labels/{dev,test}.jsonl. The fusion builder reads only dev.jsonl. Test
  labels are read only by ROOT/model/proto/eval/run_test.py.
- No feature reads a web-check verdict or URL. LLM baseline prompts never contain web-check evidence. An external
  list used as family X is never used to evaluate, and vice versa.
- All services of a facility, and all members of a leakage group, sit in one split and one CV fold.
- Hyperparameters (prior choice M0/M1/M2, Platt on or off, delta sd, t_L, t_U) are chosen only by grouped dev CV.
- Any change to evidence families after a test label is read moves that label to dev.

### 5.8 Outputs (ROOT/model/proto/fusion/)

| file | grain | columns |
| --- | --- | --- |
| pair_scores.parquet | 69,713 (unique_id, service) | z_raw, z_cal, p_s, p_s_lo, p_s_hi, band, band_reason (which rule of 5.5 decided), p_s_without_cited, model_hash |
| pair_contributions.parquet | long: pair x term | unique_id, service, head = "service", term, x_value, weight, contribution_logit, points, group (evidence or context), cited_atom_ids, rejected_atom_ids |
| facility_scores.parquet | 9,959 | p_e, p_e_lo, p_e_hi, p_l, p_l_lo, p_l_hi, p1_lat, p1_lon, p2_lat, p2_lon, loc_radius_km, existence_fitted (bool) |
| facility_contributions.parquet | long: facility x head x term | same columns as pair_contributions with head in {existence, location} |
| weights.parquet | head x term x service ("*" = shared) | prior_source, prior_mean, prior_sd, post_mean, post_sd, ci90_lo, ci90_hi, sign_constraint, at_bound, sign_flip, n_fired_dev, n_fired_all |
| reliability.parquet | family x value x bucket x service | n_all, agree_p_v_offers, agree_p_v_not, agree_woe (from 5.3.1), dev_n_conf, dev_n_not, dev_p_v_conf, dev_p_v_not, dev_woe (IPW), hand_check_ref (for example "nonoffer v2 34/40") |
| calibration.parquet | head x split x bin | split in {dev_oof, test}, bin, n, mean_p, obs_raw, obs_ipw, wilson_lo, wilson_hi, k_confirmed, k_contradicted, k_no_info |
| band_record.parquet | band x split | N, k_confirmed, k_contradicted, k_no_info, precision, wilson_lo, wilson_hi, labels_sha256, model_hash, computed_at |
| platt.json, priors_M1.json, model_selection.json | | Platt (a, c) per head; dated priors; dev CV log loss per candidate with SE |

Fallback inputs for building fusion before evidence lands: derive T from grades (n_own_distinct, own_fields),
C from n_other_facility, N from n_nonoffer, S from scope_conflict and P from corr_prereqs, and write
model_hash with the suffix "-fallback". The App shows a banner while this fallback is in use.

### 5.9 Fusion tests

- For every row of every head: |base + sum contributions - z_cal| < 1e-9 and |sigmoid(z_cal) - p| < 1e-12.
- Deletion: for 1,000 random pairs and all dev gold, set one family to its zero value, rescore with the real code,
  and check that the logit change equals the displayed contribution of that family's terms.
- Monotonicity: raising T by one level never lowers z; raising C never raises it.
- Wockhardt dialysis and Aravind (every service) are never Likely. A failure is reported as a model finding, and the
  thresholds are not edited to hide it.

## 6. Layer 3: decision

### 6.1 Inputs

pair_scores, facility_scores, facility_features (phone, group, district), the pin gazetteer and place layers, and
ROOT/model/gold/queries.json for the benchmark. Fallback: B2 grade mapping as P_S, P_E = 1, P_L from loc_conf (high
0.9, medium 0.7, low 0.4, disputed 0.5; assumption), labelled as fallback.

### 6.2 Query resolution

Service from a dropdown with English, Hindi and Marathi synonyms from the lexicon table. Place from a 6-digit PIN
(gazetteer point), a district or city name (gazetteer layers; an ambiguous name lists the matches and asks the user
to pick; it never guesses), or coordinates. Reuse ROOT/audit/geo/resolve_input.py. The resolution is echoed:
"Using PIN 843317 (Singwahini BO), Sitamarhi, Bihar".

### 6.3 Distance, travel time and utility

```
d1 = 1.3 x haversine(u, p1) + loc_radius_km        km; 1.3 is a road factor (assumption, not measured)
d2 = 1.3 x haversine(u, p2) + loc_radius_km        only when p2 exists
minutes shown as a range: road km / 40 km/h to road km / 25 km/h   (assumption, labelled "rough estimate")
G  = P_L exp(-d1 / D_s) + (1 - P_L) 1[p2] exp(-d2 / D_s)
U  = P_E x P_S x G
P_succ = P_E x P_S x (P_L 1[d1 <= R] + (1 - P_L) 1[p2 and d2 <= R])
```

An optional v1.1 replaces the road factor with a median ratio measured on 200 (query, facility) pairs from a routing
source that permits it. Until then the card says "straight-line distance x 1.3".

### 6.4 Urgency profiles (assumptions, shown as sliders)

| service | default urgency | D_s km | R start km | R max km | plan |
| --- | --- | --- | --- | --- | --- |
| trauma_emergency | emergency | 30 | 25 | 150 | top + 2 backups, call-ahead first |
| emergency_csection | emergency | 30 | 25 | 150 | top + 2 backups, call-ahead first |
| burn_care | emergency | 100 | 50 | 300 | top + 2 backups |
| nicu | urgent | 50 | 50 | 200 | top + 2 backups |
| dialysis | scheduled (2 to 3 trips a week) | 15 | 25 | 100 | top 3 list |
| mri | elective | 75 | 50 | 300 | top 5 list and Pareto view |
| cardiac_surgery | elective | 150 | 100 | 500 | top 5 list and Pareto view |

A query's urgency field changes only the plan shape and wording (emergency: "call before you leave", backups first
on screen). D_s stays per service, so a ranking never depends on how a user phrased urgency. Candidate radius R
starts at R start and doubles until 3 non-Unlikely candidates exist or R max is reached.

### 6.5 Ranking and referral plan

1. Candidates: facilities within R by d1 (or d2), band not Unlikely, one card per strong duplicate group ("also
   listed as ...").
2. Rank by U. Ties are broken by P_S, then by d1.
3. Plan: the top option, then up to two backups chosen in U order, skipping any facility whose leakage group is
   already in the plan, because copied records fail together. P(at least one works) = 1 - prod(1 - P_succ_j), shown
   with the sentence "assumes the options fail independently".
4. Trade-off line: when the nearest non-Unlikely option is not the top option, both are shown side by side.
5. Pareto view (elective): options not dominated on (P_succ, d1).

### 6.6 Abstention and outside option

- If no Likely option exists within R max, the App says in one sentence: "No facility within 150 km has enough
  public evidence that it offers emergency C-section." It then lists the best Unverified options under the heading
  "call to confirm", and never colours them as verified.
- Outside option: for dialysis and emergency C-section (essential at DH in IPHS 2022), the nearest facility with
  level_dh is listed as "district hospital: the public standard says this level should offer it; not verified in our
  data".
- Phone trust: a phone shared by 3+ cities is shown as "may be a directory number"; none means "no phone in our
  data".

### 6.7 Why the farther option comes first (exact)

For options A (ranked first) and B (nearer), U_A / U_B factors exactly into three ratios that the card prints:

```
U_A / U_B = (P_E,A P_S,A) / (P_E,B P_S,B)  x  (G_A / G_B)
          = evidence ratio                  x  location-and-distance ratio
```

Template: "B is 22 km nearer. Distance alone favours B by 2.1x (exp(22/30)). A's evidence is 3.4x stronger
(0.71 vs 0.21). So A ranks first." The numbers in the example are illustrative; the card computes them from the
stored row, and the test in 7.4 recomputes the product.

### 6.8 Planner mode (optional, cut second)

Per district and service: expected providers = sum over facilities assigned to the district of P_E P_S P_L, P(none)
by the exact Poisson-binomial, joined to NFHS-5 through the nfhs keys in facility_location. The page lists districts
with expected providers below 1, with the caveat that low web presence looks like a gap.

### 6.9 Outputs (ROOT/model/proto/decision/)

benchmark_answers.parquet, one row per (query_id, system, rank): query_id, system, service, query_lat, query_lon,
resolution_note, profile (urgency, D_s, R_used), rank, unique_id, name, d1_km, d2_km, minutes_lo, minutes_hi, P_E,
P_S, P_S_lo, P_S_hi, P_L, G, U, P_succ, band, plan_role (primary, backup1, backup2, list), plan_p_any,
leakage_group_id, abstained (bool), abstain_text, outside_option_uid, why_first_text.

benchmark_answers.json: the same content nested per query, readable by a human, with every number shown.

The decision layer has no fitted parameters, so none of the 40 queries is used for tuning.

## 7. Layer 4: explanation

### 7.1 The card for one recommendation (what a community health worker sees)

Every line is a template filled from one stored row. The source of each number is given in brackets.

```
[1] LIKELY offers dialysis - Lifeline Kidney Centre, Darbhanga            [band, name]
    About 19 km by road (28 to 46 min, rough estimate)                    [d1_km, minutes]
[2] How sure: 0.81 (range 0.70 to 0.89).                                  [p_s, p_s_lo, p_s_hi]
    Of 22 checked facilities with scores like this, 18 were confirmed,    [band_record, split = test]
    1 was wrong, 3 had no public information.
[3] Why we think it offers dialysis (from its listing):                   [cited_atom_ids -> claim_atoms.text]
    [equipment] "6 haemodialysis machines in a dedicated unit"
    [procedure] "Haemodialysis and peritoneal dialysis"
    Sources: one of these pages: <record source_urls>                     [no sentence-to-URL map exists]
[4] Is it real: own website lifelinekidney.example; mobile number,        [facility_contributions, existence]
    not shared with other listings.
[5] Where: PIN, map point and stated city agree (within 3 km).            [location votes]
[6] What we ignored: "Dialysis at Nair Hospital, Mumbai Central"          [rejected_atom_ids, rejected_reason]
    - names a different hospital.
[7] Why this one first: (6.7 sentence, when a nearer option exists)       [U factors]
[8] Call first: +91 ...  If they say no: backup Sadar Hospital, 31 km.    [plan]
```

The facility in this mock is invented to show the layout. Wording rules: "Likely" is never used outside the band
rule; Unverified cards start with "Not verified: call to confirm"; context-only evidence is phrased as "the public
standard says ..." or "large hospitals like this often ..."; numbers are always shown next to words. Templates exist
in English and Hindi with numbers inserted by code.

### 7.2 One click deeper (what a judge sees)

- Three waterfalls in points, one per head. Rows: base (context terms summed and listed), then each evidence term
  with its value on this record, its points, its prior and posterior weight, the number of dev gold pairs where it
  fired, and a link to its reliability.parquet row ("T = 5 on high-risk records: seen at X% of confirmed and Y% of
  not-confirmed dev pairs, n = ...; agreement table says ..."). The bucket row is labelled "weight reduced because
  this record merges 50 web sources".
- Total points, p, interval, and the band rule as a checklist ([x] P_S >= t_L, [x] P_L >= 0.7, [ ] ...).
- Stored counterfactual: "without the 2 quoted sentences, P_S would be 0.34" (p_s_without_cited).
- Live counterfactual: "if a call confirms B (P_S set to 0.95), B would rank 1st", which doubles as the "most useful
  call" marker.
- Ranking arithmetic for the top 3: P_E x P_S x G = U, with G expanded into its two location terms.

### 7.3 Global model card (HOW we decided)

1. Data funnel: 10,088 rows -> 9,959 records -> 69,713 pairs -> 7,300 with a tagged sentence -> bands.
2. Evidence rules: ownership classes, roles, echo collapse, with the hand-check precision of each cue and its n.
3. The three weight tables (weights.parquet): prior source and value, posterior with 90% interval, sign
   constraints, and a "findings" list of sign flips and of weights at their bound.
4. Reliability table: agreement-based and gold-based weights of evidence side by side, with hand-check references.
   A large disagreement is listed as a finding, not hidden.
5. Calibration on test: reliability plot with Wilson bars per bin, ECE with its interval.
6. Band track record (three outcomes, Wilson) on test, and the dev out-of-fold version marked as such.
7. Baselines and ablations with 95% intervals (section 8 and 9).
8. Policy knobs: D_s, R, road factor, speeds, band thresholds, each marked as an assumption.
9. Assumptions in plain words: heads independent given features; plan options fail independently except within a
   leakage group; P_S means publicly confirmable.
10. Failure walk-throughs: Aravind and Wockhardt through every layer (appendix A).
11. Versions: FROZEN hash, model hash, labels hash, date the test split was opened.

### 7.4 How faithfulness is guaranteed

- The score is the sum of the displayed terms: Platt is affine in logit space, the output is not moderated, and the
  build fails if any row breaks the 1e-9 identity (5.9).
- The App reads displayed weights and contributions from the same tables the ranking uses; nothing is recomputed
  by a second model.
- The App recomputes U and the rank order from the numbers on screen and refuses to render a result page if they
  disagree with benchmark_answers or the live computation.
- Every quoted sentence is a claim_atoms row whose text equals the raw parquet item; the build fails otherwise.
- Every rejected sentence shown is a rejected_atom_ids member for that pair, with its stored reason.
- Track-record numbers come from band_record.parquet with its labels hash shown.
- Card text comes from templates. No LLM writes or rewrites any rationale.

### 7.5 Outputs (ROOT/model/proto/explanation/)

cards/{query_id}.json (every field of 7.1 and 7.2 for the top options of each benchmark query), model_card.json (the
content of 7.3 as data), faithfulness_report.json (each test of 4.10, 5.9 and 7.4 with pass or fail and counts).

## 8. Baselines the prototype must beat

All baselines use the same query resolution, the same cleaned point p1 and the same candidate radius, so the
comparison isolates the trust logic.

| id | name | pair-level score | query-level ranking |
| --- | --- | --- | --- |
| B0 | nearest mention | 1 if any lexicon mention, else 0 | nearest facility with any mention |
| B1 | keyword count | number of tagged sentences | count x exp(-d1 / D_s) |
| B2 | rule grade | cleaning grade: strong 0.9, moderate 0.6, weak 0.3, tag_only 0.2, others 0.1 | score x exp(-d1 / D_s) |
| B3 | LLM judge | ai_query yes/no plus self-reported confidence | confidence (0 if no) x exp(-d1 / D_s) |
| B4 | prior only | Witness Ledger with M1 priors, no fitting | same U |
| B5 | gold-only scorecard | M0 fit | same U |

B3 detail: databricks-meta-llama-3-3-70b-instruct (the model already measured on the contaminated records), strict
JSON {offers: yes | no | unclear, confidence: 0 to 1, quote}. The prompt contains the record's name, city, state and
its claim sentences for the service and its prerequisites, truncated to 3,000 characters, and nothing from the web
checks. Scope: test pairs (about 113) and, per benchmark query, the top 10 candidates by B1 (at most 400). Cap: 520
calls in total, batches of 100 in one SQL statement each, one pass, results cached in
ROOT/model/proto/eval/llm_judge.parquet keyed by sha256 of the prompt.

Ablations (same test pass): no ownership filter (rejected atoms count as own), no bucket terms, no echo collapse,
P_L = 1 (location ignored), no context terms, M2 vs M1 vs M0.

## 9. Metrics and evaluation (test split only)

### 9.1 Pair level (service head, and the usable product)

- AUROC: inverse-probability-weighted Mann-Whitney statistic; 95% CI from 2,000 group-bootstrap resamples over
  leakage groups, stratified by sampling cell. AUPRC is reported alongside.
- Precision at the confirmed threshold: precision of the Likely band; raw k/N with a Wilson 95% interval and the
  weighted estimate with its bootstrap interval. NPV of Unlikely and coverage (share not Unverified) the same way.
- Calibration: 5 equal-count bins; ECE = sum over bins of (n_b / N) |observed_b - mean p_b|, weighted, with a
  bootstrap 95% CI; the reliability table lists per bin n, mean p, observed rate, Wilson interval and the
  three-outcome counts. Brier score and log loss are secondary.
- The same metrics for P_L against location_matches and for P_E x P_L x P_S against the usable target.
- Paired differences against each baseline: bootstrap the difference over the same resamples.

### 9.2 Query level (40 benchmark queries)

- Pooling: the top 1 of every system (Witness Ledger and B0 to B5) and ranks 2 and 3 of Witness Ledger and B0 are
  pooled (at most 40 x 7 + 40 x 4 = 440 pairs before overlap) and labelled once with the full protocol. Unjudged pairs count as not verified.
- success@1: the top-1 option exists, is confirmed for the service, and its verified location is within R used of the
  query point. A system that abstains scores a success only when no pooled pair within R max is confirmed.
- precision@1 over answered queries, Unsafe@1 (top-1 contradicted, wrong location or nonexistent), success@3, and
  median extra km of the top-1 option over the nearest-mention option.
- Intervals: Wilson for single proportions. Paired comparisons use an exact McNemar test and a 10,000-resample paired
  bootstrap over queries.
- Predicted vs observed P(at least one plan option works), reported as a calibration pair with n.

### 9.3 Served-evidence quality

Harmful misattribution rate: among the quotes shown on the top-3 cards of the 40 queries, the share that describe a
different facility (human-checked, Wilson 95%). The sentence proposal's pre-quarantine reference was 11/30.

### 9.4 Subgroups and sensitivity

Focus states (Bihar, Jharkhand, Odisha, Assam, Chhattisgarh) vs the rest; independent-source confirmations only;
no_info recoded as missing (secondary target); per service where n >= 15, else pooled, and the card says pooled.

### 9.5 Acceptance rules (fixed now, before any test label is read)

| id | rule |
| --- | --- |
| A1 | Service-head AUROC point estimate above B2 and B3; "better" is claimed only when the paired interval excludes 0 |
| A2 | The shipped prior's dev CV log loss beats M0 by at least one SE, else M0 ships (5.3) |
| A3 | Test ECE of P_S at most 0.10 |
| A4 | Likely precision at least 0.85 with Wilson lower bound at least 0.70 |
| A5 | success@1 at least B0 + 10 points, and Unsafe@1 not above B0 |
| A6 | Aravind and Wockhardt dialysis not Likely; every faithfulness test passes |

Power, so that nobody over-reads the results (computed with the Wilson formula): 34 of 40 Likely pairs correct gives
0.71 to 0.93; 32 of 40 queries correct gives 0.65 to 0.90. A 10-point success@1 difference on 40 queries is near the
edge of what can be detected, and the model card says so. A failed rule is reported as failed. Nothing is retuned
on test.

## 10. Label plan and budget

1. v2 sample, 140 pairs (dev 69 first, then test 71), full protocol, with the 30 overlap pairs double-labelled.
2. U sample, 84 pairs, drawn by a seeded script after FROZEN. Inclusion probabilities are stored next to the pairs.
3. Benchmark pool, at most 440 pairs, labelled after all systems have written benchmark_answers.parquet.
4. 100-sentence attribution check (4.2).

Target total: 36 + 140 + 84 = 260 pair labels plus the pool. Web checks are agent-assisted and human-reviewed. A
label is final only after a person has read the evidence URL.

## 11. Build order and parallel ownership

| step | owner | depends on | done when |
| --- | --- | --- | --- |
| 1 | evidence | inputs only | claim_atoms, pair_features, facility_features, FROZEN; tests 4.10 pass |
| 1 | labels | nothing | v2 dev labelled; priors_M1.json dated before reading it |
| 1 | decision | fallback scores (6.1) | benchmark_answers for B0, B1, B2 on 40 queries |
| 1 | explanation | fallback tables | card templates and the faithfulness harness |
| 2 | fusion | evidence, v2 dev labels | M0 and M1 fitted, dev CV, pair_scores, tests 5.9 pass |
| 3 | fusion | step 2 | M2 Dawid-Skene pass, reliability table, model selection |
| 3 | labels | FROZEN | U drawn and labelled; v2 test labelled into the sealed file |
| 4 | eval | all of the above | one test run, benchmark pool labelled, metrics with intervals |
| 5 | App | step 4 | Databricks App reads the Delta copies of these parquet files; restart before judging |

Cut order if behind: R role classifier, planner mode, M2 Dawid-Skene (the agreement columns of the reliability table
then show "not run"), Pareto view, Hindi templates. Never cut: the ownership filter, cited quotes, rejected-evidence
display, intervals, the sealed test, grouped splits, the three-outcome track record and the faithfulness tests.

Free Edition: all fitting runs offline on CPU with numpy (no scipy needed). One serverless notebook copies the
parquet outputs to Delta in one Unity Catalog schema. This needs build-phase write permission, which this design
step did not use. The App (2 vCPU, 6 GB) loads pair_scores, facility_scores, claim_atoms and the gazetteer once at
start through the SQL warehouse, then does haversine, U, plan and cards in memory. The default path makes no
ai_query, model-serving or GPU call.

## 12. Risks and known limits

- Few labels: about 150 dev and 113 test pairs. Intervals will be wide, and per-service results will often be
  pooled. Priors dominate rare terms; the sign-flip list makes that visible.
- Residual dependence between families (T, C and P come from one LLM extraction): the shipped weights are fitted on
  gold jointly, so dependence lowers efficiency rather than inflating the points. The agreement-based M2 table can
  still over-count, which is why it serves only as a prior and must beat M0 on dev.
- 95% of service sentences carry no anchor (Aravind). The record-level bucket, scope and location terms catch some
  of these and also penalise true claims on the same records. That cost is reported in the ablations.
- Target mismatch: publicly confirmable is not the same as offers. Public facilities with little web presence score
  low; the card says "little public evidence", and the outside option partly offsets it.
- Self-consistent contamination (PIN, coordinates and text copied from one wrong page) is caught only when the name
  or stated city dissents, as with Wockhardt.
- Distance is straight-line x 1.3 with assumed speeds. It is labelled as a rough estimate and is wrong in hilly and
  riverine districts.
- The cleaning outputs were still changing while this spec was written (disputed locations 177 in s2_stats.json vs
  505 in the parquet). FROZEN pins the input hashes.
- Free Edition: daily quota and the 24-hour App auto-stop. Judges must be workspace users.

## Appendix A: worked cases (also unit tests)

Wockhardt Hospital Nagpur (3ac5ae50), dialysis. Evidence: proc:17 and equi:7 are rejected (names Nair Hospital,
Mumbai Central); capa:24 (concessional pricing per session) and equi:43 ("In-house dialysis units") count as own,
in two fields, one with a unit, so T = 5 and C = 1. Bucket high. Location: p1 is in Mumbai Suburban (PIN 400078 and
listing coordinates agree), p2 is Nagpur (677 km away); the city and name-place votes are -1 and the PIN and
coordinate votes +1, so P_L sits near the middle and the band rule (P_L >= 0.7) blocks Likely. Expected card:
"Not verified: we are not sure where this is. Name and city say Nagpur; PIN and map point say Mumbai", with the two
rejected Nair Hospital sentences shown. B2 grades this pair moderate and B0 ranks it for any Mumbai dialysis query.

Aravind Eye Hospital (b8a5401f), dialysis. Evidence: 8 unanchored sentences, among them "a 20-bed Dialysis Unit
with 10 machines as part of the Pradhan Mantri National Dialysis Programme", so T = 5, while S = 1 (eye hospital)
and the bucket is high (shared content, 50 URLs). Location: loc_conf low, PIN in Delhi, coordinates 1,871 km away,
point taken from the Hyderabad city centre. The service head may still score this pair high, because the text is
strong and nothing anchors it elsewhere. The location head and the band rule keep it out of Likely, and the card
names all three conflicting locations. This case is the reason the model card states that ownership filtering alone
does not catch unanchored contamination. B3 is expected to answer yes with high confidence, as llama-3-3-70b did when
it was measured.
