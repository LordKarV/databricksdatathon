# District planner dashboard (Databricks AI/BI) spec

A read-only AI/BI dashboard for district planners and NGO coordinators, built from the storybook
(`viz/STORYBOOK.md`, `viz/gallery.json`). It answers four questions for a chosen state, district and
service: how thin is the evidence here, how far are people from confirmed care, what do the records
claim against what anyone confirmed, and which records should be checked by phone before anyone is
sent there. A fifth page shows the referral planner's sample journeys and a sixth says how far to trust
the scores.

Status: spec only. No table has been loaded and no SQL here has been run on a warehouse. Column names
were checked against the local parquet and CSV files listed below on 2026-11-21, and several tile
numbers were checked locally with duckdb (noted per tile).

## Conventions

- Tables are named `workspace.<schema>.<table>`; the schema is TBD (MODEL_SPEC 3.6 proposes
  `vf_ledger`). In the serialized dashboard JSON, write bare table names (`FROM facility_location`) and
  pass `--dataset-catalog workspace --dataset-schema <schema>` to `databricks lakeview create`; the
  prefixed names below are for reading.
- Every dataset exposes the filter columns under the same names: `state` (upper case, LGD spelling,
  for example `BIHAR`), `district` (upper case LGD district of the facility's cleaned ranking point),
  and `service` (one of `trauma_emergency`, `dialysis`, `emergency_csection`, `nicu`,
  `cardiac_surgery`, `mri`, `burn_care`). A filter only acts on datasets that carry its column; tiles
  that do not are marked "national".
- Facility-level datasets take `state` and `district` from `geo_facility` (LGD point-in-polygon on the
  cleaned point), not from `facility_location.district`, so they match the district tables. 
- Rates are stored 0 to 1 and formatted `number-percent`. Every rate tile shows its 95% interval:
  Wilson for proportions computed in SQL, or the interval columns the stories already computed.
  Bar charts with whiskers use `custom-vega-viz` (Vega-Lite `bar` + `rule`), since the standard bar
  widget draws no intervals.
- Wilson 95% interval in Spark SQL for `k` successes in `n`:

```sql
(k/n + 1.9208/n - 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS lo,
(k/n + 1.9208/n + 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS hi
```

- Small n: any rate with `n < 30` is shown with a "small sample" note in the tile description (same
  threshold as `viz/style.py`).
- No maps with outlines. Do not use `choropleth-map` (it draws state and district outlines) or
  `symbol-map` (its basemap draws national boundaries that may not follow the Survey of India, see
  `external/lgd_district_polygons/README.md`). Facility locations are shown as a `scatter` of longitude
  against latitude with no basemap, or as tables.
- Theme: `visualizationColors` = the `viz/style.py` categorical tokens in order
  (`#2a78d6`, `#eb6834`, `#1baf7a`, `#eda100`, `#e87ba4`, `#008300`); semantic colours pinned as literal
  hex for evidence states (`Likely #6da7ec`, `Unverified #c3c2b7`, `Unlikely #e34948`, flags
  `#eda100`); canvas `#fcfcfb`, font `#0b0b0b`.
- Every page carries a text widget with its caveat; the shared one is: "A record is a listing in one
  private-leaning dataset (88% private). No evidence here is not no care."

## Tables

### A. Load as-is (exist as parquet today)

| Table | Source file | Rows | Used by |
|---|---|---|---|
| `facility_location` | `derived/v1/facility_location.parquet` | 9,959 | pages 1, 3, 4 |
| `record_trust` | `derived/v1/record_trust.parquet` | 9,959 | pages 1, 4 |
| `claims` | `derived/v1/claims.parquet` | 469,498 | page 4 |
| `grades` | `derived/v1/grades.parquet` | 10,799 | page 4 |
| `pair_scores` | `model/proto/fusion/pair_scores.parquet` | 69,713 | pages 3, 6 |
| `pair_features` | `model/proto/evidence/pair_features.parquet` | 69,713 | page 3 |
| `facility_scores` | `model/proto/fusion/facility_scores.parquet` | 9,959 | page 3 |

`record_trust.trust_flags` and `scale_flags` are arrays (`array<string>`); use `array_contains`.

### B. Load from the storybook outputs (files exist, not yet tables)

| Table | Source file | Rows | Story |
|---|---|---|---|
| `geo_facility` | `viz/geography/data/_cache/facilities.parquet` (unique_id, stname, dtname, degurba, per-service claimed / corroborated flags) | 9,959 | geography 1-6 |
| `geo_state_density` | `viz/geography/data/s1_state.csv` | 36 | geography 1 |
| `geo_state_access` | `viz/geography/data/s4_state.csv` (columns `any` and `map` are reserved words: backtick them) | 36 | geography 4 |
| `geo_district` | `viz/geography/data/s1_district.csv` | 784 | geography 1 |
| `geo_dialysis_district` | `viz/geography/data/s2_district.csv` (NFHS district keys) | 704 | geography 2 |
| `geo_csection_district` | `viz/geography/data/s3_district.csv` (NFHS district keys) | 704 | geography 3 |
| `geo_settlement` | `viz/geography/data/s5_classes.csv` | 3 | geography 5 |
| `dialysis_burden_district` | `viz/journeys/data/s5_district_dialysis.csv` | 784 | journeys 5 |
| `claims_funnel_pairs` | `viz/claims/data/s3_pairs.csv` | 9,244 | claims 3 |
| `facility_hours` | `viz/claims/data/s6_facility_hours.csv` | 9,959 | claims 6 |
| `pmndp_state` | `viz/claims/data/s4_pmndp.csv` (state in lower case) | per state | claims 4 |
| `planner_plans` | `viz/journeys/data/plans_best.csv` | 3,430 | journeys 1, 2, 6 |

The `geo_*` CSVs are aggregates and may be loaded. `geo_facility` is record-level Virtue Foundation
data: team workspace only, as for every derived table.

### C. Not built yet (tiles that need them are marked)

| Table | What it needs | Blocks |
|---|---|---|
| `model_test_metrics` | A long table (system, view, auroc, lo, hi, ece) flattened from `model/review/stats/results.json` and `model/proto/fusion/test_metrics.json` | tile 6.2 |
| `facility_list_facts` | One row per (facility, list, service) from the matcher outputs in `data/external/<slug>/`, with valid_to and source URL | tile 3.4 |
| `nfhs_lgd_crosswalk` | `data/external/lgd_district_polygons/nfhs_lgd_crosswalk.csv`, so NFHS-keyed tables filter by LGD district | district filter on tiles 2.3, 2.4 |

Licence note for `facility_list_facts`: NABH, NMC and MoHFW lists may be shown as per-facility facts
with a citation, never as a list (`research/DATASETS.md`). Tiles may show counts and the matched
facility's own row with its source link; never a table of list entries without a dataset record.

## Filters (global filter page, `PAGE_TYPE_GLOBAL_FILTERS`)

| Filter | Widget | Field | Notes |
|---|---|---|---|
| State | `filter-multi-select` | `state` | Default `BIHAR` (the demo state) |
| District | `filter-multi-select` | `district` | Cascades from state through the shared datasets |
| Service | `filter-single-select` | `service` | Default `dialysis`; acts on pages 3 and 6 only |

## Page 1. District at a glance

Story: geography 1 (Bihar, 1.9 records per million), trust 1 and 2.

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 1.1 Records here | counter | `ds_facility` | state, district |
| 1.2 Records with a high-confidence location | counter (percent) | `ds_facility` | state, district |
| 1.3 Records that name another facility | counter (percent) | `ds_facility` | state, district |
| 1.4 Records per million people by state, 95% Poisson interval | custom-vega-viz bar + rule, highlight selected state | `ds_state` | national |
| 1.5 Districts in the state: people, records, records per million, "no record" flag | table | `ds_district` | state, district |
| 1.6 Facility points by location confidence (lon x, lat y, no basemap) | scatter, colour = `loc_conf` | `ds_facility` | state, district |

```sql
-- ds_facility: one row per record
SELECT g.stname AS state, upper(g.dtname) AS district, l.unique_id, l.name,
       l.loc_lat, l.loc_lon, l.loc_conf, l.loc_note, l.raw_coords_to_pin_km,
       CASE WHEN l.loc_conf = 'high' THEN 1 ELSE 0 END AS is_high_conf,
       CASE WHEN l.raw_coords_to_pin_km > 50 THEN 1 ELSE 0 END AS pin_far,
       CASE WHEN m.unique_id IS NOT NULL THEN 1 ELSE 0 END AS names_other_facility,
       CASE WHEN array_contains(r.trust_flags, 'official_phone_is_directory') THEN 1 ELSE 0 END AS directory_phone,
       r.trust_level, r.website_class, g.degurba
FROM workspace.<schema>.facility_location l
JOIN workspace.<schema>.geo_facility g USING (unique_id)
JOIN workspace.<schema>.record_trust r USING (unique_id)
LEFT JOIN (SELECT DISTINCT unique_id FROM workspace.<schema>.claims WHERE context = 'direct') m
  USING (unique_id)
```

Tiles 1.2 and 1.3 use `AVG(is_high_conf)` and `AVG(names_other_facility)`; the description shows n.
National check (local duckdb): 7,762 of 9,959 high, 1,232 name another facility, 292 directory
phones.

```sql
-- ds_state: one row per state or UT
SELECT d.stname AS state, d.label, d.pop / 1e6 AS pop_m, d.records,
       d.per_m, d.per_m_lo, d.per_m_hi,
       d.child_u5_who_are_stunted_height_for_age_18_pct / 100 AS stunting,
       a.corr AS share_60_confirmed_trauma, a.corr_lo, a.corr_hi,
       a.`any` AS share_60_any_record, a.`map` AS share_60_any_clinic,
       a.people_outside_corr / 1e6 AS people_outside_m, a.n_corr
FROM workspace.<schema>.geo_state_density d
JOIN workspace.<schema>.geo_state_access a USING (stname)
WHERE d.pop >= 1e6
ORDER BY d.per_m DESC
```

Check: Bihar per_m 1.95 (1.72 to 2.20), 260 records, 133.5 M people.

```sql
-- ds_district: one row per LGD district (784)
SELECT stname AS state, upper(dtname) AS district, dist_lgd, pop / 1e6 AS pop_m, records, per_m,
       CASE WHEN records = 0 THEN 'no record' ELSE '' END AS no_record_flag
FROM workspace.<schema>.geo_district
ORDER BY per_m ASC
```

## Page 2. Access to confirmed care

Stories: geography 4 (golden hour), 2 (dialysis need), 3 (C-section), 5 (urban/rural); journeys 5.

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 2.1 Share within 60 minutes of confirmed trauma care, by state, with route-error whisker; dots for any record and any clinic | custom-vega-viz | `ds_state` | national; highlight state |
| 2.2 People more than an hour from confirmed trauma care, by state (millions) | bar | `ds_state` | national |
| 2.3 High-need districts more than an hour from confirmed dialysis (69 nationally, 104 M people) | table | `ds_dialysis_district` | state (district needs `nfhs_lgd_crosswalk`) |
| 2.4 Districts where under 10% of births are caesareans: dataset claims vs LaQshya theatres | table | `ds_csection_district` | state (district needs crosswalk) |
| 2.5 Weekly road km for three dialysis sessions, by district and evidence tier | table | `ds_dialysis_burden` | state, district |
| 2.6 Within an hour of confirmed care, by settlement class and service | bar (grouped) | `ds_settlement` | national |
| 2.7 Public dialysis centres (PMNDP) against public records that mention dialysis | table | `ds_pmndp` | state |

```sql
-- ds_dialysis_district
SELECT upper(nfhs_state) AS state, upper(nfhs_district) AS district, pop / 1e6 AS pop_m,
       ncd / 100 AS need_proxy, burden_q, n_claim, n_corr, corr_per_m, corr_per_m_lo, corr_per_m_hi,
       share60, median_min, hot
FROM workspace.<schema>.geo_dialysis_district
ORDER BY hot DESC, share60 ASC
```

Check: `hot` is true for 69 districts with 103.8 M people. `ncd` is stored in percent (9.4 to 37.7),
hence the division by 100.

```sql
-- ds_csection_district
SELECT upper(nfhs_state) AS state, upper(nfhs_district) AS district, wra / 1e6 AS women_15_49_m,
       births_delivered_by_csection_5y_pct / 100 AS csection_rate, band,
       n_claimed, n_corroborated, n_laqshya
FROM workspace.<schema>.geo_csection_district
WHERE band IN ('under 5%', '5-10%')
ORDER BY csection_rate ASC
```

Check: 152 districts in the two bands (39 + 113).

```sql
-- ds_dialysis_burden
SELECT upper(state) AS state, upper(district) AS district, population / 1e6 AS pop_m,
       median_weekly_km_claimed, median_weekly_km_graded, median_weekly_km_corroborated,
       median_weekly_hours_corroborated
FROM workspace.<schema>.dialysis_burden_district
WHERE road_estimate_valid
ORDER BY median_weekly_km_corroborated DESC
```

```sql
-- ds_settlement (3 rows)
SELECT cls, pop_share, records_share,
       trauma_within60, dialysis_within60, csection_within60
FROM workspace.<schema>.geo_settlement
```

```sql
-- ds_pmndp
SELECT upper(state) AS state, nhsrc_functional_centres AS pmndp_centres,
       nhsrc_functional_districts AS pmndp_districts, vf_records, vf_dialysis, vf_public_dialysis
FROM workspace.<schema>.pmndp_state
```

PMNDP spellings differ from LGD for a few states ("jammu and kashmir", "the dadra and nagar haveli and
daman and diu", "andaman and nicobar islands"); add a small mapping on load so they join the state
filter.

Caveats on this page: drive times are free-flow over the MAP 2020 friction surface; the whisker is
measured route error (34 to 85 minutes), not sampling error; the need proxy is risk, not kidney-failure
counts; PMNDP is a state count, not a list of locations.

## Page 3. Services: claimed against confirmed

Stories: claims 3 (funnel), claims 4 (lists), claims 6 (hours), geography 6 (website effect).

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 3.1 Evidence ladder: mentioned, 2+ fields, plus prerequisite, plus outside check | funnel or bar | `ds_funnel` | state, district, service |
| 3.2 Facilities for the service, ranked by P_S, with range, location score, text level, website, location confidence | table | `ds_service_facilities` | state, district, service |
| 3.3 Records with any stated hours; with a 24x7 emergency statement | counter (percent) x 2 | `ds_hours` | state, district |
| 3.4 Official list facts for listed facilities (NABH, LaQshya, MoHFW, e-RaktKosh, NMC) | table | needs `facility_list_facts` | state, district, service |

```sql
-- ds_funnel: one row per (record, service) with any mention or outside evidence
SELECT g.stname AS state, upper(g.dtname) AS district, p.service,
       CAST(p.mentioned AS INT) AS mentioned,
       CAST(p.mentioned AND p.fields2 AS INT) AS in_2plus_fields,
       CAST(p.mentioned AND p.fields2 AND p.prereq AS INT) AS own_checks,
       CAST(p.mentioned AND (p.web OR p.listed) AS INT) AS outside_check,
       CAST(p.mentioned AND p.fields2 AND p.prereq AND (p.web OR p.listed) AS INT) AS own_and_outside,
       CAST(NOT p.mentioned AND (p.web OR p.listed) AS INT) AS outside_not_mentioned
FROM workspace.<schema>.claims_funnel_pairs p
JOIN workspace.<schema>.geo_facility g USING (unique_id)
```

Check (national, all services): mentioned 7,969; own checks 1,798; own checks and outside 837, as in
claims story 3. The funnel bars use `SUM(...)`; the description repeats that the website step only
counts where a site was found.

```sql
-- ds_service_facilities: one row per (record, service)
SELECT g.stname AS state, upper(g.dtname) AS district, s.service, s.unique_id, s.name,
       s.p_s, s.p_s_lo, s.p_s_hi, s.band, s.T AS text_level, s.p_l, s.p_e,
       l.loc_conf, r.website_class, r.display_phones
FROM workspace.<schema>.pair_scores s
JOIN workspace.<schema>.geo_facility g USING (unique_id)
JOIN workspace.<schema>.facility_location l USING (unique_id)
JOIN workspace.<schema>.record_trust r USING (unique_id)
WHERE s.T > 0 OR s.p_s >= 0.3
ORDER BY s.p_s DESC
```

Column labels on the table: `p_s` is "chance a public check confirms it (runs high)"; `p_l` is
"location score (0.7 or more was right 30 of 33 times)". Show `band` as text, not as a probability.

```sql
-- ds_hours
SELECT g.stname AS state, upper(g.dtname) AS district, h.unique_id,
       CASE WHEN h.dataset_any_hours OR h.web_any_hours OR h.osm_any_hours THEN 1 ELSE 0 END AS any_hours,
       CASE WHEN h.dataset_emerg24 OR h.web_emerg24 OR h.osm_emerg24 THEN 1 ELSE 0 END AS emergency_24x7,
       CASE WHEN h.dataset_schedule OR h.web_schedule OR h.osm_schedule THEN 1 ELSE 0 END AS clock_schedule
FROM workspace.<schema>.facility_hours h
JOIN workspace.<schema>.geo_facility g USING (unique_id)
```

National check from claims story 6: any hours 6,074 of 9,959; 24x7 emergency 2,829; schedule 2,808.

## Page 4. Records to check by phone

Stories: trust 1, 2, 4 (bench), 6.

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 4.1 Map pin 50+ km from its postcode | counter (percent) | `ds_facility` | state, district |
| 4.2 Location confidence mix (high / medium / low / disputed) | bar | `ds_facility` | state, district |
| 4.3 Directory phone hidden | counter | `ds_facility` | state, district |
| 4.4 What cleaning fixed, flagged, could not fix | bar (grouped by status) | `ds_cleaning` | state, district |
| 4.5 Records to call first: far pin, disputed or low location, or names another facility | table | `ds_facility` | state, district |

```sql
-- ds_cleaning: one row per record with the "cannot fix" components (trust story 6)
WITH quar AS (SELECT DISTINCT unique_id FROM workspace.<schema>.claims WHERE attribution = 'other_facility'),
anon AS (SELECT DISTINCT c.unique_id FROM workspace.<schema>.claims c JOIN quar USING (unique_id)
         WHERE c.attribution = 'unanchored' AND coalesce(c.services, '') <> ''),
direct AS (SELECT DISTINCT unique_id FROM workspace.<schema>.claims WHERE context = 'direct'),
trunc AS (SELECT DISTINCT unique_id FROM workspace.<schema>.grades WHERE coalesce(truncated, false))
SELECT g.stname AS state, upper(g.dtname) AS district, l.unique_id,
       CASE WHEN l.loc_src <> 'listing_coordinates' THEN 1 ELSE 0 END AS fixed_corrected_point,
       CASE WHEN q.unique_id IS NOT NULL THEN 1 ELSE 0 END AS fixed_quarantined_text,
       CASE WHEN l.loc_conf IN ('low', 'disputed') THEN 1 ELSE 0 END AS flagged_location,
       CASE WHEN size(r.scale_flags) > 0 THEN 1 ELSE 0 END AS flagged_size,
       CASE WHEN a.unique_id IS NOT NULL OR d.unique_id IS NOT NULL OR t.unique_id IS NOT NULL
            THEN 1 ELSE 0 END AS cannot_fix,
       CASE WHEN r.trust_level = 'no_concerns' THEN 1 ELSE 0 END AS rated_no_concerns
FROM workspace.<schema>.facility_location l
JOIN workspace.<schema>.geo_facility g USING (unique_id)
JOIN workspace.<schema>.record_trust r USING (unique_id)
LEFT JOIN quar q USING (unique_id)
LEFT JOIN anon a USING (unique_id)
LEFT JOIN direct d USING (unique_id)
LEFT JOIN trunc t USING (unique_id)
```

Check (national, local duckdb with the same logic): `cannot_fix` 2,610 of 9,959; `rated_no_concerns`
7,812; both 1,589. Tile 4.4 description: "bars overlap; 'no concerns' covers location and contact data
only".

## Page 5. Referral journeys (planner sample, stub probabilities)

Stories: journeys 1, 2, 6. Data exists only for 150 sampled PIN origins per state in Bihar, Uttar
Pradesh and Maharashtra plus the 40 benchmark points; the page says so in its header and the state
filter shows "no sample" elsewhere.

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 5.1 Definitive care within 60 minutes, by pathway, 95% Wilson interval | custom-vega-viz bar + rule | `ds_plans_window` | state |
| 5.2 Best plan type by pathway (direct, one stop, abstain, ...) | bar (stacked, 100%) | `ds_plans` | state |
| 5.3 Share of origins sent to the most-chosen definitive facility, by pathway | table | `ds_plans_concentration` | state |

```sql
-- ds_plans: one row per (origin, pathway) in the three sampled states
SELECT state, pathway, origin_id, best_type, first_name, first_eta, def_name, def_eta,
       def_low, def_high, p_objective,
       CASE WHEN def_eta <= 60 THEN 1 ELSE 0 END AS definitive_within_60,
       CASE WHEN first_eta <= 60 THEN 1 ELSE 0 END AS first_care_within_60
FROM workspace.<schema>.planner_plans
WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra')
```

```sql
-- ds_plans_window: abstaining origins stay in the denominator (def_eta is null for them)
WITH t AS (
  SELECT state, pathway, SUM(CASE WHEN def_eta <= 60 THEN 1 ELSE 0 END) AS k, COUNT(*) AS n
  FROM workspace.<schema>.planner_plans
  WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra')
  GROUP BY state, pathway)
SELECT state, pathway, k, n, k / n AS rate,
       (k/n + 1.9208/n - 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS lo,
       (k/n + 1.9208/n + 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS hi
FROM t
```

Check: Bihar major trauma 15 of 150 (10%), as in journeys story 2.

```sql
-- ds_plans_concentration
WITH c AS (
  SELECT state, pathway, def_name, COUNT(*) AS origins,
         SUM(COUNT(*)) OVER (PARTITION BY state, pathway) AS planned
  FROM workspace.<schema>.planner_plans
  WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra') AND def_name IS NOT NULL
  GROUP BY state, pathway, def_name),
r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY state, pathway ORDER BY origins DESC) AS rk FROM c)
SELECT state, pathway, def_name AS top_facility, origins, planned, origins / planned AS share
FROM r WHERE rk = 1
```

Check (local duckdb): Bihar obstetric emergency 81 of 131 to Sub Divisional Hospital Pusa and major
trauma 79 of 134 to Rajeshwar Hospital, as in journeys story 6 (abstaining origins excluded).

Header text: "Probabilities come from the derived/v1 stub (`planner/data_v1.py`), not the fitted
model. Free-flow travel, no dispatch delay. The PIN sample is not weighted by population."

## Page 6. How far to trust the scores

Stories: model 3, 4, 5; geography 6.

| Tile | Widget | Dataset | Filters |
|---|---|---|---|
| 6.1 Badges for the service: Likely / Unverified / Unlikely | bar | `ds_bands` | state, district, service |
| 6.2 Published sealed-test results: ledger, expert priors, LLM judge, any mention (AUROC with interval); ECE | table | needs `model_test_metrics` | national |
| 6.3 What the labels were: confirmed 17, contradicted 1, searched with nothing 21, never searched 32 (of 71) | text or table from `model_test_metrics` | needs `model_test_metrics` | national |
| 6.4 Records with a crawlable own website, by operator and settlement class | bar | `ds_website` | state, district |

```sql
-- ds_bands
SELECT g.stname AS state, upper(g.dtname) AS district, s.service, s.band, COUNT(*) AS pairs
FROM workspace.<schema>.pair_scores s
JOIN workspace.<schema>.geo_facility g USING (unique_id)
GROUP BY g.stname, upper(g.dtname), s.service, s.band
```

Check: nationally 37,108 Unlikely, 32,603 Unverified, 2 Likely. The tile text says why Likely is
almost empty (MODEL_SPEC: P_S runs high and the badge needs confirmation).

```sql
-- ds_website: crawlable own site, from geography story 6 flags
SELECT g.stname AS state, upper(g.dtname) AS district, g.unique_id, g.degurba,
       CASE WHEN g.operatorTypeId IN ('public', 'government') THEN 'Public'
            WHEN g.operatorTypeId = 'private' THEN 'Private' ELSE 'Not stated' END AS operator
FROM workspace.<schema>.geo_facility g
```

Tile 6.4 needs the crawl's own-site flag per record (`own_site`), which is in
`viz/geography/verify/out/records.parquet` but not in the `_cache/facilities.parquet` file loaded as
`geo_facility`. Either load `records.parquet` as `geo_facility_site` or add `own_site` to the
`geo_facility` load. Until then 6.4 is blocked. `operatorTypeId` in the cache is private 8,805,
public 465, government 2, null 687 (checked locally).

## Tiles that need data not yet in tables

| Tile | Missing | Fix |
|---|---|---|
| 2.3, 2.4 district filter | NFHS to LGD district keys | load `nfhs_lgd_crosswalk` and join on (state, NFHS district) |
| 3.4 | per-facility list facts | build `facility_list_facts` from `data/external/<slug>/` matcher outputs; per-facility with citation only |
| 6.2, 6.3 | published test metrics | flatten `results.json` and `test_metrics.json` into `model_test_metrics` (quote only, no recompute) |
| 6.4 | own-site flag | load `viz/geography/verify/out/records.parquet` or extend `geo_facility` |
| all `geo_*` and planner tiles | the CSVs in section B | load them; they are refreshed only when the theme notebooks are re-run |

## Not run

- No table was loaded and no query was executed on Databricks. The checks quoted per tile were run
  locally with duckdb over the same files on 2026-11-21, except where a tile says "check on load".
- No dashboard JSON was written or deployed (`databricks lakeview create` not run).
