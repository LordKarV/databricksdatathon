# Databricks notebook source
# MAGIC %md
# MAGIC # Planner against the gold DEV labels
# MAGIC When the multi-stop planner picks a definitive facility, is it one the gold labels confirm?
# MAGIC This notebook runs `planner/eval_gold_dev.py` (see `planner/EVAL_GOLD_DEV.md` for the method and limits).
# MAGIC
# MAGIC - Only gold pairs with `split = 'dev'` are read. TEST pairs are never read.
# MAGIC - Probabilities are the derived/v1 stub (`planner/data_v1.py`), not the fitted model.
# MAGIC - Travel is the `geo/travel.py` estimate; no network calls.
# MAGIC - The scheduled-plan ranking (least travel first) was chosen after seeing these DEV results, so only the
# MAGIC   sealed TEST counts as independent evidence for it.
# MAGIC
# MAGIC Locally it runs as a plain script: `.venv/bin/python planner/eval_gold_dev_notebook.py`.
# MAGIC Status: the local path was run on a laptop checkout. The Unity Catalog path (`PLANNER_EVAL_SOURCE=uc`) is
# MAGIC written against the table names in `databricks/README.md` and has NOT been run on a workspace.

# COMMAND ----------

# Config.
#   SOURCE = "local": read derived/v1/*.parquet from the repo checkout.
#   SOURCE = "uc":    read the same tables from Unity Catalog (CATALOG.SCHEMA.<table>) and write them as parquet
#                     under WORK/derived/v1, where the planner code looks for them.
#   CODE:  the folder that holds planner/, geo/ and kb/ (the repo root). Locally it is found from this file.
#          On Databricks set DATATHON_CODE to the workspace or Volume path of the repo.
import os
import sys
import tempfile

SOURCE = os.environ.get("PLANNER_EVAL_SOURCE", "local")
CATALOG, SCHEMA = os.environ.get("PLANNER_EVAL_CATALOG", "workspace"), os.environ.get("PLANNER_EVAL_SCHEMA", "referral_saathi")
try:
    _here = os.path.dirname(os.path.abspath(__file__))        # plain script
    CODE = os.environ.get("DATATHON_CODE") or os.path.dirname(_here)
except NameError:                                             # a Databricks notebook has no __file__
    CODE = os.environ.get("DATATHON_CODE")
    if not CODE:
        raise SystemExit("set DATATHON_CODE to the folder that holds planner/, geo/ and kb/")
WORK = os.environ.get("PLANNER_EVAL_WORK") or tempfile.mkdtemp(prefix="planner_eval_")
UC_TABLES = ["gold_pairs", "grades", "facility_location", "pin_gazetteer", "claims", "data_point_scores"]

if SOURCE == "uc":
    os.makedirs(os.path.join(WORK, "derived", "v1"), exist_ok=True)
    for table in UC_TABLES:
        dest = os.path.join(WORK, "derived", "v1", f"{table}.parquet")
        df = spark.table(f"{CATALOG}.{SCHEMA}.{table}")  # noqa: F821 (Databricks global)
        if table == "gold_pairs":
            df = df.where("split = 'dev'")               # TEST rows never leave the table
        df.toPandas().to_parquet(dest, index=False)
        print("materialised", table, "->", dest)
    os.environ["DATATHON_ROOT"] = WORK
elif SOURCE != "local":
    raise SystemExit(f"PLANNER_EVAL_SOURCE must be 'local' or 'uc', got {SOURCE!r}")

# outputs go to the work folder, so a read-only code folder is fine
os.environ.setdefault("PLANNER_OUT", os.path.join(WORK, "planner_out"))
os.environ.setdefault("PLANNER_EVAL_OUT", os.path.join(WORK, "planner_eval_out"))
os.environ["TRAVEL_CACHE"] = "off"
sys.path.insert(0, CODE)
print("source:", SOURCE, "| code:", CODE, "| work:", WORK)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Build the planner inputs
# MAGIC `planner/export_v1.py` writes the facility list, the stub probability per capability, the PIN centroids and,
# MAGIC when the e-RaktKosh outputs are under the data root, the blood-centre list.

# COMMAND ----------

from planner import export_v1  # noqa: E402

export_v1.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Run the planner at every gold DEV facility
# MAGIC The query sits on the gold facility. The planner is run without and with implied capabilities; the
# MAGIC baseline is the nearest facility whose record mentions the service.

# COMMAND ----------

from planner import eval_gold_dev  # noqa: E402

result = eval_gold_dev.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Result
# MAGIC Shares carry 95% Wilson intervals. With 4 contradicted pairs every interval on that row is wide.

# COMMAND ----------

import pandas as pd  # noqa: E402


def cell(r):
    return "none" if r["n"] == 0 else f"{r['k']} of {r['n']} ({r['share']:.2f}, {r['ci95'][0]:.2f} to {r['ci95'][1]:.2f})"


def column(s):
    by = s["picks_gold_facility_by_gold_verdict"]
    v = s["picked_verdict"]
    return {"Queries": s["queries"], "Abstained": s["abstained"],
            "Picks the gold facility when confirmed": cell(by["confirmed"]),
            "Picks the gold facility when contradicted": cell(by["contradicted"]),
            "Picks the gold facility when no information": cell(by["no_info"]),
            "Picked a confirmed facility": v["confirmed"]["k"], "Picked a contradicted facility": v["contradicted"]["k"],
            "Picked a facility with no DEV label": v["unknown"]["k"],
            "Confirmed, among picks with a clear label": cell(s["confirmed_among_picks_with_a_clear_label"])}


o = result["overall"]
summary = pd.DataFrame({"Planner without implications": column(o["planner_without_implications"]),
                        "Planner": column(o["planner"]), "Nearest mention": column(o["nearest_mention"])})
by_pathway = pd.DataFrame({p: {"Planner: gold facility when confirmed": cell(b["planner"]["picks_gold_facility_by_gold_verdict"]["confirmed"]),
                               "Planner: gold facility when contradicted": cell(b["planner"]["picks_gold_facility_by_gold_verdict"]["contradicted"]),
                               "Nearest mention: when confirmed": cell(b["nearest_mention"]["picks_gold_facility_by_gold_verdict"]["confirmed"]),
                               "Nearest mention: when contradicted": cell(b["nearest_mention"]["picks_gold_facility_by_gold_verdict"]["contradicted"])}
                           for p, b in result["by_pathway"].items()}).T
missed = result["confirmed_but_not_picked"]
print("gold DEV pairs used:", result["pairs_used"], "| verdicts:", result["gold_verdicts"])
print("blood from the blood-centre list:", result["blood_from_list"])
print("confirmed but not picked:", missed["n"], "| never a candidate:", missed["not_a_candidate"],
      "| missing capability:", missed["not_a_candidate_by_missing_capability"])
try:
    display(summary)      # noqa: F821 (Databricks global)
    display(by_pathway)   # noqa: F821
except NameError:
    print(summary.to_string())
    print(by_pathway.to_string())
