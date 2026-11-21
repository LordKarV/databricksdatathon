# VF operational details

Quote-backed facts about hours, unit beds, equipment counts, staffing, accreditation, scheme and insurance empanelment, free or government care, ambulance and blood centres, all taken from the provided Virtue Foundation dataset. The step that assembles the facility x service knowledge base reads these, and so does the fitted model.

Scope: 9,959 facilities (the claims step's de-duplicated set) and 469,498 claim sentences from `cleaning/claims/out/claims.parquet` (procedure, capability, equipment, and description split into sentences). Typed fields come from `audit/scale/scale_flags.parquet` (cleaned capacity, numberDoctors, operator) and `cleaning/claims/out/specialties.parquet`. Every number below comes from `out/stats.json`, `out/report_numbers.txt` or `out/handcheck.json`.

## Run

```
cd /Users/karthikvattem/projects/datathon/kb/vf_details
../../.venv/bin/python patterns.py          # self-check of every pattern (asserts)
../../.venv/bin/python extract.py           # facts, facility table, hour candidates, stats (35 s)
../../.venv/bin/python llm_hours.py         # ai_query on hour candidates; counts statements, cap 4
../../.venv/bin/python llm_hours.py --reverify   # re-apply the checks to saved LLM output, no statement sent
../../.venv/bin/python extract.py           # second run merges out/llm_hours.parquet
../../.venv/bin/python handcheck.py sample  # 50 stratified facts -> out/handcheck_sample.csv
../../.venv/bin/python handcheck.py score   # uses handcheck_labels.csv -> out/handcheck.json
../../.venv/bin/python report_numbers.py > out/report_numbers.txt
```

## Outputs

| File | Rows | What |
|---|---|---|
| out/facts.parquet | 42,036 | One row per fact: 35,429 regex, 18 LLM, 6,589 from typed fields |
| out/facility_details.parquet | 26,046 | One row per facility x (fact_type, attribute): support counts, the value stated most often, best quote |
| out/hour_candidates.parquet | 64 | Hour sentences the parser could not read cleanly (the LLM pool) |
| out/llm_hours.parquet, out/llm_hours_raw.json | 64 | LLM output per candidate, with the keep/reject verdict |
| out/handcheck_sample.csv, handcheck_labels.csv, out/handcheck.json | 50 | Hand check |
| out/stats.json, out/report_numbers.txt | | Coverage, flags, plausibility |

`facts.parquet` columns:
- `fact_id`: stable across reruns (claim id + type + attribute + occurrence).
- `unique_id`, `claim_id`: claim id is null for typed fields. `field`: procedure, capability, equipment, description, capacity, numberDoctors, operatorTypeId or specialties.
- `fact_type`, `attribute`, `value_num`, `value_text`: for hours, `value_text` is a normalised schedule such as `mon-sat 10:00-20:30; sun 10:00-13:30`.
- `polarity`: positive, neutral (in process, norms only, linked outside blood bank) or negative (non-NABH, not accepted, negated).
- `status`: ok, flagged or excluded. `flags` is a pipe-separated list.
- `quote`: an exact substring of `source_text`, asserted for every row. `match` is the span the pattern hit.
- `attribution`, `context`, `kind`, `dup_in_record`: copied from the claims step. `method`: regex, llm or structured.

Use a fact as evidence only when `status` is ok or flagged and `polarity` is positive. Down-weight flagged facts; they are not wrong by default.

## Method

1. Deterministic patterns first (`patterns.py`). Each pattern finds a span. The quote is that span widened to its `;`, `|` or sentence segment, or an 80-character window snapped to word edges when the segment is longer than 220 characters. Sentence ends after "Dr.", "No." and similar abbreviations are not boundaries.
   - 24x7: "24x7", "24/7", "round the clock" and "24 hours" (except durations such as "within 24 hours" or "24-hour Holter"). The scope is the nearest keyword in the same comma clause: emergency, ambulance, pharmacy, lab_imaging, blood_bank, icu, dialysis, labour_room, helpline, nursing, home_care, operation_theatre; "facility" is used only when no specific scope is in the clause. "Doctor available 24 hours" becomes `staffing.doctor_24x7`.
   - Timed schedules: clock ranges with days, day ranges, "daily" and closed days. "10 - 2 pm" infers am for the start. "10:00-17:00" is read as a 24-hour clock. Dated one-off events are dropped. Scopes: opd, doctor_session, lab, pharmacy, dialysis, emergency, visiting, general.
   - Dialysis shifts: "three shifts", "(4 shifts)", "multiple shifts" in a dialysis or renal sentence.
   - Beds: unit beds for icu, nicu, picu, ccu, hdu, dialysis and emergency in three word orders ("10-bed ICU", "ICCU with 14 beds", "75 ICU beds"). Total beds reuse the audited rules in `audit/scale/beds_text.py`: no unit word in the clause, no chain, future or history words.
   - Equipment counts: dialysis machines, stations or chairs; ventilators; CT slices; MRI tesla; cath labs; operation theatres. Model numbers ("Innova 2100") and "Class 100" theatres are excluded or capped.
   - Staffing: counts of doctors, specialty doctors (for example "7 ENT doctors"), nurses and total staff; visiting or on-call consultants; 24x7 doctor. Teaching numbers ("trained 500 doctors") and LinkedIn headcount bands are skipped.
   - Accreditation: NABH, NABL, JCI, NQAS, LaQshya and Kayakalp. Each has a status: accredited, entry_level, pre_accreditation, in_process, norms_only, non or mentioned. Kayakalp needs award or quality context, because it is also an Ayurveda package name.
   - Empanelment: PM-JAY, RSBY, CAPF, CGHS, ECHS, ESIC, railway, Maharashtra MJPJAY, Aarogyasri (AP and Telangana), CMCHIS (Tamil Nadu), KASP and MEDISEP (Kerala), Swasthya Sathi (West Bengal), BSKY (Odisha), Rajasthan (Chiranjeevi, RGHS), Gujarat MA, Karnataka (Arogya Karnataka, Yeshasvini), other state schemes, and private insurance or TPA (insurer names, "cashless"). A scheme word that appears in the facility's own name is skipped ("Ayushman Hospital"). ESI needs empanelment context, because "ESI Hospital" is usually a place in a doctor's career.
   - Free or government care: free_care, free_under_scheme, free_camp, free_ambulance, free_event (a dated one-day offer), free_with_package (a freebie inside a paid plan), and government_run_text. "blade-free", "pain-free" and similar are excluded.
   - Ambulance: service, count and type (ALS, BLS, air, neonatal, 108/102). Blood centre: blood bank or storage unit, marked on_site_claim or outside_or_linked.
2. Typed fields: cleaned capacity becomes `unit_beds.total` (field capacity). numberDoctors becomes `staffing.doctors_named`; audit S2 found it counts doctors named in sources, not the roster. A public or government operatorTypeId becomes `public_operator`. The specialty tags bloodbank and transfusionmedicine become blood_centre facts flagged `kind_specialty_tag`. affiliationTypeIds "government" is not used: audit S9 found it means empanelled, not free.
3. Attribution and cues. Excluded:
   - sentences the claims step labels other_facility (382 facts);
   - template and research sentences;
   - staff biographies for every type except staffing counts and schedules;
   - negation, past and future cues, using the audited v2 cues in `cleaning/claims/lexicon.py`;
   - zero counts, implausible values, unit beds above the facility's total beds;
   - schedules that are still impossible after parsing.

   Flagged: ambiguous attribution, list and directory sentences, third-party, hedge or part-time cues, chain, history or dated scope on counts, duplicates within the record, and plausibility disagreements.
4. LLM for ambiguous hours only. 64 sentences had clock times plus an hours word but no clean parse: no meridiem, close before open, or open before 05:00. These went to `databricks-meta-llama-3-3-70b-instruct` through `ai_query` with a strict JSON schema. The run used 2 of the 4 allowed statements: a 3-row test, then all 64. A reading is kept only when all of these hold:
   - the quote string-matches the sentence;
   - the model says the sentence gives regular hours;
   - every returned hour and non-zero minute appears as a number in the quote;
   - the returned days appear in the sentence;
   - the schedule is plausible: open at or after 05:00, close after open, or an overnight shift with an explicit am/pm.

   Result: 18 kept, 19 not operating hours (dated events, certificate validity), 12 implausible (the model often left "10:00-02:00" unresolved), 9 times not in the quote, 6 quotes not in the source. The 18 kept readings replace the regex readings for those claims and are flagged `llm_extracted`.

## Hand check

There are 50 usable text facts (status ok or flagged, positive polarity), stratified by type with seed 20261121, and at least one is an LLM schedule. A fact counts as correct when type, attribute, value and polarity are what the sentence says, and the sentence states it about this facility now. The check reads the sentence only; it was not checked against the web.

- Overall: 46 / 50 correct, precision 0.92, 95% Wilson 0.81 to 0.97.
- By status: ok 38 / 41 (0.81 to 0.98), flagged 8 / 9 (0.57 to 0.98).
- By type: hours_24x7 6/6, unit_beds 6/6, empanelment 6/6, staffing 3/5 (0.23 to 0.88), accreditation 4/5, free_or_government 3/4, ambulance 4/4, blood_centre 4/4, equipment_count 4/4, opd_hours 4/4 (including the LLM reading "11:00-05:00" as 11:00-17:00, plausible but ambiguous), dialysis shifts 2/2. Per-type intervals are wide (n of 2 to 6); see out/handcheck.json.

Errors found, and what changed after the check:
- "Has 7 ENT doctors" and "Has 2 dermatologists on staff" were stored as facility doctor counts. These now go to `staffing.specialty_doctors`: 505 facts, and `staffing.doctors` has 2,310.
- "Dental Health Plan includes Free Consultation" was stored as free care. It is now `free_with_package` (10 facts).
- "NABH accreditation in Breast Cancer Radiotherapy Planning in SAARC Countries (2024)" was read as hospital accreditation. Not fixed: it is one sentence with no general pattern.

The 0.92 measures the version before these two fixes. The fixes were checked on the three affected facts, but a fresh sample has not been drawn, so the precision of the current version is not measured.

## Coverage

Facilities with at least one usable text fact, out of 9,959:

| Fact type | Text facts | ok | flagged | excluded | Facilities | Share |
|---|---|---|---|---|---|---|
| hours_24x7 | 10,506 | 10,008 | 459 | 39 | 4,112 | 41.3% |
| staffing | 4,475 | 3,577 | 833 | 65 | 2,855 | 28.7% |
| empanelment | 6,268 | 4,979 | 1,092 | 197 | 2,283 | 22.9% |
| unit_beds | 3,636 | 2,960 | 618 | 58 | 1,875 | 18.8% |
| accreditation | 3,498 | 3,317 | 158 | 23 | 1,431 | 14.4% |
| ambulance | 1,991 | 1,791 | 181 | 19 | 1,168 | 11.7% |
| free_or_government | 1,560 | 1,269 | 204 | 87 | 805 | 8.1% |
| blood_centre | 1,380 | 1,157 | 184 | 39 | 591 | 5.9% |
| equipment_count | 1,537 | 1,404 | 103 | 30 | 568 | 5.7% |
| opd_hours | 592 | 503 | 69 | 20 | 509 | 5.1% |
| hours_dialysis_shifts | 4 | 4 | 0 | 0 | 4 | 0.04% |

6,831 facilities have at least one usable text fact; 7,489 do when typed fields are counted. Typed fields alone give total beds for 2,496 facilities, numberDoctors for 3,604, a public operator for 467 and a blood bank specialty tag for 22.

Facilities with a usable fact, for the attributes the model is most likely to use:
- 24x7: emergency 2,281 (22.9%), facility-wide 2,517, lab or imaging 393, ambulance 323, pharmacy 287, ICU 159, dialysis 68, blood bank 58. 24x7 doctor on duty: 200.
- Schedules: general 345, OPD 115, doctor session 44, lab 13, emergency 10. Dialysis shifts: 4. The text holds 7 sentences with "shift" in total, so shift data is close to absent.
- Beds: total (text) 1,757; ICU 374; NICU 48; emergency 34; PICU 21; CCU 20; dialysis 16; HDU 13.
- Equipment: operation theatres 254, MRI tesla 235, CT slices 212, dialysis machines 32, ventilators 29, cath labs 17.
- Staffing: doctor count 1,739; staff total 923; specialty doctors 365; visiting or on-call 170; nurses 58.
- Accreditation: NABH 1,242; NABL 341; JCI 36; Kayakalp 10. Non-positive NABH statements: 13 non, 13 in process, 54 norms only.
- Empanelment: private insurance or TPA 1,793; PM-JAY 642; CGHS 182; ECHS 140; other state schemes 114; ESIC 105; Rajasthan 39; Aarogyasri 23; CAPF 22; MJPJAY 15; RSBY 13; Karnataka 13; CMCHIS 7; KASP 5; Gujarat MA 5; Swasthya Sathi 5.
- Free or government: free care 377, government-run text 236, free camp 134, free under a scheme 107, free ambulance 21.
- Ambulance service 1,168; blood bank 566; blood storage unit 35.

## Plausibility

- Text total beds against cleaned capacity: 2,946 facts, 2,759 with a capacity value. 2,261 are equal and 346 differ by more than 25% (both kept, flagged `disagrees_capacity`). The agreement is not corroboration: the provenance verifier found capacity comes from the description in 383 of 416 cases.
- Unit beds (690 facts): 13 exceed the facility's total beds (excluded). 19 are ICU-type beds at a facility typed clinic or dentist (flagged; facilityTypeId is unreliable per audit S7).
- Doctor counts against numberDoctors: 2,310 facts, 1,990 with numberDoctors. 1,316 are equal and 416 differ by more than 50% (flagged, info only). 34 state more than twice the facility's beds (flagged `doctors_exceed_beds`).
- Hard caps excluded 37 values: cath labs 11 (model numbers), ICU 7, doctors 6, operation theatres 4, staff 4, dialysis machines 2, ambulances 2, ventilators 1. 55 zero counts were excluded, such as "Has 0 ambulance team members".
- 746 facility x attribute rows have more than one distinct usable value, mostly total beds (379) and doctors (226). `facility_details.value_num` takes the most frequent value (the larger on ties), and `n_distinct_values` shows the conflict.

## Limits and how to use this

- Precision here is extraction precision against the sentence. It does not show the sentence is true. About 14% of records contain text about another facility (REPORT.md F1). Only the 382 facts in sentences the claims step attributes to another facility are excluded, and same-state merges pass every check.
- Repeats of a fact across procedure, capability and description come from one extraction (audit claims-05), so they are not independent corroboration. Count distinct claims at most once per facility; `dup_in_record` marks exact repeats.
- Absence is not evidence of absence. Lists are cut at 50 items in 2,080 rows (audit claims-07), and most facilities state no hours at all.
- "24x7 facility" is generic wording. Audit claims-10 found most 24x7 emergency text is not trauma capability; use `hours_24x7.emergency` as an access-hours feature, not as a service grade.
- Empanelment from insurer network listings (flagged `listing`) is third-party evidence that may be stale.
- The LLM was used on 64 sentences only. Its 18 accepted readings are plausible interpretations of ambiguous strings, not certain ones.
- Not done: same-state district contamination checks, a web check of the facts, and a second hand check after the fixes.
