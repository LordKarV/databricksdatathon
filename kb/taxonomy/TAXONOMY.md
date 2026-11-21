# Service taxonomy

Version 1.1 (2026-11-21), revised from the adversarial review in review/REVIEW.md. The CHANGELOG at the end lists every
review issue and what was done about it, with before and after numbers.

This folder holds the canonical list of services the (service, location) model answers for, plus the tables that
connect the Virtue Foundation (VF) records to it: a specialties map, measured specialty evidence weights, a sentence
lexicon and attribute slots for hours and details. Everything here is built from the VF records and the three IPHS
2022 volumes. A mention counts as a claim. Nothing in this folder says a facility actually offers a service.

## Files

| file | what it is | built by |
| --- | --- | --- |
| services.json | 36 services in 11 categories, plus 1 candidate. Each service has id, aliases, names (en, hi, mr), definition, urgency, required capabilities, supporting and contradicting evidence, IPHS 2022 levels with citations, external lists, `name_phrases`, `symptom_phrases` (with a route), `answer_mode`, `attributes` and measured `coverage`. A top-level `facility_attributes` block lists facility-level details | written by hand (v1.1 changes placed by revise_services.py); build_lexicon.py fills `coverage`, `attributes`, `facility_attributes` |
| specialty_map.csv | all 2,933 distinct raw specialties strings mapped to a service id (or a `;` list of ids), `too_general`, `out_of_scope` or `not_a_service`, with method, confidence, facility count and prereq_for | build_specialty_map.py (rules in specialty_rules.py) |
| specialty_evidence_weights.csv | 1,346 (value, service) pairs with the measured share of tagged facilities that have positive text for the service, shrunk toward the group rate, plus split-half columns. This is the specialty evidence weight the model should use instead of the 0/1 label | specialty_weights.py |
| lexicon.json | per service: include, exclude, exclude_clause, related, negation_extra, quantity, prereqs, specialty_values, prerequisite_specialty_values, attribute_patterns; shared non-offer and weakening cues; sentence kinds; facility_attributes; clause_split | build_lexicon.py from lexicon_src.py and attributes_src.py |
| out/coverage.csv | per-service counts (table below) | build_lexicon.py |
| out/attribute_counts.csv | how often each attribute pattern fires | build_lexicon.py |
| out/lexicon_matches.parquet | one row per (claim sentence, service) match: 64,670 rows over 58,004 sentences | build_lexicon.py |
| out/diff_vs_claims_tags.csv | kb tags for the 8 ported services against the `services` column of claims.parquet | build_lexicon.py |
| out/specialty_weights_eval.json | held-out log loss of the weights against the binary label | specialty_weights.py |
| out/handcheck_*.csv | hand-check samples and verdicts (v1.0 and v1.1); doctor names are masked in v1.1 text | handcheck_*.py |
| out/v1_0/ | copies of the v1.0 outputs, for the before and after numbers | copied before the revision |
| out/llm_labels.json | cached ai_query answers; v1.1 made no new Databricks call | build_specialty_map.py |

To re-run from this folder with `/Users/karthikvattem/projects/datathon/.venv/bin/python`: build_specialty_map.py,
then build_lexicon.py, then specialty_weights.py, then `handcheck_v1_1.py score`. lexicon_src.py, attributes_src.py
and specialty_rules.py each run their own assert checks. revise_services.py was run once and refuses to run again.

## How services were chosen

1. MODEL_SPEC_v1 gold ids are kept (dialysis, emergency_csection, nicu, cardiac_surgery, mri, burn_care) with icu.
   trauma_emergency is now an alias of trauma_care (see the split below). The cleaning/claims keys are aliases:
   csection, burns, and trauma, which is an alias of emergency_24x7 because that is what its pattern finds.
2. Services an intermediary refers people for were added in v1.0 (CT, blood bank, cath lab, stroke, neurosurgery,
   fracture surgery, three cancer services, PICU, ventilator, kidney transplant, psychiatry, de-addiction, eye
   emergency, cataract, high-risk pregnancy, delivery, ultrasound, TB, HIV). v1.1 adds emergency_24x7,
   stemi_thrombolysis, paediatric_inpatient and safe_abortion_mtp, and brings snakebite_antivenom, anti_rabies and
   nutrition_rehabilitation in from the candidates.
3. Inclusion rule: a service is in when it is referral-relevant and either at least 20 of the 9,959 usable records
   mention it, or IPHS 2022 expects it at public facility levels, so a level prior over public facility lists can
   answer it (`answer_mode: prior`, shown with "Public facility expected to stock or provide this under IPHS 2022;
   call to confirm").
4. `answer_mode`: `evidence` (VF text and specialties), `evidence_plus_prior` (also an IPHS level prior, for services
   VF rarely describes at government facilities: TB, HIV, delivery, CEmONC, paediatric ward, MTP, STEMI
   thrombolysis), `prior` (snakebite, rabies, NRC), `not_answered` (candidate).
5. `low_coverage` is computed on positive text only: fewer than 100 facilities with positive text, or fewer than 100
   with positive text in 2 or more text fields. 15 services are flagged.
6. Considered and not added: ambulance (transport), poisoning (routes through emergency_24x7 and icu), joint
   replacement and dental (elective), general physician (too_general). palliative_care stays a candidate: it is not a
   time-critical referral.

## Phrase routing

`name_phrases` (148) select the service. `symptom_phrases` (76) select a route: search `route` first among
facilities that also meet `requires`, and show `second_card` next. 31 emergency symptom phrases route to
emergency_24x7, so the nearest facility that can stabilise comes first. Examples: "seene mein dard" goes to
emergency_24x7 with stemi_thrombolysis required and cath lab second. "sar pe chot" and "lakwa" go to emergency_24x7
with CT required. "behosh hai" goes to emergency_24x7 with ICU second. Obstetric emergencies (PPH, eclampsia,
breech) route to emergency_csection, now defined as CEmONC, with blood_bank required. Sick-child phrases route to
paediatric_inpatient, with PICU second. Suicide-risk phrases route to emergency_24x7 and carry a Tele-MANAS 14416
note. Nothing in this folder implements the routing; the decision layer has to.

## Counts

Facilities over the 9,959 usable records (34 states). any: a matching claim sentence or a mapped specialties value.
text positive: a matched sentence with no non-offer cue, not attributed to another facility, and not a staff or
directory sentence. text 2+ fields: the same, in 2 or more distinct text fields after in-record echoes are dropped.
spec only: the only evidence is a specialties value.

| category | service | answer mode | any | text positive | text 2+ fields | spec only | states | sentences | low coverage |
|---|---|---|---|---|---|---|---|---|---|
| emergency_and_trauma | emergency_24x7 | evidence | 3367 | 2925 | 742 | 431 | 33 | 6901 | no |
| emergency_and_trauma | trauma_care | evidence | 1270 | 1237 | 435 | 16 | 28 | 2852 | no |
| emergency_and_trauma | burn_care | evidence | 265 | 215 | 66 | 48 | 24 | 401 | yes |
| emergency_and_trauma | orthopaedic_trauma_surgery | evidence | 560 | 542 | 143 | 13 | 25 | 1094 | no |
| emergency_and_trauma | snakebite_antivenom | prior | 17 | 16 | 5 | 1 | 6 | 23 | yes |
| critical_care | icu | evidence | 2789 | 2280 | 868 | 489 | 32 | 5965 | no |
| critical_care | picu | evidence | 425 | 331 | 93 | 88 | 29 | 631 | yes |
| critical_care | ventilator_support | evidence | 462 | 459 | 120 | 1 | 24 | 836 | no |
| maternal_and_newborn | emergency_csection | evidence_plus_prior | 442 | 437 | 92 | 0 | 26 | 691 | yes |
| maternal_and_newborn | institutional_delivery | evidence_plus_prior | 1206 | 1031 | 383 | 157 | 26 | 2308 | no |
| maternal_and_newborn | high_risk_pregnancy | evidence | 963 | 482 | 174 | 476 | 28 | 1059 | no |
| maternal_and_newborn | nicu | evidence | 746 | 742 | 242 | 0 | 29 | 1555 | no |
| maternal_and_newborn | safe_abortion_mtp | evidence_plus_prior | 151 | 151 | 25 | 0 | 21 | 237 | yes |
| heart_and_brain | cardiac_surgery | evidence | 976 | 659 | 258 | 306 | 28 | 1953 | no |
| heart_and_brain | cath_lab_angioplasty | evidence | 817 | 797 | 463 | 12 | 29 | 2619 | no |
| heart_and_brain | stemi_thrombolysis | evidence_plus_prior | 22 | 21 | 2 | 0 | 12 | 30 | yes |
| heart_and_brain | stroke_care | evidence | 159 | 126 | 34 | 31 | 20 | 211 | yes |
| heart_and_brain | neurosurgery | evidence | 2235 | 1149 | 447 | 1061 | 31 | 2891 | no |
| kidney | dialysis | evidence | 1051 | 1035 | 559 | 4 | 30 | 3070 | no |
| kidney | kidney_transplant | evidence | 483 | 432 | 191 | 35 | 26 | 1065 | no |
| cancer | chemotherapy | evidence | 1568 | 468 | 198 | 1096 | 29 | 1238 | no |
| cancer | radiotherapy | evidence | 384 | 355 | 200 | 19 | 27 | 1552 | no |
| cancer | surgical_oncology | evidence | 1530 | 837 | 259 | 677 | 30 | 1954 | no |
| diagnostics_and_blood | mri | evidence | 952 | 942 | 533 | 0 | 31 | 3135 | no |
| diagnostics_and_blood | ct_scan | evidence | 1459 | 1448 | 859 | 0 | 32 | 5127 | no |
| diagnostics_and_blood | ultrasound | evidence | 2103 | 2099 | 1278 | 1 | 31 | 7132 | no |
| diagnostics_and_blood | blood_bank | evidence | 685 | 667 | 240 | 7 | 30 | 1613 | no |
| mental_health | psychiatric_care | evidence | 1317 | 228 | 35 | 1076 | 33 | 437 | yes |
| mental_health | de_addiction | evidence | 287 | 157 | 50 | 126 | 24 | 456 | yes |
| eye | cataract_surgery | evidence | 909 | 793 | 513 | 109 | 27 | 4093 | no |
| eye | eye_emergency | evidence | 369 | 205 | 61 | 164 | 23 | 409 | yes |
| infectious_disease | tb_care | evidence_plus_prior | 242 | 222 | 62 | 2 | 24 | 492 | yes |
| infectious_disease | hiv_art | evidence_plus_prior | 74 | 67 | 14 | 4 | 22 | 131 | yes |
| infectious_disease | anti_rabies | prior | 19 | 19 | 5 | 0 | 13 | 32 | yes |
| child_health | paediatric_inpatient | evidence_plus_prior | 40 | 39 | 5 | 0 | 17 | 53 | yes |
| child_health | nutrition_rehabilitation | prior | 10 | 9 | 1 | 0 | 7 | 12 | yes |
| candidate | palliative_care | not_answered | 185 | 180 | 56 | 0 | 24 | 412 | yes |

Reading notes:

- Specialty-only facilities still dominate psychiatric_care (1,076 of 1,317), chemotherapy (1,096 of 1,568) and
  neurosurgery (1,061 of 2,235). Use specialty_evidence_weights.csv rather than counting `any`.
- stemi_thrombolysis has 22 facilities and paediatric_inpatient 40. Both are answered mainly by the IPHS prior.
  In the STEMI sample, 5 of 20 sentences name thrombolysis or a thrombolytic; the rest describe heart-attack care,
  chest-pain clinics or primary PCI, which a decision layer can treat as at least as good.
- Quantities and bed counts are read per sentence and can describe the whole hospital. The KB step must check what a
  number attaches to.

## Specialty map

2,933 distinct raw strings. Facility counts are over the 9,959 usable records.

| method | values (v1.0 -> v1.1) | how |
| --- | --- | --- |
| rule | 2,360 -> 2,356 | camelCase split, lowercase, spelling fixes, then ordered keyword rules (first match wins) |
| fuzzy | 21 -> 21 | rapidfuzz ratio >= 94 against a rule-labelled value |
| llm | 538 -> 532 | cached answers from the single v1.0 ai_query statement; cached `trauma_emergency` answers are re-pointed to trauma_care when the value names trauma, accident or injury, else to emergency_24x7 |
| manual | 14 -> 24 | v1.0 overrides plus 9 multi-service values and independentDivisions |

Label totals (v1.0 -> v1.1): service 457 -> 461 values (9 of them `;` lists such as "NICU/ PICU/ Neonatology" ->
nicu;picu), too_general 447 -> 465, out_of_scope 1,985 -> 1,964, not_a_service 44 -> 43. 94 values (2,558 facility
mentions) changed label and 161 more (18,301 mentions) changed only prereq_for. prereq_for may now be set on
out_of_scope values too: urology -> kidney_transplant, pathology -> surgical_oncology;chemotherapy.

Rule for a service label (unchanged): the value itself names the service, its unit or its core procedure.

### Specialty evidence weights

The review showed the service vs too_general label contradicts the data: psychiatry (service) is confirmed by text
for 0.152 of its facilities, nephrology (too_general) for 0.389. specialty_evidence_weights.csv replaces the 0/1
switch with a measured weight per (value, service). The weight is the share of usable facilities carrying the value
that have positive text for the service, shrunk toward the pooled rate of its group (label or prereq, per service),
with a prior strength of 20 facilities. Split-half check (md5 of unique_id), fitted on one half and scored on the
other: log loss 0.4505 for per-value weights, 0.4555 for one rate per (label kind, service), which is the most a
binary label can express, and 0.5504 for a constant rate (54,035 test rows, base rate 0.239). Most of the gain over a
constant comes from treating each service separately. Per-value weights add a small further gain. The weight is a
lower bound, because text corroboration depends on lexicon recall. Examples (all facilities): emergencyMedicine ->
emergency_24x7 0.795, criticalCareMedicine -> icu 0.709, nephrology -> dialysis 0.388, medicalOncology ->
chemotherapy 0.267, psychiatry -> psychiatric_care 0.155, neurology -> stroke_care 0.047.

### Specialty map hand checks

| sample | v1.0 labels | v1.1 labels | 95% Wilson (v1.1) |
| --- | --- | --- | --- |
| builder random 60 (seed 20261121, automatic output) | 57/60 | 60/60 | 0.940 to 1.000 |
| builder service-labelled 40 (seed 11) | 37/40 | 40/40 | 0.912 to 1.000 |
| reviewer random 80 (seed 4242) | 74/80 | 80/80 | 0.954 to 1.000 |
| reviewer top 30 by facility count (labels and prereq_for) | 30/30 labels, 3 prereq errors | 30/30, 0 prereq errors | 0.886 to 1.000 |
| fresh v1.1 service-labelled 40 (seed 2027, none checked before) | not run | 39/40 | 0.871 to 0.996 |

The first four samples drove the fixes, so their v1.1 scores are not independent. The fresh sample is the honest
v1.1 estimate. Its one error is psychotherapy -> psychiatric_care (talking therapy, which the service's own
contradicting evidence excludes).

## Lexicon

The 8 services cleaning/claims tags are ported from cleaning/claims/lexicon.py, with kb-only fixes in
lexicon_src.KB_FIXES. cleaning/claims is not modified. The other services have patterns written here.

New mechanism in v1.1: `exclude_clause`. The sentence is split on `; , | bullet` and ` - `. The match stands if some
clause that carries the include hit has no clause-level exclusion. A department list such as "Emergency Medicine,
Ophthalmology, Dental" keeps its emergency evidence, while "24x7 cardiac emergency" is still excluded.
emergency_24x7, trauma_care and dialysis use it.

Against the claims.parquet tags (out/diff_vs_claims_tags.csv):

| service | only claims.parquet | only kb | both |
| --- | --- | --- | --- |
| emergency_24x7 (claims key trauma) | 2,237 | 265 | 6,636 |
| dialysis | 15 | 6 | 3,064 |
| cardiac_surgery | 6 | 0 | 1,953 |
| emergency_csection | 6 | 0 | 691 |
| burn_care | 1 | 0 | 401 |
| icu, mri, nicu | 0 | 0 | all |

emergency_24x7 drops 2,237 sentences, mainly orthopaedic "trauma surgery" lines that only matched the bare `trauma`
word; those that describe trauma care are in trauma_care. The dialysis drops are 15 catheter-insertion sentences.

### Lexicon hand checks (v1.1)

Criterion (unchanged): read alone, the sentence says this facility provides the service or has its unit or
equipment. A sentence a non-offer cue flags counts as handled. Samples are in out/handcheck_v1_1_sample.csv, with
verdicts in handcheck_v1_1.py.

| sample | result | 95% Wilson |
| --- | --- | --- |
| builder v0 sample (140 sentences), re-matched with v1.1 | still matched: 130, of which 129 correct (the error is a doctor's past experience at PGIMER); 8 of the 11 v1.0 errors no longer match; 1 v1.0-correct sentence no longer matches emergency_24x7 ("arthroplasty and trauma surgeries" is not an emergency department) | 0.958 to 0.999 |
| reviewer 40 (re-matched) | 37/40 (fetal well-being scan now matches) | 0.801 to 0.974 |
| new: emergency_24x7, 20 random positive matches (seed 1111) | 20/20 | 0.839 to 1.000 |
| new: trauma_care | 18/20 | 0.699 to 0.972 |
| new: stemi_thrombolysis | 20/20 | 0.839 to 1.000 |
| new: paediatric_inpatient | 18/20 | 0.699 to 0.972 |
| new: safe_abortion_mtp | 19/20 | 0.764 to 0.991 |
| new, all 5 | 95/100 | 0.888 to 0.978 |
| recovered by the fixes: emergency_24x7 (20), psychiatric_care (10), ultrasound (10), dialysis (6) | 17/20, 9/10, 10/10, 5/6; all 41/46 | 0.770 to 0.953 (all) |
| emergency_24x7 clause-level vetoes (10 of 267): was the veto right? | 10/10 | 0.722 to 1.000 |

These scores are on the final lexicon. A first round on the intermediate lexicon found problems that were fixed
before the final sample was drawn: emergency_24x7 16/20 (orthopaedic trauma surgery via bare `trauma`), trauma_care
14/20 (orthopaedic fracture work, a maxillofacial clinic), stemi_thrombolysis 17/20 (intra-arterial thrombolysis),
paediatric_inpatient 17/20 (PICU and ICCU bed counts), dialysis recovered 2/6 (fistula and catheter access
surgery), ultrasound recovered 9/10 (an Ayurvedic "fetal wellbeing" programme). Two of the three remaining
emergency_24x7 recovered errors (postgraduate seat intake) are removed by an exclusion added after the check and
covered by an assert. The remaining errors are listed in the WRONG table of handcheck_v1_1.py.

Not checked: the 21 v1.0 services outside the core 7 still have only the reviewer's one sentence each (19/21).

## Attribute slots (hours and details)

attributes_src.py defines what the KB step must fill. Per service, `attributes` in services.json gives the slots, and
lexicon.json `attribute_patterns` gives the extraction patterns. A service attribute is read only from a sentence that
matched that service, because a hospital's 24x7 pharmacy says nothing about its cath lab. `from_service` slots (for
example trauma_care.blood_on_site <- blood_bank) are true when the same facility has positive evidence for both. The
facility block holds beds_total, accreditation (NABH, NABL, JCI, NQAS, LaQshya, Kayakalp, ISO), empanelment (PM-JAY,
CGHS, ECHS, ESIC, state schemes, private insurance), hours_24x7, opd_hours, ownership and ambulance.

How often the patterns fire (out/attribute_counts.csv; facilities among usable records):

- Facility level: any 24x7 statement 4,181 facilities; NABH 1,292; NABL 353; JCI 40; PM-JAY 669; CGHS 180; ECHS 143;
  ESIC 141; state schemes 80; OPD hours 292; bed strength 946.
- Per service: emergency_24x7 with 24x7 in the same sentence 2,198; NICU level NICU-III 107 and SNCU 32, NBSU 0;
  cath lab primary PCI or 24x7 51; CT slices 212; dialysis machine counts 53, emergency dialysis 87, PMNDP or free
  15, shifts 3; ventilator age group neonatal 78, paediatric 36, adult 179; neurosurgery spine 146; trauma level I
  10, II and III 0 (only 14 claim sentences in the whole corpus state a trauma level, so external/mohfw_trauma_196
  must carry levels); emergency_csection with 24x7 in the same sentence 4, with blood bank evidence at the same
  facility 69.
- OPD timings and dialysis shifts are rare in the VF text. They will have to come from facility websites or calls,
  not from this lexicon.

## IPHS 2022 levels

The PDFs were fetched from nhsrcindia.org (robots.txt allowed) and converted with pdftotext into data/crawl/iphs/.
Citations name the volume, annexure or table, and row. v1.1 corrections:

- psychiatric_care: DH 100+ beds (psychiatry OPD E; D at SDH and 50-bed DH). The CHC rows are counselling (vol2
  Annexure 2 S.No. 32) and NMHP basic care by medical officers (S.No. 46), so the prior is zero below DH.
- de_addiction: CHC "Drug de-addiction" is a counselling row (S.No. 32). The IPHS prior is none.
- hiv_art: testing is ICTC at every CHC (S.No. 31). "ART Services" is a Support Services row. vol1 line 108 does
  expand ART as Anti-Retroviral Therapy, which v1.0 denied, but the row is not used as a treatment prior. The ART
  treatment prior is zero below DH (link ART at most).
- high_risk_pregnancy: the obstetric HDU is D at the 50-bed DH, not E.
- New citations for stemi_thrombolysis (vol1 Annexure 3 Recommended Service Mix, acute chest pain including
  thrombolysis; thrombolytic therapy D at 200+ bed DH; vol2 S.No. 2.11 MI), paediatric_inpatient, safe_abortion_mtp,
  nutrition_rehabilitation (vol1 NRC table: 10 (D) at SDH, 6 (D) at DH-50, 10 to 30 (E) at 100+ beds; vol2 NRC D at
  FRU-CHC) and emergency_24x7.

## Open questions

1. No native-speaker or ASHA check of names and phrases. The new phrases (programme terms, spelling variants,
   symptom phrases) are the author's.
2. Urgency windows were rewritten from ABA burn referral criteria, BOAST 4, ESC 2023 ACS and AHA/ASA 2019 as quoted
   in the review. I did not fetch those documents. A clinician should review.
3. The routing in `symptom_phrases` is data. Whether the decision layer honours `requires` and `second_card` is not
   tested here.
4. stemi_thrombolysis, paediatric_inpatient and the three prior-answered services depend on a public-facility level
   prior that does not exist yet (public lists such as HOT OSM and LGD, plus the IPHS level).
5. The specialty weights are corroboration rates, not offer probabilities, and depend on lexicon recall.
6. Quantity scope (unit vs whole hospital) is still not resolved at sentence level.

## CHANGELOG

### v1.1 (2026-11-21): review fixes

Every high and medium issue from review/REVIEW.md is applied. Low issues are applied except where noted. Numbers are
v1.0 -> v1.1 and come from the scripts in this folder.

High:

1. Symptom phrases routed to specialised services. Fixed: `phrases` is split into `name_phrases` (148) and
   `symptom_phrases` (76) with route, requires and second_card. 31 emergency symptoms route to emergency_24x7 first.
   Heart attack requires stemi_thrombolysis; head injury and stroke require CT; obstetric emergencies route to CEmONC.
2. trauma_emergency mixed general ED and trauma. Fixed: split into emergency_24x7 (the claims `trauma` pattern,
   with bare `trauma` narrowed to trauma centre, unit, ward, bay or ICU) and trauma_care (explicit trauma,
   polytrauma, road accidents, head injury; orthopaedic-only "trauma" clauses excluded). trauma_emergency is an alias
   of trauma_care. v1.0 trauma_emergency: 8,798 sentences, 3,579 facilities (any), 3,181 text positive. v1.1
   emergency_24x7: 6,901 / 3,367 / 2,925; trauma_care: 2,852 / 1,270 / 1,237. Specialty map: emergencyMedicine
   (2,079 facilities) -> emergency_24x7; 22 trauma values (40 facilities) -> trauma_care.
3. Sentence-level trauma exclusions vetoed about 30% wrongly. Fixed: `\bdental`, emergency care/services accepted by
   the ambulance guard, case-sensitive `ER`, specialty-scope words moved to clause level. Sentence-level vetoes on
   the ED pattern: 957 -> 62. Clause-level vetoes: 267, and 10/10 sampled vetoes were right. Recovered sentences
   (vs the claims tag): 265, sampled 17/20 correct.
4. Binary service vs too_general label. Fixed: specialty_evidence_weights.csv (1,346 pairs, split-half log loss
   0.4505 vs 0.4555 for the binary interface and 0.5504 for a constant). The label is kept for readability.
5. IPHS prior overstated for psychiatric_care, de_addiction and hiv_art. Fixed as described under IPHS, with
   `prior_below_dh: 0`. The ART expansion statement is corrected.
6. No thrombolysis branch for heart attack. Fixed: stemi_thrombolysis with a decision rule (cath lab first only
   within 120 minutes), IPHS citations and a lexicon (30 sentences, 22 facilities, sample 20/20).
7. Snakebite and rabies left out. Fixed: both are in the taxonomy with `answer_mode: prior` and the call-to-confirm
   note. nutrition_rehabilitation is brought in on the same basis.
8. No attribute slots for hours and details. Fixed: attributes_src.py, `attributes` per service (35 of 36 services;
   surgical_oncology has none), a facility_attributes block, and counts in out/attribute_counts.csv.

Medium:

9. `dent` matched "accident". Fixed (`\bdent`). The 10 accident values (16 facilities) now map to emergency_24x7,
   trauma_care, icu or orthopaedic_trauma_surgery. independentDivisions, which the bug had also caught, is now
   not_a_service.
10. SNCU and NICU merged. Fixed: `required_attributes` level (NBSU, SNCU, NICU-III) and ventilation, a `level_prior`
    from IPHS, and a symptom phrase for a non-breathing newborn that requires NICU-III or ventilation.
11. Neurosurgery and spine. Fixed: the definition is brain surgery including emergency head injury; spine_surgery is
    an attribute (146 facilities). 19 spine values (for example orthopedicSpineSurgery, 99 facilities) map to
    too_general with prereq_for neurosurgery;orthopaedic_trauma_surgery. spineNeurosurgery stays neurosurgery,
    because it names neurosurgery.
12. Burn window. Fixed (10% TBSA, deep burns, special sites, electrical, chemical, inhalation, children; same day).
13. Open fracture window. Fixed (BOAST 4 timings, pulseless limb and compartment syndrome as emergencies).
14. CEmONC. Fixed: emergency_csection is defined as CEmONC (id kept), with `hard_prerequisites` blood_bank, 24x7
    anaesthesia and OT. PPH and eclampsia phrases are there. high_risk_pregnancy routes emergencies to it.
15. paediatric_inpatient added (40 facilities, sample 18/20), with an IPHS level prior. Sick-child phrases route to it.
16. low_coverage on text only. Fixed: 1 flagged -> 15 flagged in the taxonomy (all nine the review named, plus
    safe_abortion_mtp, stemi_thrombolysis, paediatric_inpatient and the three prior services). The threshold for
    text 2+ fields is 100, not 25, because the review's list runs up to 99.
17. "Department of Psychiatry" word order. Fixed: 39 of 40 such sentences missed -> 1 of 40. psychiatric_care
    sentences 399 -> 437. Recovered sample 9/10.
18. Dialysis fistula exclusion. Fixed: access words (fistula, permacath, dialysis catheter, line insertion, dialysis
    access) veto only their own clause and only without a unit word; `dialysis access\b` no longer hits
    "accessories". Sentence-level dialysis vetoes 40 -> 1; clause-level 48. Net vs claims tags: +6 sentences, -15
    catheter-insertion sentences. Recovered sample 5/6 (the error: "Centre" in a hospital name defeats the unit-word
    guard).
19. Non-interventional cardiology and cardiac catheterisation. Fixed (both now behave as the review asked).

Low:

20. Obstetric scan names. Fixed: 37 of 207 missed -> 2 of 207. "fetal well-being" needs scan, ultrasound or study
    after it (an Ayurvedic programme matched).
21. Stroke rehab and neurovascular surgery. Fixed: strokeRehabilitation -> out_of_scope, neurovascularSurgery ->
    neurosurgery.
22. Cancer site values. Fixed: "<site> cancer" values -> too_general with all three cancer services (12 values carry this label now).
    "Regional Cancer Centre" is added as related evidence for the three cancer services. It is not include evidence,
    because the designation alone does not say which of the three a centre runs.
23. Multi-service values. Fixed: `service_id` may be a `;` list (9 values). Consumers in this folder split on `;`.
24. prereq_for errors. Fixed: neurology -> stroke_care only; urology -> kidney_transplant; pathology ->
    surgical_oncology;chemotherapy. general surgery -> trauma_care; laparoscopy no longer a trauma prerequisite.
    cardiology and paediatrics gain the new services.
25. Hinglish collisions. Fixed: "light lagwana (cancer)", "oxygen machine", "bachche ki jaanch (scan)" and "dard nahi
    ho raha, operation karna padega" are removed. "pregnancy mein scan" is added, and "pet ki jaanch" is kept as a
    low-weight symptom phrase.
26. Loanwords and programme terms. Partly done: HRP, FRU, CEmONC, NBSU, 108, "kam vajan ka bachcha", "samay se pehle
    janma", spelling variants (sijer, sizer, sizerian, dialisis, dayalisis, lakva, motiyabindu, tee bee) are added as
    phrases. Not done: reordering names.hi to put loanwords first, KMC and MCP card, fuzzy query matching and
    Devanagari query input. These belong in the query parser, which is not in this folder.
27. Staff and directory sentences. Fixed for the kinds claims.parquet marks: positive evidence drops `staff` and
    `directory` sentences (facilities with positive text fell by 0 to 20 per service). The two reviewer examples are tagged
    `specific` in claims.parquet, so they are still counted; a better staff detector belongs in cleaning/claims. v1.1
    hand-check CSVs mask doctor names.
28. Kidney transplant follow-up and "arranged from the district blood bank". Fixed (exclude and third_party cue;
    both have asserts).
29. Dialysis HBV machines and emergency vs maintenance. Fixed: separate machines moved to `desirable_capabilities`,
    with attributes emergency_dialysis (87 facilities) and hbv_machine.

Also from the review text (section 1, not in the ranked list): stroke window now counts from last known well and CT
24x7 is a hard prerequisite; TB window includes any cough in people with HIV, diabetes or a TB contact; psychiatric
care carries Mental Healthcare Act 2017 and Tele-MANAS context; ventilator_support has an age_group attribute;
safe_abortion_mtp is added (151 facilities, sample 19/20); palliative_care is listed as a candidate with counts.
Not done: the review's suggestion to make ventilator_support an attribute of the critical care services. It stays a
service because CHWs search for "ventilator" directly. A shared NICU and PICU factor is left to the model.

Lexicon totals: matched (sentence, service) pairs 62,910 -> 64,670; sentences with any match 57,324 -> 58,004.
No Databricks call was made in v1.1 (LLM statements used: still 1).

### v1.0 (2026-11-21)

First version: 29 services in 10 categories, 3 candidates, specialty map, lexicon and IPHS citations.
