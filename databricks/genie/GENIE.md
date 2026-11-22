# Genie space: Referral Saathi planner

A Genie space (Genie Agent) for district health planners, over 10 tables in `workspace.referral_saathi`. It answers questions about where facilities show public evidence of a service and how strong that evidence is, following the project's honesty rules.

## Space

- Space id: `01f1e60264ac19f98063e082b625c2df`
- URL: https://dbc-ea4e0abe-8cd4.cloud.databricks.com/genie/rooms/01f1e60264ac19f98063e082b625c2df (standard Genie room link built from the id; the space was read back with `databricks genie get-space`, the link was not opened in a browser)
- Warehouse: `6a2f5637720a2c17`, profile `vf`. Parent folder: the profile user's workspace home.
- Created on 2026-11-21 by `space.py deploy`. Read back: 10 tables, 10 example SQL queries, 7 join specs, 1 text instruction, 5 sample questions.

Description shown in Genie:

> For district health planners in India: where facilities show public evidence of a service (trauma or 24x7 emergency, dialysis, emergency C-section, ICU, NICU, MRI and more), how strong that evidence is (dataset claim, text grade, facility website, OpenStreetMap, official lists such as NABH, LaQshya, NMC and the MoHFW trauma list), and which districts have none. Built on the Virtue Foundation records (9,959 facilities, 88% private). Every answer is about evidence, not about care that exists.

## Files

| File | What |
|---|---|
| `space.py` | The whole space as code: tables with column descriptions, synonyms, entity matching and hidden columns; text instructions; example SQL; join specs; sample questions. `check` runs every example SQL, `build` writes `genie_space.json`, `deploy` checks, builds and creates the space, or updates it when `space_id.txt` exists |
| `genie_space.json` | The `serialized_space` payload that was sent |
| `space_id.txt` | Id of the live space; makes `deploy` an update |
| `test_space.py` | Asks the 6 test questions through the Conversation API and compares with our SQL |
| `test_results.json` | Full test output: question, ground-truth SQL and rows, Genie's SQL, rows and text |

Re-run from the project root:

```
export DATABRICKS_CONFIG_PROFILE=vf
python3 databricks/genie/space.py check     # read-only
python3 databricks/genie/space.py deploy    # updates the live space in place
cd databricks/genie && python3 test_space.py
```

When `derived/v2` is loaded under the same table names, the space needs no change; re-run `check` and the tests.

## Tables

- `claims`: One row per claim sentence (469,498): the text and attribution behind each claim_id.
- `facility_list_facts`: 3,062 per-facility matched facts from NABH, LaQshya, NMC, MoHFW trauma, e-RaktKosh and Goa PMNDP, each with citation_url.
- `facility_trust`: One row per facility: existence, location and overall record scores with plain-English drivers.
- `geo_dialysis_district`: One row per NFHS-5 district (704): dialysis need proxy, claimed and confirmed counts, share within 60 minutes, hot flag.
- `geo_district`: One row per LGD district (784, including the 227 with no records): population, records, records per million.
- `geo_facility`: One row per facility record (9,959): LGD state and district, NFHS keys, point, owner, type, and the claimed / confirmed / per-source flags for trauma or 24x7 emergency, dialysis and emergency C-section.
- `grades`: One row per (facility, service) the text mentions (10,799): text evidence grade and cite_evidence, the claim_ids behind it.
- `services`: The 37-service taxonomy, with aliases that map old ids (trauma, csection, burns) to taxonomy ids.
- `specialties`: One row per (facility, specialty tag): the weakest evidence, used for nephrology and similar departments.
- `web_service_summary`: One row per (facility, service) the facility's own website states, with best quote and URL.

Joins (declared as join specs): `geo_facility.unique_id` to `grades`, `facility_trust` (1:1), `facility_list_facts`, `specialties`, `web_service_summary` and `claims`; `geo_facility (nfhs_state, nfhs_district)` to `geo_dialysis_district`. All 9,959 facility rows match a `geo_dialysis_district` row, and its `n_claim` and `n_corr` equal the sums of the `geo_facility` dialysis flags in all 704 districts (checked with SQL on 2026-11-21).

Column configs: descriptions on the evidence columns, entity matching and format assistance on state, district, service, grade, list and status columns, and hidden grid, raw-name and JSON columns.

## General instructions (as sent)

These encode the honesty rules: every row is a claim with an evidence level, report n and the level, say "no public evidence" rather than "no care", never rank on unverified claims alone, cite claim_ids. 1542 characters, under the 2,000 limit.

```
## PURPOSE
- District planners asking where facilities show public evidence of a service and how strong it is.
- Every row is a claim from the Virtue Foundation records (88% private), not a verified fact.

## DISAMBIGUATION
- "Confirmed", "corroborated" or "second source" means the *_corroborated flags in geo_facility or n_corr in geo_dialysis_district. "Claims" means *_claimed or grades rows.
- "Trauma" in geo_facility and grades means trauma or 24x7 emergency.
- "Near X" with no radius: 50 km straight line from the facility point; say so.
- geo_facility and geo_district states are UPPER CASE (BIHAR); NFHS tables use title case (Bihar).

## DATA QUALITY NOTES
- NABH rows are facility-level (service null): a NABH listing confirms the facility, not a service.
- citation_url of '#' or 'Not Found' means no usable link.
- operatorTypeId uses the string 'null' for unknown owner.

## CONSTRAINTS
- Never rank or recommend facilities on dataset claims alone. Order by evidence level first (official list or confirmed, then grade strong, moderate, weak, tag_only), then distance, and show the level.
- Never say a place has "no care" or "no facility". Say "no public evidence in this dataset" and give n.

## Instructions you must follow when providing summaries
- Always state n (facilities, claims or districts) and the evidence level behind each number.
- When naming a facility-service claim, cite claim_ids from grades.cite_evidence, and citation_url for list facts.
- Give percentages to one decimal with numerator and denominator.
```

Sample questions shown in the UI:

- Which districts in Bihar have no corroborated dialysis?
- Which NABH-listed facilities near Patna have a nephrology service?
- What share of trauma claims is confirmed by a second source, by state?
- Which Bihar districts have the fewest facility records per million people?
- How many people live in high-need districts far from confirmed dialysis?

## Example SQL queries (trusted assets)

All 10 ran on the warehouse with `space.py check` before the deploy and returned rows (34, 19, 33, 61, 10, 24, 7, 39, 18 and 4 rows). Each sorts facilities by evidence level before distance or name.

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

## Test results

Six questions asked through the Conversation API (`genie start-conversation`) on 2026-11-21, each compared with our own SQL. The check is automatic (`test_space.py`) and I read every answer: the pass/fail column is the automatic one, and the honesty column is my reading of Genie's text.

| # | Question | Our SQL says | Genie returned | Numbers | Honesty rules in the text |
|---|---|---|---|---|---|
| 1 | How many districts in Uttar Pradesh have no confirmed dialysis facility, and how many people live in them? | 54, 149.5 | 1 rows: 54, 149.54 | pass | States n (54 districts, 149.54 M people), names the evidence level, says "no public evidence" |
| 2 | Among states with at least 100 trauma or emergency claims, which has the lowest share confirmed by a second source? | GUJARAT, 281, 38.8 | 1 rows: GUJARAT, 281, 109, 38.8 | pass | Gives 109 of 281 and 38.8%, says it is public evidence from the records |
| 3 | Cite the claim ids behind the dialysis claim of Ford Hospital And Research Center in Patna. | e8396ece:equi:5 | 1 rows: Ford Hospital And Research Center, strong, e8396ece:equi:5, equipment, Dialysis unit, unanchored | pass | Cites claim id e8396ece:equi:5, grade strong, attribution unanchored |
| 4 | How many facilities in Maharashtra hold a LaQshya certificate that is still valid? | 2 | 1 rows: 2 | pass | Says it is list evidence, not a verified fact |
| 5 | Which Bihar districts have zero facility records? | Araria; Arwal; Banka; Jamui; Jehanabad; Lakhisarai; Sheohar | 7 rows: Araria, 4.12, 0; Jamui, 2.51, 0; Banka, 2.46, 0 ... | pass | Names 5 of 7 in the text, says all 7 and "no public evidence in this dataset, not a statement about actual facility presence" |
| 6 | Is there dialysis care in Madhubani district of Bihar? | 0, 0 | 1 rows: Madhubani, 5.95, 0, 0, 0.5, false | pass | Says 0 claimed and 0 confirmed and "no public evidence in this dataset", never "no care" |

Result: 6 of 6 pass on numbers, and all 6 answers follow the honesty rules.

Limits of this test, stated plainly:

- Six questions is a smoke test, not a benchmark. Tests 3 and 6 reused an example query almost verbatim (the claim-citation and Bihar dialysis shapes), so they show the examples are picked up, not that Genie generalises. Tests 1, 2, 4 and 5 changed the state, threshold, list or filter, and Genie adapted the examples into new SQL that matched our ground truth.
- No benchmark set is attached to the space yet, so `genie-create-eval-run` was not run.
- The honesty column is my judgement of the text; the automatic check only bans phrases such as "no dialysis care available".
- Genie's summary sometimes names a column ("evidence level: n_corr = 0") instead of plain words. A planner-facing wording pass on the instructions would fix that.
