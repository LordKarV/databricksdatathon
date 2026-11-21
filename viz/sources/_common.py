# Config and shared helpers for the "Who said so?" source stories.
# make_notebook.py copies this file verbatim into the first cell of notebook.py.
import json
import math
import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "viz" / "sources"
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

# Set UC_SCHEMA (for example "workspace.referral_saathi") to read the same tables from Unity Catalog
# with spark.table(); None reads the local parquet files below.
UC_SCHEMA = None
INPUTS = {
    "source_urls": ROOT / "derived/v1/source_urls.parquet",
    "source_classes": ROOT / "derived/v1/source_classes.parquet",
    "source_domains": ROOT / "derived/v1/source_domains.parquet",
    "source_page_checks": ROOT / "derived/v1/source_page_checks.parquet",
    "claims": ROOT / "derived/v1/claims.parquet",
    "q1_records": ROOT / "audit/provenance/q1_records.parquet",
    "handcheck_research_lang": ROOT / "audit/provenance/handcheck_research_lang.csv",
}
SEED = 20261121
N_BOOT = 2000


def load(name, columns=None):
    """One input table as pandas, from Unity Catalog when UC_SCHEMA is set, else local parquet."""
    if UC_SCHEMA:
        sdf = spark.table(f"{UC_SCHEMA}.{name}")  # noqa: F821  (spark exists on Databricks)
        return (sdf.select(*columns) if columns else sdf).toPandas()
    path = INPUTS[name]
    if path.suffix == ".csv":
        return pd.read_csv(path, usecols=columns)
    return pd.read_parquet(path, columns=columns)


def src(*names):
    """Source line for a chart: the files each input came from."""
    return "Source: " + "; ".join(str(INPUTS[n].relative_to(ROOT)) for n in names)


PRETTY = {
    "health_aggregator": "Health aggregators", "social": "Social media", "official": "Facility's own site",
    "business_dir": "Business directories", "other_health_site": "Other health sites", "other": "Unclassified",
    "insurance_scheme": "Insurance and scheme lists", "maps_geo": "Maps", "official_like": "Own site (likely)",
    "government": "Government portals", "research": "Research papers", "wikipedia": "Wikipedia",
    "news": "News", "education": "Education sites", "docs_repo": "Document hosts",
    "crowdfunding_ngo": "Crowdfunding and NGO",
}

SIZE_BANDS = [0, 5, 10, 20, 50]
SIZE_LABELS = ["1-5", "6-10", "11-20", "21-50"]


def size_band(n_urls):
    return pd.cut(n_urls, SIZE_BANDS, labels=SIZE_LABELS)


def weighted_rate_ci(y, w, n_boot=N_BOOT, seed=SEED):
    """Weighted mean of 0/1 outcome y with weights w, and a 95% Poisson-bootstrap interval over rows."""
    y, w = np.asarray(y, float), np.asarray(w, float)
    keep = w > 0
    y, w = y[keep], w[keep]
    p = (w * y).sum() / w.sum()
    rng = np.random.default_rng(seed)
    reps = []
    for _ in range(n_boot):
        k = rng.poisson(1.0, len(w))
        d = (k * w).sum()
        if d > 0:
            reps.append((k * w * y).sum() / d)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return p, lo, hi


def cluster_rate_ci(df, flag, cluster, n_boot=N_BOOT, seed=SEED):
    """Rate of boolean column `flag` with a 95% bootstrap interval that resamples whole clusters."""
    g = df.groupby(cluster)[flag].agg(["sum", "size"])
    k, n = g["sum"].to_numpy(float), g["size"].to_numpy(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), (n_boot, len(g)))
    reps = k[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return k.sum() / n.sum(), lo, hi, int(k.sum()), int(n.sum()), len(g)


def write_csv(df, stem):
    path = OUT / f"{stem}.csv"
    df.to_csv(path, index=False)
    return path
