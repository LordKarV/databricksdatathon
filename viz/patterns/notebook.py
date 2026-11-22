# Databricks notebook source
# MAGIC %md
# MAGIC # Pattern discovery on the facility records
# MAGIC Seven systematic searches over the 9,959 usable Virtue Foundation records: service co-occurrence, facility
# MAGIC archetypes, correlates of data quality, district supply vs need, public vs private, anomalies and time.
# MAGIC Every pattern is found on a fixed random 70% of facilities (duplicate groups kept together, seed 20261121) and
# MAGIC re-measured on the other 30%; Benjamini-Hochberg runs across every test. Gold labels are never read.
# MAGIC Run locally with `.venv-viz/bin/python viz/patterns/notebook.py`. Write-up: `viz/patterns/PATTERNS.md`.

# COMMAND ----------

# Config. SOURCE = "local" reads every input from parquet under ROOT. SOURCE = "uc" reads the inputs listed in
# UC_TABLES from Unity Catalog (spark.table) and everything else from files under ROOT (the repo in Workspace files).
import os
import sys

ROOT = os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon")
SOURCE = os.environ.get("PATTERNS_SOURCE", "local")
sys.path.insert(0, f"{ROOT}/viz/patterns")

import common  # noqa: E402

UC_TABLES = {
    "derived/v1/facility_location.parquet": "workspace.parchi.facility_location",
    "derived/v1/record_trust.parquet": "workspace.parchi.record_trust",
    "derived/v1/facility_groups.parquet": "workspace.parchi.facility_groups",
    "derived/v1/claims.parquet": "workspace.parchi.claims",
    "derived/v1/grades.parquet": "workspace.parchi.grades",
}
if SOURCE == "uc":
    common.UC_TABLES.update(UC_TABLES)
print("source:", SOURCE, "| from Unity Catalog:", sorted(common.UC_TABLES) or "none")

# COMMAND ----------

# Build the facility table (one row per record) and the facility x 36 service matrix; assign the 70/30 split.
import p0_build  # noqa: E402

p0_build.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Service co-occurrence
# MAGIC Lift with bootstrap intervals for every pair of services with at least 30 claiming facilities, a hand-written
# MAGIC list of clinical pathways to judge the top pairs, and whether an off-focus claim (an eye or dental name
# MAGIC claiming acute care) predicts contamination once claim breadth is held fixed.

# COMMAND ----------

import p1_cooccurrence  # noqa: E402

p1_cooccurrence.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Facility archetypes (k-means, k chosen by silhouette and bootstrap stability)

# COMMAND ----------

import p2_archetypes  # noqa: E402

p2_archetypes.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Correlates of contamination, location drift and claim breadth (multivariable GLMs)

# COMMAND ----------

import p3_quality  # noqa: E402

p3_quality.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. District supply vs NFHS-5 need
# MAGIC Ecological correlations: they describe districts, never a facility or a person.

# COMMAND ----------

import p4_district  # noqa: E402

p4_district.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Public vs private hospitals

# COMMAND ----------

import p5_public_private  # noqa: E402

p5_public_private.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Anomalies (isolation forest; the top 20 hand verdicts are in data/p6_top20_classified.csv)

# COMMAND ----------

import p6_anomalies  # noqa: E402

p6_anomalies.main()
p6_anomalies.chart()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Year of establishment

# COMMAND ----------

import p7_time  # noqa: E402

p7_time.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Multiple comparisons and replication
# MAGIC Benjamini-Hochberg over every registered test; replicated = significant, same direction on the holdout and
# MAGIC the holdout 95% interval excludes the null.

# COMMAND ----------

import p9_multiple  # noqa: E402

tests = p9_multiple.main()
HEADLINES = ["p2_public_contaminated", "p3_contaminated_log2_urls", "p5_contaminated_adj", "p5_site_alive_adj",
             "p5_pmjay_adj", "p3_drift50_pmjay", "p3_drift50_nabh_listed", "p3_contaminated_C(web, Treatment('alive'))[T.none]",
             "p1_suspicious_contaminated", "p4_raw_all_pm_institutional_birth_5y_pct",
             "p4_partial_urban_dialysis_corr_pm_w15_plus_with_high_bp_sys_gte_140_mmhg_a", "p7_age_contaminated",
             "p7_age_contaminated_unadjusted", "p6_top5_contaminated"]
cols = ["test_id", "effect_type", "effect", "lo", "hi", "q", "ho_effect", "ho_lo", "ho_hi", "replicated"]
print(tests.set_index("test_id").loc[HEADLINES].reset_index()[cols].round(3).to_string())
