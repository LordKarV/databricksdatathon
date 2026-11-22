# App plumbing: call outcomes table and app resources

Done on 2026-11-21 with profile `vf`, warehouse `6a2f5637720a2c17`. The app is `referral-saathi`, and its
service principal is `app-2z9xvf referral-saathi`, application id `3770ad65-e41d-4f22-8b7d-305dfc97dc1d`.
UC grants name that application id.

## Files

| File | What |
|---|---|
| `call_outcomes.sql` | DDL for `workspace.referral_saathi.call_outcomes`: CREATE TABLE IF NOT EXISTS, then the CHECK constraint |
| `app_resources.json` | Body for `databricks apps update`: the three app resources |
| `grants.sql` | The four UC grants to the app service principal |

Backups (gitignored) are in `build/databricks_staging/`: `app_before_plumbing.json` (the app spec before the
update), `app_after_update.json`, and `deploy.sh.before_plumbing`.

## 1. Table workspace.referral_saathi.call_outcomes

This is a managed Delta table for the learning loop (issue #65). It has a table comment and a comment on
every column. The table comment says "NO PATIENT DATA MAY BE STORED" and lists what is banned: names, phone
numbers, ages, conditions, free-text notes, raw GPS and addresses. District is the finest location allowed.

| Column | Type | Note |
|---|---|---|
| outcome_id | string NOT NULL | random UUID |
| facility_id | string | the project's facility `unique_id` |
| service_id | string | `services.service_id` |
| outcome | string | CHECK constraint `outcome_valid`: yes, no, no_answer |
| questions | array<string> | suggested call questions shown |
| model_version | string | |
| district | string | coarse district only |
| created_at | timestamp | UTC |
| app_version | string | |

Checks run:
- `DESCRIBE TABLE EXTENDED` shows the columns, comments and `delta.constraints.outcome_valid`.
- I inserted one test row with outcome_id `TEST-ROW-app_plumbing-delete-me`, saw it with SELECT, then deleted it
  (`num_affected_rows 1`). Row count is now 0.
- An insert with outcome `maybe` failed with `DELTA_VIOLATE_CONSTRAINT_WITH_VALUES`, so nothing was written.
- `DESCRIBE HISTORY` shows: CREATE TABLE, ADD CONSTRAINT, WRITE (test row), DELETE, CHANGE COLUMN (comment fix).

Undo: `DROP TABLE workspace.referral_saathi.call_outcomes` (this also removes its MODIFY grant).

## 2. App resources

`databricks apps update referral-saathi --json @databricks/app_plumbing/app_resources.json`. That call
replaces the whole app spec, so the body also carries the existing description. `compute_size` cannot go in
this API (it is rejected), and it stayed MEDIUM.

| Resource key | Target | Permission |
|---|---|---|
| sql-warehouse | warehouse 6a2f5637720a2c17 | CAN_USE |
| serving-endpoint-text | databricks-meta-llama-3-3-70b-instruct | CAN_QUERY |
| serving-endpoint-vision | databricks-llama-4-maverick | CAN_QUERY |

Before the update, `resources` was null.

Undo: `databricks apps update referral-saathi --json '{"name": "referral-saathi", "description": "Referral
Saathi: evidence-backed facility referrals", "resources": []}'`. Then revert the deploy.sh change below
(otherwise `valueFrom` points at keys that no longer exist) and redeploy.

## 3. UC grants to the app service principal

Grants from `grants.sql`, confirmed with `SHOW GRANTS`:

| Privilege | Securable |
|---|---|
| USE CATALOG | catalog workspace |
| USE SCHEMA | schema workspace.referral_saathi |
| SELECT | schema workspace.referral_saathi (covers all its tables, including ones the loader replaces or adds) |
| MODIFY | table workspace.referral_saathi.call_outcomes only |

Undo, with SP = `` `3770ad65-e41d-4f22-8b7d-305dfc97dc1d` ``:

```
REVOKE MODIFY ON TABLE workspace.referral_saathi.call_outcomes FROM SP;
REVOKE SELECT ON SCHEMA workspace.referral_saathi FROM SP;
REVOKE USE SCHEMA ON SCHEMA workspace.referral_saathi FROM SP;
REVOKE USE CATALOG ON CATALOG workspace FROM SP;
```

## 4. Env vars in the generated app.yaml

`tools/deploy/deploy.sh` was changed only inside the app.yaml heredoc:

```
 command: ["python", "app/main.py"]
+env:
+  - name: DATABRICKS_WAREHOUSE_ID
+    valueFrom: sql-warehouse
+  - name: SERVING_ENDPOINT_TEXT
+    valueFrom: serving-endpoint-text
+  - name: SERVING_ENDPOINT_VISION
+    valueFrom: serving-endpoint-vision
 YAML
```

Undo: `cp build/databricks_staging/deploy.sh.before_plumbing tools/deploy/deploy.sh`, or delete those 7 lines.

## 5. Verification after redeploy

`SKIP_BUILD=1 bash tools/deploy/deploy.sh` printed `SUCCEEDED | App started successfully`. Results:

- `/api/ping` with a bearer token from `databricks auth token` returned HTTP 200 `{"ok":true}`.
- I ran a temporary check, then removed it. A copy of the bundle, with an extra route added, was deployed
  from a separate workspace folder. The route read the three env vars and ran a SELECT as the service
  principal (OAuth client credentials from the app's injected `DATABRICKS_CLIENT_ID` and
  `DATABRICKS_CLIENT_SECRET`). It returned HTTP 200 with:
  - env: `DATABRICKS_WAREHOUSE_ID=6a2f5637720a2c17`, `SERVING_ENDPOINT_TEXT=databricks-meta-llama-3-3-70b-instruct`,
    `SERVING_ENDPOINT_VISION=databricks-llama-4-maverick`
  - `SELECT current_user(), unique_id FROM workspace.referral_saathi.facility_trust LIMIT 1` SUCCEEDED, with
    the row `3770ad65-e41d-4f22-8b7d-305dfc97dc1d, 0001f41e-9db9-4e9f-a66e-a667d06e0e75`. The current user
    is the service principal.
- Then the normal source was redeployed with deploy.sh, and the check folder was deleted from the workspace
  and from `build/`. After that, `/api/ping` returned 200, `/api/_plumbing_check` returned 404, and the
  active deployment runs from `/Workspace/Users/<workspace-user>/referral-saathi-src`.

Not tested: serving endpoint calls from the app (CAN_QUERY is granted, but no request was made), and a
write to call_outcomes as the service principal.

## Notes

- `sql.sh` exits 1 with `KeyError: 'columns'` on statements that return no result set (DDL, GRANT). The
  statements still succeed. Every one of them here was confirmed with DESCRIBE or SHOW GRANTS.
- facility_trust's key column is `unique_id`. The task named the call_outcomes column `facility_id`, so it
  keeps that name and its comment says it holds the `unique_id`.
