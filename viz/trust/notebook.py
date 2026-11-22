# Databricks notebook source
# MAGIC %md
# MAGIC # How wrong is the data?
# MAGIC Seven data stories about the Virtue Foundation facility records, reproduced end to end.
# MAGIC Each cell runs one story script from `viz/trust/` and writes its chart (PNG at 2x, SVG),
# MAGIC alt text (.txt) and tidy CSV to `viz/trust/out/`. Write-up: `viz/trust/STORIES.md`.

# COMMAND ----------

# Config: where the inputs come from.
# SOURCE = "local" reads parquet under REPO_ROOT (the default, and what runs on a laptop).
# SOURCE = "uc" reads <CATALOG>.<SCHEMA>.<table> with spark; the raw tables (facilities,
# india_post_pincode_directory) exist in the provided catalog, and any table that has not been
# uploaded falls back to the local parquet with a printed note. Table names: trust_io.PATHS.
import os
import sys

REPO_ROOT = os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon")
SOURCE = os.environ.get("TRUST_SOURCE", "local")
CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
SCHEMA = "virtue_foundation_dataset"
OUT_DIR = None  # None = REPO_ROOT/viz/trust/out

sys.path.insert(0, f"{REPO_ROOT}/viz/trust")
sys.path.insert(0, f"{REPO_ROOT}/viz")
import trust_io as io  # noqa: E402

io.set_root(REPO_ROOT, OUT_DIR)
io.set_source(SOURCE, spark=globals().get("spark"), catalog=CATALOG, schema=SCHEMA)
IN_DATABRICKS = "dbutils" in globals()


def show(name):
    """Display a saved chart inside Databricks; print its path when run as a script."""
    path = io.out(f"{name}.png")
    if IN_DATABRICKS:
        from IPython.display import Image, display
        display(Image(filename=str(path)))
    print(path)


# COMMAND ----------

# MAGIC %md ## Story 1: one record, two hospitals

# COMMAND ----------

import s1_merged  # noqa: E402

r1 = s1_merged.run()
show("s1_anatomy")
show("s1_who")

# COMMAND ----------

# MAGIC %md ## Story 2: the hospital that moved

# COMMAND ----------

import s2_moved  # noqa: E402

r2 = s2_moved.run()
show("s2_map")
show("s2_distance")

# COMMAND ----------

# MAGIC %md ## Story 3: strong-looking evidence is mostly wording

# COMMAND ----------

import s3_wording  # noqa: E402

r3 = s3_wording.run()
show("s3_wording")

# COMMAND ----------

# MAGIC %md ## Story 4: one phone number, 432 records

# COMMAND ----------

import s4_phones  # noqa: E402

r4 = s4_phones.run()
show("s4_phones")

# COMMAND ----------

# MAGIC %md ## Story 5: the coverage table vs what is usable

# COMMAND ----------

import s5_coverage  # noqa: E402

r5 = s5_coverage.run()
show("s5_coverage")

# COMMAND ----------

# MAGIC %md ## Story 6: what cleaning could and could not fix

# COMMAND ----------

import s6_cleaning  # noqa: E402

r6 = s6_cleaning.run()
show("s6_cleaning")

# COMMAND ----------

# MAGIC %md ## Story 7: follow the citation

# COMMAND ----------

import s7_citations  # noqa: E402

r7 = s7_citations.run()
show("s7_citations")

# COMMAND ----------

# Self-check: every chart has its PNG, SVG, alt text and CSV, and the headline numbers hold.
CHARTS = ["s1_anatomy", "s1_who", "s2_map", "s2_distance", "s3_wording", "s4_phones", "s5_coverage",
          "s6_cleaning", "s7_citations"]
missing = [f"{c}.{ext}" for c in CHARTS for ext in ("png", "svg", "txt", "csv") if not io.out(f"{c}.{ext}").exists()]
assert not missing, f"missing outputs: {missing}"
assert (r1["k"], r1["n"]) == (1232, 9959), r1
g = r2["grp"].set_index("group")
assert (g.loc["Own text says it is located elsewhere", "k"], g.loc["All other records", "k"]) == (723, 821)
assert r2["far"] == 1367 and r4["official_multi"] == 348
assert r6[1]["n_anon_sent"] == 7514
print("notebook self-check OK:", len(CHARTS), "charts")
