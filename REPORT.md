# Decision report: what we build this weekend

Audience: our team. Scope: the Virtue Foundation facility dataset (10,088 rows; 9,970 well-formed rows with a UUID and source='kie'; 9,959 records after dropping 11 byte-identical duplicate rows). Every number below is copied from the audit, ground-truth, cleaning, capability, concept and judging results, or from the files they cite. Script paths are relative to `/Users/karthikvattem/projects/datathon/`. Where agents disagree on a number, both are given and the one to use is named.

Short version:
- Cleaning works for geometry, contacts, duplicates, numbers and claim parsing. It cannot make a merged record true. About 1 in 7 records names another facility, and 7,514 copied service sentences in 1,390 records name nobody, so no rule can see them.
- Strategy: fix what has a stated reason, flag the rest in plain words, grade every facility-service pair from quoted sentences, and send what is still uncertain to a phone call.
- Product: **Parchi**, a referral slip on a Databricks App (FastAPI, server-rendered HTML). It won the judging 24.5 to 21.5 to 21.5. It takes the Pareto ranking, time profiles and calibration line from Receipts, and the independent Plan B and planner call list from CallFirst.

---

## 1. Data fact-check

### 1.1 The 5 findings that matter most for a patient

| # | Finding | Verified count / denominator | Verdict | Reproduce with | What goes wrong for a patient |
|---|---|---|---|---|---|
| 1 | Records hold text about another facility (merged records) | 2,489 / 9,959 records have a sentence that names another facility (25.0%); in 1,232 of them it is written as if about the record itself (direct context) and is quarantined as evidence. About 5% are harmful misattributions. Other-district mentions: 23 of 30 sampled were misattribution or contradiction | adjusted | audit/merge/detect.py, analyze.py; audit/merge/verify/; derived/v1/claims.parquet (attribution, context) | Sent to an eye hospital for dialysis because a Delhi government hospital's sentence sits in its record (Aravind), or to Nagpur for services done in Mumbai (Wockhardt) |
| 2 | Listing coordinates are often in the wrong town, usually in the right state | 1,367 / 9,869 more than 50 km from their own PIN (1,101 more than 100 km); 1,297 of the 1,367 stay in the same state (nearest PIN centre to the point vs the record's own PIN). Coordinates follow the contaminating facility: 723 / 1,367 (52.9%) records that say "located in elsewhere" are far from their PIN, against 821 / 8,165 (10.1%) | confirmed | derived/v1/facility_location.parquet, pin_gazetteer.parquet; audit/geo/facility_geo.py, summary_tables.py; audit/merge/verify/v_missed.py | Told a hospital is 5 km away when it is 300 km away (HOSMAT Bangalore is placed at Gadag, about 350 km off), or never shown the nearest real option |
| 3 | "Strong-looking" evidence is often only wording or a label | Strong dialysis grades whose prerequisite is met by the claim sentence itself: 345 / 355. Trauma sentences with explicit trauma wording: 3,586 / 9,019 (the rest are generic "24/7 emergency"). Nephrology tag on 2,159 records, dialysis text on only 847 of them. An LLM rated both contaminated dialysis records "offers dialysis, confidence 1" | adjusted / confirmed | audit/claims/verify/v_grades.py, v_dialysis_unit.py; audit/claims/trauma_split.py; audit/capabilities/aiq2.sql | A one-word list item or a specialty tag ranks like a staffed unit; a highway trauma case goes to a nursing home with "24/7 emergency care" |
| 4 | The "official" phone often reaches a directory or call centre | +919693969347 sits on 431 records in 37 state strings and is the officialPhone of 87. 348 / 9,464 officialPhones are held by records in 3 or more cities; of the 45 most-shared numbers, 33 are directory numbers and 0 belong to one facility | confirmed | audit/identity/q3_contacts.py, q3b_shared_phone_source.py; audit/merge/verify/v_phone.py | The health worker calls to confirm a bed and reaches a real-estate or booking line, in an emergency |
| 5 | Typed locations are ambiguous or silently wrong | 5 / 40 realistic inputs are district names in two states (Aurangabad, Bilaspur, Hamirpur, Pratapgarh, Balrampur); "Hydrabad" silently resolves to a village office in Uttar Pradesh; "bijapur" aliasing to Karnataka hides a current Chhattisgarh district | adjusted | audit/geo/resolve_input.py; audit/geo/verify/v_resolve.py | A worker in Bihar typing "Aurangabad" gets Maharashtra hospitals about 1,000 km away |

### 1.2 Every finding

Verdicts are the verifier's. Rows marked "verifier-found" are issues the finder missed and the verifier measured; nobody re-verified them.

#### Location consistency (audit/geo)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| GEO-01 | Coordinates more than 50 km from own PIN centroid | 1,407 / 9,682 (independent centroids: 1,386 / 9,527; about 69 to 72 are centroid errors) | confirmed | geo/facility_geo.py; summary_tables.py; homonym_probe.py | Never rank on raw coordinates |
| GEO-02 | Trust order: stated state > PIN and city > coordinates | 40 / 40 judged: state right 38, PIN 27, coordinates 14 | confirmed | geo/dump_examples.py; hand_check_verdicts.csv | Anchor on state plus PIN; coordinates only for fine distance |
| GEO-03 | Multi-city source URL slugs mark merge risk | 2,134 / 9,970 (risk marker; far from PIN 38% vs 7.4%) | adjusted | geo/merge_location_signal.py | Flag and rank lower; not a count of merged records |
| GEO-04 | India Post directory needs heavy cleaning | 28,568 / 165,627 offices dropped or fixed (finder said 30,772) | adjusted | geo/pin_centroids.py; check_pin_known.py; check_dropped_offices.py | Without it a Pratapgarh PIN lands in Raipur, about 500 km off |
| GEO-05 | State, PIN and city field noise | 1,399 / 9,687 cities do not match their PIN; about 82 records lost to a state filter; 77 invalid PINs | adjusted | geo/facility_geo.py; city_match_sample.py | Normalise state; do not treat a city non-match alone as an error |
| GEO-06 | Coordinates outside India, swapped, (0,0) | 6 / 9,970 outside India; 0 swapped; 0 at (0,0) | confirmed | geo/facility_geo.py; summary_tables.py | Small; null those 6 |
| GEO-07 | District assignment and NFHS-5 join | 9,961 / 9,970 (1,258 rest on a PIN that conflicts with coordinates) | confirmed with caveats | geo/district_assign.py | NFHS context works; mark weak links |
| GEO-08 | User input homonyms and typos | 5 / 40 two-state names; Hydrabad trap; fuzzy auto-pick unsafe ("goa" ties Goalpara) | adjusted | geo/resolve_input.py | Ask which state; never auto-pick fuzzy |
| verifier-found | Busy PIN centroids badly off | 78 / 1,033 more than 25 km from facility consensus (422009 Nashik 165 km) | verifier-found | geo/verify/v_centroid_precision.py | PIN fallback wrong for those PINs |
| verifier-found | mappls URLs encode real coordinates | 75 / 283 far records get a cited replacement point | verifier-found | geo/verify/v_mappls.py | A checkable repair source |
| verifier-found | PIN district vs coordinate district disagree within 50 km | 650 / 9,678 | verifier-found | geo/verify/v_district.py | NFHS context may belong to the neighbouring district |
| verifier-found | Facility PINs missing from directory are mostly real | 167 / 206 | verifier-found | geo/verify/v_missing_pins.py | Directory gap, not a trust penalty |
| verifier-found | Old-name aliases collide with current districts | bijapur: 57 Chhattisgarh offices | verifier-found | geo/verify/v_resolve.py | Aliases must add candidates, not replace |

#### Merged and contaminated records (audit/merge)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| F1 | Claim sentences name a different facility | 2,489 / 9,959 records after cleaning, 1,232 with a direct-context sentence (audit detector: 1,952); sentence precision 20 of 30 | adjusted | merge/detect.py; analyze.py; sample.py | Quarantine direct-context sentences and show them as "mentions another facility" |
| F2 | Near-spelling merges (Batra/Katra, Vedanta/Medanta) | About 77 / 9,959 true of 107 flagged; real total about 120 to 130 | adjusted | merge/analyze.py (near_name) | Most dangerous: names look identical to user and LLM |
| F3 | Claims mention another state or district | 2,494 / 9,959 other-district (verifier lexicon; finder 2,189); 1,005 other-state | confirmed | merge/gazetteer.py; detect.py; analyze.py | "Varanasi" hospital whose own text says Noida |
| F4 | Single-specialty name with acute claims | About 44 / 3,485 true (111 candidates) | adjusted | merge/q3_name_content.py | Only detector that catches the Aravind record |
| F5 | Provenance: list-type sources and record size | Shared seed page: 1,324 / 9,959; contamination 4.2% (0-2 URLs) to 59.6% (30+ URLs); seed-page effect gone after size adjustment | adjusted | merge/analyze.py; q4_stratified.py | More sources means more merge risk, not more evidence |
| F6 | Sentence quarantine and evidence tiers | 9,506 / 469,498 sentences quarantined; dialysis tiers A 80, B 479, C 481, Q 6; demonstrably merged at most 342 / 1,046 | adjusted | merge/analyze.py; q5_service_impact.py; q5_tierC_sample.py | Quarantine alone gives false cleanliness |
| F7 | cluster_id is 1:1 after dedup; exact duplicate rows | 11 / 9,970 | confirmed | merge/q6_cluster.py; common.py | Drop duplicates; cluster_id is useless for grouping |
| verifier-found | Aggregator phones on unrelated facilities | 887 / 9,959 records carry one of 63 multi-state numbers | verifier-found | merge/verify/v_phone.py | Remove from display |
| verifier-found | Coordinates follow the contaminating facility | 723 / 1,367 vs 821 / 8,165 | verifier-found | merge/verify/v_missed.py | Merged record ranks near the other facility |
| verifier-found | Generic institutional names (ESI, PHC, district hospital) | 72 records; 75.0% contaminated vs 24.6% | verifier-found | merge/verify/v_missed.py | Branches with one generic name are never flagged foreign |
| verifier-found | Same-first-letter near-name merges hidden | 103 / 9,959 extra candidates; about half real in a 15-record sample | verifier-found | merge/verify/v_f2b.py | Near-name rule misses about 100 |
| verifier-found | Duplicate sentences within a record | 22,242 / 469,498 (4.7%) | verifier-found | merge/verify/v_sent.py; v_f1.py | Dedupe before counting evidence |
| verifier-found | Other-district hits that are same-metro neighbours | 417 / 9,959 | verifier-found | merge/verify/v_f3b.py | Upper bound on quarantine over-reach |

#### Service claim evidence (audit/claims)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| claims-01 | A prerequisite-based grader is feasible | Dialysis text mention 1,047 / 9,970; strong precision 13 of 18 on an independent read | adjusted | claims/audit.py; services.py; examples.py; labels.py | Grades can cite sentences; "prerequisites" are often the claim itself |
| claims-02 | Grader is blind to merged records | 246 / 4,350 facilities flagged by in-sentence detectors; precision 9 of 40 (named facility), 8 of 14 (cross-state place) | adjusted | claims/audit.py; place.py; handcheck_sample2.py, 3.py | Same-state merges grade strong (Hapur NICU) |
| claims-03 | Real non-offers are rare; naive negation over-fires | 94 / 26,041 sentences; naive cues right 17 of 60, v2 cues 34 of 40 | confirmed | claims/services.py; hedges.py | Show as counter-evidence; never bare "no"/"not" |
| claims-04 | Single-specialty names with tertiary claims | 194 / 9,707 grades capped | confirmed | claims/coherence.py | "Kashmir Eye Hospital: ICU available" |
| claims-05 | Multi-field matches are the same claim restated | 154 / 573 dialysis (method range 70 to 294) | adjusted | claims/audit.py; enum_check.py | Fields from one extraction never corroborate each other |
| claims-06 | Specialties are an open, noisy vocabulary | 2,927 distinct values over 9,970 rows | confirmed | claims/audit.py; enum_check.py | Tags are prerequisites at most, never offer evidence |
| claims-07 | JSON arrays cut at 50 items | 2,080 / 9,970 rows (raw length; finder said 1,789) | adjusted | claims/enum_check.py | Never show absence as "not offered" |
| claims-08 | Quantities are sparse | MRI field strength 235 / 964; dialysis machine counts 33 facilities | confirmed | claims/quantities.py | Use as a bonus when present |
| claims-09 | Over-claiming is not a clinic problem; capacity missing | Capacity missing 7,454 / 9,970; hospitals claim 1.566 of 8 services, clinics 0.232 | confirmed | claims/audit.py | Size checks run on 25% of records only |
| claims-10 | "Trauma" is mostly generic emergency wording | 3,586 / 9,019 explicit | confirmed | claims/trauma_split.py | Split "24x7 emergency" from "trauma-capable" |
| claims-11 | Weak sentence kinds (lists, staff, directory) | 2,947 / 26,041 list rows; staff 450 is an upper bound | adjusted | claims/services.py; audit.py | Only specific sentences carry a grade |
| verifier-found | Duplicate unique_id rows inflate counts | 11 / 9,970 | verifier-found | claims/verify/v_extra.py; v_grades.py | Dedupe first |
| verifier-found | Prerequisites self-referential (dialysis, MRI, trauma) | 345 / 355 strong dialysis | verifier-found | claims/verify/v_grades.py; v_dialysis_unit.py | Fixed in cleaning (prereqs from other sentences only) |
| verifier-found | MRI regex matches names (Mrityunjay) | 8 / 964 | verifier-found | claims/verify/v_extra.py; v_diff.py | Fixed in cleaning |
| verifier-found | Vendor words meet the MRI scanner check ("designated") | 23 / 964 | verifier-found | claims/verify/v_grades.py | Fixed in cleaning |
| verifier-found | Emergency obstetric care counted as C-section | 17 / 462 | verifier-found | claims/verify/v_mentions.py; v_diff.py | Fixed in cleaning |
| verifier-found | PICU as ICU; ambulance as trauma | 29 / 2,338 ICU; 31 trauma | verifier-found | claims/verify/v_extra.py | Fixed in cleaning |
| verifier-found | Glaucoma valve and neurovascular bypass as cardiac surgery | 2 / 25 sampled | verifier-found | claims/verify/v_diff.py | Fixed in cleaning |
| verifier-found | Same-state merged records pass every check | not counted (examples: Hapur 6cd599ab, Amravati 8dcf50d8) | verifier-found | claims/verify/v_show.py; v_merged.py | Needs a same-state district-name check; not built |

#### Scale, numbers and metadata (audit/scale)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| S1 | Numerics parse cleanly but hold impossible values | 45 / 9,970 (e.g. 15,000 doctors, 200,000 beds, year 0) | confirmed | scale/q1_numbers.py | Null and flag; never rank on size |
| S2 | numberDoctors counts named doctors | 1,195 / 3,630 rows say 1 doctor (KGMU, 4,000 beds) | confirmed | scale/q1_numbers.py; q2_contradictions.py | Show as "N doctors named in sources" only |
| S3 | Capacity disagrees with own text | 133 / 1,433 (stricter extractor; finder 117 / 1,639) | adjusted | scale/beds_text.py; q2_contradictions.py | Show both numbers with sources |
| S4 | Clinics with 100+ beds | 20 / 124 | confirmed | scale/q2_contradictions.py | facilityTypeId cannot gate inpatient care |
| S5 | Specialty lists inflated by duplicates | 9,848 / 9,970 repeat items | adjusted | scale/q3_specialties.py | Dedupe; group into families |
| S6 | "Claims everything" detector | 1,266 / 9,970; precision 7 of 12 | confirmed | scale/q3_specialties.py; build_flags.py | Confidence penalty only |
| S7 | facilityTypeId vs name | 1,359 rule hits; about 178 matter for routing (83 nursing homes typed clinic) | confirmed | scale/q4_types.py | Do not filter C-section to "hospital" |
| S8 | Veterinary facilities | 11 / 9,970 clear | adjusted | scale/q4_types.py | Exclude after a one-time human review |
| S9 | "government" affiliation on private operators | 265 / 670 | confirmed | scale/q4_types.py | Means empanelled, not free |
| S10 | Web-presence fields are not an "active" signal | 602 / 9,970 have a post after 2024 (crawl window runs to January 2026) | adjusted | scale/q5_web_presence.py | Do not score on them |
| verifier-found | source_urls capped at 50 | 1,243 / 9,970 | verifier-found | scale/verify/v5_specialties.py | URL counts saturate |
| verifier-found | Crawl window into January 2026 | 47 / 9,970 dates after 2025-12-31 | verifier-found | scale/verify/v10_web.py | Cutoff must be about 2026-01-31 |
| verifier-found | 2023-02-13 placeholder date | 146 / 9,970 | verifier-found | scale/verify/v10_web.py | Ignore that date |
| verifier-found | Chain-wide doctor counts below 1,000 | 23 / 141 report over 2x doctors vs beds | verifier-found | scale/verify/v1b_years_rows.py; v1c_chain_doctors.py | Flag doctors_exceed_beds |
| verifier-found | Name rules match street names ("Nizam Pet Road") | 2 / 9,970 | verifier-found | scale/verify/v7_types.py; v10_web.py | Would exclude a real human hospital |
| verifier-found | Bed extractor leaks future and history phrasing | 25 / 166 conflict rows | verifier-found | scale/verify/v3b_conflicts.py | Can pick a future bed count |
| verifier-found | build_flags.py docstring does not match code | not counted | verifier-found | scale/build_flags.py | Fix before reuse |

#### Duplicates and identity (audit/identity)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| ID1 | Exact duplicate rows | 11 / 9,970 | confirmed | identity/q5_cluster.py | Drop first |
| ID2 | Residual duplicates under different ids | 31 / 47 strict groups are duplicates or sub-units; working estimate 70+ pairs (about 1.4%) | adjusted | identity/q1_duplicates.py; q1b_missed.py; eval_dup_rules.py | Same hospital takes two slots |
| ID3 | Duplicate copies disagree; one is often contaminated | 8 / 29 | adjusted | identity/eval_dup_rules.py | Keep the copy whose coordinates agree with its PIN |
| ID4 | Different facilities on one shared geocode | 38 / 9,959 exact; about 100 by a distance test | adjusted | identity/q4_existence.py | Fall back to PIN centroid, say "approximate" |
| ID5 | Directory phones attached as facility phones | 348 / 9,464 officialPhones held in 3+ cities | confirmed | identity/q3_contacts.py; q3b_shared_phone_source.py; q4b_phone_split.py | Blocklist; label chain helplines |
| ID6 | Phone format: valid but repeated | 131 / 96,318 invalid entries | confirmed | identity/q3_contacts.py; common.py | Normalise and cap display at 2 to 3 |
| ID7 | Email placeholders | 360 / 8,512 | confirmed | identity/q3_contacts.py | Drop placeholders; parse lists |
| ID8 | officialWebsite is another organisation's domain | 12 / 34 chain-domain cases wrong | confirmed | identity/q3_contacts.py; q2_chains.py; q4_existence.py | "Website may belong to another organisation" |
| ID9 | Chain branches carry other sites' claims | 187 / 460 (verifier brand list) | confirmed | identity/q2_chains.py | Need a site-specific sentence for a branch |
| ID10 | Claim text names another city | 2,111 / 9,959 detector hits; real rate about 12 to 15% | confirmed | identity/q2_chains.py | Down-weight, not proof |
| ID11 | Tertiary claims at small chain sites | 6 / 164 | confirmed | identity/q2_chains.py | Cap tertiary claims at clinics and labs |
| ID12 | No officialPhone goes with more anomalies | 250 / 495 vs 28.9% with a phone | confirmed | identity/q4_existence.py; q4c_counts.py | Small prior; "no direct contact found" badge |
| ID13 | cluster_id does not help find duplicates | 11 / 9,970 | confirmed | identity/q5_cluster.py | Ignore it |
| ID14 | source_content_id marks the seed listing page | 1,324 / 9,959 | confirmed | identity/q5_cluster.py | Weak risk feature; TRANSTAN-type lists are provenance |
| verifier-found | Abbreviation and rebrand duplicates (AIIMS Patna) | 13 / 42 near-contact pairs | verifier-found | identity/verify/v_id2_candidates.py; v_near_contact_hand.csv | Major hospitals shown twice |
| verifier-found | Co-located units inside a host facility | 10 / 42 | verifier-found | identity/verify/v_near_contact_hand.csv | Link, do not merge or count as corroboration |
| verifier-found | Copied geocodes | 176 / 9,959 candidates, about 100 real | verifier-found | identity/verify/v_id12_id4b.py | Flag copied_geocode |
| verifier-found | PIN directory errors behind distance flags | 399 / 1,563 | verifier-found | identity/verify/v_id12_id4b.py | Check centroid before penalising |
| verifier-found | "Malformed" emails are address lists | 31 / 75 | verifier-found | identity/verify/v_id7_id8.py | Parse, do not drop |
| verifier-found | Foreign-city detector false positives | 1,462 / 9,959 after distance and education filters | verifier-found | identity/verify/v_id9_id10.py | Add locality gazetteer |

#### Provenance and auxiliary tables (audit/provenance)

| ID | Finding | Verified count / denominator | Verdict | Script | Product impact |
|---|---|---|---|---|---|
| PROV-01 | source_urls are search hits, not citations | 113,088 / 158,444 URLs not about the facility (about 28% to 37% are) | confirmed | provenance/q1_sources.py; handcheck_domains.py | Cite sentences, not URLs |
| PROV-02 | Record breadth predicts contamination | 2,545 / 9,959 any proxy; 6.9% (0-5 URLs) to 49.7% (21+) | confirmed | provenance/q1_sources.py | Breadth is a penalty, not evidence |
| PROV-03 | Similar-name merges (Kamal vs Kamat) | 186 / 9,959 strict subset | adjusted | provenance/proxies.py; q1_sources.py | Quarantine; location disputed when coords also far |
| PROV-04 | Claims naming another institution | 1,020 / 9,959 | confirmed | provenance/proxies.py | Uncertainty flag only (precision 17 of 40) |
| PROV-05 | Research-paper text as service claims | 431 / 9,959 cite research URLs | confirmed | provenance/q1_sources.py; handcheck_samples.py | Tag as "research activity" |
| PROV-06 | Coordinates vs PIN centroid over 50 km | 1,394 / 9,497 | adjusted | provenance/q3_pincode.py | Good "unreliable" flag; does not say which field is wrong |
| PROV-07 | Off-location directory URLs | 642 / 9,959 (rule-dependent, 302 to 642) | adjusted | provenance/proxies.py; q1_sources.py | Drop from citation lists |
| PROV-08 | Stated state vs PIN state conflicts | 21 / 9,372 | confirmed | provenance/q1_sources.py | Small |
| PROV-09 | Duplicate rows; non-informative id columns | 11 / 9,970 | confirmed | provenance/common.py; q1_sources.py | Ignore cluster_id and source |
| PROV-10 | Description is meta-text, label or boilerplate | 1,860 / 9,959 | confirmed | provenance/q2_description.py | Never service evidence; one cardiac boilerplate on 33 records |
| PROV-11 | Description vs structured fields | no verified count; fields extracted from the same text | adjusted | provenance/q2_description.py | Not independent corroboration |
| PROV-12 | PIN directory coordinates noisy | 3,931 / 165,627 office rows more than 200 km from PIN median | confirmed | provenance/q3_pincode.py | Use cleaned centroids |
| PROV-13 | PIN directory admin errors | 48 / 165,627 rows (799001 Agartala labelled Telangana) | confirmed | provenance/q3_pincode.py | Override state from postal circle |
| PROV-14 | Facility PINs in directory | 205 / 9,879 missing | confirmed | provenance/q3_pincode.py | Prefix fallback, flagged approximate |
| PROV-15 | NFHS small-sample notation | 9,193 / 75,542 string cells are "(x)" or "*" | confirmed | provenance/q4_nfhs.py | Parse, never cast "*" to 0 |
| PROV-16 | NFHS duplicated and missing districts | 2 / 706 (Mizoram/Chandel copy; no Purba Bardhaman) | confirmed | provenance/q4_nfhs.py | "No NFHS data" for Saiha, Purba Bardhaman |
| PROV-17 | NFHS to directory district join | 9,659 / 9,959 facilities (crosswalk adds 1,492) | confirmed | provenance/q4_nfhs.py | Use the crosswalk |
| PROV-18 | NFHS indicators usable as need context | 21 / 107 | confirmed | provenance/q4_nfhs.py | Context only, never facility evidence |
| verifier-found | US template claims ("call 911") | 63 / 9,959 | verifier-found | provenance/verify/v7_template.py; v7b_911.py | Not emergency evidence |
| verifier-found | officialWebsite is an aggregator or another facility | 53 / 9,959 aggregator; about 5 of 15 sampled low-similarity hosts are another facility | verifier-found | provenance/verify/v14_official.py; v15_misc.py | Classify before display |
| verifier-found | websites column is mostly aggregators | 6,125 / 9,959 | verifier-found | provenance/verify/v15_misc.py | Never show as "official links" |
| verifier-found | capacity and yearEstablished come from the description | 383 / 416 | verifier-found | provenance/verify/v6_desc.py | Circular, not a second source |
| verifier-found | Empty URL elements | 11,298 / 169,742 | verifier-found | provenance/verify/v1_base.py | Filter before counting |
| verifier-found | "Dr. " prefix artefact on names | 349 / 9,959 | verifier-found | provenance/verify/v7_template.py | Clean display names |
| verifier-found | Near-duplicates under different ids | 79 / 9,959 | verifier-found | provenance/verify/v16_near_dups.py | Covered by identity linking |

### 1.3 Numbers that differ between agents

- Coordinates far from PIN: 1,407 / 9,682 (geo), 1,394 / 9,497 (provenance), 1,386 / 9,527 (geo verifier), 1,367 / 9,869 (cleaning, after PIN repairs). Use the cleaning number, since that is what the product ranks on.
- NFHS join: 9,961 / 9,970 (geo), 9,659 / 9,959 (provenance), 9,934 / 9,959 (cleaning, deliberately leaving Saiha and Purba Bardhaman empty). Use 9,934.
- 50-item truncation: 2,080 / 9,970 rows (raw length), 1,495 graded records and 4,498 pairs (cleaning). Use cleaning for the product flag.
- Snapshot: every verifier confirmed the local snapshot against the warehouse (snapshot_faithful = true in all six dimensions).

---

## 2. Web ground truth

Sample: 36 facility-service pairs (8 services, 28 states and UTs), built by `audit/ground_truth/build_sample.py` with seed 20261121 and 0 warehouse queries. 12 pairs per stratum:
- strong: geo consistent (within 25 km, state matches), service in 2 or more fields, a clinical prerequisite present, no suspect signal;
- weak: geo consistent, exactly 1 mention, no prerequisite;
- suspect: another facility named, or more than 50 km from PIN, or state mismatch.

Each pair was checked on the open web (own site, directories, news). No phone calls.

| Stratum | n | Service confirmed | Contradicted | No info | Location wrong | Existence unclear |
|---|---|---|---|---|---|---|
| strong | 12 | 10 | 0 | 2 | 0 | 0 |
| weak | 12 | 1 | 3 | 8 | 0 | 1 |
| suspect | 12 | 4 | 4 | 4 | 4 | 3 |

Location verdicts: 25 yes, 4 no, 7 unclear. All 4 wrong locations are in the suspect stratum (Kaithal, Firozabad, Punalur, Satna). No facility was found not to exist; 4 have unclear existence.

What the sample says about internal signals:
- The strong-stratum features (a specific sentence, a prerequisite from another sentence, location agreement) predict a confirmed service: 10 of 10 with a verdict. Even here, the "strong" dialysis pair at Lifeline was a merged record that only happened to be right, and the "strong" MRI at Delhi Pain Management Centre found no MRI anywhere (no info).
- A single mention without a prerequisite mostly cannot be confirmed (8 of 12 no info) and is contradicted more often than confirmed (3 vs 1). Examples: an outpatient clinic chain with "C-section", a home-nursing agency with "trauma", AV-fistula surgery read as dialysis.
- Location flags work. The cleaning pipeline catches 4 of 4 wrong locations (one only after tuning on that miss) while still trusting 23 of 25 correct ones.
- The other-facility flag is noisy. 2 of the suspect pairs were real partnerships or referrals, not merges (Shillong NICU partnership, Kaithal referral to KCGMC), and suspect pairs were still confirmed 4 times.
- Grades from the cleaning pipeline (cleaning/claims/out/eval.json):

| Grader | Strong: confirmed / contradicted / no info | Moderate: confirmed / contradicted / no info |
|---|---|---|
| v1 (frozen before reading the verdicts) | 4 / 1 / 2 | 8 / 4 / 9 |
| v2 (fixes written after reading them) | 9 / 0 / 2 | 4 / 4 / 9 |

Strong precision under v2 is 9 of 9 (Wilson 0.70 to 1.00) with recall 9 of 15. Moderate is a coin toss: 4 confirmed and 4 contradicted.

Limits, stated plainly:
- 36 pairs, of which only 22 have a confirmed or contradicted verdict. 95% intervals are 30 to 60 points wide, so a 1 or 2 pair difference between graders means nothing.
- v2 is in-sample: it was tuned after the verdicts were read. Only v1 is an honest estimate, and v1 strong was 4 of 5.
- The strata share features with the grader (multiple fields, prerequisites, geo agreement), which inflates agreement.
- The sample excludes flagship chains and generic names (8,807 of 9,970 rows were eligible), so it says nothing about Apollo, AIIMS-type records.
- "Confirmed" mostly means the facility's own website says so. That is a second claim, not a bed check.
- A larger 176-pair gold set with a frozen 88-pair test split exists at `model/gold/splits.json` (grouped by duplicate cluster, stratified by service and stratum). Its labels (labels_*.json) were not evaluated for this report: not run.

---

## 3. Cleaning verdict

Answer: **data cleaning is viable for part of the problem and not for the rest, so we need a different strategy on top of it.** Cleaning fixes geometry, duplicates, contact data, impossible numbers and claim parsing. It cannot decide whether a sentence describes this building when the sentence names nobody. The strategy is: clean, then flag, then grade each facility-service pair from quoted sentences into tiers in words, and make "call first" the default for anything below the top tier. Phone calls are the only way to settle what the data cannot. Both cleaning pipelines run locally in under 5 minutes (`cleaning/geo_identity/run_all.sh` about 17 s, `cleaning/claims/run_all.sh` about 4 min) with 0 warehouse queries.

### Fixed

| Issue | Before | After | Residual risk |
|---|---|---|---|
| Exact duplicate rows | 9,970 rows | 9,959 records | None |
| Busy PINs far from facility consensus | 78 of 1,051 more than 25 km off (422009 Nashik 167.5 km) | 43 of 1,051 (422009 now 2.5 km); 69 PINs overridden | Uses facility points to fix PIN points (circular in principle) |
| PINs misplaced inside small districts (403513 Pernem at sea) | 31 PINs wrong | 31 moved to district median (radius 25 km) | Untuned 60 km, 3x rule |
| Facility PINs missing from directory | 134 PINs with no point | 127 have a point (14 consensus, 113 prefix median at 50 km radius) | Prefix point is district-level only |
| Coordinates outside India | 6 used for distance | 0 used; 9 marked city-level | Small |
| 10 to 50 km band (mostly centroid imprecision) | 1,081 records | 718 records | Some real errors labelled "approximate" |
| Stated state unusable for a filter | 82 unresolved | 32 unresolved; 0 records without a filter state | Pre-2014 Andhra labels stay flagged |
| District and NFHS join | 9,961 / 9,970 with 2 wrong joins | 9,946 districts; 9,934 NFHS joins; 12 empty by design | Parent-district figures for split districts |
| Typed location input | 38 of 40 audit tests; Hydrabad silent; homonyms auto-picked | 54 of 54 on an extended self-written suite | Regression suite, not an accuracy estimate |
| Residual duplicates | 0 linked | 75 groups (152 records) shown as one card; 52 soft links; 17 co-located units | In-sample: hard merge precision 0.84, recall 0.90 on the labels it was shaped on |
| Directory phones shown as official | 292 records | 0 displayed; 9,548 keep a number unique to them; 247 flagged no_direct_contact | Lead-gen numbers in 1 or 2 cities are missed |
| Email placeholders | 8,512 non-empty fields | 8,136 usable; 360 placeholders and 16 unrecoverable dropped | Head-office emails not marked |
| Duplicate claims in a record | 27,528 of 469,498 claims; 1,339 service claims | 0 counted | None |
| Field echo | 23,983 own service claims | 20,964 distinct claims | Fields are never independent |
| Specialty duplication | 278,994 items | 117,964 distinct tags (2,476 values) | Tags still corroborate one-word claims |
| Claim sentences naming another facility | 136 service sentences counted as evidence | Quarantined; 58 of 10,799 grades change; 0 confirmed ground-truth pairs lost | 6 of 25 hand-checked quarantines were false positives |
| Non-offers and referrals | Naive cues right 17 of 60 | 57 service sentences as counter-evidence; 14 of 15 correct | None found |
| Synonym false positives (Mrityunjay, EmOC, PICU, ambulance, glaucoma valve, post-burn) | All in audit grades | 101 pairs dropped | Other collisions not searched |
| Self-referential prerequisites | 345 of 355 strong dialysis | Prerequisites only from other sentences or tags | v2 "half the prerequisites" rule is permissive |
| Quantities | Not extracted | 700 pairs with a service quantity | Sparse for dialysis, C-section, cardiac surgery |

### Flagged (visible to the user, not repaired)

| Issue | Count after cleaning | What the user sees |
|---|---|---|
| Coordinates more than 50 km from PIN | 1,367 of 9,869 conflict; 1,165 ranked on a corrected point; 202 keep coordinates confirmed by city or state | Location note citing PIN, district and city |
| Disputed location (no rule decides) | 538 records | Both candidate towns; hand check of "city near neither": right 5, unclear 6, wrong 4 of 15 |
| PIN and coordinates agree, city elsewhere (Kaithal pattern) | 195 records | Disputed flag; 12 of 12 hand-checked were real conflicts |
| Copied geocodes | 160 records | Confidence downgraded |
| District near a boundary | 550 notes | "District from postcode; coordinates fall in neighbouring X" |
| Website class | own 7,902; directory 288; government 92; social 75; none 1,602; 32 may belong to another org | Never shown as official when it is not |
| Veterinary names | 12 for one human review | Held out |
| Scale implausibility | 19 doctors_exceed_beds; 32 small facility with tertiary claim | Caveat line |
| Claims 6 or more of 8 services | 79 records | Merge-candidate warning |
| Ambiguous attribution (credential, relation, chain) | 18 pairs graded weak | Caveat; 7 of 15 really about another facility |
| Third-party, part-time, hedged wording | 44 service sentences | Cannot carry a top grade |
| Non-specific sentence kinds (list, directory, staff, research, template) | 364 pairs weak | Shown as context |
| Single-specialty or AYUSH names with tertiary claims | 439 pairs capped | "Name suggests an eye hospital" |
| Outpatient type claiming inpatient service | 771 pairs | "Ask if they admit" |
| Strong grade corroborated only by a specialty tag | 1,035 of 4,151 strong | "Corroborated only by a specialty label" |

### Cannot be handled by cleaning

| Issue | Size | Mitigation |
|---|---|---|
| Anonymous copied text (names no facility) | 7,514 service sentences in 1,390 records; 1,161 of 4,151 v2 strong grades sit in such records; 0 of 20 hand-read sentences looked foreign | Record-level warning, "call first" default, field-call ledger. Optional offline ai_query attribution that can only lower a grade (specified, not run) |
| Merged multi-place records | About 1,370 to 1,400 records | Not split; flags, second point, "phone before travelling" |
| Arrays truncated at 50 items | 1,495 records, 4,498 pairs | "A missing service may still exist" |
| Merges where every field follows the other facility | Not countable | None in the data; only a phone call |
| Thin rural coverage | Bihar: 260 of 9,959 records, 146 in Patna district | Coverage note on every result |

Grade totals after cleaning (cleaning/claims/out/grades.parquet, v2): 10,799 facility-service pairs; strong 1,968 under v1 vs 4,151 under v2. Dialysis: strong 695, moderate 279, weak 64. C-section: strong 193, moderate 236. Of the 695 strong dialysis grades, 227 rest only on sentences of 3 words or fewer and 298 are corroborated only by a specialty label. For C-section, 90 of 193 strong grades are short-sentence only.

---

## 4. Recommended product: Parchi, a referral slip you can check

### 4.1 Why this concept

Judge totals: Parchi 24.5, Receipts 21.5, CallFirst 21.5.
- The strict-requirements judge (8.5) and the build-risk judge (8) both picked Parchi. It is the only concept that measured the delivery path for the primary user. All explanation text comes from deterministic templates, and its demo numbers reproduce against the cleaned tables.
- The originality judge picked CallFirst (8.5 vs Parchi 8). CallFirst has the two ideas no other entry will have: a Plan B that cannot fail for the same reason as Plan A, and a planner call list ranked by value of information.
- Receipts scored lowest on originality (6.5) but had the most defensible ranking (Pareto set, service time profiles, calibration line).

So we build Parchi and graft the best parts of the other two.

### 4.2 Format and why

One Databricks App: FastAPI serving server-rendered HTML with no client framework. At start-up it loads precomputed Delta tables into memory and answers every search from memory.

- **User fit (measured).** Local throttled test in app_design/feasibility/accessibility/outputs/results.json:

  | Framework | Page size (bytes) | Main action on emulated 2G (s) | axe violations |
  |---|---|---|---|
  | FastAPI HTML | 1,855 | 0.44 | 0 |
  | Streamlit (bare) | 1,278,942 | 43.47 | 3 |
  | Dash (bare) | 1,502,548 | 49.86 | 3 |
  | Gradio (bare) | 1,015,442 | 34.79 | 3 |

  An ASHA on 2G gets an answer in under a second. Chat and Genie were rejected for the ASHA's screen because they need typing, cannot guarantee the citation layout, and put an LLM in the trust seat. Planners, who do type, got both later on the same tables: the Genie space in `databricks/genie/` and the AI/BI dashboard in `databricks/dashboard/` (section 5.5).
- **Verified capability.** Warehouse, ai_query, strict JSON output and 8 chat endpoints were all probed and work. FastAPI ships pre-installed in the App runtime (documented). Not yet verified: App deploy, App reads from Unity Catalog, App calls to an endpoint, App writes. That makes a hello-world App the first hour of work.
- **Flexibility.** One backend serves the phone page, the planner page and a JSON API. A WhatsApp bot, IVR or a better grader can plug in behind the same card contract. A new service is one lexicon row plus a prerequisite list. A Genie space and a dashboard now sit on the same tables (section 5.5).
- **Caveat.** The 2G numbers come from a local server. Through Databricks Apps every viewer must sign in to the workspace, so an ASHA cannot use the hosted demo today. We present 2G as "built for public hosting" and measure the deployed URL once on Friday.

### 4.3 User workflow

1. Open the link. Pick the need from 8 large buttons (dialysis, delivery emergency / C-section, newborn care / NICU, ICU, accident / trauma, burns, heart surgery, MRI), labelled in Hindi and English.
2. Enter where: PIN, town, district, coordinates or device location. Ambiguity becomes a question, never a guess: "Aurangabad: Bihar or Maharashtra?", "Did you mean Hyderabad?".
3. Read the slip: up to 3 cards labelled "Closest, call first", "Clearest evidence within reach" and "Backup if they say no". 108 and 102 are shown on every slip, unconditionally.
4. Call, using the tap-to-call number (directory numbers removed) and the "Ask them" list of 2 to 4 questions built from what the evidence does not cover. For example: "Your listing says Specialised dialysis unit but names no nephrologist. Is one on duty today?"
5. Tap the outcome: can take the patient / not available / wrong number / no answer. "Not available" moves the backup up on this slip only.
6. Share the slip as plain text (WhatsApp or share sheet): name, address, phone, "call before you leave", 102, 108.
7. Planner tab: pick a service and state. You get a district table with the nearest clear-evidence option, counts of brief-only options, logged calls, NFHS-5 context labelled "about the district, not the facility", and a call list. Downloads as CSV.

### 4.4 How the ranking works (HOW)

This replaces Parchi's original hand-set exceptions (25 km closer, 30 minutes saved), which the strict judge flagged as unjustified.

1. **Candidates.** All facility-service pairs for the service from the v2 grade table. Drop the 12 exclude_review records. Drop pairs whose only text is counter-evidence or about another facility, and list them under "Why not these".
2. **Three axes, never blended into one score:**
   - travel: straight-line km x 1.26, plus the location radius (worst case);
   - evidence tier;
   - location confidence (checked / approximate / disputed).

   The 1.26 road factor comes from 50 OSRM routes in Bihar. It is shown as an estimate range.
3. **Pareto set.** A facility stays only if no other facility is at least as good on all three axes and better on one.
4. **Role labels from the set:**
   - Closest, call first: the nearest member of the set.
   - Clearest evidence within reach: the best-tier member inside the service's reach limit.
   - Backup: must be independent of the first two. Not in the same duplicate or soft-link group, no shared display phone, not on a copied geocode. The extra km if the first choice fails is shown.
5. **Service time profiles** (team defaults, labelled as such on screen, not clinical guidance):
   - Time-first, with a minimum evidence floor: C-section, trauma, burns, NICU. Trauma requires explicit trauma wording; generic "24/7 emergency" goes to a separate "stabilise only" list.
   - Weekly burden: dialysis, shown as 6 one-way trips a week.
   - Evidence-first: MRI, cardiac surgery.
6. **Funnel on every slip, with live counts.** Example for dialysis: records -> dialysis pairs -> after removing refer-out and other-facility text -> in reach -> Pareto set. Followed by "Why not these": each passed-over facility with its reason and the quote.

### 4.5 How WHY appears on screen

Each card has three separate checks, each with its source:
- **Does it offer this?** The tier in words, with verbatim quotes, each tagged with field and claim_id. Prerequisites are marked met (with the sentence or tag) or missing. Specialty-label corroboration gets its own line. Tiers:
  - "Stated clearly": strong grade, specific sentence longer than 3 words.
  - "Mentioned briefly": strong grade resting on 3 words or fewer.
  - "Label-backed": strong grade corroborated only by a tag.
  - "Claimed, not corroborated": moderate.
  - "Mentioned only": weak.
  - "Record says it refers out": counter_evidence.
  - "Text is about another facility": attributed_elsewhere.
  - "Only a specialty label": tag_only.
- **Is it where we think?** Checked / approximate (with radius) / disputed (both towns, both source fields), using the cleaning location note. Example: "Listing coordinates are 146 km from postcode 202001 (ALIGARH, UTTAR PRADESH); address city is 'Firozabad'".
- **Can you reach them?** Cleaned phone, or a labelled chain helpline, or "no direct number". Website class.

Below the checks: record-level warnings in plain words ("contains text about other hospitals", "claims 6 or more of 8 acute services", "record cut at 50 items"), and one "why this order" sentence filled from a template with the two distances and the two quotes. Tapping a quote opens the record text around it and the source URLs, with the caveat that only about 28% of source URLs are about the facility.

### 4.6 How uncertainty appears

- Tiers in words, never percentages or stars. Under each tier is a calibration line with n and a "small sample" tag: today "strong: 9 of 9 confirmed by web check (in-sample)" and "moderate: 4 confirmed, 4 contradicted of 8". Replace these with the frozen 88-pair test split once its labels are scored.
- A disputed location drops a card one tier and shows both towns.
- Anything below "Stated clearly" defaults to "call first", with the generated questions.
- An honest empty state: "No facility within N km has a clear statement of X in our data", then the nearest unconfirmed options and 102/108.
- Every slip carries a "What we cannot know" line (open today, free slot, copied text that names no other hospital) and a coverage note.
- Field calls appear as separate, dated evidence lines labelled with role. A single call never raises a tier, turns a card green or removes a facility. It reorders only the current slip. This fixes the strict judge's objection to CallFirst.

### 4.7 What makes it unique

- The output is a handover object (a referral slip for a family plus a phone call), not a chat reply or a ranked list.
- The backup cannot fail for the same reason as the first choice, because it is checked against duplicate groups, shared phones and copied geocodes. Those three come straight from the audit.
- "Why not these" makes omissions auditable, with quotes.
- Call questions are generated from the specific evidence gap in that record.
- "Strong" is split into Clear, Brief and Label-backed, based on a measured fact: 227 of 695 strong dialysis grades are 3 words or fewer.
- A planner call list ranks which unverified facilities are most worth a phone call, measured as PIN-km of shorter plans and labelled "places, not people". CallFirst's headline figures (634 PINs in 84 districts from 20 dialysis calls) have no saved script yet, so they stay off slides until recomputed.
- The LLM never grades a facility, and the demo shows why: llama-3-3-70b rated contaminated Aravind and Wockhardt records "offers dialysis, confidence 1".
- 2G-first, backed by measurement.

---

## 5. Architecture on Free Edition

### 5.1 Tables (schema `workspace.parchi`; the probe found `workspace` is the catalog for our own tables)

| Table | Grain | Source today |
|---|---|---|
| facility | 1 row per record (9,959): display name, cleaned contacts, website class, type, scale flags | cleaning/geo_identity/record_trust.parquet + audit/scale/scale_flags.parquet |
| facility_location | 1 per record: ranking point, radius, confidence, second point, loc_note, state, district, NFHS key | cleaning/geo_identity/facility_location.parquet |
| facility_groups | duplicate groups, soft links, co-located units | cleaning/geo_identity/facility_groups.parquet |
| pin_gazetteer, place_gazetteer | 1 per PIN / place name | cleaning/geo_identity/pin_gazetteer.parquet, place_gazetteer.parquet |
| claims | 1 per sentence (trim to service sentences plus prerequisites; full file is 14.8 MB) | cleaning/claims/out/claims.parquet |
| grades | 1 per facility x service (10,799): grade, rule id, cited claim ids, prerequisites, risk flags | cleaning/claims/out/grades.parquet |
| card | 1 per facility x service: tier word, three check sentences, ask-list, why-not reasons | new, built by pipeline |
| nfhs_context | 1 per district: parsed indicators with small-sample flags | audit/provenance/q4_nfhs.py output + audit/geo/district_nfhs_map.csv |
| calibration | 1 per tier: n, confirmed, contradicted, interval | cleaning/claims/out/eval.json, later model/gold test split |
| call_value | 1 per facility x service: PIN-km saved if confirmed | new (stretch) |
| call_ledger | 1 per logged call: facility, service, outcome, date, role, coarse district; no patient data | new; in-process first |

### 5.2 Pipeline (one serverless notebook, run once)

1. Read the shared catalog, then dedupe on unique_id. That gives 9,959 records.
2. Rebuild the PIN gazetteer: audit cleaning plus R0 and R1 repairs.
3. Facility location rule chain, followed by districts and NFHS keys.
4. Identity: duplicate groups, phone blocklist, email and website classification, trust flags.
5. Explode claims. The SQL is already written in a Spark-compatible style (from_json plus posexplode, row_number in place of QUALIFY).
6. Label claims: attribution, kind, cues, quantities. Then grade v2, after fixing the G_nonspec leaks: department-list and research-protocol sentences must fall to weak.
7. Build the card table and the planner district table.
8. Golden tests on the demo scenarios, plus the 54 resolver tests.
9. Write the Delta tables.

The cleaning code is pandas and numpy on tables of at most 165,627 rows, so it runs on the driver. rapidfuzz needs `%pip install rapidfuzz` on serverless, which is unverified; difflib is the fallback. Nothing has been run on Databricks yet: not run.

### 5.3 App

FastAPI in 1 of the 3 allowed Apps. It reads the tables once at start-up through the single 2X-Small warehouse and holds them in memory: about 22 MB of Parquet, against 6 GB of App memory. Each search costs 0 warehouse queries. Only ledger writes would touch the warehouse, and the default ledger is in-process (shared by all viewers until restart, labelled "demo"). The Delta write path is enabled only if the Friday smoke test passes.

### 5.4 Deterministic vs LLM

- **Deterministic:** location choice, grading, tiers, ranking, role labels, every explanation sentence (templates over precomputed columns), call questions, the funnel. Same inputs give the same output.
- **LLM use 1, live but optional:** map free text in any language to one of the 8 services, with llama-3-3-70b and a strict JSON schema. The model must return the phrase it used, and the app checks that phrase is a verbatim substring of the input. Offline results: 30 of 30 on the main set, 6 of 6 on the hard set, phrase quoted verbatim 36 of 36. The buttons work without it. Not used in the live demo; shown in the video only.
- **LLM use 2, offline, gated, not run:** ai_query attribution on the 242 ambiguous or other-facility service sentences. A row survives only if its claim_id exists and its quote is an exact substring after whitespace folding. It may only lower a grade, and is labelled "model-assessed". Enable it only if it beats the rules on the 40 labelled sentences.
- **Not used:** Vector Search or RAG (the problem is attribution, not retrieval), GPU, Lakebase (only as a stretch for the ledger), Agent Bricks, live routing (outbound internet is restricted).

### 5.5 Genie space and dashboard

Planned as a stretch and built once the App was stable, both for district planners and both over `workspace.referral_saathi`:

- Genie space "Referral Saathi planner": `databricks/genie/space.py` holds the tables, instructions, example SQL and benchmark questions, and `databricks/genie/GENIE.md` has the benchmark accuracy.
- AI/BI dashboard "Referral Saathi: district planner": `databricks/dashboard/build_dashboard.py` builds it, and `databricks/dashboard/DASHBOARD.md` lists its pages and query tests.

---

## 6. Weekend build plan (3 to 4 people)

Roles: P1 data pipeline, P2 backend engine, P3 front end and language, P4 evaluation, demo and ops. With 3 people, P4's work splits between P1 and P3.

**Friday evening (everyone, about 2 h)**
1. Deploy a hello-world FastAPI App that reads one Delta table and (optionally) calls llama-3-3-70b. Measure the deployed page on throttled 2G.
2. Email the organisers about judge access: Apps cannot be public, so judges must be workspace users with CAN_USE.
3. Freeze the card contract (table columns and JSON shape).

**Saturday**
- P1: port cleaning/geo_identity and cleaning/claims to one serverless notebook. Diff the result against local (10,799 pairs). Fix the G_nonspec leaks (Getwell Nagpur NICU strong on a department list; GMC Chandrapur C-section moderate on a research protocol). Write the Delta tables.
- P2: resolver port, candidate filter, worst-case distance, Pareto set, role labels, Plan B independence, why-not, funnel and templates. Assert tests on Aravind, Wockhardt Nagpur, Madhubani, Gadchiroli and Kakinada.
- P3: phone and planner HTML, need buttons, tap-to-call, share text, 102/108, Hindi string table.
- P4: generate every demo figure from P2's engine and freeze them as golden tests. Score the 88-pair test split in model/gold for the calibration line. Build the "How good is this?" page.

**Sunday morning**
- P1 builds the card and planner district tables with NFHS context.
- P2 builds the in-process ledger and, only if the smoke test passed, the Delta write.
- P3 runs the 2G and accessibility check and gets a native-speaker review of the Hindi strings.
- P4 builds the static HTML export of the golden scenarios from the same templates, records the demo video and writes the README.

**Sunday afternoon:** freeze at 15:00, rehearse the 3-minute script twice, restart the App (it stops 24 h after start), confirm judge access.

**Demo numbers to settle before freezing** (checked by the judges against the cleaned tables):
- Madhubani (PIN 847211), dialysis: Dr. Global Darbhanga, strong, 26.6 km straight line (37 km with a 1.4 factor, which is why two concepts disagree). Phular Muzaffarpur, 73.4 km. All 8 nearest options are corroborated only by a specialty tag. R. B. Memorial (moderate, 29.4 km) appears in neither demo and must be explained.
- Gadchiroli (20.18, 80.0), C-section: GMC Chandrapur, moderate, 77.6 km, low location confidence. It should fall to weak after the G_nonspec fix. Mogre (140.0 km, strong) and Nelson (142.9 km, strong) are closer than the originally chosen backup Ketkar (143.7 km), so the Pareto set will change the cards.
- Kakinada (PIN 533001), dialysis: Apollo Kakinada, moderate, 0.9 km. Queen's NRI and Sai Spoorthy, strong, about 143 km.

**Cut lines, in order** (cut from the top when behind):
1. Genie space and dashboard.
2. Planner call_value list (keep the district table).
3. Free-text LLM parse (buttons only).
4. Delta call_ledger writes (keep in-process).
5. Offline ai_query attribution.
6. Marathi (Hindi and English stay).
7. Planner tab entirely (keep the CSV export of one district table).

Never cut: quotes with claim ids, the three checks, tier words with the calibration line, disputed-location display, Plan B independence, "why not these", the call questions, 108/102 on every slip, the static fallback and the video.

---

## 7. Risks and what is still unverified

| Risk | Status | Mitigation |
|---|---|---|
| Databricks Apps deploy, App reads from UC, App calls endpoints, App writes | Documentation only; `apps list` is empty | Hello-world on Friday evening |
| Judges cannot open a public link | Per docs, not tested | Ask organisers Friday; recorded video; static HTML export of golden scenarios; notebook displayHTML fallback |
| App auto-stops 24 h after start | Documented | Restart on judging morning; note the time in the README |
| Daily fair-usage quota | Real | 0 queries per search; pipeline runs once; no live LLM in the demo |
| Calibration is tiny and in-sample | 22 usable pairs; v2 tuned on them | Score the frozen 88-pair test split; publish n with every rate |
| Anonymous copied contamination | 1,161 of 4,151 strong grades in affected records | Record warning plus call-first; say so on the methods page |
| Grader leaks on list and research sentences | Found in prototype | Fix before freezing demo numbers |
| Road factor 1.26 from 50 Bihar routes, free-flow | Measured once | Show as a range labelled "estimate" |
| Hindi strings on a referral slip | Need a native speaker | Review Sunday; English fallback |
| rapidfuzz on serverless | Unverified | difflib fallback |
| gemma-3-12b returned HTTP 429 under light load | Observed | llama-3-3-70b primary; buttons work without a model |
| CallFirst value-of-information numbers | No saved script found | Recompute in a saved script or leave off slides |
| Thin rural coverage | Bihar 260 of 9,959 records | Coverage note on every slip |
| Reading as triage | Design risk | 108 and 102 on every slip; never "safe to wait"; no danger-sign keyword detection |
| Not verified at all | - | NFHS crosswalk on Databricks; the 176-pair gold labels; Lakebase; App bundle size limits; Spark run of any cleaning step |
