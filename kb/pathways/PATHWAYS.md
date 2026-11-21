# Care pathways for multi-stop referral plans

Data for the planner (#8): for each service, the stages of care, what a facility must be able to
do at each stage, the time windows, the time spent at a stop, and the rules for adding or skipping
a stop. Facility-level routing only. It is not clinical advice and not a triage tool.

## Files

| File | What |
|---|---|
| `care_pathways.json` | 7 pathways, their stages, rules and the source list |
| `capabilities.json` | 26 capability tags the stages need, with evidence words, for `kb/taxonomy` to reconcile |
| `check_pathways.py` | Shape and sourcing self-check: `python3 kb/pathways/check_pathways.py` |
| `PATHWAYS.md` | This file |

## How to read the JSON

- `stages` are in order. The last one is the definitive (or recurring) stage. A stage needs every tag
  in `requires_all` and one tag from each group in `requires_any`.
- `window.minutes` counts from `window.from`. `kind` is `hard` (treatment is not given after it) or
  `target`.
- `dwell_minutes.typical` is the time at a stop before the patient can move on.
- `rules[].type`: `add_stop_only_if` (the only way a stabilising stop gets added), `skip_stop_if`,
  `never_delay`, `before_transfer`, `refer_if`. `condition` holds the thresholds; `when` and `then`
  say the same in words.
- Every number has `basis`:
  - `guideline`: carries a `source` id and a verbatim `quote`.
  - `assumption`: carries `why`. These are placeholders for the lead to accept or change.
- Every time-critical pathway with a stabilising stop has an `add_stop_only_if` rule with
  `definitive_travel_minutes_gt`. A stop is never added unless the definitive facility is beyond it.

## The seven pathways

| Pathway | Service | Stabilising stage needs | Definitive stage needs | Window | Add a stop only if definitive is beyond | Dwell |
|---|---|---|---|---|---|---|
| `stemi` | stemi | ecg, thrombolysis, emergency_24x7 | pci_cath_lab | 720 min from symptom onset (guideline); 120 min from first medical contact (guideline) | 120 min (guideline) | 90 min (guideline) |
| `major_trauma` | trauma | emergency_24x7 | general_surgery_ot, blood_transfusion, ct_scan, icu, trauma_centre or neurosurgery or orthopaedics | 60 min from injury (ASSUMED) | 60 min (ASSUMED) | 30 min (ASSUMED) |
| `obstetric_emergency` | csection | basic_emoc | comprehensive_emoc, blood_transfusion | 60 min from decision to refer (guideline) | 60 min (ASSUMED) | 30 min (ASSUMED) |
| `burns` | burns | iv_fluid_resuscitation, burns_dressing or emergency_24x7 | general_surgery_ot, burn_unit or plastic_surgery | none found | 60 min (ASSUMED) | 60 min (ASSUMED) |
| `sick_newborn` | nicu | neonatal_stabilisation | sncu or nicu | none found | 60 min (ASSUMED) | 60 min (ASSUMED) |
| `snakebite` | snakebite | none (single stop) | anti_snake_venom | none found | not applicable | not applicable |
| `dialysis_start` | dialysis | nephrology, laboratory | haemodialysis_unit | 60480 min from fistula creation (guideline) | not applicable | 240 min (ASSUMED); 1440 min (ASSUMED) |

`dialysis_start` is the scheduled one: assessment, then vascular access, then sessions 3 times a
week of at least 4 hours. Its objective is fewest trips, so the recurring-session unit should be
the nearest one. An urgent dialysis need skips to a single emergency stop.

`snakebite` is a single stop by design: the Indian guideline says nearest facility immediately and
full dose without delay. The planner should minimise time to the first facility with anti-snake
venom and prompt a phone call to confirm stock.

## Assumptions to accept or change

These numbers are not from a guideline. Each is marked `basis: assumption` in the JSON.

| Pathway | Where | Value | Why it is an assumption |
|---|---|---|---|
| `major_trauma` | stage `stabilise` window | 60 min | IPHS 2022 asks for stabilisation within the 'Golden Hour' from onset of the emergency but gives no number. 60 minutes is the usual meaning and was not found stated in an Indian source. |
| `major_trauma` | stage `stabilise` dwell | 30 min | No Indian time-at-stabilising-facility target was found. The guideline only says not to delay transfer for CT or wound procedures. 30 minutes is a planning placeholder. |
| `major_trauma` | rule `stop_only_if_definitive_far` | definitive_travel_minutes_gt 60 | The 60 minute threshold comes from the planner design in issue #6. No Indian guideline gives a time or distance threshold for bypassing the nearest facility. |
| `obstetric_emergency` | stage `basic_emoc` dwell | 30 min | No general time-at-stabilising-facility figure was found; only condition-specific limits (tamponade judged at 15 minutes, 4 hours between partograph alert and action lines). 30 minutes is a planning placeholder. |
| `obstetric_emergency` | rule `stop_only_if_fru_far` | definitive_travel_minutes_gt 60 | Taken from the one-hour access norm in the MoHFW 2010 guideline. No Indian guideline states a rule for bypassing the nearer facility. |
| `burns` | stage `fluids` dwell | 60 min | No source states the time spent at the first facility before onward transfer. 60 minutes is a planning placeholder for survey, IV access and first fluids. |
| `burns` | rule `stop_only_if_burn_unit_far` | definitive_travel_minutes_gt 60 | The Indian guideline grades by burn size and type, not by travel time, and gives no time threshold. 60 minutes matches the trauma placeholder. |
| `sick_newborn` | stage `stabilise` dwell | 60 min | No pre-transfer time was found. The 2 day average stay in FBNC 2025 is for full admissions, not stabilisation before transfer. 60 minutes is a planning placeholder. |
| `sick_newborn` | rule `stop_only_if_special_care_far` | definitive_travel_minutes_gt 60 | No newborn referral time target exists in the sources read. FBNC 2025 lets distance decide for 1500 to 1800 g babies without giving a number. 60 minutes matches the other pathways. |
| `dialysis_start` | stage `assessment` dwell | 240 min | No source gives the length of the assessment visit. Half a day is a planning placeholder for a consultation with blood tests. |
| `dialysis_start` | stage `access` dwell | 1440 min | The ICMR workflow says admission is needed for access creation but gives no length of stay. One day is a planning placeholder. |

The 60 minute add-stop threshold for trauma comes from issue #6. The same value is reused for
obstetric emergencies (where it matches the one-hour access norm in the MoHFW 2010 guideline),
burns and sick newborns, where no guideline gives any travel-time rule.

## Rationale and what the sources say

### Heart attack (STEMI)

- ICMR (2026) and the Cardiological Society of India (2017): transfer for primary PCI if it can be
  done within 120 minutes of first medical contact; otherwise thrombolyse within 12 hours of symptom
  onset, then transfer for PCI 3 to 24 hours later, or at once if thrombolysis fails.
- MoHFW (2022) describes the hub-and-spoke model: thrombolysis at district, sub-district and
  community hospitals, PCI at the hub. It also states a stricter trigger: thrombolyse first when
  transfer time is 30 minutes or more. Both readings are encoded as separate rules; the planner
  must pick one.
- IPHS 2022 lists streptokinase and heart attack management at CHC, SDH and DH, nothing at PHC,
  and calls a cath lab at a district hospital aspirational.

### Major trauma

- The Indian guideline (DGHS 2025) says immediate transport to the nearest facility, then
  stabilise and transfer early, and "do not delay transfer" for CT or wound procedures.
- It gives no rule for going past the nearest facility to a trauma centre. The direct branch in
  this pathway follows the planner design and the US field triage guideline, not an Indian source.
- MoHFW trauma care facility levels I to III could not be opened, so `trauma_centre` has no
  official definition here.

### Obstetric emergency including emergency caesarean

- MoHFW (2010): level 2 facilities (24x7 PHCs, CHCs that are not First Referral Units) stabilise
  eclampsia, bleeding, sepsis and shock; level 3 (First Referral Units) do caesarean section and
  blood transfusion. A referral centre should be reachable within one hour.
- First Referral Unit criteria (2025): operating theatres, anaesthesia and blood storage, all 24/7.
- Before transfer: first dose of magnesium sulphate for eclampsia; oxytocin drip and tamponade
  for bleeding; tranexamic acid within 3 hours of delivery; dexamethasone for preterm labour.
- Slow labour: 4 hours between the partograph alert and action lines to reach the unit.

### Burns

- DGHS (2025) grades by burn size and type, not by travel time. Small burns stay at primary
  level; larger ones go to secondary; inhalation, electrical, chemical eye and airway cases go
  straight to a tertiary burn centre.
- IV fluids for burns over 15% (adults) or 10% (children), started before transfer.
- The same guideline says most burns are not a threat to life in the first hour. Treating burns
  as time-critical is therefore a design choice; see the open questions in the JSON.

### Sick newborn

- FBNC (2025): newborn care corner at every delivery point (identify and refer), stabilisation
  unit at CHC or First Referral Unit, special newborn care unit at district level (no ventilation
  or surgery), NICU at teaching hospitals.
- ICMR neonatal transport workflow gives who moves up: under 1800 g or under 34 weeks to a special
  newborn care unit; under 1000 g, under 28 weeks, or needing ventilation or surgery to a NICU.
- Transfer only after stabilisation. For preterm labour, move the mother before delivery.

### Snakebite

- MoHFW (2017): nearest facility immediately; no tourniquet or traditional first aid; full dose
  of anti-snake venom without waiting for tests; if the facility has none, go to the nearest one
  where stock is confirmed by phone.
- Escalate only for failing breathing (ventilator) or bleeding and kidney injury (dialysis).
- IPHS 2022 lists anti-snake venom at PHC, CHC, SDH and DH.

### Starting dialysis

- PMNDP: a dialysis centre in each district hospital; sessions of at least 4 hours; the patient
  travels each time. The decision to start comes from a nephrologist or trained physician.
- Indian Society of Nephrology: 3 sessions a week; a new fistula is used no earlier than 6 weeks
  after creation; late presenters start on a temporary catheter and get permanent access within
  3 months.
- Where a fistula can be created is contested between PMNDP, ICMR and IPHS.
- Peritoneal dialysis (catheter at a hub hospital, 10 to 14 days before first use, 4 to 5 days of
  training, then home exchanges) is an alternative that is not encoded.

## Capability tags

26 tags in `capabilities.json`: 6 map to a service already graded in `derived/v1`, 20 are proposed.
None of the proposed tags or their evidence words has been run against the facility text.

| Tag | Status | Used by |
|---|---|---|
| `emergency_24x7` | existing: trauma | stemi.thrombolysis, major_trauma.stabilise, burns.fluids |
| `ecg` | proposed | stemi.thrombolysis |
| `thrombolysis` | proposed | stemi.thrombolysis |
| `pci_cath_lab` | proposed | stemi.pci |
| `general_surgery_ot` | proposed | major_trauma.definitive, burns.burn_unit |
| `blood_transfusion` | proposed | major_trauma.definitive, obstetric_emergency.comprehensive_emoc |
| `ct_scan` | proposed | major_trauma.definitive |
| `icu` | existing: icu | major_trauma.definitive |
| `trauma_centre` | proposed | major_trauma.definitive |
| `neurosurgery` | proposed | major_trauma.definitive |
| `orthopaedics` | proposed | major_trauma.definitive |
| `anti_snake_venom` | proposed | snakebite.asv |
| `ventilator` | proposed | rules only: snakebite.cannot_lift_neck |
| `iv_fluid_resuscitation` | proposed | burns.fluids |
| `burns_dressing` | proposed | burns.fluids |
| `burn_unit` | existing: burns | burns.burn_unit |
| `plastic_surgery` | proposed | burns.burn_unit |
| `nephrology` | proposed | dialysis_start.assessment |
| `laboratory` | proposed | dialysis_start.assessment |
| `vascular_access_surgery` | proposed | dialysis_start.access |
| `haemodialysis_unit` | existing: dialysis | dialysis_start.sessions |
| `basic_emoc` | proposed | obstetric_emergency.basic_emoc |
| `comprehensive_emoc` | existing: csection | obstetric_emergency.comprehensive_emoc |
| `neonatal_stabilisation` | proposed | sick_newborn.stabilise |
| `sncu` | proposed | sick_newborn.special_care |
| `nicu` | existing: nicu | sick_newborn.special_care |

Notes for the taxonomy:
- `nicu` in `derived/v1` matches NICU and SNCU wording together. The newborn pathway needs them
  apart: only a NICU ventilates or operates.
- `emergency_24x7` maps to the existing `trauma` service, which is really "has an emergency
  department". `trauma_centre` is the narrower tag.
- `comprehensive_emoc` maps to `csection`. Whether a CHC is a First Referral Unit is rarely stated
  in facility text; `external/laqshya_master` may help.
- `anti_snake_venom` and `thrombolysis` are about stock and trained staff on the day. Facility
  text is weak evidence for both; the call-ahead question should ask.
- The stemi and snakebite pathways have no graded service in `derived/v1` yet.

## Sources

| Id | Title | Publisher | Year | Origin | URL |
|---|---|---|---|---|---|
| `icmr_stw_stemi` | Standard Treatment Workflow: ST Elevation Myocardial Infarction (STEMI), ICD-11 BA41.0 | ICMR / Department of Health Research, MoHFW | 2026 | india | https://www.icmr.gov.in/icmrobject/uploads/STWs/1768823342_cardiology_1-5.pdf |
| `mohfw_stemi_2022` | Guidelines for Management of ST-Elevated Myocardial Infarction (NP-NCD) | Directorate General of Health Services, MoHFW | 2022 | india | https://medbox.org/preview/65c9d158f8d597982c0b9646/doc.pdf |
| `csi_stemi_2017` | Cardiological Society of India: Position statement for the management of ST elevation myocardial infarction in India. Indian Heart J 2017;69 Suppl 1:S63-S97 | Cardiological Society of India | 2017 | india | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC5388060/fullTextXML |
| `iphs_2022_dh` | Indian Public Health Standards 2022, Volume I: Sub District Hospital and District Hospital | MoHFW | 2022 | india | https://nhsrcindia.org/sites/default/files/Volume%201_SDH-DH.pdf |
| `iphs_2022_chc` | Indian Public Health Standards 2022, Volume II: Community Health Centre | MoHFW | 2022 | india | https://nhsrcindia.org/sites/default/files/CHC%20IPHS%202022%20Guidelines%20pdf.pdf |
| `iphs_2022_phc` | Indian Public Health Standards 2022, Volume III: Health and Wellness Centre - Primary Health Centre | MoHFW | 2022 | india | https://nhsrcindia.org/sites/default/files/PHC%20IPHS_2022_Guideline_pdf.pdf |
| `fru_2025` | Revised Guidelines for Operationalizing First Referral Units (FRUs) | National Health Mission, MoHFW | 2025 | india | https://www.nhsrcindia.org/sites/default/files/2025-12/FRU%20guidenline%202%201.pdf |
| `dghs_trauma_stg_2025` | Standard Treatment Guidelines for Management of Trauma: A Guidance Document for Clinical Management of Trauma in India | Trauma and Burn Division, DGHS, MoHFW | 2025 | india | https://www.dghs.mohfw.gov.in/uploads/assets/SwQ7pJMiJepMtqfUQNUJrGOROd584XHIgipqf7gI.pdf |
| `field_triage_2021` | National guideline for the field triage of injured patients: Recommendations of the National Expert Panel on Field Triage, 2021. J Trauma Acute Care Surg | American College of Surgeons Committee on Trauma expert panel | 2022 | international | https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9323557/fullTextXML |
| `snake_stg_2017` | Standard Treatment Guidelines: Management of Snake Bite | National Health Mission, MoHFW | 2017 | india | https://ncdc.mohfw.gov.in/uploads/pdf/Standard-Treatment-Guidelines-for-Management-of-Snake-Bite.pdf |
| `dghs_burns_stg_2025` | Standard Treatment Guidelines for Management of Burns: A Guidance Document for Clinical Management and Rehabilitation of Burn Injuries in India | Trauma and Burn Division, DGHS, MoHFW | 2025 | india | https://www.dghs.mohfw.gov.in/uploads/assets/S1Ipab4025VceQpFs7Qa6THwh07NLmggStsg1cDD.pdf |
| `bba_first_aid_2018` | British Burn Association First Aid Clinical Practice Guidelines | British Burn Association | 2018 | international | https://www.salisbury.nhs.uk/media/kgklfbxt/british-burn-association-first-aid-clinical-practice-guidelines.pdf |
| `pmndp_og` | Operational Guidelines for Pradhan Mantri National Dialysis Programme (Part 1 Haemodialysis, Part 2 Peritoneal Dialysis) | MoHFW | 2026 | india | https://nhsrcindia.org/sites/default/files/2026-07/Operational%20Guidelines%20for%20PMNDP.pdf |
| `pmndp_bid_2023` | Revised Bid Document for Provision of Hemodialysis Services at District Hospitals (PMNDP model RFP) | Department of Health and Family Welfare | 2023 | india | https://www.nhsrcindia.org/sites/default/files/FINAL%20DIALYSIS%20REVISED%2006%20JUN%2023.pdf |
| `icmr_stw_hd` | Standard Treatment Workflow: Hemodialysis (ICD-11-N005.9) | ICMR / Department of Health Research, MoHFW | 2026 | india | https://www.icmr.gov.in/icmrobject/uploads/STWs/1784807343_hemodialysis-new2.pdf |
| `icmr_stw_ckd` | Standard Treatment Workflow: Chronic Kidney Disease (ICD-11-GB61) | ICMR / Department of Health Research, MoHFW | 2026 | india | https://www.icmr.gov.in/icmrobject/uploads/STWs/1784807344_chronickidneydisease-updated.pdf |
| `isn_mhd` | Guidelines for Maintenance Hemodialysis in India / Standard Treatment Guidelines Haemodialysis | Indian Society of Nephrology / MoHFW | not printed | india | https://medbox.org/index.php/dl/5e3be55792355f4aff08cee4 |
| `mnh_2010` | Operational Guidelines on Maternal and Newborn Health | MoHFW (NRHM), Govt of India | 2010 | india | https://nhsrcindia.org/sites/default/files/2021-04/Operational%20Guidelines%20for%20Maternal%20Newborn%20Health.pdf |
| `dakshata_jobaids` | DAKSHATA Job-aids and Checklists (includes Safe Childbirth Checklist) | Maternal Health Division, MoHFW / NHM | not printed | india | https://nhm.gov.in/images/pdf/Dakshata_Implementation/3-days_Dakshata_Training-English/Resource_Material/Spiral_Booklet_for_printing-Job-aids_and_checklists/Job_aids_and_Checklists.pdf |
| `dakshata_facilitators` | Dakshata Facilitators Guidelines | Maternal Health Division, MoHFW / NHM | not printed | india | https://nhm.gov.in/images/pdf/programmes/maternal-health/guidelines/Dakshata-Facilitators_Guidelines.pdf |
| `uterotonics_note_2015` | Guidance Note on Use of Uterotonics during labour | Maternal Health Division, MoHFW, Govt of India | 2015 | india | https://nhm.gov.in/images/pdf/programmes/maternal-health/guidelines/Guidance_Notes_on_Use_of_Uterotonics_during_labor.pdf |
| `icmr_stw_pph` | Standard Treatment Workflow (STW): Postpartum Haemorrhage (updated) | ICMR / Department of Health Research, MoHFW | 2025 | india | https://www.icmr.gov.in/icmrobject/uploads/STWs/1768382528_updatedpostpartumhaemorrhage.pdf |
| `antenatal_steroids_2014` | Use of Antenatal Corticosteroids in Preterm Labour (Under Specific Conditions by ANM): Operational Guidelines | Child Health Division, MoHFW, Govt of India | 2014 | india | https://medbox.org/index.php/dl/5e148832db60a2044c2d3cf0 |
| `nice_ng192` | Caesarean birth, NICE guideline NG192, Recommendations | National Institute for Health and Care Excellence | 2021 | international | https://www.nice.org.uk/guidance/ng192/chapter/Recommendations |
| `fbnc_2025` | Facility Based Newborn Care Operational Guidelines 2025 | Child Health Division, MoHFW, Govt of India | 2025 | india | https://nhm.gov.in/images/pdf/programmes/CH-Programmes/FBNC/FBNC%20Operational%20Guidelines%202025.pdf |
| `icmr_stw_neonatal_transport` | Standard Treatment Workflow (STW): Neonatal Transport | ICMR / Department of Health Research, MoHFW | 2020 | india | https://www.icmr.gov.in/icmrobject/uploads/STWs/1726568619_neonatal_transport.pdf |

23 of 26 sources are Indian. International sources fill three gaps and are labelled: trauma
destination (US field triage), cooling time for burns (British Burn Association) and the 30 minute
decision-to-delivery interval (NICE).

## How the facts were checked

- Each source document was downloaded and its text extracted; quotes were copied from that text.
- All 55 quotes in `care_pathways.json` were matched by script against the collected source
  extracts (55 of 55 found verbatim, after replacing non-ASCII characters and joining line breaks).
- Spot check against freshly downloaded PDFs: 9 quotes from the ICMR STEMI workflow and the MoHFW
  snakebite guideline, 9 of 9 found.
- Not done: no clinician has reviewed this. The other 24 sources were not re-downloaded for a
  second check. Table-derived facts from IPHS 2022 (essential or desirable marks by facility type)
  come from text extraction and are used only in `facility_level_note`, not as numbers.

## Not found

- Any Indian door-in-door-out or time-at-stabilising-facility target, for any pathway.
- Any Indian rule for bypassing the nearer facility (trauma, obstetric, newborn).
- A number of minutes for the IPHS 2022 "Golden Hour".
- Decision-to-delivery interval in a primary Indian document.
- A bite-to-treatment target for snakebite; the 2024 national snakebite action plan (404).
- A deadline for starting IV fluids in burns; an Indian definition of burn unit against burn centre.
- A newborn referral time target; NICU equipment and admission norms.
- A travel-time or distance norm to a dialysis unit.
- MoHFW trauma care facility levels and spacing norms (search snippets only, not used).
- Unreachable: main.mohfw.gov.in and several state health sites. Mirrors were used where noted in
  the source list.

## Where sources disagree

- STEMI: lyse-first trigger of PCI not within 120 minutes (ICMR, CSI) against transfer time of 30
  minutes or more (MoHFW). Time to start thrombolysis: 10 minutes (ICMR) against 30 (CSI). The
  MoHFW text also has a 6 hour lysis window in one appendix against 12 hours elsewhere.
- Trauma: nearest facility first (India) against highest-level trauma centre first unless in
  extremis (US).
- Burns: cooling for 10 minutes (India) against 20 minutes within 3 hours (UK, WHO). IV fluid
  threshold in adults 15% (India) against 20% (international). IPHS says district hospitals
  "manage" burns of any size; DGHS says refer the largest to tertiary.
- Dialysis: fistula creation at tertiary level (PMNDP), district hospital (ICMR), or desirable
  only at 200+ bed district hospitals (IPHS). Sessions 3 a week (ISN, ICMR) against 2 to 3 (PMNDP).
- Obstetric: caesarean essential at a First Referral Unit CHC, only desirable at other CHCs.

## Open questions for the lead

Each pathway lists its own under `open_questions` in the JSON. The ones that change planner output:

1. STEMI: 120 minute rule or 30 minute rule? And how many minutes to add to travel for time inside
   the PCI centre?
2. Trauma: keep the direct-to-trauma-centre branch, given the Indian guideline says nearest
   facility?
3. Accept, change or remove the 11 assumed values in the table above.
4. Burns: plan by travel time (as encoded) or only by burn size and type, which needs patient
   details the app does not collect?
