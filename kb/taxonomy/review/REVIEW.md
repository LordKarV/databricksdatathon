# Adversarial review of the service taxonomy

Reviewed: kb/taxonomy/services.json, specialty_map.csv, lexicon.json, TAXONOMY.md (version 1.0, 2026-11-21).
Nothing outside kb/taxonomy/review/ was modified.

## Verdict

The taxonomy is usable as the service axis of the (service, location) model after a short list of fixes. IPHS
citations check out against the IPHS text, with two exceptions that inflate the public-facility prior. Specialty-map
precision is close to what the builder reported. The lexicon is precise, but its sentence-level exclusions and a
`dent` substring bug throw away real trauma and emergency evidence. The weakest part is design rather than regex:
symptom phrases ("behosh hai", "seene mein dard", "head injury") point straight at specialised services, so a CHW
could be routed past the nearest facility that can stabilise the patient. trauma_emergency also mixes general 24x7
emergency with trauma care, and the service vs too_general split for specialties does not match how often each
value is confirmed by text.

## How it was checked

All scripts are in this folder and run with /Users/karthikvattem/projects/datathon/.venv/bin/python from kb/taxonomy.

| script | what it does | output |
| --- | --- | --- |
| sample_specialty_map.py | 80 random values (seed 4242, excluding the 99 values the builder hand-checked) and the top 30 by facility count | specialty_sample_random80.csv, specialty_top30.csv |
| corroboration.py | for each specialties value used by 100+ facilities, the share of those facilities with positive text for the mapped service (or its prereq_for services) | corroboration.csv |
| sample_lexicon.py | 21 matched sentences (one per service the builder did not precision-check) and 19 unmatched sentences that contain a referral keyword | lexicon_sample40.csv |
| probe_lexicon.py | 55 hand-written adversarial sentences plus 6 non-offer cue probes | stdout |
| exclusion_loss.py | sentences where an include pattern hits but the exclude pattern vetoes the whole sentence; counts of specific recall gaps | stdout |
| overlap.py | facility and sentence overlap between service pairs; text-only 2+ field counts | stdout |
| record_verdicts.py | writes my hand verdicts into the CSVs and prints tallies with 95% Wilson intervals | the three CSVs |

The verdict criterion matches the builder's. A specialty label is correct when it follows the stated rule (service:
the value names the service, its unit or its core procedure; too_general: a broad specialty; out_of_scope: a real
specialty no service covers). A matched sentence is correct when, read alone, it says this facility provides the
service or has its unit or equipment.

IPHS claims were checked against data/crawl/iphs/*.txt (the builder's pdftotext output). The other guideline URLs
below are cited from my own knowledge. I did not fetch them in this review, except that a web search confirmed that
the ABA burn referral page exists and still uses the 10% TBSA partial-thickness trigger.

## 1. Clinical correctness

### IPHS citations (checked against the text)

Confirmed: dialysis 4+1 beds at SDH and every DH size, 8+2 at 300+ beds (vol1 Annexure 2). SNCU at every SDH and DH,
NICU beds added from 100-bed DH. Paediatric ICU from 200-bed DH (3 adult + 1 paediatric ICU). CT is "-, D, D, E, E,
E, E" across SDH and DH 50 to 500 beds, so it is essential from 200 beds. MRI is D everywhere. Burn ward 6*D at SDH and
3/6/6/6/10/10 beds at DH. Caesarean is E at FRU-CHC and D at non-FRU CHC (vol2 Annexure 2). NBSU is E at all CHC types
(4 beds). Cataract and glaucoma services run weekly at CHC.

Wrong or overstated:

- psychiatric_care says "CHC (mental health services essential)". The vol2 row (Annexure 2, S.No. 32) sits under
  "INTEGRATED COUNSELLING SERVICES", next to tobacco cessation and nutritional counselling. That is counselling,
  which the service's own contradicting_evidence lists as "counselling or psychology only". The same block lists
  "Drug de-addiction" as E at every CHC type, also counselling, while de_addiction says "not a separate IPHS
  service area". Fix: psychiatric_care expected_from = "DH 100+ beds (psychiatry OPD); CHC counselling only, not
  psychiatric care". For de_addiction, cite the CHC counselling row and set the IPHS prior to none.
- TAXONOMY.md says the IPHS tables "do not expand" ART. vol1 line 108 of the abbreviation list reads "ART
  Anti-Retroviral Therapy", so the reading is right. The trouble is the other way round: IPHS marks "ART Services" E
  at every 30-bed CHC, inside "Support Services", next to the pharmacy and registration counter. NACO runs full ART
  centres mainly at medical colleges and district hospitals, and link ART centres at smaller facilities. If the IPHS
  E mark is used as a presence prior, it will claim ART at every CHC. Fix: cite vol2 S.No. 31 "Integrated Counseling
  and Testing services (HIV)" for testing at CHC. Treat ART at CHC as "link ART at most", and leave the IPHS prior
  for ART treatment at zero below DH.
- high_risk_pregnancy and emergency_csection say obstetric HDU/ICU is essential "at SDH and DH". The 50-bed DH column
  reads "2HDU(D)", which is desirable. This matters little.

### Definitions, prerequisites and urgency windows

- burn_care window: "large burns (over about 20% body surface in adults) need a burn unit within 24 hours". 20% is
  the formal fluid-resuscitation threshold, not the referral threshold. ABA referral criteria
  (https://ameriburn.org/burnreferral) refer at partial thickness of 10% TBSA or more, any full-thickness burn, burns
  of the face, hands, feet, genitalia, perineum or major joints, and every electrical, chemical or inhalation injury,
  with lower thresholds for children. Fix: window = "refer the same day for burns of 10% or more of the body (about
  10 palms), any deep burn, burns of the face, hands, feet, genitals or joints, electrical or chemical burns, smoke
  inhalation, or a child; start fluids first". Drop "within 24 hours".
- orthopaedic_trauma_surgery window: "open fractures need debridement within about 24 hours". BOAST 4 (open
  fractures, https://www.boa.ac.uk/resource/boast-4-pdf.html) gives antibiotics within 1 hour, immediate surgery
  for heavily contaminated wounds or vascular injury, debridement within 12 hours for high-energy fractures and
  within 24 hours for others. Fix that window. Also add "a cold, pale or pulseless limb, or severe pain under a
  plaster (compartment syndrome) is an emergency".
- emergency_csection: the 30-minute decision-to-delivery window is correct for category 1 (NICE NG192,
  https://www.nice.org.uk/guidance/ng192; category 2 is 75 minutes). The real problem is scope. Of the phrases,
  "khoon jaa raha hai delivery mein" is postpartum haemorrhage and "jhatke aa rahe hain" (eclampsia) sits in
  high_risk_pregnancy, whose profile is "scheduled". Both need a CEmONC facility with blood and an obstetric HDU,
  not a C-section as such. Fix: define the service as CEmONC (24x7 obstetric surgery, blood, anaesthesia), keep the
  id for MODEL_SPEC compatibility, and add blood_bank to its required capabilities as a hard prerequisite (it is
  already in the list). Move the eclampsia phrase here and mark high_risk_pregnancy's emergency phrases
  "route to emergency_csection".
- cath_lab_angioplasty window: "90 to 120 minutes of first medical contact, otherwise thrombolysis at the nearest
  capable facility". This is consistent with ESC 2023 ACS (https://doi.org/10.1093/eurheartj/ehad191: primary PCI
  if it can be done within 120 minutes of diagnosis, otherwise fibrinolysis within 10 minutes, within 12 hours of
  onset). But the taxonomy has no service for the "otherwise" branch. See missing services.
- stroke_care: the 4.5-hour thrombolysis window and the thrombectomy window of up to 24 hours for selected patients
  are consistent with AHA/ASA 2019 (https://www.ahajournals.org/doi/10.1161/STR.0000000000000211). Add "from last
  known well, not from when symptoms were found" (a wake-up stroke counts from bedtime), and make "CT 24x7" a hard
  prerequisite. Today it is a required capability, but nothing enforces it.
- neurosurgery: the definition and EN names say "brain and spine surgery", but the lexicon has no spine pattern
  (1,753 of 1,965 "spine/spinal surgery" sentences are not tagged neurosurgery), and the specialty map sends
  spineNeurosurgery (687 facilities) to neurosurgery but orthopedicSpineSurgery (99) and spineSurgery (12) to
  out_of_scope. For referral, what counts is emergency craniotomy for head injury. Fix: define neurosurgery as
  "brain surgery, including emergency surgery for head injury"; make spine a sub-attribute; map spine values to
  too_general with prereq_for neurosurgery;orthopaedic_trauma_surgery.
- dialysis: "separate machines for HBV/HCV positive patients" is reasonable practice. I could not confirm whether it
  is a PMNDP requirement (https://main.mohfw.gov.in/sites/default/files/Guidelines%20PMNDP.pdf was not read). The
  PMNDP self-assessment checklist found in the search covers hepatitis B vaccination, not dedicated machines. Mark
  it "desirable", not required. Add the referral-relevant split: emergency dialysis (AKI, high potassium) needs a
  hospital with an ICU, while standalone PPP centres do only maintenance sessions.
- nicu: merges SNCU (level II, NHM) and NICU (level III with ventilation). For a CHW the difference is real: a baby
  who needs a ventilator should not be sent to a 12-bed SNCU. Fix: keep one service, but add a required attribute
  `level` (NBSU / SNCU / NICU-III) and a `ventilation` flag. The IPHS table gives the prior (SNCU at every DH, NICU
  from 100 beds).
- psychiatric_care: add Mental Healthcare Act 2017 context. Emergency treatment is allowed at any health
  establishment for up to 72 hours, and admission needs a registered mental health establishment. Also add Tele-MANAS
  (14416) as a non-facility fallback the app shows for suicide-risk phrases.
- tb_care: "test within days of a 2-week cough" follows the classic NTEP presumptive-TB definition. NTEP now screens
  vulnerable groups (PLHIV, contacts, diabetics) for cough of any duration. Add that, or soften it to "cough of 2
  weeks or more, or any cough in a person with HIV, diabetes or a TB contact".
- trauma_emergency "golden hour" is a convention, not an evidence threshold. Keep it, worded "as fast as possible;
  the first hour matters most".

## 2. Specialty map precision

Random 80 values (seed 4242, none of them in the builder's 99 checked values): 74/80 = 0.925 (95% Wilson 0.846 to
0.965). The builder's own random 60 gave 0.950 (0.863 to 0.983), so the two agree.

Errors (details in specialty_sample_random80.csv): spine-surgery (out_of_scope, while spineNeurosurgery is
neurosurgery), neurovascularSurgery (stroke_care, should be neurosurgery), rhinoplastyAndFacialPlasticSurgery
(too_general with prereq burn_care, should be out_of_scope), haematologyAutomation (too_general with prereqs
blood_bank and chemotherapy, but it is a lab analyser), swasthavritta (not_a_service, should be out_of_scope like
shalyatantra), placentalAbruption (out_of_scope, should be too_general with prereq emergency_csection). One more row
has a wrong prereq but an acceptable label: advanceLaparoscopicSurgery has prereq_for trauma_emergency, but
laparoscopy is elective.

68 of the 80 are out_of_scope or not_a_service, mostly singletons, so this sample says little about the service
labels that drive the model. Value-weighted precision overstates how good the model input is.

Top 30 values by facility count (77,907 facility mentions): 30/30 labels follow the stated rule (Wilson 0.886 to
1.000). Prereq problems: neurology lists neurosurgery as prereq_for (neurologists do not operate). urology should be
prereq_for kidney_transplant (the service's own required capabilities name a urologist). pathology should be
prereq_for surgical_oncology and chemotherapy (histopathology).

Errors outside the sample, found by grouping values on shared tokens:

- Bug in rule 1 (specialty_rules.py line 35): `dent` is unanchored, so it matches "accident". Ten values go to
  out_of_scope, including accidentAndEmergency (5 facilities), accidentAndTrauma, "Accident & Trauma",
  accidentAndTraumaCare, accidentTraumaCare, accidentEmergencyMedicine, accidentFractureCare and
  polyTraumaAndAccidentCare: 16 facilities in all. "accident and emergency" is one of trauma_emergency's own EN
  names. Fix: `\bdent`.
- "Non-Interventional Cardiology" maps to cath_lab_angioplasty (rule 9 matches "interventional cardiolog"). Fix:
  add `non[- ]?interventional` to the cardiology too_general rule, above rule 9.
- cardiacCatheterisation is labelled too_general. It names the cath lab procedure. Fix: add `catheteri[sz]ation`
  to rule 9.
- strokeRehabilitation maps to stroke_care, which contradicts the service's contradicting evidence. Fix: put
  `stroke rehab` in the rehab out_of_scope rule above rule 19.
- Cancer site values are inconsistent: "Breast Cancer" maps to surgical_oncology, but "Prostate Cancer", "GI Cancer"
  and "Head and Neck Cancer" go to out_of_scope (a later rule wins on `\bgi\b`, `prostate`, `head and neck`). Fix:
  label `<site> cancer` values too_general with prereq_for all three cancer services.
- The map is single-label, so "NICU/ PICU/ Neonatology" goes to picu only, and "Haematology, Haemato-Oncology & Bone
  Marrow Transplant" can carry only one service. Fix: allow `service_id` to be a semicolon list.

The service vs too_general split is not consistent with the data (corroboration.csv). Rate = share of the
facilities tagged with that value that have positive text for the service:

| value | label | rate |
| --- | --- | --- |
| emergencyMedicine | trauma_emergency (service) | 0.817 (1,699/2,079) |
| criticalCareMedicine | icu (service) | 0.710 (1,188/1,673) |
| neurosurgery | neurosurgery (service) | 0.572 (967/1,690) |
| nephrology | too_general, prereq dialysis | 0.389 (838/2,153) |
| neurology | too_general, prereq neurosurgery | 0.379 (743/1,958) |
| radiology | too_general, prereq ct_scan | 0.344 (1,031/2,993) |
| medicalOncology | chemotherapy (service) | 0.267 (383/1,435) |
| psychiatry | psychiatric_care (service) | 0.152 (178/1,172) |

psychiatry is a "service" label, but text confirms it less than half as often as nephrology, which is too_general.
The rate is a lower bound, because it depends on lexicon recall (the psychiatry lexicon misses "Department of
Psychiatry", see below). Still, the ordering shows the binary label is the wrong interface. Fix: the KB step should
use corroboration.csv-style rates (recomputed on a held-out half of facilities) as the specialty-evidence weight
per (value, service), instead of a 0/1 service vs too_general switch. This also settles open questions 3 and 5 in
TAXONOMY.md with data.

## 3. Lexicon false positives and negatives

40 sentences from claims.parquet (lexicon_sample40.csv):

- Part A, one matched sentence for each of the 21 services that were never precision-checked: 19/21 correct, 0.905
  (Wilson 0.711 to 0.973). One false positive is a staff sentence about a named doctor as "Director of
  Interventional Cardiology" at a clinic (cath_lab_angioplasty). Sentences naming individual doctors should not be
  stored as evidence. The other is a private diagnostic centre that a directory lists among "HIV Testing Centres"
  (hiv_art), which the service's own contradicting evidence excludes ("HIV test in a lab panel only").
- Part B, 19 unmatched sentences that contain a referral keyword: 2 should have matched, 0.105 (Wilson 0.029 to
  0.314): "Regional Cancer Center" (radiotherapy, chemotherapy, surgical oncology) and "Fetal well-being scan"
  (ultrasound). The pool holds 53,768 such sentences, so the interval puts somewhere between roughly 1,600 and
  16,900 sentences in this miss class. That range is wide, and most of the pool is genuinely off-target.
- All 40: 36/40 = 0.900 (Wilson 0.769 to 0.960).

Probes (probe_lexicon.py): 8 of 55 differ from my expectation. One of them ("Emergency obstetric care" ->
institutional_delivery) I accept. The other 7, with corpus counts from exclusion_loss.py:

| gap | corpus effect | fix |
| --- | --- | --- |
| trauma_emergency exclusion vetoes the whole sentence | 957 sentences vetoed; my 30-sentence sample had 9 wrongly vetoed, 0.300 (Wilson 0.167 to 0.479), so about 160 to 460 lost sentences. Causes: department lists that also name "ophthalmology", "psychology" or "dental"; "24x7 emergency services and ambulance" (the ambulance lookahead accepts only emergency department/room/ward/unit); "Trauma/Accidental Surgery" (`dental` matches "accidental") | `\bdental`; add `emergency (care\|services?)` to the ambulance lookahead; apply specialty-scope exclusions to the clause around the match (split on `;` `,`) instead of the whole sentence |
| `\bER\b` under re.I | 7 false trauma matches ("Er:YAG laser", "Er. Subhash") | `(?-i:\bER\b)` |
| dialysis exclude `fistula` | 40 vetoed; includes "Piles & Fistula Specialist" department lists and "peritoneal dialysis accessories provided free" | exclude only `(av\|arterio-?venous) fistula` when no unit word (unit, centre, machine, session, shift) is present |
| psychiatric_care word order | "department/unit/ward of psychiatry": 39 of 40 sentences missed | add `(department\|dept\|division\|unit\|ward\|centre\|clinic) (of\|for) psychiatr` |
| ultrasound obstetric scan words | 37 of 207 "fetal well-being / anomaly / NT / growth / level 2 / TIFFA scan" sentences missed | add those words |
| kidney_transplant follow-up | "Kidney transplant follow-up clinic" matches; the exclude needs `post[- ]?transplant` before the words | add `transplant follow[- ]?up` |
| blood_bank third-party | "Blood is arranged from the district blood bank" matches with no third-party cue | add `arranged (from\|through)`, `(from\|through) (the )?(district\|government\|nearby) blood bank` to the third_party cue |

Also, "Level III NICU with neonatal ventilators" tags ventilator_support. That is defensible, but ventilator_support
has no age scope, so an adult snakebite or poisoning case could be matched to a NICU. Fix: give ventilator_support
an `age_group` attribute filled from co-occurring NICU/PICU text.

Only 11 of 469,498 claim sentences contain Devanagari, so the source lexicon does not need Hindi patterns. Hindi
matters only on the query side (section 5).

## 4. Overlaps, gaps and thin services

Overlaps (overlap.py, positive text only):

- trauma_emergency: only 3,547 of 8,743 matched sentences (0.406) and 1,476 of 3,181 facilities (0.464) contain a
  trauma, accident, injury, fracture or casualty word. More than half of the facilities are in on general
  "emergency" text alone. Fix: split into `emergency_24x7` (any round-the-clock emergency department) and
  `trauma_care` (explicit trauma or polytrauma, MoHFW levels, CT plus surgery). Keep `trauma_emergency` as an alias
  of trauma_care for MODEL_SPEC. Most of the other urgent services then get "nearest emergency_24x7" as a fallback.
- nicu and picu: 264 of 335 PICU facilities also have NICU text, and 265 sentences match both ("NICU and PICU",
  combined units). PICU therefore has about 71 facilities of independent evidence. Fix: keep both, but let the model
  learn a shared paediatric critical care factor, and do not count a combined sentence as two independent
  witnesses.
- icu and ventilator_support: 391 of 460 ventilator facilities also have ICU text. ventilator_support is close to a
  sub-attribute of icu (plus picu or nicu). Fix: make it an attribute (`ventilators: count or yes`) of the three
  critical care services, unless the model needs it as a query in its own right.
- emergency_csection and institutional_delivery: 302 of 437 C-section facilities also have delivery text. That is
  expected, since CEmONC includes delivery. No change.
- stroke_care and neurosurgery share 77 facilities but no sentences, so they are separate in the text. No change.

Missing referral-relevant services:

- `stemi_thrombolysis` (chest pain / heart attack: ECG plus thrombolysis at the nearest capable facility when a
  cath lab is more than 120 minutes away). Today every heart attack phrase points at cath_lab_angioplasty.
- `snakebite_antivenom` and `anti_rabies` are left out for lack of VF text. They are among the most common CHW
  emergencies, and IPHS expects ASV and rabies vaccine at every PHC and CHC (vol3 Annexure 6, vol2 S.No. 2.3).
  Include them, answered by an IPHS level prior over public facility lists, and show "public facility expected to
  stock; call to confirm" instead of hiding them. Omission is the less honest choice for a CHW tool.
- `paediatric_inpatient` (sick child admission at a DH or CHC paediatric ward). PICU is the wrong answer for most
  sick children. Today "bachcha serious hai" points at picu (335 facilities with text).
- `safe_abortion_mtp` (MTP Act; IPHS vol1 line 4167 lists mid-trimester abortion among SDH/DH procedures). Referral
  matters for NGO coordinators, and its absence is conspicuous.
- `nutrition_rehabilitation` (NRC for SAM children; IPHS vol1 shows NRC 6 to 15 beds at DH, E from 200 beds) has the
  same case as ASV: include it with a public-list prior.
- `palliative_care` (7 facilities with palliativeCare, plus hospice and pain-palliative values in the sample) can
  wait. Mention it in candidates.

Thin services (positive text facilities in 2+ text fields, specialties excluded): hiv_art 14, stroke_care 34,
psychiatric_care 36, de_addiction 51, eye_emergency 64, tb_care 68, burn_care 71, emergency_csection 95, picu 99.
The builder's `low_coverage` flag counts specialties as a field and flags only hiv_art. Fix: compute low_coverage on
text-only fields; that flags all nine above. For hiv_art, tb_care and institutional_delivery the VF data is the wrong
source anyway. REPORT.md classifies 7,902 of the records' websites as own sites and only 92 as government, so public
programme services are under-represented. The model should say "VF records rarely describe government facilities;
estimate from the public list and IPHS level" instead of returning a low-confidence private hospital.

Hours and details. The task frames the KB as needing hours and details, but the taxonomy has no attribute slots. In
the claims, 9,576 sentences mention 24x7, 24 hours or round the clock, 3,783 mention a bed count, 3,780 mention
NABH, NABL or JCI, and 3,007 mention empanelment (PM-JAY, CGHS, ECHS, ESIC). Only 95 mention OPD timings. Fix: give
each service an `attributes` list the KB step must fill. For example: trauma_care {24x7, level}, nicu {level,
ventilation, beds}, dialysis {machines, shifts, hbv_machine, free_under_pmndp}, emergency_csection {24x7,
blood_on_site}, ct_scan {24x7, slices}, icu {beds, ventilators}, cath_lab_angioplasty {24x7_primary_pci}. A
facility-level block holds beds, accreditation and empanelment. "24x7" is the attribute that most changes a CHW's
decision, and it should be a per-service slot, because a hospital's 24x7 pharmacy says nothing about its cath lab.

## 5. Hindi names and phrases

These are reviewer judgements, not native-speaker or ASHA field checks. The NHM ASHA training modules (Hindi) are
the right reference vocabulary, and a field check with a few ASHAs is still needed.

- Names are mostly formal, government-document Hindi: गहन चिकित्सा इकाई, नवजात शिशु गहन चिकित्सा इकाई, उच्च
  जोखिम गर्भावस्था देखभाल, संस्थागत प्रसव, गुर्दा प्रत्यारोपण, आंख की आपातकालीन चोट का इलाज. ASHAs usually say the
  English loanword, written in Devanagari or in Latin script: आईसीयू, एसएनसीयू, "HRP / हाई रिस्क", डिलीवरी, किडनी
  ट्रांसप्लांट, आंख में चोट. Fix: put the loanword first in `names.hi` for display and keep the formal term as an
  alias.
- Missing programme vocabulary that ASHAs are trained on: HRP (high_risk_pregnancy), FRU and "badi aspatal" or "zila
  aspatal" (emergency_csection), NBSU, KMC, "kam vajan ka bachcha" and "samay se pehle janma" (nicu; the phrase
  list has "kamzor paida hua" and "premature baby"), "108 / 102" (any emergency), NRC, "MCP card".
- Collisions:
  - "light lagwana (cancer)" for radiotherapy collides with neonatal phototherapy ("bachche ko light mein rakhna"
    for jaundice). Drop it, or require "cancer" in the same query.
  - "oxygen machine" for ventilator_support usually means an oxygen concentrator. Drop it.
  - "sar ka scan" is listed under ct_scan, and "sar ka MRI" under mri. Fine, but a "sar ka scan" query after a head
    injury should go to CT, which it does.
  - "pet ki jaanch" for ultrasound also means a stomach check-up or a stool test. Keep it low weight.
  - "bachche ki jaanch (scan)" can read as a sex-determination request under PCPNDT. Replace it with "pregnancy
    mein scan" or "sonography".
- Unnatural phrase: "dard nahi ho raha, operation karna padega" (emergency_csection). Delete it.
- Symptom phrases routed to specialised services (the highest-severity design issue in this review): "behosh hai",
  "serious patient", "critical", "oxygen kam hai" point at icu. "heart attack", "seene mein dard", "dil ka daura"
  point at cath_lab_angioplasty. "head injury" and "sar mein khoon jam gaya" point at neurosurgery. "bachcha
  serious hai" and "bachche ko saans nahi aa rahi" point at picu. An unconscious adult, a chest pain case or a head
  injury should first reach the nearest 24x7 emergency with the right minimum capability (CT for head injury, ECG
  and thrombolysis for chest pain). Fix: split `phrases` into `name_phrases` (they select the service) and
  `symptom_phrases` (they select an emergency route: nearest emergency_24x7 that meets the hard prerequisites, with
  the specialised service as the second card).
- Spelling: Hinglish input varies more than vocabulary does. Add variants such as sijer, sizer and sizerian; dialisis
  and dayalisis; motiyabindu; lakva; tibi and "tee bee". Match queries with rapidfuzz (already in the venv) instead
  of exact strings, and accept Devanagari input for every phrase.
- "pagalpan" is correctly flagged as stigmatising. Keep it match-only and never display it.
- Coverage: Hindi and an unverified Marathi only. The app's GPS default will place many users in Tamil Nadu,
  Kerala, Karnataka, Andhra Pradesh, Telangana and West Bengal, where Hindi names do not help. Not a fix for this
  version, but list it as a known limit in the UI.

## Issues, ranked

| # | service | severity | issue | fix |
| --- | --- | --- | --- | --- |
| 1 | icu, cath_lab_angioplasty, neurosurgery, picu, emergency_csection | high | Symptom phrases send emergencies to specialised services and skip the nearest stabilising facility | Separate name_phrases from symptom_phrases; symptom phrases route to nearest emergency_24x7 meeting hard prerequisites, specialised service second |
| 2 | trauma_emergency | high | 54% of its facilities are in only on general emergency text; trauma and general ED are mixed | Split into emergency_24x7 and trauma_care; keep trauma_emergency as an alias of trauma_care |
| 3 | trauma_emergency | high | Sentence-level exclusions veto about 160 to 460 real sentences (department lists, ambulance lookahead, `dental` in "accidental") | `\bdental`; add emergency care/services to the lookahead; clause-level exclusion; `(?-i:\bER\b)` |
| 4 | all (specialty map) | high | Service vs too_general split contradicts corroboration (psychiatry service 0.152 vs nephrology too_general 0.389) | Use per (value, service) corroboration rates as evidence weights, fitted on held-out facilities |
| 5 | psychiatric_care, de_addiction, hiv_art | high | IPHS prior overstated: CHC rows are counselling or support-service entries, not psychiatric care or ART treatment | Rewrite expected_from as in section 1; IPHS prior zero below DH for ART and psychiatry |
| 6 | (new) stemi_thrombolysis | high | No service for the thrombolysis branch of the heart attack pathway | Add it: ECG plus thrombolytic 24x7, IPHS NCD level prior, urgency within 12 h of onset |
| 7 | snakebite_antivenom, anti_rabies | high | Dropped for lack of VF text although they are top CHW emergencies with an IPHS mandate | Include them with an IPHS and public-list prior and explicit "call to confirm stock" |
| 8 | (all) | high | No per-service attribute slots for 24x7, level, shifts, machines, beds, accreditation and empanelment | Add an `attributes` schema per service plus a facility-level block (section 4) |
| 9 | trauma_emergency (specialty map) | medium | Rule 1 `dent` matches "accident": 10 values, 16 facilities, mapped out_of_scope | `\bdent` |
| 10 | nicu | medium | SNCU and level III NICU merged; a ventilated baby can be routed to an SNCU | Add a required `level` and `ventilation` attribute |
| 11 | neurosurgery | medium | Definition includes spine, lexicon misses 1,753 of 1,965 spine-surgery sentences, map labels spine values three ways | Narrow the definition to brain and emergency head injury; spine as attribute; spine values too_general |
| 12 | burn_care | medium | Referral threshold given as about 20% TBSA within 24 h; ABA refers at 10% and for special sites, electrical, chemical and inhalation burns | Rewrite the window (section 1) |
| 13 | orthopaedic_trauma_surgery | medium | Open fracture window omits antibiotics within 1 h and the 12 h limit for high-energy injuries; no limb-threat red flags | Rewrite per BOAST 4 |
| 14 | emergency_csection, high_risk_pregnancy | medium | PPH and eclampsia phrases sit under C-section or a "scheduled" service | Define the service as CEmONC; move the emergency phrases there |
| 15 | (new) paediatric_inpatient | medium | Most sick children need a paediatric ward, not a PICU | Add the service with an IPHS level prior |
| 16 | hiv_art, stroke_care, psychiatric_care, de_addiction, eye_emergency, tb_care, burn_care, emergency_csection, picu | medium | low_coverage counts specialties as a field and flags only hiv_art; text-only 2+ field counts are 14 to 99 | Compute low_coverage on text fields only; show those nine as thin |
| 17 | psychiatric_care | medium | "department of psychiatry" word order missed (39 of 40) | Add the reversed pattern |
| 18 | dialysis | medium | `fistula` exclusion vetoes department lists and real PD service sentences | Exclude AV fistula only when no unit word is present |
| 19 | cath_lab_angioplasty (specialty map) | medium | "Non-Interventional Cardiology" mapped to cath lab; cardiacCatheterisation too_general | Add a non-interventional guard; add catheterisation to rule 9 |
| 20 | ultrasound | low | Obstetric scan names missed (37 of 207) | Add fetal well-being, anomaly, NT, growth, level 2, TIFFA |
| 21 | stroke_care (specialty map) | low | strokeRehabilitation and neurovascularSurgery mapped to stroke_care | Rehab to out_of_scope; neurovascular to neurosurgery |
| 22 | surgical_oncology, chemotherapy, radiotherapy | low | Site-cancer values labelled inconsistently; "Regional Cancer Centre" (65 sentences) untagged | Site-cancer values too_general for all three; add RCC as related evidence for all three |
| 23 | (specialty map) | low | Single-label map cannot hold multi-service values ("NICU/ PICU/ Neonatology") | Allow a semicolon list in service_id |
| 24 | neurology, urology, pathology | low | Wrong or missing prereq_for | neurology: drop neurosurgery; urology: add kidney_transplant; pathology: add surgical_oncology and chemotherapy |
| 25 | radiotherapy, ventilator_support, ultrasound, emergency_csection | low | Hindi/Hinglish collisions and an unnatural phrase | Drop "light lagwana", "oxygen machine", "bachche ki jaanch (scan)", "dard nahi ho raha..." |
| 26 | all | low | names.hi are formal; ASHA loanwords and programme terms missing; no spelling variants | Loanword first; add HRP, FRU, NBSU, KMC, 108; fuzzy matching; Devanagari input |
| 27 | cath_lab_angioplasty, hiv_art | low | Evidence sentences include named individual doctors (staff kind) | Drop staff-kind sentences from offer evidence; never store doctor names |
| 28 | kidney_transplant, blood_bank | low | Follow-up and "arranged from district blood bank" sentences count as offers | Add the exclude and the third-party cue |
| 29 | dialysis | low | HBV/HCV separate machines stated as required; not confirmed as a PMNDP rule | Mark it desirable; add emergency vs maintenance dialysis split |

## Not run

- No native Hindi or Marathi speaker or ASHA reviewed section 5.
- Guideline URLs other than IPHS were not fetched and read in this review.
- No fix above was applied or re-measured. Rates after the fixes are not known.
- The lexicon was not checked for recall on a random unselected sample (part B samples only keyword-bearing
  sentences), so overall recall is not estimated.
- Marathi names were not reviewed.
