# Independent verification of the Databricks layer

Run on 2026-11-21 against profile `vf`, warehouse `6a2f5637720a2c17`. Every result below comes from a
command run during this check, not from the earlier reports. The scripts are in `databricks/verify/` and
can be re-run; their raw output goes to `build/databricks_staging/independent_*.json`.

## Summary

| # | Check | Result |
|---|---|---|
| 1 | Tables in `workspace.referral_saathi`: rows vs local source, key uniqueness, comments | Pass (57 of 57) |
| 2 | Dashboard: exists, published, every dataset runs with rows, published URL HTTP 200 | Pass (rendering not checked) |
| 3 | Genie space: exists, 3 new planner questions vs our SQL | Pass (3 of 3) |
| 4 | `call_outcomes`: schema vs issue #65, test row gone, least-privilege grants | Pass |
| 5 | App: `/api/ping` 200, real `POST /api/plan` returns options, env vars present | Pass |

Fixes made during this check: none were needed. No workspace object was changed. The only new files are
the four scripts in `databricks/verify/`, this file, and the JSON outputs in `build/databricks_staging/`.

## Re-run on 2026-11-22 (plan 6e; raw output not committed)

The four read-only scripts were re-run unchanged, after the dashboard dropped its v1 pages (#143), the Genie
space gained benchmarks (#155) and the six v1 tables were commented SUPERSEDED (#148). Run from a checkout
that has the unpublished inputs (see databricks/README.md, "What a clean checkout can rebuild"). No workspace
object was changed by the scripts. Call_outcomes (section 4) was not re-run.

| # | Check | Result on 2026-11-22 |
|---|---|---|
| 1 | Tables: rows vs local source, keys, comments | Pass, 61 of 61 (the manifest grew from 57); only `call_outcomes` is in UC and not in the manifest |
| 2 | Dashboard: lifecycle, published, datasets, HTTP | ACTIVE, 6 pages, 41 widgets, published 2026-11-22T07:20:02Z with embed_credentials true, both URLs HTTP 200. 10 of 11 datasets ran with rows |
| 3 | Genie: the 3 VERIFY questions vs our SQL | Pass on numbers, 3 of 3: e-RaktKosh Kerala 41, Uttar Pradesh 33, Punjab 29; Kerala C-section 11 claimed, 3 confirmed; Odisha Sundargarh 3.66 M, 0 and 0 |
| 5 | App: ping, real plan | `/api/ping` 200; `POST /api/plan` (dialysis, 25.6, 85.14) 200, 15.6 KB, 3 options: Satyavrat Hospital, Advanced Neuro Hospital, Ford Hospital And Research Center (all Patna) |

Notes from this run:
- The one dataset that "failed" is ds_pairs. The verifier fetches its rows inline and hit the 25 MB inline
  limit: since the v2 repoint it returns 358,092 rows. This is a limit of the verifier, not the dashboard.
  `build_dashboard.py test` counts the same SQL with `SELECT COUNT(*)` and gets 358,092 rows, SUCCEEDED.
- Genie's Odisha answer restates the question as "districts in Bihar" in its first line, then answers for
  Odisha. That is a wording slip; the numbers are right.
- Genie native benchmark, 12 questions: 9 of 12, then 10 of 12 on the live space (two runs,
  `databricks/genie/benchmark_results.json`; details in databricks/genie/GENIE.md).
- Rendering of the dashboard pages and the Genie Benchmark tab is still unchecked in a browser.

The sections below are the first run, on 2026-11-21.

## 1. Tables

Script: `databricks/verify/verify_tables.py` (run through `uv run --offline --with pyyaml --python .venv/bin/python`).

How it differs from the loader's own check: local rows are counted with duckdb straight from the source file
named in `tables.yaml` (CSV sources read as CSV, not the staged parquet copy), and the UC side is one
`UNION ALL` statement written for this check: `count(*)`, number of duplicate keys, number of null keys per
table. Comments come from `information_schema`. Build-only tables (services, pathways, model_test_metrics,
pmndp_state, facility_list_facts and similar) have no other local copy, so they are compared with the staged
parquet the builder wrote.

- 57 of 57 PASS. Every UC row count equals the local count (for example data_point_scores 518,191,
  claims 469,498, source_urls 158,444, facility_list_facts 3,062).
- Duplicate keys: 0 in 56 tables. `open_data_facts` has 1, which is the known exact duplicate row in the
  source (`known_dup_keys: 1` in the manifest). Null keys: 0 everywhere.
- Table comments: 57 of 57 present.
- Column comments are sparse: 104 columns in total, and 43 of the 57 tables have none. Not a failure (the
  table comments name the source and the key), but Genie and dashboard authors get less help on those tables.
- One table in UC is not in the manifest: `call_outcomes` (expected, created by the plumbing step).
- facility_list_facts holds only matched per-facility facts: every row has a unique_id; list counts are
  NABH 2,061, NMC 480, e-RaktKosh 388, LaQshya 112, MoHFW trauma 20, Goa PMNDP 1. No full restricted list
  was found in the schema.
- Data quality found: 245 of the 2,061 NABH rows have an unusable `citation_url` (null, empty, `#` or
  `Not Found`). All other lists have 0.

## 2. Dashboard

Script: `databricks/verify/verify_dashboard.py`. It reads the serialized dashboard from the workspace
(`lakeview get`), not the local JSON, and runs each dataset query with that dataset's own catalog and schema.

- `lakeview get`: lifecycle ACTIVE, 7 pages, 49 widgets.
- Published: revision 2026-11-21T23:25:27Z (after the last draft update at 23:25:26Z), embed_credentials true.
- 16 of 16 datasets SUCCEEDED with rows: ds_facility 9959, ds_state 32, ds_district 784,
  ds_dialysis_district 781, ds_csection_district 169, ds_dialysis_burden 780, ds_settlement 9, ds_pmndp 36,
  ds_funnel 9244, ds_pairs 69713, ds_list_facts 3062, ds_plans 3150, ds_plans_window 21,
  ds_plans_concentration 18, ds_test_metrics 14, ds_test_labels 4. All on workspace.referral_saathi.
- HTTP with a bearer token: `GET /sql/dashboardsv3/01f1e602d4de168ea830c833c7865de6/published` 200
  (52 KB page), `GET /api/2.0/lakeview/dashboards/<id>/published` 200.
- Not run: widget rendering. The 200 is the page shell; whether the 7 Vega-Lite widgets draw needs a person
  to open each page in a signed-in browser.
- Risk: ds_pairs returns 69,713 rows and ds_facility 9,959 to the widgets unaggregated. Widgets that plot
  raw rows may hit the widget row limit. Check those tiles when opening the pages.

## 3. Genie space

Script: `databricks/verify/verify_genie.py` (reuses `ask()` from `genie/test_space.py`). The 3 questions
are not among the 10 example queries, the 5 sample questions or the 6 earlier tests.

- `genie get-space`: "Referral Saathi planner", warehouse 6a2f5637720a2c17, 10 tables, 10 example SQL,
  7 join specs. The room URL `https://dbc-ea4e0abe-8cd4.cloud.databricks.com/genie/rooms/01f1e60264ac19f98063e082b625c2df`
  returned HTTP 200 with a bearer token.

| Question | Our SQL | Genie | Result |
|---|---|---|---|
| Which three states have the most facilities on the e-RaktKosh blood bank list? | Kerala 41, Uttar Pradesh 33, Punjab 29 | Kerala 41, Uttar Pradesh 33, Punjab 29; says "public evidence from the e-RaktKosh list" | Pass |
| In Kerala, how many facility records claim emergency C-section, and how many are confirmed by a second source? | 11 claim, 3 confirmed | 11 and 3; says "public evidence from Virtue Foundation records, not verified facts" | Pass |
| Which district in Odisha with no confirmed dialysis facility has the largest population? | Sundargarh, 3.66 M, 0 claim, 0 confirmed | Sundargarh, 3.66 M, 0 claiming, 0 confirmed | Pass |

Wording notes from reading the answers: none said "no care". The Odisha answer says "no confirmed dialysis
facility" (the question's own words) rather than "no public evidence in this dataset", and ends with
"n = 1 district", which is the LIMIT 1 row count, not a sample size. Both are wording, not number, issues.
Three questions plus the earlier six is still a smoke test, not a benchmark.

## 4. call_outcomes

Contract: GitHub issue #65 (read with `gh issue view 65`): facility_id, service_id, outcome (yes / no /
no answer), asked questions, model_version, coarse location (district, never raw GPS), timestamp, no patient
data.

- Columns (`information_schema.columns`): outcome_id string NOT NULL, facility_id string, service_id string,
  outcome string, questions array<string>, model_version string, district string, created_at timestamp,
  app_version string. All 9 commented. Every field the issue names is present; outcome_id and app_version
  are additions.
- Constraint: `delta.constraints.outcome_valid = outcome IN ('yes', 'no', 'no_answer')`. The issue writes
  "no answer"; the app must send `no_answer`.
- facility_id holds the facility `unique_id`. Confirmed that the 3 facility_ids returned by `/api/plan`
  exist in `facility_trust.unique_id`, so the app can write its ids as they are.
- Rows: `count(*) = 0`, no row with outcome_id like `TEST%`. History: CREATE, ADD CONSTRAINT, WRITE,
  DELETE, CHANGE COLUMN (the test row was written and deleted).
- Grants for the app SP `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`: catalog USE_CATALOG on workspace; schema
  USE_SCHEMA and SELECT on referral_saathi only; table privileges other than SELECT: exactly one, MODIFY on
  call_outcomes; no table privileges outside referral_saathi; no volume privileges. Least privilege holds.

## 5. App

Script: `databricks/verify/verify_app.py`.

- `apps get referral-saathi`: RUNNING, compute ACTIVE (MEDIUM), active deployment
  01f1e603e4341bef8aaa7affe7109dc7 SUCCEEDED from `/Workspace/Users/<workspace-user>/referral-saathi-src`.
- Resources: sql-warehouse (6a2f5637720a2c17, CAN_USE), serving-endpoint-text
  (databricks-meta-llama-3-3-70b-instruct, CAN_QUERY), serving-endpoint-vision (databricks-llama-4-maverick,
  CAN_QUERY).
- Env vars: the deployed `app.yaml` in the workspace source has `DATABRICKS_WAREHOUSE_ID`,
  `SERVING_ENDPOINT_TEXT` and `SERVING_ENDPOINT_VISION`, each with `valueFrom` the matching resource. I did
  not read the values inside the running process (that needed the temporary route the plumbing step used).
- `GET /api/ping`: HTTP 200 `{"ok":true}`.
- `POST /api/plan` with the dialysis body for (25.6, 85.14): HTTP 200, 14 KB, `meta.stub` false, data
  snapshot "derived/v1 2026-11-21", 3 options, each with 3 evidence items: 1 Satyavrat Hospital (Patna),
  2 Patna Dialysis Centre (Patna), 3 Rastra Kavi Dinkar Blood Bank, Sadar Hospital (Gopalganj).
- Observation for the app team: option 3 for a dialysis search is a blood bank in
  Gopalganj. That is a ranking question, not a Databricks layer fault.

## What remains

- Open each dashboard page once in a signed-in browser to confirm the widgets render, especially the 7
  Vega-Lite charts and the raw-row tiles (ds_pairs, ds_facility).
- The app does not have `POST /api/outcome` yet (no reference to it or to call_outcomes in `app/`). A write
  to call_outcomes as the SP has not been run.
- No LLM call from the app to either serving endpoint has been run.
- Genie: a 12-question native benchmark is attached (9 of 12, then 10 of 12 on the live space; two runs on
  2026-11-22, `databricks/genie/benchmark_results.json`); a wording pass so answers
  say "no public evidence in this dataset" and avoid column names is still open.
- 245 NABH facts lack a usable citation URL; the dashboard and Genie should show them as missing links.
- Column comments: 43 of 57 tables have none.
- Primary keys are verified but not declared as UC constraints.
- derived/v2 reload: not run (v2 is still being written).
- `sql.sh` exits with a KeyError on statements that return no columns (DDL, GRANT). Outside this directory,
  so not changed.
