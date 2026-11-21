# Databricks notebook source
# MAGIC %md
# MAGIC # The golden hour: referral journeys
# MAGIC Reproduces every chart in `viz/journeys/charts/` (see `viz/journeys/STORIES.md`).
# MAGIC Probabilities come from the derived/v1 stub (`planner/data_v1.py`), not the fitted model, until the model lands.
# MAGIC Locally it runs as a plain script: `.venv-viz/bin/python viz/journeys/notebook.py`.

# COMMAND ----------

# Config: where code, inputs and outputs live.
#   SOURCE = "local": read parquet and files from DATATHON_ROOT (default: the laptop checkout).
#   SOURCE = "uc":    read the tabular inputs from Unity Catalog tables (CATALOG.SCHEMA.<table>) and write them as
#                     parquet into DATATHON_ROOT (a Volume path) at the paths the scripts expect. Non-tabular inputs
#                     (kb/pathways/*.json, model/gold/queries.json, the WorldPop raster, LGD polygons, the PMNDP csv)
#                     must already be in that Volume with the same relative layout.
import os
import sys

SOURCE = os.environ.get("JOURNEYS_SOURCE", "local")
CODE = os.environ.get("DATATHON_CODE", "/Users/karthikvattem/projects/datathon")        # repo with planner/, geo/, viz/
DATA_ROOT = os.environ.get("DATATHON_ROOT", CODE)                                       # e.g. /Volumes/workspace/referral_saathi/files
OUT = os.environ.get("JOURNEYS_OUT", f"{CODE}/viz/journeys")
CATALOG, SCHEMA = "workspace", os.environ.get("JOURNEYS_SCHEMA", "referral_saathi")
RERUN_PLANNER = True      # False reuses data/plans_raw.json.gz and data/plans_best.csv

UC_TABLES = {             # relative parquet path -> Unity Catalog table name
    "derived/v1/claims.parquet": "claims",
    "derived/v1/grades.parquet": "grades",
    "derived/v1/data_point_scores.parquet": "data_point_scores",
    "derived/v1/facility_location.parquet": "facility_location",
    "derived/v1/pin_gazetteer.parquet": "pin_gazetteer",
    "kb/web_evidence/out/web_service_summary.parquet": "web_service_summary",
}

os.environ.update({"DATATHON_CODE": CODE, "DATATHON_ROOT": DATA_ROOT, "JOURNEYS_OUT": OUT, "TRAVEL_CACHE": "off"})
os.makedirs(f"{OUT}/data", exist_ok=True)
os.makedirs(f"{OUT}/charts", exist_ok=True)

if SOURCE == "uc":
    for rel, table in UC_TABLES.items():
        dest = os.path.join(DATA_ROOT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        spark.table(f"{CATALOG}.{SCHEMA}.{table}").toPandas().to_parquet(dest, index=False)  # noqa: F821 (Databricks global)
        print("materialised", table, "->", dest)
elif SOURCE != "local":
    raise ValueError(f"SOURCE must be 'local' or 'uc', got {SOURCE!r}")

sys.path.insert(0, f"{CODE}/viz/journeys/scripts")
print("code", CODE, "| data", DATA_ROOT, "| out", OUT, "| source", SOURCE)

# COMMAND ----------

# Planner runs: 40 benchmark queries + 150 PIN centroids each in Bihar, Uttar Pradesh, Maharashtra, x 7 pathways.
import run_plans  # noqa: E402

if RERUN_PLANNER:
    run_plans.main()

# COMMAND ----------

# Story 1: direct vs stop vs abstain, and what a stabilising stop buys.
import s1_plan_mix  # noqa: E402

s1_plan_mix.main()

# COMMAND ----------

# Story 2: time to definitive care, with the travel estimate's range.
import s2_time_to_care  # noqa: E402

s2_time_to_care.main()

# COMMAND ----------

# Story 3: three real itineraries with evidence quotes.
import s3_itineraries  # noqa: E402

s3_itineraries.main()

# COMMAND ----------

# Story 4: the invisible service (snakebite).
import s4_snakebite  # noqa: E402

s4_snakebite.main()

# COMMAND ----------

# Story 5: dialysis travel burden by district.
import s5_dialysis  # noqa: E402

s5_dialysis.main()

# COMMAND ----------

# Story 6: the funnel to one hospital.
import s6_funnel  # noqa: E402

s6_funnel.main()

# COMMAND ----------

# Outputs
import glob  # noqa: E402

charts = sorted(glob.glob(f"{OUT}/charts/*.png"))
print(len(charts), "charts:", *[os.path.basename(c) for c in charts], sep="\n  ")
try:
    from IPython.display import Image, display  # inline in Databricks / Jupyter
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:
        for c in charts:
            display(Image(filename=c))
except ImportError:
    pass
