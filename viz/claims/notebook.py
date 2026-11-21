# Databricks notebook source
# MAGIC %md
# MAGIC # What facilities say vs what we can confirm
# MAGIC Six data stories on the Virtue Foundation facility records: the specialty long tail, claim inflation, the
# MAGIC confirmation funnel, official lists, facility websites, and hours. Each cell rebuilds one story's charts
# MAGIC (PNG at 2x, SVG, alt text) and tidy CSVs under `viz/claims/charts` and `viz/claims/data`.
# MAGIC Run locally with `.venv-viz/bin/python viz/claims/notebook.py`. Write-up: `viz/claims/STORIES.md`.

# COMMAND ----------

# Config. Inputs are read through claims_io.read(name). Locally they come from the parquet / CSV / JSON paths in
# claims_io.INPUTS. On Databricks, set ROOT to the repo checkout in Workspace files and map any input that lives in
# Unity Catalog to its table in UC_TABLES; unmapped inputs are read from files under ROOT.
import os
import sys

ROOT = os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon")
os.environ["DATATHON_ROOT"] = ROOT
sys.path.insert(0, f"{ROOT}/viz/claims")

import claims_io as io  # noqa: E402

UC_TABLES = {
    # Example mapping (uncomment the ones uploaded to the workspace):
    # "claims": "workspace.vf.claims",
    # "facility_location": "workspace.vf.facility_location",
    # "facilities_raw": "workspace.default.vf_facilities",
}
io.UC_TABLES.update(UC_TABLES)
missing = [k for k, p in io.INPUTS.items() if k not in io.UC_TABLES and not p.exists()]
assert not missing, f"inputs not found locally and not mapped to Unity Catalog: {missing}"
print("inputs ok:", len(io.INPUTS), "| from Unity Catalog:", sorted(io.UC_TABLES) or "none")

# COMMAND ----------

# Story 1: 2,933 specialty values, a long tail, and the type-default tags at its head
import s1_longtail  # noqa: E402

st1 = s1_longtail.main()

# COMMAND ----------

# Story 2: claim inflation, services claimed against stated size
import s2_inflation  # noqa: E402

st2 = s2_inflation.main()

# COMMAND ----------

# Story 3: confirmation funnel for the 7 core services
import s3_funnel  # noqa: E402

s3_funnel.main()

# COMMAND ----------

# Story 4: official lists vs the dataset (NABH, e-RaktKosh, LaQshya, MoHFW trauma) and PMNDP by state
import s4_lists  # noqa: E402

s4_lists.main()

# COMMAND ----------

# Story 5: facility websites vs the dataset (asserts it re-derives kb/web_evidence/out/compare_by_service.csv)
import s5_web  # noqa: E402

s5_web.main()

# COMMAND ----------

# Story 6: hours and 24x7 evidence by source
import s6_hours  # noqa: E402

s6_hours.main()

# COMMAND ----------

# Check: every chart has its PNG, SVG and alt text, and every CSV is non-empty
import pandas as pd  # noqa: E402

charts = ["s1_longtail", "s1_default_tags", "s2_inflation", "s3_funnel", "s4_lists", "s4_pmndp",
          "s5_web_by_service", "s5_why_unconfirmed", "s6_hours"]
for c in charts:
    for ext in (".png", ".svg", ".txt"):
        p = io.CHARTS / f"{c}{ext}"
        assert p.exists() and p.stat().st_size > 0, p
for p in sorted(io.DATA.glob("*.csv")):
    assert len(pd.read_csv(p)) > 0, p
print(f"{len(charts)} charts and {len(list(io.DATA.glob('*.csv')))} CSVs written to {io.HERE}")
