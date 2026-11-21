# Witness Ledger: final model spec with measured results

Status (2026-11-21). The evidence, fusion and decision prototypes are built and were run on all 10,088
records. A statistical review and an explainability review then recomputed their numbers. This spec is
the build contract for the weekend and the judges' reference. It covers what the model does, what it
measured, which claims failed review, and what changes before the App ships.

Every number names its source file. Paths are relative to ROOT = /Users/karthikvattem/projects/datathon.
Short forms: P = ROOT/model/proto, RV = ROOT/model/review, G = ROOT/model/gold. The model whose
numbers are reported is hash de82eeee9ea0d0f6-fallback (P/fusion/model_selection.json). "Fallback"
means fusion derived its families from the cleaning tables, not from P/evidence. "Not run" means not
run.

## 1. The approach

Witness Ledger treats every piece of a record as a witness. That includes a sentence, a structured
field, a PIN, a map pin, the place in the facility's name and a phone number. For each (facility,
service) pair it estimates three probabilities: the facility exists (P_E), it is where we think it is
(P_L), and a public check would confirm it offers the service (P_S). Each probability comes from an
additive logistic scorecard of named, sign-constrained terms. The points shown on screen are therefore
the computation, not a summary of it. Rules run before any sentence counts: they decide whether the
sentence is about this facility at all, and copies of one sentence across fields are collapsed into one
unit. Sentences that name another hospital, branch or state are removed and listed as "What we
ignored". The App ranks candidates by U = P_E x P_S x G, where G is a distance discount weighted by
location belief. It returns a call-first plan with backups from distinct copied-content groups. When no
option clears the evidence bar, it says so in one sentence. Uncertainty is reported as three-outcome
counts from web-checked labels (confirmed, contradicted, no public information), never as an LLM's
self-confidence. No LLM sits on the trust or explanation path. Measured on the benchmark candidates,
the LLM judge said yes on 239 of 243 (P/decision/llm_b3_stats.json).

```
 data/raw/facilities.parquet  10,088 rows
   | cleaning/claims (469,498 sentences), audit/merge, cleaning/geo_identity, audit/identity, external lists
   v
 L1 EVIDENCE (offline, rules, 34 s on a laptop CPU)
   22,787 claim atoms -> ownership + role -> counts_as_own -> echo collapse -> 15,550 units
   per pair (69,713):  T text  C contamination  N non-offer  S scope  P prerequisites  X list  R role model
   per facility (9,959): 7 location votes, existence witnesses, leakage_group_id (8,562 groups)
   |
   v
 L2 FUSION (offline, numpy only, about 3 min)          gold labels: dev CV only, sealed test opened once
   P_S head (pair)      P_L head (facility)      P_E head (facility)
   z = base + sum of term contributions (stored per term); P = sigmoid(z)
   badge per pair: LIKELY | CALL FIRST | NO SERVICE TEXT | PLACE UNCLEAR | UNLIKELY
   |  Delta tables (section 3.6)
   v
 L3 DECISION (live in the App, closed form, no fitted parameters)
   query -> resolve place (asks when ambiguous) -> candidates within R -> U = P_E x P_S x G
   -> plan: top + 2 backups from distinct leakage groups -> answer or abstain + outside option
   |
   v
 L4 EXPLANATION (live, templates over stored rows, no LLM)
   level 0 phone card | level 1 "why this one" | level 2 points waterfall | global model card
   gate: App recomputes U and rank from displayed numbers and refuses to render on a mismatch
```

## 2. What makes it unique

1. The explanation is the computation. Platt scaling is affine and the output is not moderated, so
   base + sum of displayed contributions equals the shipped logit. Measured maximum error: 8.9e-16 over
   69,713 service rows, and 4.4e-16 for location and existence (P/fusion/tests_report.json). A
   deletion test on 1,105 pairs zeroes one family at a time and checks that the score changes by that
   family's displayed points, with maximum error 5.6e-16. The decision layer recomputes G, U, P_succ
   and rank order on 1,929 rows with error 0.0. The "why the farther one first" identity holds to
   3.0e-16 over 462 rows (P/decision/faithfulness_report.json). An independent reviewer rebuilt the
   Panipat card by hand from model.json and matched every stored number to 1e-15
   (RV/explain/recompute_s1.json). Screen: the level 2 waterfall (section 5.2).
2. Attribution comes before counting, and the rejected evidence is shown. For Wockhardt Hospital
   Nagpur, "Provides dialysis treatment at Nair Hospital, Mumbai Central" and "Dialysis machines
   donated by Jivan Jyot Drug Bank are used at Nair Hospital, Mumbai Central" are rejected and listed
   with the hospital named. The record ranks 51 of 63 dialysis candidates for Nagpur
   (RV/explain/probe_ranks.json). The llama-3.3-70b judge said "yes, confidence 1" on this record and
   on Aravind. Measured limit: ownership rejection changes only 130 of 69,713 pairs, and the
   no-ownership ablation is within noise (section 4.11).
3. Location is its own probability, with named witnesses. On test, 30 of the 33 pairs with
   P_L >= 0.7 had their location confirmed by the web check (Wilson 0.76 to 0.97;
   P/fusion/test_metrics.json). The card names which witnesses support each candidate point and
   leads with a [PLACE UNCLEAR] badge when they disagree (section 5.1). Known miss: Sharda Hospital
   (section 8).
4. The uncertainty display measures the labels as well as the model. Each card shows the three
   outcomes behind its score bin. The model card also reports what the gold labels measure. When both
   labellers reached a verdict they agreed 6 of 6 times. All 9 disagreements were "found something"
   against "found nothing". P_S predicts whether a pair was searched at all with AUROC 0.736
   (RV/stats/results.json). The model card states this, and never-searched pairs are treated as
   missing (section 3.2).
5. An LLM is used only where it measurably helps. As a pair-level judge it is weak: raw AUROC 0.585
   [0.486, 0.685] against Witness Ledger's 0.776, a paired gain of +0.191 [0.090, 0.284]
   (RV/stats/results.json). As a classifier asked "is this sentence about this facility", the same
   model beats the rules by +0.037 [0.009, 0.076] on 108 test sentences
   (P/evidence/sentence_metrics.json). So it enters only as the optional family R: a verified, cached
   sentence classifier whose output is one more scorecard term.

## 3. The layers

### 3.1 Evidence layer (offline)

Method: deterministic rules over the cleaning outputs. No learned parameters. Code: P/evidence/{atoms,
facility,build}.py. Inputs are pinned by sha256 in P/evidence/FROZEN.json.

Claim atoms. There is one atom per (claim sentence, service) for the 7 services (dialysis,
emergency_csection, nicu, cardiac_surgery, mri, burn_care, trauma_emergency), plus one per
specialties-enum hit: 22,787 atoms (P/evidence/build_stats.json). Each atom gets:
- ownership: unanchored 21,842, own_anchored 771, ambiguous 81, other_facility 70, sibling 21,
  other_place 2.
- role: offer 11,545, unit_or_equipment 5,641, list 5,008, quantity 341, directory 101, staff 72,
  nonoffer 54, research_or_template 18, hedge 7.
- counts_as_own = ownership in {own_anchored, unanchored} and role in {offer, unit_or_equipment,
  quantity}: 17,403 atoms.
- rejected_reason with the named entity, e.g. names_other_facility: "Nair Hospital, Mumbai Central".
- Echo collapse: single-link clustering within (facility, service) at rapidfuzz ratio >= 85 gives
  15,550 units. One sentence repeated in two fields counts once. The test changes T from 4 to 2 on that
  input (P/evidence/test_evidence.py test_echo_collapse, passing in test_results.json).

Families per pair (one vote per family, so the single LLM extraction behind all fields is not counted
several times):

| family | values | definition | measured distribution (build_stats.json) |
| --- | --- | --- | --- |
| T text_own | 0-5 | 0 none; 1 enum or list only; 2 one own unit; 3 2+ units in one field; 4 units in 2+ fields; 5 level 4 plus a unit or quantity | 61,744 / 1,083 / 3,178 / 1,388 / 883 / 1,437 |
| C contamination | 0-2 | rejected-for-ownership atoms alongside T >= 2 (1) or with T <= 1 (2) | 69,589 / 86 / 38 |
| N non-offer | 0/1 | an atom with a non-offer cue (referral, camp, future, negation) | 43 pairs |
| S scope | 0/1 | eye, dental, IVF or lab facility claiming the service | 20,531 pairs |
| P prerequisites | 0-2 | distinct prerequisite cues (ICU, OT, blood bank...) in sentences not about the service | 48,180 / 17,028 / 4,505 |
| X external list | on / absent / abstain | government or registry list (3.1 v2 change 4) | abstains everywhere today |
| R role model | 0-2 | own-offer units confirmed by the optional LLM classifier | not built |

Context (not votes): merge bucket g (low 3,281, mid 3,685, high 2,993 records), list_truncated,
facility type, operator, public level from name patterns, iphs_essential, and beds, doctors and
specialty-breadth bins.

Location votes per facility, each +1, -1 or 0 against the primary point p1, also computed against
the alternative p2:

| witness | +1 / -1 / 0 |
| --- | --- |
| coordinates | 8,788 / 1,165 / 6 |
| PIN centroid | 9,193 / 682 / 84 |
| stated city | 8,041 / 486 / 1,432 |
| place in the name | 824 / 70 / 9,065 |
| stated state | 9,798 / 80 / 81 |
| PIN written in text | 266 / 93 / 9,600 |
| name-matched map link | 652 / 255 / 9,052 |

Existence witnesses: website class, phone class (directory number if seen in 3+ cities), source
multiplicity, recency, coordinate shared by 3+ names, pharmacy, strong duplicate member.

Leakage groups: union-find over strong duplicate groups, official domain, official phone, chain and
shared source_content_id. Phone and domain keys seen in 3+ cities are skipped. The result is 8,562
groups; the largest has 133 members. They drive the splits, the bootstrap and the plan rule.

v2 changes, all from the reviews, all to be made before the fresh test:
1. Store raw_pos next to idx. 2,171 of 18,936 list atoms (0.115, Wilson 0.110 to 0.119) sit at a
   different raw position, because blank items are skipped when indexing; 18,934 of 18,936 texts do
   appear verbatim (RV/explain/proposed_cards.txt). The quote test must compare against the untouched
   raw array.
2. Derive the type from name and specialties when facilityTypeId is "clinic". type_dentist fired on 0
   dev pairs (P/fusion/weights.parquet), so Smile Kraft Dental Clinic ranked first for trauma. Set
   S = 1 from name or specialties even when grades has no row (Nayan Jyoti Eye Hospital was the
   primary option for emergency C-section, q06).
3. Use one set of place layers for query resolution and for the city vote. Count a stated city that
   cannot be placed, or a PIN missing from India Post, as a dissent, not an abstention. 22 of 181
   benchmark cards (Wilson 0.08 to 0.18) had a city vote that silently abstained
   (RV/explain/audit_benchmark_cards.json).
4. Family X from external lists, with each list's hand-checked match precision as its prior. These
   are the only evidence not produced by the same web extraction:
   - LaQshya Maternity OT certificates (C-section): 58 matched VF rows, hand check 17 correct, 3
     plausible, 0 wrong of 20. For 44 matched public facilities it is the only C-section evidence
     (external/laqshya_master/README.md).
   - NMC postgraduate courses (DM Nephrology for dialysis, MCh CTVS for cardiac surgery, MCh Plastic
     Surgery for burns, and so on): 81 matched rows (external/nmc_colleges/README.md). A course shows
     that a department exists, not that the service runs today, so the prior is weaker.
   - MoHFW trauma care facilities: 20 accepted matches, 19 of 20 correct (external/mohfw_trauma_196/README.md).
   - OSM health facilities as an existence witness only: 3,532 matches, 15 of 20 correct or likely
     correct (external/hotosm_ind_health_facilities/README.md).
   A list used as X is never used as an evaluation label.
5. Feed fusion from P/evidence outputs instead of the fallback. This changes the model hash, so every
   test label read so far moves to dev (5.7 of the v1 rules).

### 3.2 Service head P_S (offline fit, stored scores)

Model (identical for all three heads):

```
z(i)    = b_s + sum_j w_j x_j(i)                 x_j are 0/1 indicators; ordinal families use steps 1[T >= v]
z*(i)   = a z(i) + c                             Platt; a = 1, c = 0 unless it passes the rule below
P(i)    = sigmoid(z*(i))                         shipped point estimate, not moderated
contrib_j(i) = a w_j x_j(i);  base = a b_s + c   exact identity: base + sum_j contrib_j = z*
points  = (20 / ln 2) x contrib                  +20 points doubles the odds
prior   w_j ~ N(mu_j, sd_j^2), sign constraints: evidence steps >= 0, C, N, S <= 0
monotone composite constraints: t2 + t2@s + tb_g >= 0 and t1 - trunc0 >= 0 (sign constraints alone
        let one more own unit lower the score; P/fusion fit notes)
fit     MAP by Newton with case weights; active set (a violated constraint becomes an equality), at most 10 rounds
```

Terms (P/fusion/model.json): 7 intercepts; evidence t1-t5, tb_mid, tb_high, trunc0, c1, c2, n1, s1,
p1, p2 (x_on, x_absent, r1, r2 when X and R exist); context g_mid, g_high, type_*, public, level_*,
iphs_essential, beds_*, doctors_*, breadth_*, scale_contradiction; service deviations for t2, t4 and
p1 with sd 0.5. That is about 60 weights.

Target. y = 1 if the web check confirmed the service. y = 0 if it was contradicted, or if it was
searched (at least one evidence URL) and found nothing. Never-searched pairs are missing, in training
and in evaluation. The prototype trained on this rule but the contract-literal test still coded them
0. The review showed that 32 of 71 test labels were never searched and that P_S predicts searching
with AUROC 0.736. P_S therefore means "chance a public web check confirms it", and the card says
exactly that.

Model selection (v2 rule, dev only, grouped 5-fold CV by leakage group):
- Candidates: B4 prior-only (M1 means, no fitting), prior-only plus Platt, M1 fitted, M0 fitted
  (zero means, sd 2.5). M2 (Dawid-Skene agreement priors) stays an ablation. It over-counts
  dependent families (t1 prior mean 5.17 against M1 0.40) and lost on dev (P/fusion/weights.parquet,
  model_selection.json).
- Ship the least-fitted candidate unless a more-fitted one beats it on out-of-fold log loss by at
  least one paired SE. In v1 M0 played the "simple" role, although with about 60 free weights it was
  the most flexible candidate.
- Platt is used only when its out-of-fold gain is at least one SE. The prototype kept a = 0.38 on a
  gain of 0.0011 with SE 0.067 (P/fusion/platt.json). That slope shrank every evidence term by 62%
  and capped P_S at 0.733, so 40 of 40 benchmark queries abstained.
- Disclosure: this rule was written after the test showed B4 ranking at least as well as the fitted
  model (section 4.2). The current test therefore cannot evaluate v2, and section 7 adds a fresh test.

Prior means (M1, P/fusion/priors_M1.json, dated 2026-11-21T13:29:11): each is a log likelihood
ratio from a named audit rate, for example n1 = -1.67 from the non-offer hand check (34/40) and the
t-steps from the v1 strata. That file was written after the builder had read v2 dev notes and the
marginal label counts, so it is not "fixed before labels" (section 4.12).

Intervals: draws from the truncated Laplace posterior plus a 200-replicate group bootstrap of Platt.
In the prototype only 1.4% of draws were accepted (P/fusion/model_selection.json). v2 keeps drawing
until 1,000 draws are accepted and records the acceptance rate. The 90% range is shown on the judge
view only. The lay card shows the empirical score-bin record instead.

Badges (replace the v1 three bands; reviewer layout rule 2):

| badge | rule |
| --- | --- |
| LIKELY | P_S >= t_L and P_L >= 0.7 and P_E >= 0.7 and T >= 2; add "(borderline)" when P_S - t_L < 0.05 |
| CALL FIRST | not Likely, not Unlikely, T >= 2 |
| NO SERVICE TEXT | not Likely, not Unlikely, T < 2 (context or prerequisite only) |
| PLACE UNCLEAR | overlay: P_L < 0.7, or any location vote is -1, or the stated city or PIN cannot be placed |
| UNLIKELY | P_S <= t_U, or C = 2 with T <= 1 |
| ON A PUBLIC LIST | overlay when X = on, with the list name and validity date |

t_L is the smallest dev threshold with out-of-fold precision >= 0.85, and t_U the largest with NPV
>= 0.90, when at least 20 dev pairs lie beyond them. Otherwise the fallbacks t_L = 0.70 and
t_U = 0.20 apply and the model card says so. The prototype used both fallbacks
(model_selection.json).

### 3.3 Location head P_L and existence head P_E (offline)

Location: logit P_L = b + sum of vote weights x vote + flag terms, one row per facility. P_L is the
probability that the facility is within 25 km of p1. Training rows: 121 (65 dev gold, 30 geo hand
verdicts, 26 cleaning hand checks; 20 negatives). The prototype shipped M0, which put weight 0 on the
coordinate and name-place votes and +2.19 on the city vote (P/fusion/weights.parquet). v2 changes:
- The remaining mass 1 - P_L goes to p2 only when a witness other than the raw pin supports p2;
  otherwise it goes to "unknown", which earns no utility. Referal Hospital (q01) put 64% on a map pin
  whose own vote was -1.
- City-vote cut-off: one radius for the vote and for loc_note. The Nalanda centre was 29.5 km from p1
  against a 25 km cut-off, while the note said it "lies near the postcode".
- Candidate flag f_remote_cell from the MAP 2020 motorized travel-time raster. 56% of facility points
  with tt_motor > 10 min (83 of 149) are flagged geo_conflict, against 14.9% overall
  (external/map_travel_time_healthcare_2020/README.md). It enters only if it wins on dev.

Existence: 5 dev negatives, so the head ships prior-only (expert settings, n >= 15 negatives needed
to fit). The card says "existence weights are expert settings, not learned". v2 fix: phone_class and
the displayed phone come from one source. The Panipat card took -0.7 logit for "no phone" while
showing a number (RV/explain/recompute_s1.json).

### 3.4 Decision layer (live in the App)

```
d1 = 1.3 x haversine(query, p1) + loc_radius_km           1.3 = road factor (assumption, slider)
d2 = same for p2 when p2 has a supporting witness
G  = P_L exp(-d1/D_s) + (1 - P_L) 1[p2 supported] exp(-d2/D_s)
U  = P_E x P_S x G
P(within R) = P_L 1[d1 <= R] + (1 - P_L) 1[p2 supported, d2 <= R]        must be >= 0.5 to be a candidate
P_succ = P_E x P_S x P(within R)
why first:  U_A / U_B = (P_E,A P_S,A / P_E,B P_S,B) x (G_A / G_B)          printed as one sentence
plan P(any) = 1 - prod(1 - P_succ), options from distinct leakage groups (independence assumed)
```

Per-service profiles (assumptions, shown as sliders): D_s / R start / R max in km. Trauma and
C-section 30/25/150, burns 100/50/300, NICU 50/50/200, dialysis 15/25/100, MRI 75/50/300, cardiac
surgery 150/100/500. R doubles until 3 non-Unlikely candidates exist. Query urgency changes only the
plan shape. Measured sensitivity: the top-1 changes on 8 of 40 queries at D_s x 0.5, 11 at D_s x 2,
10 at road factor 1.0 and 7 at 1.6 (P/decision/sensitivity.json). About a quarter of answers depend on
these unmeasured knobs, and the model card says so.

Place resolution reuses audit/geo/resolve_input.py and accepts a PIN, "village, district, state", a
district, a city or coordinates. A name found in two states (for example "Aurangabad") returns the
list and asks the user. All 40 benchmark places resolve, landing 0.0 to 11.5 km from the stored point
(P/decision/run_stats.json). v2: echo the point actually used. For q35 the echo said "district median"
while the distances used the GPO point 4.4 km away.

v2 plan rules (reviewer):
- Emergency services (trauma, C-section, burns) never lead with a NO SERVICE TEXT or PLACE UNCLEAR
  option. Backup slots take only CALL FIRST or LIKELY options; otherwise the card says "no second
  option found".
- Abstention: "We found no facility within 150 km whose listing says it does emergency C-sections and
  whose location we trust." The outside option for dialysis and C-section is the nearest district
  hospital with P_L >= 0.7 inside R max, labelled "the public standard says this level should offer
  it; not verified in our data". This guard was added after reading benchmark output (disclosed).
- Near-tie notice when adjacent U ratios are below 1.1: "options 1 to 3 are close; any is a
  reasonable first call".

### 3.5 Leakage controls (all layers)

- Splits by sha256 of the duplicate cluster; all services of a facility and all members of a leakage
  group share one split and one CV fold. No unique_id is shared between train and test. 2 leakage
  groups were shared, and those 2 dev rows were dropped (RV/stats/results.json, model_selection.json).
- No feature reads a web verdict or URL. LLM prompts contain only the record's own text. X lists are
  never labels.
- The test is read only by one sealed script (FUSION_SEALED_EVAL=1), and each opening is logged with
  a reason and diff (P/fusion/test_open_log.jsonl).
- Any change to features after a test label is read moves that label to dev. v2 applies this, so the
  39 searched v2 test pairs become dev data.
- The 40 benchmark queries are never used for tuning. WLpost_T2gate was built after reading benchmark
  output and is excluded from all comparisons.

### 3.6 Delta tables (Unity Catalog: workspace.vf_ledger)

Offline jobs write every table. The App only reads them, except app_query_log.

| table | grain, rows | columns |
| --- | --- | --- |
| claim_atoms | atom, 22,787 | atom_id str, claim_id str, unique_id str, field str, idx int, raw_pos int, text str, service str, ownership str, role str, specificity str, counts_as_own bool, rejected_reason str, named_entity str, unit_id str, is_unit_rep bool, attribution_score double, attribution_n int, support_score double, support_n int |
| pair_features | pair, 69,713 | unique_id, service, T, C, N, S, P, X, R int (null = abstain), bucket str, list_truncated bool, n_units_own int, n_fields_own int, cited_atom_ids array<str>, rejected_atom_ids array<str>, prereq_atom_ids array<str>, grade str, context columns |
| facility_features | facility, 9,959 | unique_id, name, p1_lat, p1_lon, p2_lat, p2_lon, p2_supported bool, loc_radius_km, district, state, v_coords, v_pin, v_city, v_name, v_state, v_text_pin, v_map int, loc_note str, phone str, phone_class str, website_class str, leakage_group_id str, group_size int, x_lists array<struct<list,service,valid_to,source_url>> |
| pair_scores | pair, 69,713 | unique_id, service, z_raw, z_cal, p_s, p_s_lo, p_s_hi, badge str, badge_reason str, p_s_without_cited, score_bin int, model_hash str |
| pair_contributions | pair x term, about 480k (478,734 in the prototype) | unique_id, service, term, group (base, text, prerequisite, list, contamination, context), x_value, fitted_weight, platt_a, contribution_logit, points |
| facility_scores | facility, 9,959 | unique_id, p_e, p_e_lo, p_e_hi, p_l, p_l_lo, p_l_hi, existence_fitted bool |
| facility_contributions | facility x head x term, about 92k (91,901) | unique_id, head, term, x_value, fitted_weight, contribution_logit, points |
| weights | head x term x service | prior_source, prior_mean, prior_sd, derivation str, post_mean, ci90_lo, ci90_hi, sign_constraint, at_bound bool, sign_flip bool, n_fired_dev, n_fired_all |
| score_bin_record | head x split x bin | split (dev_oof, test), p_min, p_max, n, mean_p, k_confirmed, k_contradicted, k_no_info, k_never_searched, wilson_lo, wilson_hi, labels_sha256 |
| reliability | family x value x bucket | dev_n_conf, dev_n_not, dev_woe, agree_woe (M2), hand_check_ref str |
| model_meta | 1 row per model | model_hash, frozen_sha256, labels_sha256, created_at, platt_a, platt_c, t_L, t_U, fallback_used bool, test_openings int, selection_json str |
| gazetteer | PIN office, 165,627 | pincode, office, district, state, lat, lon, layer |
| benchmark_answers | query x system x rank, 2,600 (prototype) | query_id, system, rank, unique_id, d1_km, d2_km, P_E, P_S, P_L, G, U, P_succ, badge, plan_role, plan_p_any, abstained, why_first_text |
| app_query_log | one row per App query | ts, service, place_input, resolved_point, model_hash, top_uids array<str>; no personal data |

## 4. Results (test split, statistical reviewer's recomputation)

All figures are from RV/stats/results.json unless another file is named. Where the prototypes and the
reviewer differ, the reviewer's numbers are used. Intervals are 95%: cluster bootstrap over leakage
groups (2,000 resamples) for AUROC and ECE, Wilson for proportions.

### 4.1 What the labels are

| set | pairs | outcome |
| --- | --- | --- |
| v1 web gold | 36 | all dev (read during design) |
| v2 test | 71 | 17 confirmed, 1 contradicted, 53 no_info, of which 32 were never searched; IPW ESS 29.0 |
| v2 dev | 69 | 14 confirmed, 3 contradicted, 52 no_info |
| overlap (double-labelled) | 30 | kappa below |
| end-to-end pool | 158 | 125 labelled (16 confirmed, 15 contradicted, 94 no_info), 33 not run, 60 labelled with no URL |

All labelling batches shared one budget of 200 WebSearch calls, which ran out early (G/labels_p1.json
note). Never-searched counts were 16 of 70 in the first 10 pairs of each batch and 42 of 70 in the
last 10.

### 4.2 Pair-level discrimination, P_S vs baselines

Primary target (confirmed = 1, else 0), raw AUROC:

| system | all 71 test | searched only (39, 17 pos) | IPW, all 71 | WL minus system, raw, all 71 |
| --- | --- | --- | --- | --- |
| WL shipped | 0.776 [0.680, 0.862] | 0.711 [0.614, 0.810] | 0.615 [0.406, 0.866] | |
| B0 any mention | 0.560 [0.471, 0.647] | 0.548 [0.444, 0.652] | 0.557 [0.445, 0.805] | +0.216 [0.109, 0.316] |
| B1 keyword count | 0.712 [0.590, 0.839] | 0.697 [0.556, 0.837] | 0.585 [0.458, 0.861] | +0.064 [-0.047, 0.164] |
| B2 rule grade | 0.697 [0.580, 0.826] | 0.693 [0.569, 0.823] | 0.583 [0.459, 0.860] | +0.078 [-0.035, 0.183] |
| B3 LLM judge (llama-3.3-70b) | 0.585 [0.486, 0.685] | 0.533 [0.416, 0.644] | 0.563 [0.427, 0.793] | +0.191 [0.090, 0.284] |
| B4 prior only (M1, unfitted) | 0.789 [0.692, 0.875] | 0.754 [0.639, 0.864] | 0.684 [0.483, 0.906] | -0.013 [-0.076, 0.048] |
| B5 gold only (M0) | 0.687 [0.566, 0.795] | 0.655 [0.569, 0.750] | 0.491 [0.350, 0.679] | +0.088 [0.019, 0.165] |
| stratum label alone | 0.671 [0.562, 0.796] | 0.673 [0.548, 0.802] | 0.567 | +0.105 [-0.018, 0.218] |

The strata were built from the model's own features, so the circularity control is the pooled
within-stratum AUROC. Values: WL 0.737 [0.586, 0.873], B4 0.717 [0.563, 0.834], B1 0.650 [0.548,
0.760], B5 0.639 [0.497, 0.787], B2 0.577 [0.490, 0.680], B3 0.505 [0.427, 0.583]. No paired
interval was computed for these.

Confirmed against contradicted: 17 against 1. No AUROC is reported, because each value would be the
rank of one pair.

Decision product P_E x P_L x P_S on the usable target (exists, location and service all confirmed),
39 searched test pairs, 15 usable: WL 0.719 [0.536, 0.870]; with P_L = 1, 0.683, a difference of -0.036
[-0.114, +0.024] (P/decision/eval_metrics.json).

### 4.3 Calibration of P_S (5 equal-count bins, all 71 test pairs)

ECE raw 0.097 [0.078, 0.180]; ECE IPW 0.197 [0.143, 0.292]. Mean P_S 0.337 against an observed 0.239.
On the searched set, ECE raw is 0.107 [0.067, 0.227] and IPW 0.147.

| bin | P_S range | n | mean P_S | confirmed share [Wilson] | confirmed / contradicted / no_info |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.086-0.239 | 15 | 0.187 | 0.00 [0.00, 0.20] | 0 / 0 / 15 |
| 1 | 0.240-0.285 | 14 | 0.269 | 0.14 [0.04, 0.40] | 2 / 0 / 12 |
| 2 | 0.288-0.363 | 14 | 0.317 | 0.21 [0.08, 0.48] | 3 / 1 / 10 |
| 3 | 0.365-0.429 | 14 | 0.406 | 0.36 [0.16, 0.61] | 5 / 0 / 9 |
| 4 | 0.433-0.610 | 14 | 0.514 | 0.50 [0.27, 0.73] | 7 / 0 / 7 |

The ranking is monotone in the bins. Among decisive labels only, 17 of 18 were confirmed while mean
P_S was 0.42. P_S is not a probability that the facility offers the service, and the card never
words it that way.

### 4.4 Precision at the decision threshold

- Likely band: N = 0 on test; 2 of 69,713 pairs overall (both Civil Hospital, Panipat). Maximum P_S
  0.733. A4 is not testable.
- At P_S >= 0.50 (an ad hoc diagnostic threshold, not shipped): 8 pairs, 4 confirmed, 0 contradicted,
  4 no_info. Confirmed share 0.50 [0.22, 0.78].
- For comparison, B2 "strong": 13 called, 9 confirmed, 0 contradicted (share 0.69 [0.42, 0.87]).
  B0 any mention: 52 called, 14 confirmed, 1 contradicted (0.27 [0.17, 0.40]).
- Test badges under v1 bands: 61 Unverified, 10 Unlikely.

### 4.5 Location and existence heads

- P_L, 38 test pairs (30 location yes): AUROC 0.923 with no interval computed (8 negatives). Of the
  33 pairs with P_L >= 0.7, 30 were yes (Wilson 0.76 to 0.97) (P/fusion/test_metrics.json).
- P_E: not fitted (5 dev negatives). No metric.
- Focus states (Bihar, Jharkhand, Odisha, Assam, Chhattisgarh): 11 test pairs. Too small to compare
  with the rest (28 pairs).

### 4.6 End-to-end top-1 on the 40 benchmark queries

Denominator 40 for every system; unlabelled counts as not confirmed.

| system | confirmed top-1 [Wilson] | usable top-1 [Wilson] | contradicted, wrong place or nonexistent (Unsafe@1) | confirmed / decisive |
| --- | --- | --- | --- | --- |
| WL shipped | 5 [0.055, 0.261] | 4 [0.040, 0.231] | 5 | 5/7 |
| B0 nearest mention | 6 [0.071, 0.291] | 3 [0.026, 0.199] | 5 | 6/7 |
| B1 keyword count | 7 [0.088, 0.320] | 5 [0.055, 0.261] | 3 | 7/7 |
| B2 rule grade | 6 [0.071, 0.291] | 4 [0.040, 0.231] | 7 | 6/10 |
| B3 LLM judge | 6 [0.071, 0.291] | 3 [0.026, 0.199] | 4 | 6/6 |
| B4 prior only | 9 [0.123, 0.375] | 7 [0.088, 0.320] | 4 | 9/10 |
| B5 gold only | 1 [0.004, 0.129] | 0 [0.000, 0.088] | 9 | 1/10 |
| WL fallback (B2 as P_S) | 7 [0.088, 0.320] | 4 [0.040, 0.231] | 3 | 7/7 |

Exact McNemar over all 40: WL vs B0, 2 against 3 discordant, p = 1.0; WL vs B4, 3 against 7,
p = 0.34; WL vs B5, 5 against 1, p = 0.22. Caveats: 13 of the 15 contradicted labels have no URL and
are name-based ("dental clinic is unrelated to cardiac surgery"). That is the same rule as the model's
type terms, so Unsafe@1 is not evidence for or against them. The "decisive" column uses a different
denominator for each system, so do not compare it across rows. The prototype WL abstained on 40 of 40
queries; its mean printed P(at least one option works) was 0.62 and has not been checked against
outcomes.

### 4.7 Sentence-level attribution (evidence layer, P/evidence/sentence_metrics.json)

224 sentences labelled blind to rule outputs by one annotator from the listing text (109 dev, 115
test). Detecting "about another facility" on 108 decided test sentences:
- rules v0: 0.954 [0.896, 0.980]
- rules v1 (two fixes chosen on dev): 0.944 [0.884, 0.974], precision 10/15, recall 10/11
- LLM: 0.981 [0.935, 0.995]
- LLM minus v1: +0.037 [0.009, 0.076]; v1 minus v0: -0.009 [-0.030, 0.000], so the dev fixes did not
  carry over

Support ("the sentence says the service is provided"), test: rules 93/107 [0.79, 0.92], LLM 104/107
[0.92, 0.99]. Rejections that were wrong (all 224): other_facility 4 of 18, ambiguous 7 of 16 were the
facility's own sentence. Weighted misattribution among quotable sentences: dev 0.023, test 0.000 (77
test sentences across strata, 0 found).

### 4.8 Inter-annotator agreement (30 overlap pairs, Cohen's kappa [bootstrap 95%])

| field | all 30 | test 17 | both labellers searched (15) |
| --- | --- | --- | --- |
| service | 0.382 [0.022, 0.699], agreement 0.70 | 0.460 [-0.017, 0.866] | 0.405 [-0.105, 0.783] |
| exists | 0.360 [0.027, 0.667] | 0.271 [-0.149, 0.653] | agreement 15/15 |
| location_ok | 0.473 [0.178, 0.715] | 0.497 [0.055, 0.817] | 0.737 [0.286, 1.0] |

When both labels were decisive they agreed 6 of 6. All 9 service disagreements were decisive against
no_info (4 one way, 5 the other). The sign is reliable; whether anything is found depends on effort.

### 4.9 Faithfulness tests (all pass)

Additivity (8.9e-16), deletion per family (1,105 pairs, 5.6e-16), monotone in T (minimum change
-2e-15, which is rounding), adding foreign evidence lowers z by at least 0.58, location vote weights
>= 0, Wockhardt dialysis not Likely (P_S 0.54, P_L 0.58), Aravind not Likely for any service
(P/fusion/tests_report.json). Decision recomputation: 1,929 rows, error 0.0
(P/decision/faithfulness_report.json). Quotes: 11 of 12 card quotes match the raw array at idx; the
twelfth is the raw_pos offset in 3.1 (RV/explain/recompute_s1.json). Evidence tests pass
(P/evidence/test_results.json). The Wockhardt/Aravind test is weak while only 2 pairs are Likely: it
passes for any model whose P_S stays below t_L.

### 4.10 Acceptance rules (fixed in v1 before test)

| rule | status |
| --- | --- |
| A1 beat B2 and B3, paired interval excludes 0 | fails against B2 (+0.078 [-0.035, 0.183]); passes against B3 (+0.191 [0.090, 0.284]) |
| A2 shipped prior beats M0 by 1 SE on dev | marginal pass, 1.15 SE (-0.123, SE 0.107) under uniform weights only; under IPW the gap is 0.003 |
| A3 test ECE <= 0.10 | fails (IPW 0.197) |
| A4 Likely precision >= 0.85 | not testable (N = 0) |
| A5 success@1 >= B0 + 10 points, Unsafe@1 <= B0 | fails (5 vs 6 of 40) |
| A6 contaminated records not Likely, faithfulness passes | passes, trivially, since nothing is Likely |

### 4.11 Claims that did not survive review

- "The fitted scorecard beats the baselines." Only against B0, B3 and B5 do the intervals exclude 0.
  The unfitted expert ledger B4 does at least as well: -0.013 [-0.076, 0.048] raw on all 71; fusion's
  own IPW comparison on the searched 39 gives -0.129 [-0.252, -0.026] (P/fusion/test_metrics.json).
  Fitting on about 22 effective dev labels (ESS) does not identify about 60 weights.
- "Likely carries a precision guarantee." The band is empty on test.
- "P_S is calibrated." IPW ECE is 0.197, and P_S tracks searchability as well as truth.
- "Evidence on heavily merged records earns visibly less weight." The bucket discounts tb_mid and
  tb_high were fitted to 0 at their bound. The free main effects are positive (g_mid +1.055, g_high
  +0.460 before Platt), so records built from many pages score higher. That is a web-visibility
  effect: confirmed share is 1 of 21 for facilities without a website against 30 of 119 with one.
- "More own text means more confidence." Steps t2 and t3 are 0, and t4 is cancelled for 4 of 7
  services. Three sentences in three fields earn what one any-mention tag earns. Among the text
  steps only t1 (+0.754) and t5 (+1.075) are materially above 0 before Platt.
- "The name-place witness catches Wockhardt." The fitted location head gave v_name weight 0. Wockhardt
  is caught by the stated city vote (-63.3 points) and the band rule (P/fusion/examples.txt).
- "The ownership filter improves accuracy." No ablation interval excludes 0: shipped minus
  no-ownership-filter is +0.050 [-0.018, 0.167] IPW AUROC (P/fusion/test_metrics.json). Rejection
  touches 130 pairs.
- "The track record line is informative." Every Unverified card printed the same 16 of 35, at P_S 0.22
  and at 0.65.
- "The no-text line explains the score." On 64 of 113 benchmark cards with T < 2 (0.57 [0.47, 0.65])
  a prerequisite hit drove the score. On 22 (0.19 [0.13, 0.28]) context lowered it.
- Subgroup AUROCs without intervals (focus states 0.964, n = 11) are withdrawn.

### 4.12 Process disclosures

- The evidence layer wrote v2 test metrics at 13:50:37, then changed facility.py and common.py at
  13:51:58 and froze at 13:52:53. Fusion's sealed run (13:54:13) used fallback inputs, so it is not
  affected. Any model built on evidence outputs needs fresh test labels.
- The decision layer opened test twice (14:10:20, 14:12:33) with no diff logged.
- 14 selection configurations were tried on dev (weighting x prior x prior-strength).
- priors_M1.json was written after the v2 dev notes and the marginal label counts had been read.

## 5. Explainability

### 5.1 What the App shows

Level 0, the phone view: at most 4 lines. One badge, with hard warnings before the name; the action;
the call script; one plain line of how sure.
Level 1, "Why this one" (one tap): quotes with field, the driver line, what we ignored, where the
location comes from, why it ranks above a nearer option.
Level 2, "How the score was made" (judge view): the points waterfall grouped as base / text /
related-service hints / public list / contamination / facility type / web footprint. Columns:
fitted weight, x calibration slope, contribution, points. Then the badge checklist, the stored
counterfactual without the quotes, the live counterfactual "if a call confirms B it ranks 1st", and
U = P_E x P_S x G expanded.

Wording rules (applying the explainability review):
- "How sure" uses the score-bin record from score_bin_record (test bins), with "(small sample)" below
  n = 20, not one band-wide line.
- P_S is "chance a public check confirms it". P(at least one works) never appears next to an
  abstention on the lay card; the judge view labels it "not yet checked against outcomes".
- When T < 2, the line names the real drivers: the prerequisite sentence that set P, quoted, and the
  top two context terms with points.
- The bucket row is labelled truthfully: "records built from many web pages are confirmed more often in
  our checks: +11.6 points".
- Distances above 100 km are given in hours. With two candidate points, lead with the one with more
  belief and name its witnesses.
- Call script on every card: "Ask: 1) Do you do <service> now? 2) What is your full address and town?
  3) Is someone available today?" A call to the real facility in another town would otherwise
  confirm the wrong place.
- Why-first: one sentence, omitted when the nearer option is less than 1 km nearer.
- Footer: model hash, labels hash, number of test openings, and the banner "built on fallback
  evidence" while the hash ends in -fallback.

### 5.2 Worked example from the real data: dialysis near Panipat

Query "Panipat district, Haryana", dialysis. Resolved as "Using Panipat (district layer, median of 13
PIN points), Haryana". Radius 25 km. The record is Civil Hospital, Panipat (acde9be7), the only Likely
pair in the dataset. Numbers are from the current fallback model (P/decision/worked_examples.txt,
RV/explain/recompute_s1.json). After the v2 Platt and selection rules they will change.

Level 0:
```
[LIKELY, borderline] Civil Hospital, Panipat (government district hospital) - 9 km, about 13 to 21 min
Call first: <number from the listing, not checked>. Ask: dialysis now? full address? a slot this week?
Its listing says: "Hemodialysis facility run under Public-Private Partnership" (+2 similar)
How sure: score 0.70, just at our 0.70 cut-off. We have not yet checked any listing this high.
```

Level 1:
```
Why we think it offers dialysis (sentences from its own listing):
  [capability] "Hemodialysis facility run under Public-Private Partnership"
  [equipment]  "Haemodialysis facility run in PPP mode"
  [procedure]  "Provides haemodialysis treatment"
  Sources: one of these pages: panipat.gov.in/public-utility-category/hospitals/ ... (13 pages)
Most of this score comes from the kind of hospital it is: a government district hospital, where the
  public standard (IPHS 2022) expects dialysis (+24 points), with 20+ specialties (+9). The three
  sentences add 8 points. Without them the score would be 0.64.
Where: PIN centre, stated city, place in the name and stated state agree. P_L 0.99.
What we ignored: nothing.
Why above Ravindra Hospital (2 km nearer): distance favours Ravindra 1.16x; this hospital's evidence
  is 1.23x stronger (P_E x P_S 0.50 vs 0.41); net 1.06x for Civil Hospital.
```

Level 2 (points = 20/ln 2 x contribution; contribution = fitted weight x Platt slope 0.380):
```
base: dialysis intercept -27.7, calibration offset -7.3                      -35.0
text: any own mention (t1; weight 0.754 x 0.380 = 0.286)                     +8.3
text: more units and fields (t2, t4 net of dialysis deviations)               0.0  fitted to zero
related-service hints (p1, net of dialysis deviation)                         +10.0
web footprint, mid bucket (g_mid)                                             +11.6
district hospital (level_dh)                                                  +12.9
IPHS essential at district level (iphs_essential)                             +10.8
20+ specialties +8.9, 100+ beds +2.6, 20+ doctors -0.5, public -4.8           +6.3
total +24.8 points -> logit 0.859 -> P_S 0.702 (t_L 0.70, margin 0.002)
P_L 0.991, P_E 0.711 (expert settings), d1 8.7 km, G = 0.99 exp(-8.7/15) = 0.556
U = 0.711 x 0.702 x 0.556 = 0.278; Ravindra U = 0.263; ratio 1.057 = 1.227 x 0.861
```

What this card teaches the team: facility context contributes a net +41.6 points, the quoted text
+8.3. The badge rests
on a fallback threshold. The existence head charged "no phone" (-0.7 logit) although a number is
shown. These are three of the v2 fixes.

The contaminated contrast, Wockhardt Hospital Nagpur, dialysis, level 1:
```
[PLACE UNCLEAR] Wockhardt Hospital Nagpur
Name and city say Nagpur. PIN 400078 and the map point say Mumbai (677 km apart). We put 58% on Mumbai.
Do not travel on this listing; call and ask for the address.
What we ignored: "Provides dialysis treatment at Nair Hospital, Mumbai Central"
  and "Dialysis machines donated by Jivan Jyot Drug Bank are used at Nair Hospital, Mumbai Central"
  - each names a different hospital.
```

### 5.3 Global model card (HOW we decided)

1. Data funnel: 10,088 rows, 9,959 records, 69,713 pairs, 22,787 atoms, 15,550 units, badge counts.
2. Evidence rules with each class's measured precision and n (attribution_rates.csv,
   sentence_metrics.json).
3. Weight tables, prior next to posterior with a derivation per prior, plus a findings list: sign
   flips, weights at bound (t2, t3, tb_*, c2), and the positive bucket effect.
4. Reliability table: gold-based and agreement-based weight of evidence side by side, with hand-check
   references (non-offer 34/40, named-other 9/40).
5. Score-bin record on test with never-searched counts in their own column; ECE with interval.
6. Baselines, ablations and end-to-end results from section 4, failed acceptance rules marked failed.
7. Label quality: kappa decomposition, the search-budget note, visibility bias (1/21 vs 30/119).
8. Policy knobs with their sensitivity (8 to 11 of 40 top-1s move).
9. Assumptions in words: heads independent given features; options fail independently except within
   a leakage group; P_S means publicly confirmable; road factor 1.3 and speeds of 25 to 40 km/h are
   not measured.
10. Walk-throughs: Wockhardt (caught), Aravind (caught only by location and scope), Sharda (not
    caught).
11. Versions and test openings.

### 5.4 Faithfulness guarantee

- Each score is the sum of its displayed terms. The build fails if any row breaks |base + sum -
  z| < 1e-9.
- Displayed and ranking numbers come from the same Delta rows. Nothing is recomputed by a second
  model.
- The App recomputes G, U, P_succ, the rank order and the why-first identity from the rendered
  numbers, and shows an error page instead of a result on any mismatch.
- Every quote is a claim_atoms row whose text equals the raw item at (unique_id, field, raw_pos);
  every ignored sentence is a stored rejected_atom_id with its stored reason.
- Track-record counts come from score_bin_record with labels_sha256 printed.
- All card text is filled from templates. No LLM writes or rewrites a rationale. Family R, if
  shipped, appears as a named term ("an automated check agreed this sentence is about this facility")
  with its own points.

## 6. GPU

Not worth using. Every prototype measured the same thing: accuracy is limited by labels, not compute.
- Fusion fits about 60 weights on 76 dev labels in seconds, and the whole build reruns in about 3
  minutes on CPU. The evidence build takes 34 s.
- The one GPU-shaped option is a fine-tuned sentence-attribution model. It would be trained against
  224 human sentence labels and validated no more tightly than that. The pay-per-token ai_query
  classifier already gives the measured +0.037, with no GPU. Ownership rejection affects 130 pairs.
- Free Edition has no GPU serving and no custom-model batch inference, and GPU training needs
  LinkedIn verification that was not done (research/gpu/GPU.md). Nothing in the demo may depend on
  it.

Fallback, which is also the plan: CPU numpy for all fitting, and ai_query for the optional family R.
The highest-value use of the time a GPU job would take is labelling: re-searching the 58 never-searched
v2 pairs and drawing the uniform U sample.

## 7. Build plan on Databricks

Write access to the workspace is a build-phase permission. It was not used in any step of this
design. Fitting code is pure numpy/pandas. The builders also import duckdb and rapidfuzz, and
installing those on serverless is not verified under restricted egress. The safe path is to run the
builders locally and upload the parquet outputs to a Unity Catalog volume; a notebook then registers
the Delta tables. If %pip works on serverless, the same scripts run there unchanged.

Order (each step lists its done-when):

1. NB00_setup: create workspace.vf_ledger and a volume, upload raw, cleaning, audit and external
   match parquets. Done when every input sha256 matches FROZEN.json.
2. Evidence v2 (local, about 1 h of code): raw_pos, type derivation and S from name, unified place
   layers with unplaceable city or PIN as dissent, X from LaQshya, NMC and TCF matches, OSM existence
   witness, single phone source. Done when the evidence tests plus new tests pass (Sharda gets a
   dissent; Smile Kraft gets S = 1) and FROZEN is rewritten.
3. Labels, in parallel with steps 2 to 5: re-search the 58 never-searched v2 pairs, finish the 33
   not-run and re-search the 60 URL-less end-to-end pairs, then draw and label U (84 pairs, 12 per
   service, seeded, inclusion probabilities stored). Adjudicate overlap: a decisive verdict with a
   checked URL beats no_info. A label is final only after a person reads the URL.
4. Fusion v2 (local): consume evidence outputs; searched-only target; the selection rule of 3.2 with
   B4 prior-only as the default; the Platt one-SE rule; location p2-support rule; draws until 1,000
   accepted. Done when the fusion tests pass and model_meta is written without -fallback.
5. Fresh sealed test: the 32 newly searched v2 test pairs plus the U test half (about 42). Opened once
   by the sealed script and logged. Then the benchmark pool labels and the end-to-end table.
6. NB01_register: write the section 3.6 tables to Delta.
7. App (Streamlit, 2 vCPU, 6 GB): at start, load pair_scores, facility_scores, facility_features,
   claim_atoms and gazetteer through the SQL warehouse into memory; fetch contributions per selected
   card. Live: resolve place, haversine over 9,959 points, U, plan, cards, the recompute gate. No
   ai_query, serving or GPU call on any path.
8. Model card page and the three walk-throughs (Wockhardt, Aravind, Sharda) from stored rows. Restart
   the App before judging; it auto-stops after 24 h, and judges must be workspace users.

Cut lines:
- Never cut: ownership filter and "What we ignored", verbatim quotes, location badges, the
  faithfulness gate, the sealed test, grouped splits, score-bin records with three outcomes, the
  fallback banner.
- Cut line 1 (ship without, say so on the model card): the fresh test in step 5. Without it, the App
  shows the current test numbers labelled "model v1, test read before v2 changes".
- Cut line 2: family X from external lists, then the OSM existence witness.
- Cut line 3: family R. One cached ai_query pass over about 7,300 pairs with a tagged sentence; at
  most 1,500 records, batches of 250, prompt-sha256 cache, stop at the first quota warning. It enters
  only if it beats the rules on a fresh 100-sentence check.
- Cut line 4: Hindi templates, planner mode, Pareto view, M2.

## 8. Known limitations and open risks

- Labels are the binding constraint. There are 39 searched test pairs with 1 contradiction; IPW ESS
  is 29 (all 71) and 13.4 (searched). Service kappa is 0.38. A fresh test of about 74 pairs will
  still have AUROC intervals about +/- 0.1 wide, as in section 4.2. No claim that the model beats B2
  or B4 is supported today.
- Target mismatch. "A budget-limited web check confirms it" is not "offers it". Small rural and public
  facilities are under-confirmed: 1 of 21 confirmed without a website, against 30 of 119 with one.
  The outside option and the list family X partly offset this.
- Context dominates where text is thin. 22 of 40 prototype top-1s had no own sentence about the
  service. 12 of 40 had more context logit than evidence logit (RV/explain/audit_benchmark_cards.json).
  The emergency plan rule hides these as leads, but the ranking still uses them.
- Unanchored contamination. 95% of service sentences carry no anchor. Aravind's dialysis text counts as
  own and is held back only by the scope and location terms.
- Self-consistent contamination. Sharda Hospital (listed city Greater Noida, PIN 270001 not in India
  Post, map point in Chandauli) ranked first for q29 trauma with P_L 0.77 and no warning. The v2
  dissent rule is designed for this case and has not yet been run on it.
- Distance is straight-line x 1.3 with assumed speeds, and is wrong in hilly and riverine districts.
  The MAP raster is used only as a candidate coordinate flag, not for routing.
- Existence weights are expert settings. The location head rests on 121 rows with 20 negatives.
- External lists are small (58, 81 and 20 matched rows) and partly stale. Only 509 of 2,173 LaQshya
  certificate rows were valid on 2026-11-21. NMC courses are a proxy for a running service.
- Free Edition: the daily quota can stop compute for the day, the App auto-stops after 24 h, and
  installing duckdb and rapidfuzz on serverless is unverified.
- Every v2 change in sections 3.1 to 3.4 is designed but not run. Its effect on the numbers in
  section 4 is unknown until step 5 of section 7.
