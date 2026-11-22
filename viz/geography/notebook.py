# Databricks notebook source
# MAGIC %md
# MAGIC # Where care is missing
# MAGIC Six data stories about where facility evidence exists in India and where it does not, built from the
# MAGIC Virtue Foundation facility records, NFHS-5, WorldPop 2025, the MAP 2020 friction surface and public
# MAGIC government lists. Every chart says "no evidence in this dataset", never "no care".
# MAGIC Run top to bottom; locally `python notebook.py` reproduces every chart in `charts/`.

# COMMAND ----------

# Config: where inputs come from. "local" reads the parquet and raster files listed in common.P.
# "uc" reads the tabular inputs from Unity Catalog tables into pandas first (rasters and polygons must
# still be files, for example in a UC volume; set RASTER_ROOT). Nothing is written to Databricks.
import os
import sys
from pathlib import Path

SOURCE = os.environ.get("GEO_SOURCE", "local")          # "local" or "uc"
ROOT = Path(os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon"))
HERE = ROOT / "viz" / "geography"
UC_TABLES = {                                             # common.P key -> Unity Catalog table
    "nfhs": "workspace.datathon.nfhs_5_district_health_indicators",
    "loc": "workspace.datathon.facility_location",
    "groups": "workspace.datathon.facility_groups",
    "raw": "workspace.datathon.facilities",
    "lex": "workspace.datathon.lexicon_matches",
    "web": "workspace.datathon.web_service_summary",
    "osm_facts": "workspace.datathon.vf_opendata_facts",
}
RASTER_ROOT = os.environ.get("RASTER_ROOT")               # e.g. /Volumes/workspace/external/geo

sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

if SOURCE == "uc":
    tmp = Path("/tmp/geo_inputs")
    tmp.mkdir(exist_ok=True)
    for key, table in UC_TABLES.items():
        out = tmp / f"{key}.parquet"
        spark.table(table).toPandas().to_parquet(out)  # noqa: F821 (spark exists on Databricks)
        C.P[key] = out
    if RASTER_ROOT:
        for key in ("wp_total", "wp_f", "lgd", "crosswalk", "friction", "map_tt"):
            C.P[key] = Path(RASTER_ROOT) / Path(str(C.P[key])).name
print({k: str(v) for k, v in C.P.items()})


def show(name):
    """display() the PNG on Databricks; print the path locally."""
    p = C.CHARTS / f"{name}.png"
    try:
        from IPython.display import Image, display
        display(Image(filename=str(p)))
    except Exception:
        print("chart:", p)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shared inputs and checks
# MAGIC Population grid, LGD district assignment (aggregation only, never drawn), settlement classes,
# MAGIC facility evidence flags, then the raster travel-time solver checked against measured OSRM routes.

# COMMAND ----------

C.selfcheck()
import travel_check  # noqa: E402

travel_check.main()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Records per million people (Bihar)

# COMMAND ----------

import s1_density  # noqa: E402

s1_density.main()
show("s1_state_density")
show("s1_district_dots")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Dialysis need against confirmed supply

# COMMAND ----------

import s2_dialysis  # noqa: E402

s2_dialysis.main()
show("s2_dialysis_need_access")
show("s2_public_vs_dataset")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Caesarean access against caesarean rates

# COMMAND ----------

import s3_csection  # noqa: E402

s3_csection.main()
show("s3_csection_access")
show("s3_public_private")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. The golden hour

# COMMAND ----------

import s4_golden_hour  # noqa: E402

s4_golden_hour.main()
show("s4_golden_hour")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Urban and rural

# COMMAND ----------

import s5_urban_rural  # noqa: E402

s5_urban_rural.main()
show("s5_urban_rural")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. What "confirmed" measures

# COMMAND ----------

import s6_website_test  # noqa: E402

s6_website_test.main()
show("s6_website_test")

# COMMAND ----------

# Every chart must ship with PNG, SVG, alt text and its CSV.
expected = ["s1_state_density", "s1_district_dots", "s2_dialysis_need_access", "s2_public_vs_dataset",
            "s3_csection_access", "s3_public_private", "s4_golden_hour", "s5_urban_rural", "s6_website_test"]
for n in expected:
    for ext in ("png", "svg", "txt"):
        assert (C.CHARTS / f"{n}.{ext}").exists(), f"missing {n}.{ext}"
print(f"all {len(expected)} charts present with png, svg and alt text")
