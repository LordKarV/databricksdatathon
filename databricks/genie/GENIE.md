# Genie space: Referral Saathi planner

A Genie space (Genie Agent) for district health planners, over 12 tables in `workspace.referral_saathi`. It answers questions about where facilities show public evidence of a service and how strong that evidence is, following the project's honesty rules.

## Space

- Space id: `01f1e60264ac19f98063e082b625c2df`
- URL: https://dbc-ea4e0abe-8cd4.cloud.databricks.com/genie/rooms/01f1e60264ac19f98063e082b625c2df (standard Genie room link built from the id; the space was read back with `databricks genie get-space`, the link was not opened in a browser)
- Warehouse: `6a2f5637720a2c17`, profile `vf`. Parent folder: the profile user's workspace home.
- Created on 2026-11-21 by `space.py deploy`. Read back: 10 tables, 10 example SQL queries, 7 join specs, 1 text instruction, 5 sample questions. Updated 2026-11-21 for model v2; read back: 12 tables, 12 example SQL queries, 9 join specs, 1 text instruction, 6 sample questions. Updated 2026-11-22 (plan 6b); read back: 12 tables, 13 example SQL queries, 12 benchmark questions.

## Benchmark accuracy

Native Genie benchmark (`genie genie-create-eval-run`, Chat mode: Genie's SQL result set is compared with our ground-truth SQL) over the 12 benchmark questions in `space.py`. These are the 7 test_space.py questions, the 3 from VERIFY.md, and the brief's two.

| Run | Space version | Correct | Needs review | Wrong |
|---|---|---|---|---|
| `01f1e6463ee51718b27bd75fd04fb54e` | first deploy of the benchmarks | 9 of 12 (75.0%) | 1 | 2 |
| `01f1e646eac711e6b10f1231c5c37539` | after rewording the app instruction (live version) | 10 of 12 (83.3%) | 1 | 1 |

Per question, from the second run (`benchmark_results.json` has both runs, with Genie's SQL):

- The brief's two:
  - "Where can a patient get dialysis near Jaipur?" was correct in both runs: the first 10 facilities within 50 km of the Jaipur district centre (the query returns at most 10), Likely first, with claim ids (Deep Hospital and Research Centre, Jhotwara, 2.6 km, claim 4a89be71:proc:13).
  - "Which hospital near Lucknow can handle an emergency C-section?" was correct in both runs: BNK Hospital (4.0 km, Likely, claims d93e5058:equi:0, d93e5058:proc:2), then Fatima Hospital (4.4 km, Likely, claims 8b1f6969:proc:2, 8b1f6969:proc:7).
  - Asked again through the Conversation API, both answers name the claim ids for every facility they list.
- Wrong in both runs: "Which three states have the most facilities on the e-RaktKosh blood bank list?". Genie counts list rows, not distinct facilities (in run 1 it also added `service = 'blood_bank'`).
- Needs review in both runs: "How many districts in Uttar Pradesh ...". Genie returns 54 districts and 149.54 M people, against our 149.5 (it rounds to two decimals). The numbers are right.
- Wrong in run 1 only: "How many facilities in Bihar does model v2 band Likely for dialysis?". Genie split the 36 by owner, copying example 12. With unchanged data, the same question went from wrong to right between runs, so one run is not a stable measure.

Limits: 12 questions is below the 30 the Genie optimisation guide asks for before tuning on the score. Two of the 12 (Jaipur, Lucknow) share their SQL shape with example 13 (ICU near Patna), so they test that Genie adapts the example to a new place and service, not open generalisation. Both brief questions use `near_sql()`, which ends in `LIMIT 10`, so 10 is the cap, not the count; yet Genie's Conversation-API answers say "There are 10 facilities" (Jaipur) and "There are 10 hospitals" (Lucknow) (`brief_questions_conversation_api`). The instructions should tell it to say when a list is capped; that needs a redeploy of the space. Nobody has opened the Benchmark tab in a browser; the screenshot is still to take.

Description shown in Genie:

> For district health planners in India: where facilities show public evidence of a service (trauma or 24x7 emergency, dialysis, emergency C-section, ICU, NICU, MRI and more), how strong that evidence is (dataset claim, text grade, facility website, OpenStreetMap, official lists such as NABH, LaQshya, NMC and the MoHFW trauma list), and which districts have none. Built on the Virtue Foundation records (9,959 facilities, 88% private). Every answer is about evidence, not about care that exists.
>
> Capabilities:
> - Facilities near a district for a service, model v2 band Likely first, then straight-line km, with the cited claim ids and sentences
> - Districts with no corroborated dialysis or C-section evidence, with people and need
> - Share of claims confirmed by a second source (website, OpenStreetMap, official list), by state or district
> - Official list facts (NABH, LaQshya, NMC, MoHFW trauma, e-RaktKosh) with citation links
> - Model v2 band counts by service, state and owner
> Not here: travel time, phone calls and the emergency order. The Referral Saathi app adds those.

## Files

| File | What |
|---|---|
| `space.py` | The whole space as code: tables with column descriptions, synonyms, entity matching and hidden columns; text instructions; example SQL; join specs; sample questions. `check` runs every example SQL, `build` writes `genie_space.json`, `deploy` checks, builds and creates the space, or updates it when `space_id.txt` exists |
| `genie_space.json` | The `serialized_space` payload that was sent |
| `space_id.txt` | Id of the live space; makes `deploy` an update |
| `test_space.py` | Asks the 7 test questions through the Conversation API and compares with our SQL |
| `test_results.json` | Full test output: question, ground-truth SQL and rows, Genie's SQL, rows and text |
| `benchmark_results.json` | Both benchmark eval runs, per question: assessment, reasons and Genie's SQL; plus the Conversation API answers to the brief's two questions |

Re-run from the project root:

```
export DATABRICKS_CONFIG_PROFILE=vf
python3 databricks/genie/space.py check     # read-only
python3 databricks/genie/space.py deploy    # updates the live space in place
cd databricks/genie && python3 test_space.py
```

Model v2 (2026-11-21): derived/v2 is loaded as `facility_service_scores_v2` and `facility_attributes_v2` (validation report H7). The space now carries both tables, two v2 example queries, two join specs and a MODEL V2 SCORES instruction block; owner questions use `facility_attributes_v2.operator` and `geo_facility.operatorTypeId` is hidden. The geo_facility claimed and corroborated flags are unchanged.

## Tables

- `claims`: One row per claim sentence (469,498): the text and attribution behind each claim_id.
- `facility_list_facts`: 3,062 per-facility matched facts from NABH, LaQshya, NMC, MoHFW trauma, e-RaktKosh and Goa PMNDP, each with citation_url.
- `facility_attributes_v2`: One row per facility record (9,959), model v2: operator (public, private, unknown), level, type, beds, PM-JAY.
- `facility_service_scores_v2`: One row per (eligible record, service), 358,092: model v2 band, p, score-bin track record lo/hi, P_L, P_E, operator, overlays.
- `facility_trust`: One row per facility: existence, location and overall record scores with plain-English drivers.
- `geo_dialysis_district`: One row per NFHS-5 district (704): dialysis need proxy, claimed and confirmed counts, share within 60 minutes, hot flag.
- `geo_district`: One row per LGD district (784, including the 227 with no records): population, records, records per million.
- `geo_facility`: One row per facility record (9,959): LGD state and district, NFHS keys, point, owner, type, and the claimed / confirmed / per-source flags for trauma or 24x7 emergency, dialysis and emergency C-section.
- `grades`: One row per (facility, service) the text mentions (10,799): text evidence grade and cite_evidence, the claim_ids behind it.
- `services`: The 37-service taxonomy, with aliases that map old ids (trauma, csection, burns) to taxonomy ids.
- `specialties`: One row per (facility, specialty tag): the weakest evidence, used for nephrology and similar departments.
- `web_service_summary`: One row per (facility, service) the facility's own website states, with best quote and URL.

Joins (declared as join specs): `geo_facility.unique_id` to `grades`, `facility_trust` (1:1), `facility_list_facts`, `specialties`, `web_service_summary`, `claims` and `facility_service_scores_v2`, and 1:1 to `facility_attributes_v2`; `geo_facility (nfhs_state, nfhs_district)` to `geo_dialysis_district`. All 9,959 facility rows match a `geo_dialysis_district` row, and its `n_claim` and `n_corr` equal the sums of the `geo_facility` dialysis flags in all 704 districts (checked with SQL on 2026-11-21).

Column configs: descriptions on the evidence columns, entity matching and format assistance on state, district, service, grade, list and status columns, and hidden grid, raw-name and JSON columns.

## General instructions (as sent)

These encode the honesty rules: every row is a claim with an evidence level, report n and the level, say "no public evidence" rather than "no care", never rank on unverified claims alone, cite claim_ids. 1,991 characters, under the 2,000 limit.

```
## PURPOSE
- Planners ask where facilities show public evidence of a service and how strong it is.
- Every row is a claim from the Virtue Foundation records (88% private), not a verified fact.
- Your km are straight line. Travel time and call-ahead come from the Referral Saathi app, which in an emergency calls the nearest plausible place first; say so for a patient.

## DISAMBIGUATION
- "Confirmed", "corroborated" or "second source" means the *_corroborated flags in geo_facility or n_corr in geo_dialysis_district. "Claims" means *_claimed or grades rows.
- "Trauma" in geo_facility and grades means trauma or 24x7 emergency.
- "Near X" with no radius: 50 km straight line from the centre of district X (geo_district cx, cy); say so.
- geo_facility and geo_district states are UPPER CASE; NFHS tables title case.

## DATA QUALITY NOTES
- NABH rows are facility-level (service null): they confirm the facility, not a service.
- citation_url '#' or 'Not Found' means no usable link.

## MODEL V2 SCORES
- "Likely", "can handle", band, score or P_S mean facility_service_scores_v2; state and district from geo_facility. Order by band (LIKELY, CALL_FIRST, NO_SERVICE_TEXT, UNLIKELY), then p or km. Never show p for NO_SERVICE_TEXT. lo/hi are a score bin's track record, not an interval.
- Owner is facility_attributes_v2.operator. The score cannot rank public facilities: say so.

## CONSTRAINTS
- Never rank facilities on claims alone. Order by evidence level (model band, or official list or confirmed, then grade), then distance, and show the level.
- Never say a place has "no care" or "no facility". Say "no public evidence in this dataset" and give n.

## Instructions you must follow when providing summaries
- Always state n (facilities, claims or districts) and the evidence level behind each number.
- Cite claim_ids for every facility named (grades.cite_evidence or v2 contributions), and citation_url for list facts.
- Percentages to one decimal, with numerator and denominator.
```

Sample questions shown in the UI:

- Which districts in Bihar have no corroborated dialysis?
- Which NABH-listed facilities near Patna have a nephrology service?
- What share of trauma claims is confirmed by a second source, by state?
- Which Bihar districts have the fewest facility records per million people?
- How many people live in high-need districts far from confirmed dialysis?
- Which facilities in Patna district are likely to offer dialysis?

## Example SQL queries (trusted assets)

All 13 ran on the warehouse with `space.py check` before the deploy and returned rows (the first 12 as before; 13 returned 10 rows). `check` also runs the 12 benchmark SQL queries, and all returned rows. Each sorts facilities by evidence level before distance or name.

### 1. Which districts in Bihar have no corroborated dialysis?

District with no corroborated service: use geo_dialysis_district for dialysis; report n districts, people, and that zero means no public evidence, not no care.

```sql
SELECT d.nfhs_district, ROUND(d.pop / 1e6, 2) AS pop_millions, d.n_claim AS facilities_claiming_dialysis,
  d.n_corr AS facilities_confirmed_dialysis, ROUND(100 * d.share60, 1) AS pct_people_within_60_min_confirmed, d.hot
FROM workspace.referral_saathi.geo_dialysis_district d
WHERE d.nfhs_state = 'Bihar' AND d.n_corr = 0
ORDER BY d.pop DESC
```

### 2. Which facilities with a NABH listing and a nephrology service are near Patna?

Facility list near a place: NABH is facility-level, the service comes from specialties, grades and geo_facility flags. Order by evidence level, then distance.

```sql
WITH nabh AS (
  SELECT l.unique_id, l.status AS nabh_status, l.citation_url AS nabh_citation
  FROM workspace.referral_saathi.facility_list_facts l WHERE l.list_slug = 'nabh'),
neph AS (
  SELECT s.unique_id, CONCAT_WS(', ', COLLECT_SET(s.spec)) AS nephrology_tags
  FROM workspace.referral_saathi.specialties s WHERE s.spec ILIKE '%nephro%' GROUP BY s.unique_id)
SELECT g.unique_id, g.name, g.dtname, ROUND(2 * 6371 * ASIN(SQRT(POWER(SIN(RADIANS(g.loc_lat - 25.5941) / 2), 2) + COS(RADIANS(25.5941)) * COS(RADIANS(g.loc_lat)) * POWER(SIN(RADIANS(g.loc_lon - 85.1376) / 2), 2))), 1) AS km_from_patna,
  nabh.nabh_status, nabh.nabh_citation, neph.nephrology_tags,
  gr.grade AS dialysis_text_grade, gr.cite_evidence AS dialysis_cited_claims,
  g.dialysis_corroborated, ROUND(t.overall_score, 2) AS record_trust
FROM workspace.referral_saathi.geo_facility g
JOIN nabh ON nabh.unique_id = g.unique_id
JOIN neph ON neph.unique_id = g.unique_id
LEFT JOIN workspace.referral_saathi.grades gr ON gr.unique_id = g.unique_id AND gr.service = 'dialysis'
LEFT JOIN workspace.referral_saathi.facility_trust t ON t.unique_id = g.unique_id
WHERE 2 * 6371 * ASIN(SQRT(POWER(SIN(RADIANS(g.loc_lat - 25.5941) / 2), 2) + COS(RADIANS(25.5941)) * COS(RADIANS(g.loc_lat)) * POWER(SIN(RADIANS(g.loc_lon - 85.1376) / 2), 2))) <= 50
ORDER BY g.dialysis_corroborated DESC,
  CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 ELSE 4 END,
  km_from_patna
```

### 3. What share of trauma claims is confirmed by a second source, by state?

Confirmation share: denominator is claimed facilities, numerator corroborated. Same shape for dialysis_ and csection_ flags.

```sql
SELECT g.stname, COUNT(*) AS n_trauma_claims,
  SUM(CASE WHEN g.trauma_corroborated THEN 1 ELSE 0 END) AS n_confirmed,
  ROUND(100 * SUM(CASE WHEN g.trauma_corroborated THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_confirmed
FROM workspace.referral_saathi.geo_facility g
WHERE g.trauma_claimed
GROUP BY g.stname
ORDER BY n_trauma_claims DESC
```

### 4. Show the claim sentences behind dialysis claims in Patna district

Citing claim_ids: explode grades.cite_evidence; join claims for attribution.

```sql
WITH cited AS (
  SELECT gr.unique_id, gr.grade,
    EXPLODE(FROM_JSON(gr.cite_evidence, 'array<struct<claim_id:string,field:string,text:string>>')) AS e
  FROM workspace.referral_saathi.grades gr WHERE gr.service = 'dialysis')
SELECT g.name, cited.grade, cited.e.claim_id AS claim_id, cited.e.field AS field, cited.e.text AS claim_text,
  c.attribution
FROM cited
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = cited.unique_id
LEFT JOIN workspace.referral_saathi.claims c ON c.claim_id = cited.e.claim_id
WHERE g.dtname = 'Patna'
ORDER BY CASE cited.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END, g.name
```

### 5. Which districts in Bihar have the fewest facility records per million people?

Coverage of the dataset by district; zero records means the dataset is thin there, not that care is absent.

```sql
SELECT d.dtname, ROUND(d.pop / 1e6, 2) AS pop_millions, d.records, ROUND(d.per_m, 2) AS records_per_million
FROM workspace.referral_saathi.geo_district d
WHERE d.stname = 'BIHAR'
ORDER BY d.per_m ASC, d.pop DESC
LIMIT 10
```

### 6. How many LaQshya certificates are still valid, by state?

Official list counts by state: count distinct facilities, a facility has one row per certified department.

```sql
SELECT g.stname,
  COUNT(DISTINCT CASE WHEN l.status = 'certified, valid' THEN l.unique_id END) AS facilities_valid,
  COUNT(DISTINCT CASE WHEN l.status = 'certified, expired' THEN l.unique_id END) AS facilities_with_expired,
  COUNT(DISTINCT l.unique_id) AS facilities_listed
FROM workspace.referral_saathi.facility_list_facts l
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = l.unique_id
WHERE l.list_slug = 'laqshya'
GROUP BY g.stname
ORDER BY facilities_listed DESC
```

### 7. What is the evidence for emergency C-section at each facility in Patna district?

Evidence ladder for one service in one district: grade, claimed, confirmed and which second source.

```sql
SELECT g.name, gr.grade AS text_grade, g.csection_claimed, g.csection_corroborated, g.csection_web,
  g.csection_laqshya, ROUND(t.overall_score, 2) AS record_trust, gr.cite_evidence
FROM workspace.referral_saathi.geo_facility g
LEFT JOIN workspace.referral_saathi.grades gr ON gr.unique_id = g.unique_id AND gr.service = 'csection'
LEFT JOIN workspace.referral_saathi.facility_trust t ON t.unique_id = g.unique_id
WHERE g.dtname = 'Patna' AND (g.csection_claimed OR gr.grade IS NOT NULL)
ORDER BY g.csection_corroborated DESC,
  CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 ELSE 4 END, g.name
```

### 8. Which ICUs in Patna district are confirmed on the facility's own website?

Website evidence for services other than trauma, dialysis and C-section: web_service_summary with taxonomy service_id; cite best_url.

```sql
SELECT g.name, w.web_positive_strong, w.best_quote, w.best_url, gr.grade AS text_grade, gr.cite_evidence
FROM workspace.referral_saathi.web_service_summary w
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = w.unique_id
LEFT JOIN workspace.referral_saathi.grades gr ON gr.unique_id = w.unique_id AND gr.service = 'icu'
WHERE w.service_id = 'icu' AND w.web_positive AND g.dtname = 'Patna'
ORDER BY w.web_positive_strong DESC, g.name
```

### 9. How many people live in high-need districts far from confirmed dialysis, by state?

Need against access: hot = top need quarter and under half within 60 minutes of confirmed dialysis.

```sql
SELECT d.nfhs_state, COUNT(*) AS hot_districts, ROUND(SUM(d.pop) / 1e6, 1) AS pop_millions,
  SUM(CASE WHEN d.n_corr = 0 THEN 1 ELSE 0 END) AS hot_districts_with_no_confirmed_facility
FROM workspace.referral_saathi.geo_dialysis_district d
WHERE d.hot
GROUP BY d.nfhs_state
ORDER BY pop_millions DESC
```

### 10. How are trauma claims graded in Bihar?

Grade distribution: strong and moderate rest on the facility's own sentences; tag_only is a specialty tag.

```sql
SELECT gr.grade, COUNT(*) AS n_facilities
FROM workspace.referral_saathi.grades gr
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = gr.unique_id
WHERE gr.service = 'trauma' AND g.stname = 'BIHAR'
GROUP BY gr.grade
ORDER BY CASE gr.grade WHEN 'strong' THEN 1 WHEN 'moderate' THEN 2 WHEN 'weak' THEN 3 WHEN 'tag_only' THEN 4 ELSE 5 END
```

### 11. Which facilities in Patna district are likely to offer dialysis?

Model v2 shortlist for one service and district: LIKELY then CALL_FIRST, by p. State the public-facility caveat when public rows appear.

```sql
SELECT g.name, s.band, CASE WHEN s.band <> 'NO_SERVICE_TEXT' THEN ROUND(s.p, 2) END AS p_s,
  ROUND(s.lo, 2) AS bin_confirmed_rate_lo, ROUND(s.hi, 2) AS bin_confirmed_rate_hi, s.operator, s.overlays
FROM workspace.referral_saathi.facility_service_scores_v2 s
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = s.unique_id
WHERE s.service_id = 'dialysis' AND g.dtname = 'Patna' AND s.band IN ('LIKELY', 'CALL_FIRST')
ORDER BY CASE s.band WHEN 'LIKELY' THEN 1 ELSE 2 END, s.p DESC
```

### 12. How many facilities in Bihar does the model band Likely for each service, public against private?

Band counts by owner: operator from facility_attributes_v2; ranking ability for public facilities is not demonstrated.

```sql
SELECT s.service_id, a.operator, COUNT(*) AS n_likely
FROM workspace.referral_saathi.facility_service_scores_v2 s
JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = s.unique_id
JOIN workspace.referral_saathi.facility_attributes_v2 a ON a.unique_id = s.unique_id
WHERE g.stname = 'BIHAR' AND s.band = 'LIKELY'
GROUP BY s.service_id, a.operator
ORDER BY s.service_id, a.operator
```

### 13. Which facilities near Patna are likely to have an ICU?

Service near a place: model v2 band (LIKELY, then CALL_FIRST), then straight-line km from the district centre in geo_district; cite claim ids from contributions with the claim text. Say the app adds travel time and call-ahead.

```sql
WITH c AS (SELECT cy AS lat, cx AS lon FROM workspace.referral_saathi.geo_district WHERE dtname = 'Patna' AND stname = 'BIHAR'),
near AS (
  SELECT g.unique_id, g.name, g.dtname, s.band, s.p, s.contributions, 2 * 6371 * ASIN(SQRT(POWER(SIN(RADIANS(g.loc_lat - c.lat) / 2), 2) + COS(RADIANS(c.lat)) * COS(RADIANS(g.loc_lat)) * POWER(SIN(RADIANS(g.loc_lon - c.lon) / 2), 2))) AS km
  FROM workspace.referral_saathi.facility_service_scores_v2 s
  JOIN workspace.referral_saathi.geo_facility g ON g.unique_id = s.unique_id
  CROSS JOIN c
  WHERE s.service_id = 'icu' AND s.band IN ('LIKELY', 'CALL_FIRST')),
ev AS (
  SELECT n.unique_id,
    EXPLODE(FLATTEN(TRANSFORM(FROM_JSON(n.contributions, 'array<struct<evidence_ids:array<string>>>'),
                              x -> x.evidence_ids))) AS claim_id
  FROM near n WHERE n.km <= 50)
SELECT n.name, n.dtname AS district, n.band, ROUND(n.p, 2) AS p_s, ROUND(n.km, 1) AS km_straight_line,
  ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(cl.claim_id)), ', ') AS claim_ids, MIN_BY(cl.text, cl.claim_id) AS claim_text
FROM near n
LEFT JOIN ev e ON e.unique_id = n.unique_id
LEFT JOIN workspace.referral_saathi.claims cl ON cl.claim_id = e.claim_id AND cl.attribution <> 'other_facility'
WHERE n.km <= 50
GROUP BY n.unique_id, n.name, n.dtname, n.band, n.p, n.km
ORDER BY CASE n.band WHEN 'LIKELY' THEN 1 ELSE 2 END, n.km
LIMIT 10
```

## Test results

Seven questions asked through the Conversation API (`genie start-conversation`) on 2026-11-21 (re-run after the v2 update; tests 1 to 6 gave the same answers as before), each compared with our own SQL. The check is automatic (`test_space.py`) and I read every answer: the pass/fail column is the automatic one, and the honesty column is my reading of Genie's text.

| # | Question | Our SQL says | Genie returned | Numbers | Honesty rules in the text |
|---|---|---|---|---|---|
| 1 | How many districts in Uttar Pradesh have no confirmed dialysis facility, and how many people live in them? | 54, 149.5 | 1 rows: 54, 149.54 | pass | States n (54 districts, 149.54 M people), names the evidence level, says "no public evidence" |
| 2 | Among states with at least 100 trauma or emergency claims, which has the lowest share confirmed by a second source? | GUJARAT, 281, 38.8 | 1 rows: GUJARAT, 281, 109, 38.8 | pass | Gives 109 of 281 and 38.8%, says it is public evidence from the records |
| 3 | Cite the claim ids behind the dialysis claim of Ford Hospital And Research Center in Patna. | e8396ece:equi:5 | 1 rows: Ford Hospital And Research Center, strong, e8396ece:equi:5, equipment, Dialysis unit, unanchored | pass | Cites claim id e8396ece:equi:5, grade strong, attribution unanchored |
| 4 | How many facilities in Maharashtra hold a LaQshya certificate that is still valid? | 2 | 1 rows: 2 | pass | Says it is list evidence, not a verified fact |
| 5 | Which Bihar districts have zero facility records? | Araria; Arwal; Banka; Jamui; Jehanabad; Lakhisarai; Sheohar | 7 rows: Araria, 4.12, 0; Jamui, 2.51, 0; Banka, 2.46, 0 ... | pass | Names 5 of 7 in the text, says all 7 and "no public evidence in this dataset, not a statement about actual facility presence" |
| 6 | Is there dialysis care in Madhubani district of Bihar? | 0, 0 | 1 rows: Madhubani, 5.95, 0, 0, 0.5, false | pass | Says 0 claimed and 0 confirmed and "no public evidence in this dataset", never "no care" |
| 7 | How many facilities in Bihar does model v2 band Likely for dialysis? | 36 | 3 rows: private 27, public 4, unknown 5 | pass | States 36 and the split, says they are claims; reads facility_service_scores_v2 joined to facility_attributes_v2. No public-facility caveat (it counts, it does not rank) |

Result: 7 of 7 pass on numbers, and all 7 answers follow the honesty rules.

Limits of this test, stated plainly:

- Seven questions is a smoke test, not a benchmark. Tests 3 and 6 reused an example query almost verbatim (the claim-citation and Bihar dialysis shapes), so they show the examples are picked up, not that Genie generalises. Tests 1, 2, 4 and 5 changed the state, threshold, list or filter, and Genie adapted the examples into new SQL that matched our ground truth.
- The benchmark run (12 questions, section "Benchmark accuracy") supersedes this smoke test as the accuracy figure.
- The honesty column is my judgement of the text; the automatic check only bans phrases such as "no dialysis care available".
- Genie's summary sometimes names a column ("evidence level: n_corr = 0") instead of plain words. A planner-facing wording pass on the instructions would fix that.
