"""Input paths and the loader every story script in viz/model uses.

A story's build(load, out) receives `load(name)`: a DataFrame for parquet inputs, a dict for JSON.
Locally that reads the files below. notebook.py swaps in a loader that reads Unity Catalog tables
when it runs on Databricks. All inputs are read only.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "viz/model"
sys.path.insert(0, str(ROOT / "viz"))

FUSION = "model/proto/fusion"
PATHS = {
    # model outputs (no labels)
    "pair_contributions": f"{FUSION}/pair_contributions.parquet",
    "pair_scores": f"{FUSION}/pair_scores.parquet",
    "facility_contributions": f"{FUSION}/facility_contributions.parquet",
    "facility_scores": f"{FUSION}/facility_scores.parquet",
    "variant_scores": f"{FUSION}/variant_scores.parquet",
    "weights": f"{FUSION}/weights.parquet",
    "platt": f"{FUSION}/platt.json",
    "atoms": f"{FUSION}/atoms.parquet",
    "llm_b3_pairs": "model/proto/decision/llm_b3_pairs.parquet",
    "llm_b3_stats": "model/proto/decision/llm_b3_stats.json",
    "cases": "model/review/explain/cases.json",
    # published evaluation results (quoted, never recomputed)
    "results": "model/review/stats/results.json",
    "test_metrics": f"{FUSION}/test_metrics.json",
}


POINTS_PER_LOGIT = 20 / 0.6931471805599453  # +20 points doubles the odds (MODEL_SPEC 3.2)

# Service-head terms grouped into the families the App's level-2 waterfall shows.
FAMILY_ORDER = ["base", "text", "hints", "flags", "web", "type_size"]
FAMILY_LABEL = {"base": "Base rate for the service", "text": "Own service text",
                "hints": "Related-service hints", "flags": "Contamination, non-offer, scope",
                "web": "Web footprint", "type_size": "Facility type and size"}


def family(term):
    t = term.split("@")[0]
    if t.startswith("b_") or t == "platt_offset":
        return "base"
    if t in ("t1", "t2", "t3", "t4", "t5", "tb_mid", "tb_high", "trunc0"):
        return "text"
    if t in ("p1", "p2"):
        return "hints"
    if t in ("c1", "c2", "n1", "s1"):
        return "flags"
    if t in ("g_mid", "g_high"):
        return "web"
    return "type_size"


def local_load(name):
    p = ROOT / PATHS[name]
    if p.suffix == ".json":
        return json.loads(p.read_text())
    return pd.read_parquet(p)


def source(*names):
    """'Source: a; b' line naming the files a chart read."""
    return "Source: " + "; ".join(PATHS[n] for n in names)
