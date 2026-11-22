# Witness knowledge base v2: assembly report

Built 2026-11-21 by `build.py` in this folder. Every number below is from `derived/v2/build_stats.json`,
`out/report.json`, `out/coverage_by_service.csv` or `out/spotcheck.csv`, all written by the scripts here.
Nothing in this step reads gold labels: no v1, v2 or v3 label file was opened, and no model was fitted.
`model/gold/v3/` does not exist yet, so there were no v3 DEV labels to use. `derived/v2/reader_scores.parquet`
(issue #50) does not exist either, so family R is an empty slot (see "Reader slot").

## Outputs (derived/v2)

| file | rows | size | grain |
| --- | --- | --- | --- |
| witnesses.parquet | 4,011,386 (349,290 present) | 17.6 MB | one row per (facility, service, witness); service `*` marks a facility-level witness (12,663 rows) |
| facility_features.parquet | 358,524 | 2.0 MB | one row per (facility, service): 9,959 x 36, 137 columns |
| facility_attributes.parquet | 9,959 | 0.6 MB | one row per facility, 68 columns |
| claim_atoms.parquet | 79,806 atoms, 48,752 echo units | 2.9 MB | one row per (claim sentence or specialties item, service), with raw_pos |
| build_stats.json | | | counts used here |

### witnesses.parquet columns

`witness_id`, `unique_id`, `service` (taxonomy id or `*`), `family` (T C N S P X W O D R K), `witness` (named
witness, for example `vf_text_unit`, `nabh_code_DIA`, `web_service_A`, `iphs_expected`), `role` (offer,
unit_or_equipment, list, department, certificate, designation, prerequisite, existence, location_warning,
level_prior ...), `value` (1 for a plain witness; the specialty evidence weight for specialties; 0.5 for a
weaker form such as an expired LaQshya certificate, an NMC support course or an IPHS "desirable" level),
`value_text`, `observability` (present / absent / not_observable), `evidence_id` (claim_id, list record id,
or stored page path), `evidence_url`, `fetched_date`, `field`, `raw_pos`, `quote` (verbatim), `source`,
`source_key`, `precision_k`, `precision_n`, `precision`, `precision_basis`, `note`.

Every (facility, service, family) has at least one row; this is asserted (9,959 x 36 x 11). When a family has no
present witness for a pair, one placeholder row says `absent` (the source can see this facility and says
nothing) or `not_observable` (the source cannot see it: no attributable website, facility type not covered by
the list, not matched to OSM, not public). Placeholder rows carry value 0, no evidence and no quote; this is
asserted, so absence and non-observability can never enter a scorecard as negative evidence.

### facility_features.parquet columns

All 64 features the feature study kept, displayed or marked context-only (`viz/features/recommended_feature_set.json`)
are present under their catalogue names; none is missing. Pair-level values are rebuilt here for 36 services;
facility-level columns that v2 does not change (NFHS, MAP travel time, WorldPop, cited-source shares, OSM flags,
`b_loc_conf`, `b_coord_pin_km`, `a_quarantine_share` and similar) are copied from
`viz/features/out/features_pairs.parquet`. List and website features are NaN where the source cannot see the
pair (fairness coding, below), and `obs_<family>` gives present / absent / not_observable for each of the 11
families.

New columns, not in the catalogue: `a_spec_weight` (largest specialty evidence weight for the pair),
`operator_public` (1 / 0 / NaN for unknown), `web_state` (alive / dead / none), `c_log2_n_urls` (record breadth;
PATTERNS finding 5 reports its effect per doubling), `g_iphs_prior` (0 / 0.5 / 1, NaN when not public or level
unknown), `x_any_list`, `e_web_cell` (A to E), `d_laqshya_labour_room` (for institutional_delivery),
`r_reader_p_offers` (empty slot), `focus`, and the per-facility fusion inputs: p1/p2, the 7 votes against p1 and
p2, `n_votes_for`, `n_votes_against`, `p2_supported`, `city_resolve_status`, `pin_in_india_post`, phone and
`phone_class`, website class, source multiplicity, recency, shared coordinate, pharmacy, strong duplicate,
`leakage_group_id`, `group_size`.

### facility_attributes.parquet columns

Operator (`operator`: public 469, private 8,805, unknown 685; `operator_src`: operatorTypeId 9,272, name 2,
none 685), `facility_level` from the name (mc 182, dh 66, sdh 19, phc 11, chc 7, unknown 9,674),
`facility_type` (1,300 rows retyped from name or specialties, for example dental clinics to `dentist`),
`is_24x7_<scope>` for 10 scopes with `_src` (vf_text, web, web+vf_text) and `_date` (page fetch date for web
facts), OPD hours with source, quote, evidence and date (2,677 facilities; web 2,349, dataset text 328), beds
from the cleaned capacity field (2,628) and from the website, empanelment from text and web (PM-JAY at 767
facilities), accreditation from text and web plus the NABH list status, acc_no, certificate URL and tier, and
`web_state` with its crawl date.

## What was ported and what changed

Text families (T C N S P) for 36 services. `evidence.py` reads the v1.1 lexicon matches
(`kb/taxonomy/out/lexicon_matches.parquet`, 64,670 rows less palliative_care) and reuses
`model/proto/evidence/atoms.py` for ownership (`_ownership`, rules v1), echo collapse (`echo_units`, ratio 85)
and the pair families (`pair_families`, grid switched to 36 services). Non-offer cues come from the lexicon's
clause-level cue instead of the sentence-level claims cue. Results: T = 0 / 1 / 2 / 3 / 4 / 5 on 328,302 /
8,323 / 10,613 / 3,594 / 3,335 / 4,357 pairs; C = 1 on 327 and C = 2 on 132; N on 142; P = 1 on 79,096 and
P = 2 on 6,880.

Specialty evidence weights instead of 0/1 tags. Each raw specialties item that has a row in
`kb/taxonomy/specialty_evidence_weights.csv` becomes a witness with value = its weight: kind `label` in family
T (it still sets T = 1 when nothing else speaks), kind `prereq` in family P. The lexicon's prerequisite patterns
exist for 9 services only; for the other 27 the specialty weights are the only P source.

v2 change 1, raw_pos. Every atom stores `raw_pos`, its index in the untouched raw array, next to the claims
`idx`. For 7,818 of 61,868 list atoms (0.126, Wilson 0.124 to 0.129) the two differ. All 81,462 present text
witnesses string-match the raw item at (unique_id, field, raw_pos), and all 86,877 specialties witnesses equal
the raw specialties item at raw_pos (`out/report.json`).

v2 change 2, type and scope from name and specialties. A facility focus (dental, eye, diagnostic, AYUSH, IVF,
skin or hair, ENT, physiotherapy or rehab) is read from facilityTypeId, the name (the audit's SCOPE_NAME words
and exemptions) and, when 80% of its specialties are dental or eye, the specialties. 3,540 facilities have a
focus (dental 1,671, eye 573, diagnostic 519, AYUSH 290, IVF 195, skin or hair 157, ENT 74, physio 61); 11 come
from specialties alone. S = 1 for every service outside the focus, with no grades row needed (123,204 pairs).
`test_assemble.py` checks that Smile Kraft Dental Clinic gets S = 1 for trauma_care and Nayan Jyoti Eye Hospital
for emergency_csection. The diagnostic focus is my addition (MODEL_SPEC 3.1 names lab facilities); it is not
hand-checked.

v2 change 3, one set of place layers, unplaceable as dissent. The city vote now resolves the stated city through
`model/proto/decision/resolve.py` (the same layers the App uses for queries) within the stated state: 9,570
resolve, 338 are ambiguous even within the state (vote 0) and 51 cannot be placed (vote -1, was 0). City vote
+1 / -1 / 0: 8,718 / 903 / 338; it changed for 2,169 facilities against the v1 vote. A stated PIN missing from
the India Post directory now votes -1 (162 changed). Sharda Hospital (PIN 270001) gets the PIN dissent and a
city dissent, 2 votes against (asserted in `test_assemble.py`).

Single phone source. `phone_class` is computed from the cleaned phone the card displays
(`derived/v1/record_trust.display_phones`): listed 9,547, none 412, shared in 3+ cities 0 under this source.
634 facilities change class against v1.

List family X. Accepted matches from the external/<slug> match scripts, thresholds unchanged, each row carrying
the list's match precision:

| list | services (role) | present pairs | match precision | observable where |
| --- | --- | --- | --- | --- |
| NABH specialty codes | DIA dialysis (service code); NPH dialysis, kidney transplant; TRN kidney transplant; OBG C-section, delivery, high-risk pregnancy; EMD emergency, trauma; CAR cardiac surgery, cath lab, STEMI (proxy); ONC three cancer services (departments) | 7,183 | 39/40 | NABH-matched facility with at least one fetched code |
| NMC PG courses | 32 services, strong (1.0) or support (0.5) course | 1,486 | 19/20 | NMC-matched college |
| LaQshya | Maternity OT to C-section, Labour Room to delivery; 1.0 valid on 2026-11-21, 0.5 expired | 103 | 17/20 (+3 plausible) | public CHC, SDH, DH, MC, or matched |
| MoHFW trauma care facilities | trauma_care (designation) | 20 | 19/20 | public hospital or matched |
| e-RaktKosh | blood_bank (service); prerequisite for C-section, trauma, burns, cardiac surgery | 1,825 | 16/20 strict | hospital or matched |
| PMNDP Goa list | dialysis | 1 | 1/1 (recall 1/8) | public facility in Goa |

The NMC course map extends `external/nmc_colleges/join.py` COURSE_SERVICE (8 services, patterns kept) to 32
services; the extension is my mapping and is not hand-checked. NABH codes are self-declared departments.

Website W. Attributable sites only (`kb/web_evidence`, identity high or medium, not a chain homepage): 4,866
facilities are observable, 5,093 are not. Each positive pair is coded with the QA evidence-structure cell and
its precision: A strong on 2+ pages 13/13, B strong list item 3/3, C strong sentence 8/14, D weak 2+ pages 5/12,
E weak 1 page 7/18 (`kb/web_evidence/qa/QA.md`). Negated lines are kept as `web_negated` rows (a guard, never
evidence of absence). 24x7 emergency facts (9/10 in QA) are W witnesses for emergency_24x7, trauma_care and
emergency_csection.

Open data O (`kb/opendata`): existence witnesses per facility (OSM high 2,596, medium 195; Wikidata high 182,
medium 24) with tier precision 17/20 high and 7/10 medium; 665 `osm_conflict` rows are location warnings only
(4/15 are really the facility); service tags from OSM speciality and emergency=yes (680 pairs).

Dataset details D (`kb/vf_details`, extraction 46/50): service-level facts (24x7 by unit, equipment counts,
unit beds, blood centre, dialysis shifts) mapped to 12 services, and facility-level facts as `*` rows. D comes
from the same record text as T, so it is not an independent witness; the note column says so.

Context K. The IPHS 2022 expected-service prior for public facilities: a table in `acommon.IPHS` (1 essential,
0.5 desirable or size or FRU dependent, 0 not expected), my reading of `services.json iphs.expected_from`,
which is quoted in each row. It is observable only for public facilities whose level the name gives: 176 of
the 469 public facilities. For the other 293 public facilities the level is unknown and K is not observable.

## Fairness coding (PATTERNS findings 1 to 5)

- Website features are NaN, and W is `not_observable`, when the facility has no attributable website.
  Public facilities: 137 of 469 have a live site (29%), against 5,422 of 8,805 private.
- `d_nabh_listed` is NaN for a public facility without a NABH match (427 of 469), 0 only for private or unknown
  operators. NABH codes are observable only for NABH-coded facilities.
- List features are NaN outside the facility types each list covers (table above).
- The IPHS prior is the public-sector substitute, in family K, observable for 176 public facilities.
- Added as features: `operator_public` and `c_log2_n_urls` (contamination priors), `web_state`, `d_nabh_listed`
  (also a location prior), `k_text_pmjay` (weak drift risk). Not added, as PATTERNS says: the off-focus flag,
  year established, the anomaly score.

## Coverage per service

Facilities with each family present / absent / not observable (each cell sums to 9,959). Facility-level `*`
witnesses (OSM existence, facility-wide details) are not counted in these cells.

| service | T | C | N | S | P | X | W | O | D | R | K |
|---|---|---|---|---|---|---|---|---|---|---|---|
| emergency_24x7 | 3,363 / 6,596 / 0 | 32 / 9,927 / 0 | 9 / 9,950 / 0 | 3,540 / 6,419 / 0 | 299 / 9,660 / 0 | 316 / 804 / 8,839 | 1,963 / 2,903 / 5,093 | 166 / 2,678 / 7,115 | 2,292 / 7,667 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| trauma_care | 1,256 / 8,703 / 0 | 27 / 9,932 / 0 | 7 / 9,952 / 0 | 3,419 / 6,540 / 0 | 5,691 / 4,268 / 0 | 649 / 5,046 / 4,264 | 2,019 / 2,847 / 5,093 | 2 / 2,842 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| burn_care | 262 / 9,697 / 0 | 2 / 9,957 / 0 | 3 / 9,956 / 0 | 3,419 / 6,540 / 0 | 1,864 / 8,095 / 0 | 378 / 5,267 / 4,314 | 310 / 4,556 / 5,093 | 9 / 2,835 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| orthopaedic_trauma_surgery | 556 / 9,403 / 0 | 7 / 9,952 / 0 | 1 / 9,958 / 0 | 3,419 / 6,540 / 0 | 3,564 / 6,395 / 0 | 70 / 11 / 9,878 | 719 / 4,147 / 5,093 | 42 / 2,802 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| snakebite_antivenom | 17 / 9,942 / 0 | 0 / 9,959 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 12 / 9,947 / 0 | 0 / 0 / 9,959 | 58 / 4,808 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| icu | 2,785 / 7,174 / 0 | 43 / 9,916 / 0 | 8 / 9,951 / 0 | 3,540 / 6,419 / 0 | 2,955 / 7,004 / 0 | 69 / 12 / 9,878 | 1,682 / 3,184 / 5,093 | 0 / 2,844 / 7,115 | 517 / 9,442 / 0 | 0 / 0 / 9,959 | 158 / 18 / 9,783 |
| picu | 425 / 9,534 / 0 | 3 / 9,956 / 0 | 3 / 9,956 / 0 | 3,540 / 6,419 / 0 | 3,438 / 6,521 / 0 | 68 / 13 / 9,878 | 271 / 4,595 / 5,093 | 0 / 2,844 / 7,115 | 21 / 9,938 / 0 | 0 / 0 / 9,959 | 158 / 18 / 9,783 |
| ventilator_support | 459 / 9,500 / 0 | 5 / 9,954 / 0 | 1 / 9,958 / 0 | 3,540 / 6,419 / 0 | 1,689 / 8,270 / 0 | 69 / 12 / 9,878 | 647 / 4,219 / 5,093 | 0 / 2,844 / 7,115 | 29 / 9,930 / 0 | 0 / 0 / 9,959 | 158 / 18 / 9,783 |
| emergency_csection | 436 / 9,523 / 0 | 7 / 9,952 / 0 | 1 / 9,958 / 0 | 3,345 / 6,614 / 0 | 5,536 / 4,423 / 0 | 1,232 / 4,468 / 4,259 | 1,587 / 3,279 / 5,093 | 70 / 2,774 / 7,115 | 41 / 9,918 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| institutional_delivery | 1,196 / 8,763 / 0 | 32 / 9,927 / 0 | 3 / 9,956 / 0 | 3,345 / 6,614 / 0 | 4,517 / 5,442 / 0 | 992 / 263 / 8,704 | 938 / 3,928 / 5,093 | 70 / 2,774 / 7,115 | 41 / 9,918 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| high_risk_pregnancy | 962 / 8,997 / 0 | 4 / 9,955 / 0 | 0 / 9,959 / 0 | 3,345 / 6,614 / 0 | 4,517 / 5,442 / 0 | 949 / 171 / 8,839 | 632 / 4,234 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| nicu | 741 / 9,218 / 0 | 8 / 9,951 / 0 | 3 / 9,956 / 0 | 3,345 / 6,614 / 0 | 5,044 / 4,915 / 0 | 68 / 13 / 9,878 | 636 / 4,230 / 5,093 | 6 / 2,838 / 7,115 | 48 / 9,911 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| safe_abortion_mtp | 151 / 9,808 / 0 | 2 / 9,957 / 0 | 0 / 9,959 / 0 | 3,345 / 6,614 / 0 | 0 / 9,959 / 0 | 69 / 12 / 9,878 | 101 / 4,765 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| cardiac_surgery | 973 / 8,986 / 0 | 16 / 9,943 / 0 | 5 / 9,954 / 0 | 3,540 / 6,419 / 0 | 3,618 / 6,341 / 0 | 815 / 4,880 / 4,264 | 560 / 4,306 / 5,093 | 2 / 2,842 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 81 / 95 / 9,783 |
| cath_lab_angioplasty | 814 / 9,145 / 0 | 15 / 9,944 / 0 | 9 / 9,950 / 0 | 3,540 / 6,419 / 0 | 3,072 / 6,887 / 0 | 553 / 567 / 8,839 | 609 / 4,257 / 5,093 | 32 / 2,812 / 7,115 | 17 / 9,942 / 0 | 0 / 0 / 9,959 | 81 / 95 / 9,783 |
| stemi_thrombolysis | 21 / 9,938 / 0 | 0 / 9,959 / 0 | 1 / 9,958 / 0 | 3,540 / 6,419 / 0 | 3,072 / 6,887 / 0 | 562 / 558 / 8,839 | 54 / 4,812 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| stroke_care | 158 / 9,801 / 0 | 1 / 9,958 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 2,037 / 7,922 / 0 | 23 / 58 / 9,878 | 158 / 4,708 / 5,093 | 22 / 2,822 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| neurosurgery | 2,233 / 7,726 / 0 | 25 / 9,934 / 0 | 3 / 9,956 / 0 | 3,540 / 6,419 / 0 | 1,587 / 8,372 / 0 | 23 / 58 / 9,878 | 940 / 3,926 / 5,093 | 5 / 2,839 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 81 / 95 / 9,783 |
| dialysis | 1,040 / 8,919 / 0 | 27 / 9,932 / 0 | 10 / 9,949 / 0 | 3,540 / 6,419 / 0 | 2,332 / 7,627 / 0 | 501 / 620 / 8,838 | 913 / 3,953 / 5,093 | 15 / 2,829 / 7,115 | 111 / 9,848 / 0 | 0 / 0 / 9,959 | 158 / 18 / 9,783 |
| kidney_transplant | 480 / 9,479 / 0 | 9 / 9,950 / 0 | 4 / 9,955 / 0 | 3,540 / 6,419 / 0 | 3,321 / 6,638 / 0 | 516 / 604 / 8,839 | 333 / 4,533 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 0 / 176 / 9,783 |
| chemotherapy | 1,568 / 8,391 / 0 | 14 / 9,945 / 0 | 2 / 9,957 / 0 | 3,540 / 6,419 / 0 | 2,683 / 7,276 / 0 | 337 / 783 / 8,839 | 445 / 4,421 / 5,093 | 12 / 2,832 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| radiotherapy | 380 / 9,579 / 0 | 13 / 9,946 / 0 | 6 / 9,953 / 0 | 3,540 / 6,419 / 0 | 104 / 9,855 / 0 | 348 / 772 / 8,839 | 282 / 4,584 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 0 / 176 / 9,783 |
| surgical_oncology | 1,529 / 8,430 / 0 | 15 / 9,944 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 2,507 / 7,452 / 0 | 338 / 782 / 8,839 | 596 / 4,270 / 5,093 | 12 / 2,832 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 0 / 176 / 9,783 |
| mri | 945 / 9,014 / 0 | 17 / 9,942 / 0 | 8 / 9,951 / 0 | 3,021 / 6,938 / 0 | 3,276 / 6,683 / 0 | 62 / 19 / 9,878 | 662 / 4,204 / 5,093 | 20 / 2,824 / 7,115 | 235 / 9,724 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| ct_scan | 1,448 / 8,511 / 0 | 24 / 9,935 / 0 | 15 / 9,944 / 0 | 3,021 / 6,938 / 0 | 3,187 / 6,772 / 0 | 62 / 19 / 9,878 | 989 / 3,877 / 5,093 | 20 / 2,824 / 7,115 | 212 / 9,747 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| ultrasound | 2,099 / 7,860 / 0 | 21 / 9,938 / 0 | 5 / 9,954 / 0 | 2,826 / 7,133 / 0 | 3,187 / 6,772 / 0 | 62 / 19 / 9,878 | 1,727 / 3,139 / 5,093 | 21 / 2,823 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| blood_bank | 680 / 9,279 / 0 | 27 / 9,932 / 0 | 7 / 9,952 / 0 | 3,540 / 6,419 / 0 | 506 / 9,453 / 0 | 373 / 5,272 / 4,314 | 510 / 4,356 / 5,093 | 0 / 2,844 / 7,115 | 598 / 9,361 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| psychiatric_care | 1,317 / 8,642 / 0 | 5 / 9,954 / 0 | 1 / 9,958 / 0 | 3,540 / 6,419 / 0 | 0 / 9,959 / 0 | 51 / 30 / 9,878 | 167 / 4,699 / 5,093 | 12 / 2,832 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 158 / 18 / 9,783 |
| de_addiction | 284 / 9,675 / 0 | 9 / 9,950 / 0 | 5 / 9,954 / 0 | 3,540 / 6,419 / 0 | 0 / 9,959 / 0 | 51 / 30 / 9,878 | 148 / 4,718 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 0 / 176 / 9,783 |
| cataract_surgery | 904 / 9,055 / 0 | 24 / 9,935 / 0 | 18 / 9,941 / 0 | 2,967 / 6,992 / 0 | 2,827 / 7,132 / 0 | 64 / 17 / 9,878 | 741 / 4,125 / 5,093 | 46 / 2,798 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| eye_emergency | 369 / 9,590 / 0 | 0 / 9,959 / 0 | 0 / 9,959 / 0 | 2,967 / 6,992 / 0 | 2,827 / 7,132 / 0 | 64 / 17 / 9,878 | 260 / 4,606 / 5,093 | 46 / 2,798 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| tb_care | 232 / 9,727 / 0 | 16 / 9,943 / 0 | 4 / 9,955 / 0 | 3,540 / 6,419 / 0 | 2,263 / 7,696 / 0 | 44 / 37 / 9,878 | 304 / 4,562 / 5,093 | 3 / 2,841 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| hiv_art | 73 / 9,886 / 0 | 5 / 9,954 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 1,006 / 8,953 / 0 | 0 / 0 / 9,959 | 39 / 4,827 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 142 / 34 / 9,783 |
| anti_rabies | 19 / 9,940 / 0 | 0 / 9,959 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 26 / 4,840 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 176 / 0 / 9,783 |
| paediatric_inpatient | 38 / 9,921 / 0 | 3 / 9,956 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 3,438 / 6,521 / 0 | 68 / 13 / 9,878 | 52 / 4,814 / 5,093 | 40 / 2,804 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |
| nutrition_rehabilitation | 9 / 9,950 / 0 | 1 / 9,958 / 0 | 0 / 9,959 / 0 | 3,540 / 6,419 / 0 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 8 / 4,858 / 5,093 | 0 / 2,844 / 7,115 | 0 / 9,959 / 0 | 0 / 0 / 9,959 | 165 / 11 / 9,783 |

Reading notes: R is not observable everywhere (no reader output yet). K is not observable for 9,783
facilities (not public, or public with no level in the name). D has no mapped detail for 24 services. X is
widest for services e-RaktKosh or NABH codes can see (trauma, burns, C-section, cardiac surgery, blood bank),
and not observable for 9,878 facilities for most of the rest, where only NMC reaches.

## Spot check of 15 witnesses

Drawn with seed 20261121 from present rows with a quote, stratified as in `report.SPOT`. Each was re-read from
its own source: the raw record item at raw_pos, the stored web page file and field, the NABH specialty table,
the LaQshya facility table, the e-RaktKosh directory, the open-data match table, the claim sentence, the record
name, or the services.json IPHS text. 15 of 15 quotes string-match (Wilson 0.80 to 1.00). Full rows with what
was read are in `out/spotcheck.csv`.

| witness_id | family | witness | service | quote | matches |
| --- | --- | --- | --- | --- | --- |
| w1176386 | T | vf_text_unit | emergency_24x7 | Provides emergency care | True |
| w2069865 | T | vf_text_unit | mri | Performs MRI scans | True |
| w3530980 | T | vf_specialty | surgical_oncology | gynecologicalOncology | True |
| w3885860 | C | vf_rejected_names_other_facility | ultrasound | Ultrasound imaging equipment depicted in page imagery for the Womens C | True |
| w2101351 | N | vf_nonoffer | mri | Online dashboard will be available for project management of PPP MRI/C | True |
| w3610447 | S | scope_skin_hair | tb_care | Dr. Goyal's skin clinic | True |
| w3775727 | P | prereq_surgery_or_ortho | trauma_care | General Surgery | True |
| w1907835 | X | nabh_code_NPH | kidney_transplant | NPH | True |
| w1808413 | X | laqshya_expired | institutional_delivery | Govt Tirunelveli Medical College & Hospital | True |
| w131971 | X | eraktkosh_centre | blood_bank | Mundakapadam Mandiram Hospital Bsu | True |
| w441052 | W | web_service_A | cardiac_surgery | CARDIAC OT | True |
| w1214628 | W | web_service_E | emergency_24x7 | Emergency Care | True |
| w6592 | O | osm_match_high | * | Suyash Hospital | True |
| w797263 | D | vf_equipment_count:ct_slices | ct_scan | 32-slice CT scanner | True |
| w2389698 | K | iphs_expected | nutrition_rehabilitation | FRU-CHC and UCHC (10-bed NRC desirable); SDH and 50-bed DH (desirable) | True |

The spot check tests that the quote is really in the source, not that the witness is true. The truth rates
are the precision columns, which come from the hand checks named in `acommon.PRECISION`.

## Leakage notes for the fit

- Each X row carries `source_key` (nabh, nmc, laqshya, mohfw_tcf, eraktkosh, pmndp_goa). A fit that uses a list
  as a label for service s must drop that source_key's rows for s from the features (cross-fitting by label
  family). This table does not decide that; it makes it possible.
- The website and cited-source witnesses share pages with the gold web check (FEATURES.md finding 5), so their
  DEV numbers will look better than they are.
- `b_loc_conf` and `b_coord_pin_km` are copied unchanged from the feature study, which marks them as tuned.

## Reader slot

`external.r_reader` reads `derived/v2/reader_scores.parquet` (claim_id, service_id, p_about_this, p_offers)
when it exists and emits one R row per (claim, service) joined to the atoms, plus `r_reader_p_offers` per pair.
Rerun `build.py` once the file lands; nothing else changes.

## Not run and limits

- No hand check of the new pieces: the 36-service IPHS table, the NMC course extension, the diagnostic and
  specialties focus rules, the NABH code to service map beyond the 7 v1 services, the OSM speciality map.
- Prerequisite text patterns exist for 9 services; 27 services get P only from specialty weights. P has no
  hand-checked precision (NaN in 23,329 present rows).
- Text witnesses for 21 of the 36 services rest on lexicon patterns checked on one reviewer sentence each
  (TAXONOMY.md "Not checked").
- The city vote is 0 for 338 facilities whose city name is ambiguous within the stated state; I treated that
  as an abstention, not a dissent.
- Public operator rests on operatorTypeId: the name added only 2 public facilities, and 685 stay unknown.
- No Databricks run. The build took 926 s on the first run and 3,244 s on the second under heavy machine load.

## Rebuild

```
PY=/Users/karthikvattem/projects/datathon/.venv-viz/bin/python
cd /Users/karthikvattem/projects/datathon/model/v2/assemble
$PY acommon.py && $PY evidence.py        # self-checks
$PY build.py                             # writes derived/v2
$PY test_assemble.py && $PY report.py    # named cases, coverage, full quote test, spot check
```

Files: `acommon.py` (paths, services, precision registry, IPHS table, operator and level rules), `evidence.py`
(T C N S P), `external.py` (X W O D K R), `facloc.py` (location votes, existence, attributes), `build.py`,
`report.py`, `test_assemble.py`.
