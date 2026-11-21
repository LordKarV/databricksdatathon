# Web evidence

Quote-verified facts from the facilities' own websites: whether a site belongs to the facility, which taxonomy services it states, its hours, and details such as beds, accreditation, scheme empanelment, ambulance and blood centre. This is the first source in the knowledge base that the provided dataset did not write, so the step that assembles the facility x service table can use it to confirm or question the dataset's claims.

Every number below comes from `out/report_numbers.txt`, `out/stats_build.json`, `out/stats_compare.json`, `out/compare_by_service.csv` or `out/selfcheck.json`.

## Run

```
cd /Users/karthikvattem/projects/datathon
.venv/bin/python kb/web_evidence/build_web_evidence.py --test   # asserts on segmenting, negation, identity, quotes
.venv/bin/python kb/web_evidence/build_web_evidence.py          # about 90 s on 8 processes
.venv/bin/python kb/web_evidence/web_llm_hours.py --limit 3     # test statement (already run)
.venv/bin/python kb/web_evidence/web_llm_hours.py --batches 2   # all ambiguous hour lines (already run)
.venv/bin/python kb/web_evidence/build_web_evidence.py          # second run merges the LLM readings
cd kb/web_evidence
../../.venv/bin/python compare_dataset.py                       # summaries and the dataset comparison
../../.venv/bin/python selfcheck.py sample                      # 40 items -> out/selfcheck_sample.csv
../../.venv/bin/python selfcheck.py score                       # verdicts in selfcheck.py -> out/selfcheck.json
../../.venv/bin/python report_numbers.py > out/report_numbers.txt
```

Setting `WEB_EVIDENCE_CACHE=<file>.pkl` keeps the per-file pass between runs. Do not rerun `web_llm_hours.py` without reason: it has used 3 of its 6 statements, and the counter in `out/llm_statements.json` refuses a 7th.

## Outputs (out/)

| File | Rows | What |
|---|---|---|
| site_identity.parquet | 6,770 | One row per (crawl target, record): name, PIN and locality evidence with quote and URL, conflicts, `confidence` (high, medium, low, none) and `attributable` |
| page_identity.parquet | 30,517 | The same evidence per (page, record) |
| web_services.parquet | 153,160 | One row per (record, page, line, service): `service_id`, `quote`, `url`/`final_url`, `fetched_at`, `role` (page section from the crawl: home, seed, link:services ...), `field` (text or chrome_text), `negated`, `nonoffer_cue`, `weak_cue`, sentence `kind`, `edu`, `positive`, `strength`, `scope`, `identity_conf`, `attributable` |
| web_service_summary.parquet | 20,886 | One row per (record, service) over attributable rows: `web_positive`, `web_positive_strong`, counts, best quote and URL |
| web_hours.parquet | 43,540 | 24x7 statements by scope, OPD and other schedules, dialysis shifts, 24x7 doctor; VF-details schema plus page columns |
| web_details.parquet | 41,191 | Beds by unit, equipment counts, accreditation, empanelment, ambulance, blood centre, free or government care, staffing, emergency phone listed |
| web_facility_details.parquet | 17,908 | One row per (record, fact_type, attribute) from hours and details, same columns as `kb/vf_details/out/facility_details.parquet`, plus `best_url` |
| compare_by_service.csv | 37 | The dataset comparison per service and for all services |
| hour_candidates.parquet, llm_hours.parquet, llm_hours_raw.json | 833, 633 | The ambiguous hour lines, and the LLM answers with keep or reject verdicts |
| selfcheck_sample.csv, selfcheck.json; selfcheck_round1.csv, selfcheck_round2.csv | 40 each | The scored self-check (round 3) and the two development rounds |

Use a row as evidence only when `attributable` is true. For services, also require `positive`; prefer `strength == "strong"`. For hours and details, require `status` in (ok, flagged) and `polarity == "positive"`, as in vf_details. Rows with `scope == "chain_home"` are chain-wide statements and are never attributable to a branch. Note that `flags` is a column name that pandas also uses for an attribute, so read it as `df["flags"]`.

## Method

Inputs are the 28,589 stored pages (27,809 distinct files) of the crawl targets whose `site_status` is ok or ok_thin, linked to usable records. Both the main `text` and the header and footer `chrome_text` are read, and the title for identity.

Reuse. Nothing is reimplemented where the project already has it:
- services: `kb/taxonomy/lexicon_src.match` on `lexicon.json` (the 36 taxonomy services, with clause-level exclusions);
- hours and details: the `kb/vf_details/patterns.py` extractors and the `extract.py` cue, plausibility, status and facility-table rules, so web facts and VF facts share one schema;
- sentence kinds (staff, directory, research, template, list): `cleaning/claims/lexicon.py`;
- the LLM schema and keep rules: `kb/vf_details/llm_hours.py`.

### 1. Site identity

For each (target, record), every page is searched for:
- the record's name, built from the core name (text before the first comma, dash, bracket or " in "): the full token sequence, the distinctive tokens (generic words and the record's own city words removed, 5 or more letters), a fuzzy match (rapidfuzz alignment 90 or more on 6 or more letters), or a weaker head match (first two distinctive words, or the first one followed by a facility word);
- the record's 6-digit PIN, and its city or district.

Every match keeps a quote cut from the page and the URL it came from. Confidence:
- high: name and (PIN or locality) on the site;
- medium: a name match with no conflict, or PIN plus a host name that spells the facility name;
- low: only locality, PIN or host name, or a name with a conflict;
- none: nothing, or a for-sale or expired-domain page.

A conflict is a site that shows only other PINs, or a district or city name in the host (`guptahospitalbathinda.com` for a Gupta Hospital in Amritsar) or after "in" in the name line ("Best Multi-Specialty Hospital in Hyderabad | Medistar Hospitals" for a Medistar record in Vadodara). Branch pages need name and locality, since a chain brand names every branch.

`attributable` means high or medium, and not a chain homepage. A page whose host is not the target's site (a record-given deep URL elsewhere, not a same-organisation redirect) must itself show the name and the PIN or locality. Rows that fail are dropped from the fact tables: 17,113 service rows and 9,912 hour and detail rows.

| kind | high | medium | low | none |
|---|---|---|---|---|
| own site | 4,643 | 312 | 819 | 227 |
| branch page | 222 | 0 | 51 | 7 |
| chain homepage | 290 | 35 | 128 | 36 |

5,177 of the 6,770 rows are attributable. Among them, the PIN is on the site for 3,398 and the city or district for 4,789. Conflicts found: 408 sites show only other PINs, 178 name another place, and 3 are parked.

### 2. Services

Each field is cut into lines; lines over 400 characters are split at sentence ends. A line matches a service by the taxonomy matcher. Cues are read only in the clause that carries the hit, so "Dialysis unit with 10 machines; no ICU facility" is not a dialysis negation:
- `negated`: the shared negation cue or the service's own negation;
- `nonoffer_cue`: referral, future, past or camp.

Web-specific changes:
- "non-surgical" negates only the 7 surgical services. On the web it mostly describes cath lab work, chemotherapy or medical abortion.
- A short doctor-card line ("Consultant Interventional Cardiologist") is a staff line.
- `edu` marks blog, news, FAQ or condition URLs and question or definition lines.

`positive` means: not negated, no non-offer cue, not a staff, directory, research or template line, and not edu. `strength` is strong when a positive line also carries an offer cue: we or our, available, department, unit, wing, facility, service, clinic, centre, a 24x7 badge, or a list item on a services page. Otherwise it is weak. The quote is the line, or a word-snapped window of at most 300 characters around the hit.

Of 125,052 attributable rows, 55,116 are strong, 60,848 weak and 9,088 not positive. Only 117 are negated: websites almost never say what they do not offer. 3,664 records have at least one positive service, and 3,202 have a strong one.

| service | records with a positive quote | strong |
|---|---|---|
| emergency_24x7 | 1,903 | 1,775 |
| icu | 1,682 | 1,488 |
| ultrasound | 1,727 | 1,178 |
| trauma_care | 1,457 | 1,063 |
| ct_scan | 988 | 688 |
| neurosurgery | 939 | 747 |
| institutional_delivery | 938 | 647 |
| dialysis | 910 | 766 |
| cataract_surgery | 741 | 493 |
| orthopaedic_trauma_surgery | 716 | 367 |
| mri | 660 | 406 |
| ventilator_support | 647 | 442 |
| nicu | 635 | 518 |
| high_risk_pregnancy | 631 | 388 |
| cath_lab_angioplasty | 609 | 471 |
| surgical_oncology | 596 | 390 |
| cardiac_surgery | 558 | 397 |
| blood_bank | 510 | 426 |
| chemotherapy | 445 | 303 |
| emergency_csection | 356 | 188 |
| kidney_transplant | 333 | 213 |
| burn_care | 309 | 171 |
| tb_care | 304 | 120 |
| radiotherapy | 282 | 182 |
| picu | 271 | 215 |
| eye_emergency | 260 | 166 |
| psychiatric_care | 167 | 149 |
| stroke_care | 158 | 106 |
| de_addiction | 148 | 96 |
| safe_abortion_mtp | 101 | 77 |
| snakebite_antivenom | 58 | 27 |
| stemi_thrombolysis | 54 | 30 |
| paediatric_inpatient | 52 | 33 |
| hiv_art | 39 | 34 |
| anti_rabies | 26 | 10 |
| nutrition_rehabilitation | 8 | 4 |

### 3. Hours

The vf_details extractors run on each line. A short heading line such as "Opening Hours:" or "OPD Timings" is joined to the next line when that line carries a time. The quote then spans both lines (newline included), and it is still an exact substring.

Web-specific changes:
- "Emergency Care (24/7)" comes back from the shared scope rule as facility. On a line of 80 characters or less, an emergency word sets the scope to emergency.
- A bare "24 Hours" or "24*7" line is flagged `bare_24x7_line`.
- "Call between 9 am and 8 pm" becomes scope helpline, not OPD.

Ambiguous hour lines go to the LLM: 833 lines in all, 633 distinct texts, with no parse, close before open, a guessed am/pm or an odd opening time. They were sent to `databricks-meta-llama-3-3-70b-instruct` through `ai_query` with a strict JSON schema, in 3 statements (a 3-line test, then 317 and 316 lines). A reading is kept only under the vf_details rules: the quote string-matches the line, every returned hour is in the quote, the days are in the line, and the schedule is plausible.

The LLM kept 303 readings. It rejected 135 as not operating hours, 75 with times not in the quote, 45 implausible, 39 with a quote not in the source, 34 with days not in the source and 2 with no entries. Kept readings replace the regex reading of the same line on every page where that line appears: 405 usable hour rows, flagged `llm_extracted`.

Records with a usable, attributable fact:
- 24x7 emergency: 1,433 (1,287 with status ok);
- facility-wide 24x7: 1,716;
- 24x7 pharmacy 481, lab or imaging 416, ambulance 371, ICU 304, dialysis 79, labour room 75, blood bank 50;
- 24x7 doctor on duty: 432;
- an OPD or general schedule: 2,349 (397 with an explicit OPD scope);
- doctor sessions 93, visiting hours 61, lab hours 50, dialysis hours 8;
- dialysis shifts: 5.

### 4. Details

These come from the same extractors, with the vf_details exclusion rules (negation, past and future cues, staff biographies, zero or implausible counts, unit beds above total beds). Records with a usable, attributable fact:
- total beds: 722. Unit beds: ICU 231, NICU 58, emergency 48, dialysis 26, CCU 21, PICU 14, HDU 11.
- equipment: operation theatres 202, CT slices 151, MRI tesla 148, dialysis machines 32, ventilators 31, cath labs 20.
- accreditation: NABH 684, NABL 233, JCI 30, Kayakalp 11, NQAS 3. Pre-entry NABH is stored as `pre_entry_level`.
- empanelment: private insurance or cashless 1,412, PM-JAY 189, other state schemes 150, CGHS 147, ECHS 94, ESIC 37, Rajasthan 27, Aarogyasri 24, MJPJAY 23. A state scheme name containing "health insurance" (CMCHIS) is not counted as private insurance.
- ambulance 1,048; blood bank 389, blood storage unit 39.
- emergency phone listed: emergency 348, helpline 84, ambulance 49. The crawl replaced phone numbers with `[phone]`, so these rows say a number is published on that URL, not what it is. At least one landline in another format ("02167 - 220233", self-check item 39) escaped the crawl's redaction and appears in a quote; it is a facility number.

### Quote rule

Every service, hour and detail row, and every identity quote, is asserted to be an exact substring of the stored field it names. The assertion runs twice: in the worker, against the line, and again after all tables are built, by re-opening each cited gz file. 237,608 (file, field, quote) triples were verified. LLM quotes are also asserted against their line before use.

## Comparison with the provided dataset

Population: 4,866 usable records with an attributable own site or branch page. A dataset claim for a (record, service) pair is a positive claim sentence under the taxonomy rule, or a specialties value mapped to the service. 17,735 such claims fall in the population. All 95% Wilson intervals are in `compare_by_service.csv`.

| measure | all services |
|---|---|
| dataset claims the site confirms with a positive quote | 10,621 of 17,735 = 0.599 (0.592 to 0.606) |
| same, strong quotes only | 0.493 |
| claims from text sentences | 0.671 of 14,351 |
| claims from a specialties value only | 0.294 of 3,384 |
| claims of records whose VF source_urls do not include this site | 0.425 |
| claims of records whose VF source_urls include this site | 0.623 |
| positive web pairs with no dataset mention at all (web-only) | 9,557 of 20,218 = 0.473 (0.466 to 0.480) |
| same, strong quotes only | 6,006 of 14,774 = 0.407 |
| dataset claims the site never mentions, where it has a services, specialty or facilities page (silent) | 4,961 of 14,495 = 0.342 (0.335 to 0.350) |

Read these with four cautions:
1. The web is not fully independent of the dataset. For 4,110 of the 4,866 records, the VF source_urls list a page on the same site, so the dataset text may have been extracted from these very pages. The confirm rate is 0.425 where the site is not among the sources and 0.623 where it is. The first number is the closer estimate of independent agreement.
2. Web-only pairs are noisy. In the self-check, 5 of 6 strong web-only items were right, and 3 of 4 weak ones. In the two development rounds, before the fixes, the figures were 5 of 8 and 4 of 8. Errors are educational lines, job titles and acronyms ("NRC" as a board committee). A web-only pair should raise a facility for a service only as weak evidence, and more when it is strong or found on 2 or more pages.
3. Silence is weak evidence of absence. The crawl stored at most 6 pages per site, and JavaScript pages and PDFs were not read. Even so, silence separates services: it is lowest for ICU (0.146), trauma care (0.174), cataract surgery (0.178), emergency 24x7 (0.195) and dialysis (0.217). It is highest where the dataset leans on specialties values: psychiatric care 0.846, HIV ART 0.767, STEMI thrombolysis 0.714 (14 claims), chemotherapy 0.619, de-addiction 0.605.
4. Specialty-only claims are confirmed far less often (0.294) than text claims (0.671). This agrees with the taxonomy's finding that specialties values are weak offer evidence.

Per service (confirm rate, web-only rate, silent rate; full columns in the CSV):
- strongest agreement: ICU 0.771, 0.267, 0.146; cataract surgery 0.780, 0.404, 0.178; trauma care 0.759, 0.603, 0.174; emergency 24x7 0.722, 0.273, 0.195; dialysis 0.717, 0.477, 0.217;
- weakest: psychiatric care 0.143, 0.359, 0.846; HIV ART 0.179, 0.821, 0.767; chemotherapy 0.330, 0.339, 0.619; safe abortion 0.381, 0.683, 0.577; stroke care 0.402, 0.747, 0.566.

## Self-check (40 items)

The scored round uses seed 3033 (`selfcheck.py`, verdicts in `LABELS`, notes in `out/selfcheck_sample.csv`). Each item was read with its line, page URL and the record's name, city and PIN; doubtful identity items were also checked against the stored page titles and text. Criteria:
- identity: the attributable or not-attributable verdict is right for the record;
- service: the quote says this facility provides the service now;
- negated: the line should not count as positive evidence for this service here;
- hours and details: type, attribute and value are what the quote says about this facility.

| group | correct | 95% Wilson |
|---|---|---|
| all | 37 / 40 | 0.801 to 0.974 |
| identity (4 attributable, 4 not) | 8 / 8 | 0.676 to 1.000 |
| services (6 confirming, 6 web-only strong, 4 web-only weak, 4 negated) | 18 / 20 | 0.699 to 0.972 |
| hours (3 emergency 24x7, 2 OPD, 1 LLM, 1 service 24x7) | 6 / 7 | 0.487 to 0.974 |
| details (beds, accreditation, empanelment, ambulance, blood centre) | 5 / 5 | 0.566 to 1.000 |

The 3 errors:
- 24x7 phone support for a child-care OPD, read as an emergency department;
- "NRC" meaning a board committee, read as nutrition rehabilitation;
- a bare "7AM - 8AM" on an accreditation page, read as a general schedule.

Two development rounds came before this one, and the scored round is the first draw after their fixes:
- round 1 (seed 20261121): 35/40;
- round 2 (seed 2027): 29/40.

Their errors drove these fixes:
- clause-level negation;
- doctor job-title lines treated as staff;
- phone enquiry hours scoped as helpline;
- parked domains rejected;
- off-site deep URLs required to name the facility;
- another city in the name line treated as a conflict;
- "non-surgical" limited to surgical services;
- CMCHIS no longer read as private insurance;
- pre-entry NABH stored as pre-entry.

Across all three rounds, none of the 12 negated items was an explicit "we do not offer X". `negated` rows are statements to exclude, not evidence that a service is absent.

The sample is small per stratum (1 to 6 items), so the per-stratum intervals are wide. Web-only service quotes are the weakest part: 5 of 8, 4 of 8 and 8 of 10 correct in rounds 1, 2 and 3 (17 of 26 pooled, Wilson 0.46 to 0.81; rounds 1 and 2 predate the fixes). Quotes that confirm a dataset claim were right 21 of 22 times over the three rounds (Wilson 0.78 to 0.99).

## Coverage

- Records with an attributable own site or branch page: hospitals 2,843 of 5,611, clinics 1,778 of 3,770, dentists 215 of 488. All 34 states have at least one. The lowest shares among states with 10 or more records are Jammu and Kashmir 0.257, Meghalaya 0.286 and Jharkhand 0.350.
- 3,664 records have at least one positive service quote, 1,433 a 24x7 emergency quote, and 2,349 an OPD or general schedule.

## Known limits

- Recall is bounded by the crawl's 6 pages per site. Hours often sit on contact pages; only 390 timing pages were stored.
- Lines are the unit, and menu items count. A navigation menu that lists "Dialysis" on every page gives one quote per page. Use `n_pages_positive` and `strength`, not row counts.
- `line_kind == "item"` rows (single menu or list entries) carry no sentence context. The self-check found them right when on the facility's own services pages, but a template menu copied across sites would pass.
- Identity "medium" (312 own sites) rests on the name alone. A same-name hospital in another city with no PIN or place on its pages would pass; the conflict rules catch only those that print another PIN or place.
- Quotes in doctor-session hours contain doctor names. They carry no contact data (phones and emails were redacted by the crawl).
- The web says nothing about whether a service runs at night or is free unless the page says so; the hours tables cover only stated hours.
- Not run: no hand check of the comparison rates beyond the 40 items, and no fetch of PDFs or JavaScript pages.
