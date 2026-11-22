# District planner dashboard (AI/BI)

A read-only Databricks AI/BI dashboard for district planners and NGO coordinators, built to
`viz/dashboard/DASHBOARD_SPEC.md` over the tables in `workspace.referral_saathi`. It answers, for a chosen
state, district and service: how thin is the evidence, how far are people from confirmed care, what do
records claim against what anyone confirmed, which records to check by phone, what the planner's sample
journeys look like, and how far to trust the scores.

## Links

- Published (embedded credentials): https://dbc-ea4e0abe-8cd4.cloud.databricks.com/sql/dashboardsv3/01f1e602d4de168ea830c833c7865de6/published
- Draft: https://dbc-ea4e0abe-8cd4.cloud.databricks.com/sql/dashboardsv3/01f1e602d4de168ea830c833c7865de6
- Workspace file: `/Users/<workspace-user>/databricksdatathon/dashboards/Referral Saathi: district planner.lvdash.json`
- Dashboard id: `01f1e602d4de168ea830c833c7865de6` (also in `dashboard_id.txt`), warehouse `6a2f5637720a2c17`

State after deploy, read back with the API on 2026-11-21: `lakeview get` returns lifecycle ACTIVE, 16
datasets all with catalog `workspace` and schema `referral_saathi`, 7 pages (6 canvas plus the filter page);
`GET /api/2.0/lakeview/dashboards/<id>/published` returns `embed_credentials: true`. Permissions: owner
CAN_MANAGE, admins CAN_MANAGE, group `users` CAN_READ (granted so teammates added to the workspace can open
it; the workspace has 1 user today).

Not run: nobody has opened the dashboard in a browser yet. The API accepts the JSON and the dataset SQL is
tested, but widget rendering (in particular the 7 Vega-Lite custom charts) has not been looked at. Open each
page once before the demo; if a custom chart is blank, see "If a widget does not render" below.

## Model v2 repoint (2026-11-21)

Validation report H7 found `ds_pairs` read the fusion prototype (`pair_scores`: 2 pairs Likely for the 7 gold
services, where the app bands 45). `ds_pairs` now reads `facility_service_scores_v2` (derived/v2, model A_platt,
358,092 rows: 9,947 eligible records x 36 services) and shows the model's four bands: Likely 20,073, Call first
1,671, No service text 242,131, Unlikely 94,217. P_S is blank for No service text rows (derived/v2/README.md:
show the band, not p). The two bin columns are the observed confirmed rate of DEV pairs in the same 0.2 score
bin, not an interval around P_S. Operator in `ds_facility` and `ds_pairs` comes from `facility_attributes_v2`.
State and district still come from `geo_facility` (LGD polygon of the cleaned point): `facility_attributes_v2`
has no district, and `facility_location.district` uses postcode district names that differ from the LGD names
on 689 of 9,959 records, which would break the shared district filter. The phones column was removed from
3.2 (#82). Pages 3 and 6 state that the score has no demonstrated ranking ability for public facilities.
The service filter now lists v2 taxonomy ids for `ds_pairs` (trauma_care, emergency_24x7) beside the v1 ids
of `ds_funnel` (trauma_emergency); dialysis, emergency_csection, nicu, mri, cardiac_surgery and burn_care
match in both. Tables 6.2 and 6.3 still quote the v1 sealed test.

## Files

| File | What |
|---|---|
| `build_dashboard.py` | Single source: dataset SQL, widgets, layout, theme, spec checks, test runner and deploy |
| `planner_dashboard.json` | The serialized dashboard as deployed (bare table names) |
| `query_tests.json` | Row count and timing per dataset, and the spec check results, from the last `test` run |
| `dashboard_id.txt` | The dashboard id, so re-deploys update in place and the link stays the same |

## Rebuild, retest, redeploy

From the project root:

```
export DATABRICKS_CONFIG_PROFILE=vf
python3 databricks/dashboard/build_dashboard.py all      # build JSON, test every query, update + publish
python3 databricks/dashboard/build_dashboard.py test     # only rerun the queries and checks
```

`all` stops before deploying if any dataset query fails or returns no rows. When the tables are reloaded
from `derived/v2` (`load_tables.py --only derived --derived derived/v2`), run `all` again: the spec checks
will then show the v2 numbers next to the v1 numbers quoted in their labels, so text widgets that quote
national v1 numbers can be updated where they differ.

## Pages and tiles

Filters (global page): State (multi-select, default BIHAR), District (multi-select, cascades from state),
Service (single-select, default dialysis). A filter acts only on the datasets it is bound to; national tiles
are not bound.

| Page | Tiles | Filters |
|---|---|---|
| 1. District at a glance | 1.1 records (counter), 1.2 high-confidence location (percent), 1.3 names another facility (percent), 1.x the four record checks as k of n with Wilson 95% intervals, 1.4 records per million by state with Poisson interval, 1.6 facility points (lon x, lat y, no basemap), 1.5 district table | state, district; 1.4 national |
| 2. Access to confirmed care | 2.1 within 60 min of confirmed trauma by state with route-error whisker and dots for any record and any clinic, 2.2 people over an hour away, 2.3 dialysis need against access by district, 2.4 low caesarean districts, 2.5 weekly dialysis km by tier, 2.6 within an hour by settlement class, 2.7 PMNDP against records | 2.1, 2.2, 2.6 national; 2.3-2.5 state and district; 2.7 state |
| 3. Claimed against confirmed | records counter (n), 3.3 any stated hours and 24x7 emergency statement, 3.1 evidence ladder as k of mentions with intervals, 3.2 facilities ranked by P_S, 3.4 official list facts with citation | state, district, service (3.4: state and district only) |
| 4. Records to check by phone | records counter (n), 4.1 pin 50+ km, 4.3 directory phones hidden, 4.2 location confidence mix, 4.4 fixed / flagged / cannot fix as k of n, 4.5 records to call first | state, district |
| 5. Referral journeys (sample) | 5.1 definitive care within 60 min by pathway with Wilson interval, 5.2 best plan type (100% stacked), 5.3 concentration on the most-chosen facility | state |
| 6. How far to trust the scores | 6.1 badges, 6.4 crawlable own website by operator and settlement with intervals, 6.2 published sealed-test AUROC and ECE, 6.3 label counts | 6.1 state, district, service; 6.4 state, district; 6.2, 6.3 national |

Honesty rules applied: every page starts with a caveat text widget (the shared one plus the page's caveats
from `viz/STORYBOOK.md`); every rate shows n, either as k of n on the bar (with "small sample" when n < 30)
or as a records counter on the same page; gaps are labelled "no public evidence of care", never "no care";
no choropleth or symbol map (facility locations are a scatter with no basemap and no boundaries; the rest
are ranked bars and tables). Theme colours are the `viz/style.py` tokens, with evidence states pinned
(Likely `#6da7ec`, Call first `#eda100`, No service text `#c3c2b7`, Unlikely `#e34948`).

## Skipped tiles

None. Every tile in the spec has its data loaded (`facility_list_facts`, `model_test_metrics`,
`nfhs_lgd_crosswalk` keys and `geo_facility_site` were added by the loader). Differences from the spec:

- 1.4 and 2.1 do not highlight the selected state. They are national; a highlight would need a dataset
  parameter bound to the state filter, which I did not add.
- 3.4 does not follow the service filter. NABH facts have no service, so binding it would hide all 2,061 of
  them; the list's own service is shown as a column instead.
- 2.3 and 2.4 filter by LGD district through `geo_district`'s NFHS keys (the same keys as
  `nfhs_lgd_crosswalk`): one row per LGD district, so an NFHS district split into several LGD districts repeats
  (704 NFHS districts become 781 rows in 2.3). The two `dist_lgd = 0` rows (Muzaffarabad, Mirpur) are left out
  because they would repeat Jammu.
- 2.5 Sanchor (dist_lgd 779) is not in `geo_district`; it keeps its own state and district names.
- 2.6 has no interval: it is a share of the whole population from the access grid, not a sample.
- 6.3 is a table with a text widget beside it, not text alone.
- `ds_cleaning`, `ds_hours` and `ds_website` from the spec are columns of one record-level `ds_facility`, and
  `ds_bands` is an aggregation of `ds_pairs`, so widgets on a page cross-filter. The logic is the spec's SQL.
- 6.2 also lists keyword count and rule grade, and the 39-searched-pairs view next to all 71.

## If a widget does not render

The JSON follows the skill's widget contracts, but rendering is unchecked. The likeliest failures, in order:
Vega-Lite features in the 7 custom charts (`fold`, `yOffset`, the `colors.textPrimary.default` signal), then
the scatter's `zero: false` scale option. Fix in `build_dashboard.py` and run `all`; the link does not change.

## Query tests

| Dataset | Rows | Seconds | Widgets that read it |
|---|---|---|---|
| `ds_facility` | 9,959 | 1.7 | f_district, f_state, p1_highconf, p1_other, p1_points, p1_rates, p1_records, p3_24x7, p3_hours, p3_records, p4_callfirst, p4_cleaning, p4_dirphone, p4_locconf, p4_pinfar, p4_records, p6_website |
| `ds_state` | 32 | 1.5 | p1_state, p2_golden, p2_outside |
| `ds_district` | 784 | 1.1 | f_district, f_state, p1_districts |
| `ds_dialysis_district` | 781 | 1.4 | f_district, f_state, p2_dialysis |
| `ds_csection_district` | 169 | 1.4 | f_district, f_state, p2_csection |
| `ds_dialysis_burden` | 780 | 1.5 | f_district, f_state, p2_burden |
| `ds_settlement` | 9 | 1.3 | p2_settlement |
| `ds_pmndp` | 36 | 1.3 | f_state, p2_pmndp |
| `ds_funnel` | 9,244 | 1.6 | f_district, f_service, f_state, p3_funnel |
| `ds_pairs` | 358,092 | 1.1 | f_district, f_service, f_state, p3_facilities, p6_bands |
| `ds_list_facts` | 3,062 | 2.2 | f_district, f_state, p3_lists |
| `ds_plans` | 3,150 | 1.4 | f_state, p5_plantype |
| `ds_plans_window` | 21 | 1.7 | f_state, p5_window |
| `ds_plans_concentration` | 18 | 1.4 | f_state, p5_concentration |
| `ds_test_metrics` | 14 | 1.6 | p6_metrics |
| `ds_test_labels` | 4 | 1.1 | p6_labels |

Run at 2026-11-21 22:01:57 (local time) through `/api/2.0/sql/statements` with catalog `workspace` and schema `referral_saathi`, as `SELECT COUNT(*) FROM (<dataset SQL>) t`. All 16 returned SUCCEEDED.

### Spec checks

Each check wraps the dataset SQL itself, so it tests what the widgets read.

| Check | Result |
|---|---|
| ds_facility national: records, high conf, names other, directory phones (spec 9959, 7762, 1232, 292) | SUCCEEDED: [['9959', '7762', '1232', '292']] |
| ds_facility cleaning: cannot_fix, rated_no_concerns, both (spec 2610, 7812, 1589) | SUCCEEDED: [['2610', '7812', '1589']] |
| ds_facility hours: any, 24x7, schedule (spec 6074, 2829, 2808) | SUCCEEDED: [['6074', '2829', '2808']] |
| ds_state Bihar per_m, lo, hi, records, pop_m (spec 1.95, 1.72, 2.20, 260, 133.5) | SUCCEEDED: [['1.95', '1.72', '2.2', '260', '133.5']] |
| geo_dialysis_district hot districts and people (spec 69, 103.8 M) | SUCCEEDED: [['69', '103.8']] |
| geo_csection_district districts in the two low bands (spec 152 = 39 + 113) | SUCCEEDED: [['5-10%', '113'], ['under 5%', '39']] |
| ds_funnel national: mentioned, own checks, own and outside (spec 7969, 1798, 837) | SUCCEEDED: [['7969', '1798', '837']] |
| ds_pairs v2 bands (derived/v2: Likely 20073, Call first 1671, No service text 242131, Unlikely 94217) | SUCCEEDED: [['Call first', '1671'], ['Likely', '20073'], ['No service text', '242131'], ['Unlikely', '94217']] |
| ds_pairs v2 contract: rows (358092), exclude_review ids (0), NO_SERVICE_TEXT with P_S (0), operators | SUCCEEDED: [['358092', '0', '0', '3']] |
| ds_plans_window Bihar major trauma (spec 15 of 150) | SUCCEEDED: [['15', '150', '0.1', '0.062', '0.158']] |
| ds_plans_concentration Bihar (spec obstetric 81 of 131 Pusa, trauma 79 of 134 Rajeshwar) | SUCCEEDED: [['obstetric_emergency', 'Sub Divisional Hospital Pusa', '81', '131'], ['major_trauma', 'Rajeshwar Hospital', '79', '134']] |
| ds_test_metrics shipped vs priors, all 71 (storybook 0.776 [0.680, 0.862] vs 0.789; ECE IPW 0.197) | SUCCEEDED: [['AUROC', 'Same scorecard, expert priors', '0.7887', '0.6923', '0.875', '0.684'], ['AUROC', 'Fitted ledger (shipped)', '0.7756', '0.6804', '0.8619', '0.6149'], ['ECE (lower is better)', 'Fitted ledger (shipped)', '0.097', '0.0783', '0.1804', '0.1966']] |
| ds_test_labels (storybook 17, 1, 21, 32 of 71) | SUCCEEDED: [['Confirmed', '17', '71'], ['Contradicted', '1', '71'], ['No public information, searched', '21', '71'], ['No public information, never searched', '32', '71']] |
| ds_dialysis_district coverage: NFHS districts reached and LGD rows | SUCCEEDED: [['704', '781']] |
| filter values: states in ds_facility, districts in ds_facility | SUCCEEDED: [['34', '557']] |

## Dataset SQL

As deployed (bare table names). `build_dashboard.py` is the source of truth.

### ds_facility

Records (one row per facility record).

```sql
WITH direct AS (SELECT DISTINCT unique_id FROM claims WHERE context = 'direct'),
quar AS (SELECT DISTINCT unique_id FROM claims WHERE attribution = 'other_facility'),
anon AS (SELECT DISTINCT c.unique_id FROM claims c JOIN quar q ON c.unique_id = q.unique_id
         WHERE c.attribution = 'unanchored' AND coalesce(c.services, '') <> ''),
trunc AS (SELECT DISTINCT unique_id FROM grades WHERE coalesce(truncated, false)),
base AS (
  SELECT g.stname AS state, upper(g.dtname) AS district, l.unique_id, l.name,
         l.loc_lat, l.loc_lon, l.loc_conf, l.loc_note, round(l.raw_coords_to_pin_km, 1) AS pin_km,
         CASE WHEN l.loc_conf = 'high' THEN 1 ELSE 0 END AS is_high_conf,
         CASE WHEN l.raw_coords_to_pin_km > 50 THEN 1 ELSE 0 END AS pin_far,
         CASE WHEN d.unique_id IS NOT NULL THEN 1 ELSE 0 END AS names_other_facility,
         CASE WHEN array_contains(r.trust_flags, 'official_phone_is_directory') THEN 1 ELSE 0 END AS directory_phone,
         r.trust_level, r.website_class,
         CASE g.degurba WHEN 3 THEN 'Urban centre' WHEN 2 THEN 'Town or semi-dense' WHEN 1 THEN 'Rural' END AS settlement,
         CASE fa.operator WHEN 'public' THEN 'Public' WHEN 'private' THEN 'Private' ELSE 'Not stated' END AS operator,
         CASE WHEN l.loc_src <> 'listing_coordinates' THEN 1 ELSE 0 END AS fixed_corrected_point,
         CASE WHEN q.unique_id IS NOT NULL THEN 1 ELSE 0 END AS fixed_quarantined_text,
         CASE WHEN l.loc_conf IN ('low', 'disputed') THEN 1 ELSE 0 END AS flagged_location,
         CASE WHEN size(r.scale_flags) > 0 THEN 1 ELSE 0 END AS flagged_size,
         CASE WHEN a.unique_id IS NOT NULL OR d.unique_id IS NOT NULL OR t.unique_id IS NOT NULL
              THEN 1 ELSE 0 END AS cannot_fix,
         CASE WHEN r.trust_level = 'no_concerns' THEN 1 ELSE 0 END AS rated_no_concerns,
         CASE WHEN h.dataset_any_hours OR h.web_any_hours OR h.osm_any_hours THEN 1 ELSE 0 END AS any_hours,
         CASE WHEN h.dataset_emerg24 OR h.web_emerg24 OR h.osm_emerg24 THEN 1 ELSE 0 END AS emergency_24x7,
         CASE WHEN h.dataset_schedule OR h.web_schedule OR h.osm_schedule THEN 1 ELSE 0 END AS clock_schedule,
         CASE WHEN w.own_site THEN 1 ELSE 0 END AS own_site
  FROM facility_location l
  JOIN geo_facility g ON g.unique_id = l.unique_id
  JOIN record_trust r ON r.unique_id = l.unique_id
  LEFT JOIN facility_attributes_v2 fa ON fa.unique_id = l.unique_id
  LEFT JOIN facility_hours h ON h.unique_id = l.unique_id
  LEFT JOIN geo_facility_site w ON w.unique_id = l.unique_id
  LEFT JOIN direct d ON d.unique_id = l.unique_id
  LEFT JOIN quar q ON q.unique_id = l.unique_id
  LEFT JOIN anon a ON a.unique_id = l.unique_id
  LEFT JOIN trunc t ON t.unique_id = l.unique_id)
SELECT *,
       CASE WHEN pin_far = 1 OR flagged_location = 1 OR names_other_facility = 1 THEN 1 ELSE 0 END AS call_first,
       concat_ws('; ',
         CASE WHEN pin_far = 1 THEN concat('pin ', pin_km, ' km from postcode') END,
         CASE WHEN flagged_location = 1 THEN concat('location ', loc_conf) END,
         CASE WHEN names_other_facility = 1 THEN 'text names another facility' END) AS call_reason
FROM base
```

### ds_state

States and UTs over 1 million people (national).

```sql
SELECT d.stname AS state, d.label, d.pop / 1e6 AS pop_m, d.records,
       d.per_m, d.per_m_lo, d.per_m_hi,
       d.child_u5_who_are_stunted_height_for_age_18_pct / 100 AS stunting,
       a.corr AS share_60_confirmed_trauma, a.corr_lo, a.corr_hi,
       a.`any` AS share_60_any_record, a.`map` AS share_60_any_clinic,
       a.people_outside_corr / 1e6 AS people_outside_m, a.n_corr
FROM geo_state_density d
JOIN geo_state_access a USING (stname)
WHERE d.pop >= 1e6
ORDER BY d.per_m DESC
```

### ds_district

LGD districts.

```sql
SELECT stname AS state, upper(dtname) AS district, dist_lgd, nfhs_district, pop / 1e6 AS pop_m, records, per_m,
       CASE WHEN records = 0 THEN 'no record' ELSE '' END AS no_record_flag
FROM geo_district
ORDER BY per_m ASC
```

### ds_dialysis_district

Dialysis need and access by district (NFHS keys mapped to LGD).

```sql
SELECT g.stname AS state, upper(g.dtname) AS district, d.nfhs_district, d.pop / 1e6 AS pop_m,
       d.ncd / 100 AS need_proxy, d.burden_q, d.n_claim, d.n_corr, d.corr_per_m, d.corr_per_m_lo, d.corr_per_m_hi,
       d.share60, d.median_min, CASE WHEN d.hot THEN 'high need, over 1 h' ELSE '' END AS hot_flag,
       CASE WHEN d.hot THEN 1 ELSE 0 END AS hot
FROM geo_dialysis_district d
JOIN geo_district g ON g.nfhs_state = d.nfhs_state AND g.nfhs_district = d.nfhs_district AND g.dist_lgd > 0
ORDER BY hot DESC, d.share60 ASC
```

### ds_csection_district

Low caesarean districts (NFHS keys mapped to LGD).

```sql
SELECT g.stname AS state, upper(g.dtname) AS district, c.nfhs_district, c.wra / 1e6 AS women_15_49_m,
       c.births_delivered_by_csection_5y_pct / 100 AS csection_rate, c.band,
       c.n_claimed, c.n_corroborated, c.n_laqshya
FROM geo_csection_district c
JOIN geo_district g ON g.nfhs_state = c.nfhs_state AND g.nfhs_district = c.nfhs_district AND g.dist_lgd > 0
WHERE c.band IN ('under 5%', '5-10%')
ORDER BY csection_rate ASC
```

### ds_dialysis_burden

Weekly road travel for dialysis.

```sql
SELECT coalesce(g.stname, upper(b.state)) AS state, upper(coalesce(g.dtname, b.district)) AS district,
       b.population / 1e6 AS pop_m,
       b.median_weekly_km_claimed, b.median_weekly_km_graded, b.median_weekly_km_corroborated,
       b.median_weekly_hours_corroborated
FROM dialysis_burden_district b
LEFT JOIN (SELECT * FROM geo_district WHERE dist_lgd > 0) g ON g.dist_lgd = b.dist_lgd
WHERE b.road_estimate_valid
ORDER BY b.median_weekly_km_corroborated DESC
```

### ds_settlement

Within an hour of confirmed care, by settlement class (national).

```sql
SELECT cls AS settlement, code, pop / 1e6 AS pop_m, pop_share, records, records_share,
       care, within60, confirmed_facilities
FROM geo_settlement
LATERAL VIEW stack(3, 'Trauma', trauma_within60, trauma_corr,
                      'Dialysis', dialysis_within60, dialysis_corr,
                      'Emergency C-section', csection_within60, csection_corr) s AS care, within60, confirmed_facilities
ORDER BY code DESC
```

### ds_pmndp

PMNDP public dialysis centres by state.

```sql
SELECT state_lgd AS state, nhsrc_functional_centres AS pmndp_centres,
       nhsrc_functional_districts AS pmndp_districts, vf_records, vf_dialysis, vf_public_dialysis
FROM pmndp_state
ORDER BY pmndp_centres DESC
```

### ds_funnel

Evidence ladder (one row per record and service).

```sql
SELECT g.stname AS state, upper(g.dtname) AS district, p.service,
       CAST(p.mentioned AS INT) AS mentioned,
       CAST(p.mentioned AND p.fields2 AS INT) AS in_2plus_fields,
       CAST(p.mentioned AND p.fields2 AND p.prereq AS INT) AS own_checks,
       CAST(p.mentioned AND (p.web OR p.listed) AS INT) AS outside_check,
       CAST(p.mentioned AND p.fields2 AND p.prereq AND (p.web OR p.listed) AS INT) AS own_and_outside,
       CAST(NOT p.mentioned AND (p.web OR p.listed) AS INT) AS outside_not_mentioned
FROM claims_funnel_pairs p
JOIN geo_facility g USING (unique_id)
```

### ds_pairs

Facility and service scores, model v2 (one row per record and service).

```sql
SELECT g.stname AS state, upper(g.dtname) AS district, s.service_id AS service, s.unique_id, l.name,
       CASE s.band WHEN 'LIKELY' THEN 'Likely' WHEN 'CALL_FIRST' THEN 'Call first'
                   WHEN 'NO_SERVICE_TEXT' THEN 'No service text' WHEN 'UNLIKELY' THEN 'Unlikely' END AS band,
       CASE WHEN s.band <> 'NO_SERVICE_TEXT' THEN s.p END AS p_s,
       s.lo AS bin_lo, s.hi AS bin_hi, s.p_location AS p_l, s.p_exists AS p_e,
       CASE s.operator WHEN 'public' THEN 'Public' WHEN 'private' THEN 'Private' ELSE 'Not stated' END AS operator,
       array_join(s.overlays, ', ') AS flags, l.loc_conf, r.website_class,
       CASE WHEN s.band IN ('LIKELY', 'CALL_FIRST') THEN 1 ELSE 0 END AS shortlisted
FROM facility_service_scores_v2 s
JOIN geo_facility g ON g.unique_id = s.unique_id
JOIN facility_location l ON l.unique_id = s.unique_id
JOIN record_trust r ON r.unique_id = s.unique_id
ORDER BY s.p DESC
```

### ds_list_facts

Official list facts per matched facility, with citation.

```sql
SELECT g.stname AS state, upper(g.dtname) AS district, f.unique_id, l.name AS facility, f.list_name, f.status,
       nullif(f.service, '') AS list_service, f.valid_to, f.as_of, f.citation_url
FROM facility_list_facts f
JOIN geo_facility g ON g.unique_id = f.unique_id
JOIN facility_location l ON l.unique_id = f.unique_id
ORDER BY state, district, facility, f.list_name
```

### ds_plans

Planner sample journeys (one row per origin and pathway).

```sql
SELECT state, pathway, origin_id, best_type, first_name, first_eta, def_name, def_eta,
       def_low, def_high, p_objective,
       CASE WHEN def_eta <= 60 THEN 1 ELSE 0 END AS definitive_within_60,
       CASE WHEN first_eta <= 60 THEN 1 ELSE 0 END AS first_care_within_60
FROM planner_plans
WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra')
```

### ds_plans_window

Definitive care within 60 minutes, by pathway.

```sql
WITH t AS (
  SELECT state, pathway, SUM(CASE WHEN def_eta <= 60 THEN 1 ELSE 0 END) AS k, COUNT(*) AS n
  FROM planner_plans
  WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra')
  GROUP BY state, pathway)
SELECT state, pathway, k, n, k / n AS rate,
       (k/n + 1.9208/n - 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS lo,
       (k/n + 1.9208/n + 1.96*sqrt((k/n)*(1 - k/n)/n + 0.9604/(n*n))) / (1 + 3.8416/n) AS hi
FROM t
ORDER BY state, rate DESC
```

### ds_plans_concentration

Most-chosen definitive facility per pathway.

```sql
WITH c AS (
  SELECT state, pathway, def_name, COUNT(*) AS origins,
         SUM(COUNT(*)) OVER (PARTITION BY state, pathway) AS planned
  FROM planner_plans
  WHERE origin_set IN ('Bihar', 'Uttar Pradesh', 'Maharashtra') AND def_name IS NOT NULL
  GROUP BY state, pathway, def_name),
r AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY state, pathway ORDER BY origins DESC, def_name) AS rk FROM c)
SELECT state, pathway, def_name AS top_facility, origins, planned, origins / planned AS share
FROM r WHERE rk = 1
ORDER BY state, share DESC
```

### ds_test_metrics

Published sealed-test results (quoted from results.json, not recomputed).

```sql
WITH a AS (
  SELECT regexp_extract(path, '^pair_level_test[.]primary_target_(all|searched)[.]auroc[.]([A-Za-z0-9_]+)[.](.+)$', 1) AS view, regexp_extract(path, '^pair_level_test[.]primary_target_(all|searched)[.]auroc[.]([A-Za-z0-9_]+)[.](.+)$', 2) AS sys,
         regexp_extract(path, '^pair_level_test[.]primary_target_(all|searched)[.]auroc[.]([A-Za-z0-9_]+)[.](.+)$', 3) AS stat, value_num
  FROM model_test_metrics WHERE source_file = 'model/review/stats/results.json' AND path RLIKE '^pair_level_test[.]primary_target_(all|searched)[.]auroc[.]([A-Za-z0-9_]+)[.](.+)$'),
e AS (
  SELECT regexp_extract(path, '^pair_level_test[.]calibration_primary_(all|searched)[.](ece_raw|ece_ipw)(.*)$', 1) AS view, regexp_extract(path, '^pair_level_test[.]calibration_primary_(all|searched)[.](ece_raw|ece_ipw)(.*)$', 2) AS kind,
         regexp_extract(path, '^pair_level_test[.]calibration_primary_(all|searched)[.](ece_raw|ece_ipw)(.*)$', 3) AS stat, value_num
  FROM model_test_metrics WHERE source_file = 'model/review/stats/results.json' AND path RLIKE '^pair_level_test[.]calibration_primary_(all|searched)[.](ece_raw|ece_ipw)(.*)$'),
auroc AS (
  SELECT 'AUROC' AS metric, view, sys,
         max(CASE WHEN stat = 'raw' THEN value_num END) AS value,
         max(CASE WHEN stat = 'raw_boot.ci95[0]' THEN value_num END) AS lo,
         max(CASE WHEN stat = 'raw_boot.ci95[1]' THEN value_num END) AS hi,
         max(CASE WHEN stat = 'ipw' THEN value_num END) AS ipw_value
  FROM a WHERE sys IN ('WL_shipped', 'B4_prior_only', 'B3_llm_judge', 'B0_any_mention', 'B1_keyword_count', 'B2_rule_grade')
  GROUP BY view, sys),
ece AS (
  SELECT 'ECE (lower is better)' AS metric, view, 'WL_shipped' AS sys,
         max(CASE WHEN kind = 'ece_raw' AND stat = '' THEN value_num END) AS value,
         max(CASE WHEN kind = 'ece_raw' AND stat = '_boot.ci95[0]' THEN value_num END) AS lo,
         max(CASE WHEN kind = 'ece_raw' AND stat = '_boot.ci95[1]' THEN value_num END) AS hi,
         max(CASE WHEN kind = 'ece_ipw' AND stat = '' THEN value_num END) AS ipw_value
  FROM e GROUP BY view)
SELECT metric,
       CASE view WHEN 'all' THEN 'All 71 test pairs' ELSE '39 searched pairs' END AS test_view,
       CASE sys WHEN 'WL_shipped' THEN 'Fitted ledger (shipped)'
                WHEN 'B4_prior_only' THEN 'Same scorecard, expert priors'
                WHEN 'B3_llm_judge' THEN 'LLM judge'
                WHEN 'B0_any_mention' THEN 'Any mention'
                WHEN 'B1_keyword_count' THEN 'Keyword count'
                WHEN 'B2_rule_grade' THEN 'Rule grade' END AS system,
       value, lo, hi, ipw_value
FROM (SELECT * FROM auroc UNION ALL SELECT * FROM ece)
ORDER BY metric, test_view, value DESC
```

### ds_test_labels

What the sealed-test labels were.

```sql
WITH m AS (SELECT path, value_num AS v FROM model_test_metrics WHERE source_file = 'model/review/stats/results.json'),
p AS (
  SELECT max(CASE WHEN path = 'inputs.test_label_counts.confirmed' THEN v END) AS confirmed,
         max(CASE WHEN path = 'inputs.test_label_counts.contradicted' THEN v END) AS contradicted,
         max(CASE WHEN path = 'inputs.test_label_counts.no_info' THEN v END) AS no_info,
         max(CASE WHEN path = 'inputs.test_never_searched' THEN v END) AS never_searched,
         max(CASE WHEN path = 'pair_level_test.primary_target_all.n' THEN v END) AS n
  FROM m)
SELECT ord, label, CAST(pairs AS INT) AS pairs, CAST(n AS INT) AS of_pairs, pairs / n AS share
FROM p LATERAL VIEW stack(4,
  1, 'Confirmed', confirmed,
  2, 'Contradicted', contradicted,
  3, 'No public information, searched', no_info - never_searched,
  4, 'No public information, never searched', never_searched) s AS ord, label, pairs
ORDER BY ord
```

