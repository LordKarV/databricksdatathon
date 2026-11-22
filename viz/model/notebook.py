# Databricks notebook source
# MAGIC %md
# MAGIC # How the model decides: chart notebook
# MAGIC Reproduces every chart in viz/model (stories 1 to 5) from the Witness Ledger outputs.
# MAGIC Locally it reads the parquet and JSON files listed in `_inputs.PATHS`. On Databricks it reads the
# MAGIC Unity Catalog tables in `UC_TABLES` and the published JSON results from `UC_VOLUME`.
# MAGIC Sealed test rule: this notebook never touches gold labels; story 3 and 4 only quote the published
# MAGIC numbers in results.json and test_metrics.json.

# COMMAND ----------

# Config: where inputs come from and where charts go.
import json
import os
import sys
from pathlib import Path

import pandas as pd

ON_DATABRICKS = "DATABRICKS_RUNTIME_VERSION" in os.environ
ROOT = Path(os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon"))
CODE_DIR = ROOT / "viz/model"            # story scripts; on Databricks point DATATHON_ROOT at the repo folder
OUT = Path(os.environ.get("VIZ_MODEL_OUT", "/tmp/viz_model" if ON_DATABRICKS else str(CODE_DIR)))

# Unity Catalog mode (MODEL_SPEC 3.6 schema workspace.vf_ledger). Assumes NB01_register loaded these tables
# from the same parquet files; JSON results are read from a volume. Not run on Databricks yet.
UC_SCHEMA = "workspace.vf_ledger"
UC_TABLES = {"pair_contributions": "pair_contributions", "pair_scores": "pair_scores",
             "facility_contributions": "facility_contributions", "facility_scores": "facility_scores",
             "variant_scores": "variant_scores", "weights": "weights", "atoms": "claim_atoms",
             "llm_b3_pairs": "llm_b3_pairs"}
UC_VOLUME = f"/Volumes/{UC_SCHEMA.replace('.', '/')}/inputs"

sys.path.insert(0, str(CODE_DIR))
sys.path.insert(0, str(ROOT / "viz"))
import _inputs as I  # noqa: E402


def uc_load(name):
    if name in UC_TABLES:
        return spark.table(f"{UC_SCHEMA}.{UC_TABLES[name]}").toPandas()  # noqa: F821 (Databricks global)
    p = Path(UC_VOLUME) / Path(I.PATHS[name]).name
    return json.loads(p.read_text()) if p.suffix == ".json" else pd.read_parquet(p)


load = uc_load if ON_DATABRICKS and os.environ.get("VIZ_INPUT", "uc") == "uc" else I.local_load
OUT.mkdir(parents=True, exist_ok=True)
print("inputs:", "Unity Catalog" if load is uc_load else "local files", "| charts ->", OUT)

# COMMAND ----------

# MAGIC %md ## Story 1. The witness ledger: three real cases as points waterfalls

# COMMAND ----------

import s1_ledger  # noqa: E402

for c in s1_ledger.build(load, OUT):
    print(c["case"], c["name"], f"P_S {c['p_s']:.3f}", f"P_L {c['p_l']:.3f}", f"rank {c['rank']} of {c['n_cand']}")

# COMMAND ----------

# MAGIC %md ## Story 2. The LLM judge said yes 239 of 243 times

# COMMAND ----------

import s2_llm_judge  # noqa: E402

print(s2_llm_judge.build(load, OUT))

# COMMAND ----------

# MAGIC %md ## Story 3. Honest evaluation (published sealed-test numbers)

# COMMAND ----------

import s3_evaluation  # noqa: E402

print(s3_evaluation.build(load, OUT)[["system", "auroc_all71", "lo", "hi"]].round(3).to_string(index=False))

# COMMAND ----------

# MAGIC %md ## Story 4. The label problem

# COMMAND ----------

import s4_labels  # noqa: E402

print(s4_labels.build(load, OUT).to_string(index=False))

# COMMAND ----------

# MAGIC %md ## Story 5. What each evidence family contributes

# COMMAND ----------

import s5_families  # noqa: E402

print(s5_families.build(load, OUT)[["T", "n_pairs", "text", "hints", "p_s_median"]].round(2).to_string(index=False))

# COMMAND ----------

# Check: every chart has its png, svg, alt text and csv.
expected = ["s1_service_waterfalls", "s1_location_waterfalls", "s2_llm_vs_ledger", "s3_auroc_forest",
            "s3_calibration_location", "s4_label_budget", "s4_label_agreement", "s5_points_by_text_level",
            "s5_prior_vs_fitted"]
missing = [f"{s}{ext}" for s in expected for ext in (".png", ".svg", ".txt") if not (OUT / f"{s}{ext}").exists()]
assert not missing, missing
assert len(list(OUT.glob("s*.csv"))) >= len(expected)
print(f"{len(expected)} charts written to {OUT}")
