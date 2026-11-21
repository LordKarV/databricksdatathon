# Adversarial QA of the web evidence

This is an independent check of `kb/web_evidence/out`. I drew a fresh stratified sample of 150 items, read each one against the stored page text in `data/crawl/pages/`, and ran population-wide scans over every output row. Nothing in `kb/web_evidence/out` was modified. Every number below comes from `qa/out/qa_results.json`, `qa/out/scan.json` or a command recorded in this file.

Bottom line: the quotes are verbatim, but the facts are less reliable than the self-check (37 of 40) suggested.
- Service pairs: 36 of 60 correct (0.47 to 0.71). Weighted to the population, 0.69.
- Hours: 22 of 30.
- Details: 21 of 30.
- Identity: accepted decisions 12 of 15, rejected decisions 11 of 15.

The errors are concentrated in places the downstream model can see: weak quotes, single-page quotes, "other" 24x7 scopes, medium identity, and facility-level values. Most of the fixes below are cheap.

## Run

```
cd /Users/karthikvattem/projects/datathon/kb/web_evidence/qa
../../../.venv/bin/python qa.py sample   # 150 items, seed 4242 -> out/sample.csv
../../../.venv/bin/python qa.py show     # each item with record, page title and text around the quote
../../../.venv/bin/python qa.py score    # joins qa_labels.py -> out/sample_scored.csv, out/qa_results.json
../../../.venv/bin/python scan.py        # population checks and fix effects -> out/scan.json (about 25 s)
```

## Sample and criteria

The sample uses seed 4242. It skips every (record, item) pair that the three self-check rounds already read, so it is independent of the rounds that drove the extraction fixes. The sampling units are what a downstream step reads:
- (record, service) pairs from `web_service_summary` (positive, not chain homepage), judged on `best_quote`;
- (record, fact_type, attribute) rows from `web_facility_details` with `n_usable > 0`, judged on `best_quote` and the facility-level value;
- `site_identity` rows (own sites and branch pages).

| type | strata (items) |
|---|---|
| services, 60 | confirms a dataset claim, strong (15) and weak (15); web-only, strong (15) and weak (15) |
| hours, 30 | 24x7 emergency (10), OPD or general regex schedule (10), LLM reading (5), all other hour facts (5) |
| details, 30 | beds (6), accreditation (6), empanelment (6), ambulance (4), blood centre (4), other (4) |
| identity, 30 | accepted: high (10), medium (5); rejected: low (10), none (5) |

Criteria:
- A service is correct when the quote, read in its page, says this facility provides this service now.
- An hour or detail fact is correct when its type, attribute and facility-level value are what the quote says about this facility.
- An accepted identity is correct when the site is this record's facility.
- A rejected identity is correct when the stored pages do not show this facility. A rejected site that plainly is the facility counts as wrong.

All verdicts and notes are in `qa_labels.py`.

## Precision

The "raw" column is k of n, with a 95% Wilson interval. The "population-weighted" column weights each stratum by its population size. Its bounds are the stratum Wilson bounds, weighted the same way, so they are conservative.

| type | raw | Wilson | population-weighted | weighted bounds |
|---|---|---|---|---|
| services | 36 / 60 = 0.600 | 0.474 to 0.714 | 0.690 | 0.459 to 0.844 |
| hours | 22 / 30 = 0.733 | 0.556 to 0.858 | 0.508 | 0.274 to 0.786 |
| details | 21 / 30 = 0.700 | 0.521 to 0.833 | 0.787 | 0.379 to 0.929 |
| identity, accepted | 12 / 15 = 0.800 | 0.548 to 0.930 | 0.964 | 0.686 to 0.986 |
| identity, rejected (rejection right) | 11 / 15 = 0.733 | 0.480 to 0.891 | 0.721 | 0.393 to 0.907 |

| stratum | population | correct | Wilson |
|---|---|---|---|
| service, confirms, strong | 8,739 | 13 / 15 | 0.621 to 0.963 |
| service, confirms, weak | 1,888 | 8 / 15 | 0.301 to 0.752 |
| service, web-only, strong | 5,986 | 11 / 15 | 0.480 to 0.891 |
| service, web-only, weak | 3,541 | 4 / 15 | 0.109 to 0.520 |
| hours, 24x7 emergency | 1,433 | 9 / 10 | 0.596 to 0.982 |
| hours, OPD or general (regex) | 2,554 | 8 / 10 | 0.490 to 0.943 |
| hours, LLM reading | 48 | 4 / 5 | 0.376 to 0.964 |
| hours, other (facility 24x7, pharmacy, lab, helpline ...) | 4,284 | 1 / 5 | 0.036 to 0.624 |
| details, beds | 1,131 | 2 / 6 | 0.097 to 0.700 |
| details, accreditation | 961 | 4 / 6 | 0.300 to 0.903 |
| details, empanelment | 2,183 | 5 / 6 | 0.436 to 0.970 |
| details, ambulance | 1,048 | 2 / 4 | 0.150 to 0.850 |
| details, blood centre | 428 | 4 / 4 | 0.510 to 1.000 |
| details, other (staffing, equipment ...) | 3,478 | 4 / 4 | 0.510 to 1.000 |
| identity accepted, high | 4,851 | 10 / 10 | 0.722 to 1.000 |
| identity accepted, medium | 312 | 2 / 5 | 0.118 to 0.769 |
| identity rejected, low | 861 | 7 / 10 | 0.397 to 0.892 |
| identity rejected, none | 231 | 4 / 5 | 0.376 to 0.964 |

### Comparison with the self-check

The self-check scored services 18 of 20, hours 6 of 7, details 5 of 5 and identity 8 of 8. This sample scores lower for three reasons:
- It is four times larger per type.
- It counts explanatory text as wrong. Examples: "An ultrasound will confirm your due date" for ultrasound, and a glaucoma explainer that mentions eye injuries for eye_emergency.
- It checks the facility-level value, not only the row value.

Two strata carry most of the difference:
- Web-only weak pairs: 4 of 15 here. The self-check pooled 17 of 26 over all web-only items.
- "Other" hour facts: 1 of 5 here. The self-check did not sample them.

The 24x7 emergency facts (9 of 10) and high-confidence identity (10 of 10) hold up.

### Evidence structure predicts correctness

The structure of the evidence separates correct from wrong service pairs much better than the dataset-confirmation strata do. Each cell below is read from the pair's summary row: strength, `n_pages_positive`, and the `line_kind` of the best quote.

| cell | positive pairs | share | sample correct | Wilson |
|---|---|---|---|---|
| A strong, 2+ pages | 9,190 | 0.455 | 13 / 13 | 0.772 to 1.000 |
| B strong, 1 page, list item | 1,571 | 0.078 | 3 / 3 | 0.438 to 1.000 |
| C strong, 1 page, sentence | 4,013 | 0.198 | 8 / 14 | 0.326 to 0.786 |
| D weak, 2+ pages | 1,187 | 0.059 | 5 / 12 | 0.193 to 0.680 |
| E weak, 1 page | 4,257 | 0.211 | 7 / 18 | 0.203 to 0.614 |

Cells A and B were 16 of 16 correct (Wilson 0.81 to 1.00), and they cover 10,761 of 20,218 positive pairs. List items were 15 of 17 correct across all cells. Menu and list lines on a facility's own pages are good evidence; explanatory sentences are not.

## Are the quotes verbatim?

Yes, against the stored text. I re-checked 227,761 (file, field, quote) triples, from all fact tables and all `page_identity` name, PIN and locality quotes, with code written separately from `verify_quotes`. 0 were not exact substrings. All 17,548 facility-level `best_quote` values equal the quote of the fact row they cite.

Caveats a reader of the quotes should know:
- The stored text is the crawl's HTML-to-text with phones and emails redacted. 1.5% of quotes contain `[phone]` or `[email]`. 2.9% contain a newline, either from a joined heading line or from the original layout. Text-extraction artifacts are kept as they are; one sampled quote reads "oered" for "offered" because the "ff" ligature was lost.
- 6.4% of service quotes are word-snapped windows of a longer line. 29.5% of all quotes are three words or fewer, mostly menu items. These are verbatim but carry no context, so a reader cannot judge them without the page.
- Verbatim is not the same as supported. In 1,128 of 17,548 usable facility facts (6.4%), the facility-level value differs from the value of the row whose quote is cited. These include 716 of 3,038 OPD facts, 168 ambulance, 86 free-or-government, 71 beds and 54 staffing. Example: item 71 shows "days? 18:00-20:00" next to the quote "Mon-Sat: 11:00 AM - 01:00 PM". The quote is verbatim, but it does not support the value shown next to it.

## Error patterns

There are 48 wrong items. The patterns the task asked about come first.

| pattern | errors | examples (item) | population size, where measured |
|---|---|---|---|
| chain-wide or other-branch page | 6 | Apollo Cradle Chennai page for an Amritsar record (20); Regencare Calicut branch page for a Kochi record (82); group page with a Haldwani hospital's 200 beds for the Lucknow record (93); 50 beds across two branches (95); chain homepage accreditations for the Siliguri branch (97); Shuddhi Ayurveda chain site accepted as one clinic's own site (135) | see fix 9 |
| doctor bio | 3 | founder of a blood bank society (47); presented at a critical care CME (52); a vascular surgeon's thrombolysis for STEMI (59). One more bio was right, because the doctor is on that hospital's roster (17) | 898 positive service rows; 119 pairs rest only on such lines |
| menu or footer text | 3 | chain-wide "Eye Diseases" encyclopedia menu (22); article category menu (56); the parent foundation's office hours in the footer (76) | Menus are mostly right: list items were 15 of 17 correct |
| list of other hospitals, or copied text | 2 | "top cancer hospitals" blog credits RGCIRC's NABL to this hospital (102); a department page copied from Ruby Hall Clinic (2) | not measured |
| coming soon | 1 | "will be operational soon" (49) | 27 rows, 9 pairs |
| explanatory or generic text | 7 | pregnancy, physiotherapy, kidney and lab-test explainers (29, 54, 57, 58); chemotherapy as a reason to freeze sperm (53) | see fix 2 |
| same-name facility elsewhere (accepted identity) | 6 | Green City Hospital, Kathmandu (21); Pulse Hospital Bhagalpur for Siliguri (88); Bharati Vidyapeeth Sangli for Chandrapur (94); "Asian Hospital" for "Asian Eye Hospital" (111); Dr. Anand Patel, Ahmedabad, for Anand Hospital, Rajpipla (131); Navkar Dental of Khapar for Ahmedabad (132) | 39 of 312 medium own sites show another place in a page title or the name line |
| wrong service sense | 4 | psychological trauma read as trauma_care (37, 48); eye trauma read as trauma_care (26), because the clause split moved "Eye" out of the clause that holds "trauma"; orthopaedic trauma at an OPD clinic (45) | 203 rows, 42 pairs |
| missed name variant (wrong rejection) | 4 | Sri vs Sree (137); Udyan vs Udayan (144); "&" vs "and" plus Trivandrum vs Thiruvananthapuram (150); a doctor-named site carrying the record's street address (141) | 58 rejected rows recoverable (fix 7) |
| lexicon false hit | 3 | "3D scans" of a dental CBCT read as ultrasound (33); "advanced life support" read as ventilator support (40); "paramount importance" read as the Paramount TPA (108) | "paramount": 261 rows, 102 of them in the adjective sense |
| helpline or visiting hours read as 24x7 | 3 | "Emergency 24 hours" over phone numbers at a diagnostic centre (66); NICU parent visiting "24/7 only for parents" (86); "Call Us 24/7" (89) | 137 facts |
| facility-level value mismatch | 2 | evening session shown with a morning quote (71); "24 Hrs ICCU Ambulance" read as 24 ambulances (109) | 1,128 facts; 71 ambulance facts with value 24 |
| other: testimonial (51), event page (15), HDU 24x7 stored as facility 24x7 (87), AMCU beds stored as total beds (92) | 4 | | 721 testimonial-cue rows; 512 rows on event or article URLs; 109 facility 24x7 quotes name a unit; 86 total-bed quotes name a unit |

Identity errors reach the fact tables: 4 of the 90 sampled hour, detail and service-confirm items were about a same-name facility elsewhere (21, 88, 94, 111), and 5 were about another branch of a chain (20, 82, 93, 95, 97).

## Fixes and expected effect

I measured each fix on the full population (pairs or facts it would drop or change) and on the scored sample (wrong items removed, right items lost). I wrote the text rules after reading this sample, so their sample effect is optimistic. The population numbers bound their real reach.

1. Use evidence structure as the service-evidence feature, not only `positive`. Treat cells A and B (strong, and on 2 or more pages or a list item) as positive evidence: 16 of 16 correct, covering 10,761 pairs. Feed cells C, D and E (9,457 pairs) to the model as separate weaker features, with their own likelihoods (sample precision 0.57, 0.42 and 0.39). Expected effect: precision of the "positive" set goes from about 0.69 (weighted) to at least 0.81 (Wilson lower bound), at 53% of the current positive pairs. Recall of true services in C, D and E is kept as weaker evidence rather than lost.
2. Exclude service lines that match these line-level rules:
   - doctor bio;
   - explanatory text ("refers to", "may include", "caused by", "response to" ...);
   - coming soon;
   - testimonial;
   - psychological or eye sense for trauma services;
   - event and article URLs.

   The regexes are in `scan.py` (`SVC_RULES`, `TRAUMA_SENSE`, `EVENT_URL`). Population: 3,490 rows, 429 pairs dropped (2.1%). Sample: 13 wrong items removed, 0 right lost. Caveat: in the population these rules drop only 6.8% of weak web-only pairs, while the sample puts that stratum's error rate near 0.73. They clean up the worst lines but do not fix weak evidence in general. Fix 1 or 3 does that.
3. Add an LLM verifier for cells C to E: one question per quote plus one line of context ("does this line state that this facility offers this service now?"), with the existing strict-JSON and quote-substring keep rules. Not run: its cost and accuracy are unknown, so label about 60 more items to measure it before trusting it.
4. Take the facility-level value from the cited row, and keep days on split sessions. Build `web_facility_details.value_text` and `value_num` from `best_fact_id`, or store all sessions. When a session line has no day ("06:00 PM - 08:00 PM"), inherit the days of the line before it. Expected: fixes 1,128 facts whose value differs from the cited row, and most of the 1,118 OPD facts with "days?". In the sample this removes 2 of 17 hour and detail errors (71, 109).
5. Make hour and detail extraction stricter:
   - Ambulance counts need a count noun ("3 ambulances") and no hours word after the number (71 facts with value 24).
   - A 24x7 line with a phone, booking or visiting cue becomes scope helpline or visiting (137 facts; sample: 2 wrong removed, 0 right lost).
   - A facility 24x7 quote that names a unit (HDU, ICU, pharmacy ...) becomes that unit (109 facts; sample: 1 wrong fixed).
   - A total-beds quote that names a unit becomes unit beds (86 of 1,131 total-bed facts; sample: 1 wrong fixed).
   - "Paramount" counts as an insurer only next to TPA, Health or an insurer list (102 of 261 rows are the adjective).

   Taken together these touch about 2.4% of usable facts. They remove 5 of the 17 sampled hour and detail errors outside identity.
6. Do not drop flagged rows wholesale. Dropping facts with no ok row (3,712) would remove 4 wrong and 8 right sample items. Drop only the `edu_page` flag (741 usable rows); the blog item (102) was one of them.
7. Recover missed identities. Normalise "&" to "and" and Sri, Sree, Shri and Shree to one form. Also accept the record's street address (address_line1, 12 or more characters) on the site. Count either only when there is no conflict and the PIN or locality is on the site. Population: 17 rejected rows recovered by name and 41 by address. Sample: 3 of the 4 wrong rejections fixed (137, 141, 144), 0 right changed. The fourth (150) also needs locality aliases (Trivandrum = Thiruvananthapuram, Bangalore = Bengaluru, Calicut = Kozhikode); that part was not run.
8. Tighten medium identity. Treat another district or city anywhere in a page title or the name line as a conflict, not only after "in" or "at". Population: 39 of 312 medium own sites. Sample: fixes 131, 0 right lost. Medium stays weak after this (2 of 5 correct here). The model should give medium-identity facts less weight than high, or require a second source.
9. Chain and branch pages need a scope check. A blanket "page title or URL names another place" rule is not recommended: it lost more right items than it removed wrong ones (services: 1 wrong removed, 2 right lost; facts: 3 removed, 5 lost). Instead, when one site serves several records, or its pages name several branch cities, apply the branch-page rule (the page names the record and its own place) to each page. Not run.

## What the model step should take from this

- Use `n_pages_positive`, `strength` and the best quote's `line_kind` as separate evidence features. Fit their likelihoods on labelled items; the sample's 150 verdicts in `out/sample_scored.csv` are a start.
- Weak web-only pairs should only nudge a ranking (sample precision 0.27). Strong pairs found on 2 or more pages can carry real weight.
- For hours, trust 24x7 emergency (9 of 10) and the facility's OPD schedule (8 of 10). Do not treat `hours_24x7:facility` as "open 24x7" until fix 5 is in. Do not show the facility-level OPD value until fix 4 is in.
- Identity high (10 of 10) is sound. Medium is not.

## Not run

- No re-extraction with the fixes. Effects come from filters applied to the existing tables.
- No LLM verifier (fix 3), and no locality aliases (part of fix 7).
- No check of recall: items the extraction missed on pages it read were not sampled. The one seen was item 55, where the best quote is a weaker line than "Non-invasive and invasive ventilation" on the same page.
- No check against live sites or PDFs, and no second reader, so the verdicts are one reviewer's.
- The population-weighted estimates rest on 4 to 15 items per stratum, hence the wide bounds.

## Files

- `qa.py`: sample, show and score.
- `qa_labels.py`: verdicts and notes.
- `scan.py`: quote re-check, value consistency, pattern prevalence and fix effects.
- `out/sample.csv`, `out/sample_scored.csv`: the 150 items, with verdicts.
- `out/qa_results.json`: precision by type and stratum.
- `out/scan.json`: population checks.
