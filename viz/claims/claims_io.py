"""Inputs and shared definitions for the "what facilities say vs what we can confirm" stories.

Every story script reads through `read(name)`, so the Databricks notebook can point the same code at
Unity Catalog tables by filling `UC_TABLES` (name -> catalog.schema.table) before running a story.
Nothing here writes outside viz/claims.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get("DATATHON_ROOT", "/Users/karthikvattem/projects/datathon"))
HERE = ROOT / "viz" / "claims"
CHARTS = HERE / "charts"
DATA = HERE / "data"
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

EXT = ROOT / "data" / "external"
WEB = ROOT / "kb" / "web_evidence" / "out"
INPUTS = {
    "specialty_map": ROOT / "kb/taxonomy/specialty_map.csv",
    "services": ROOT / "kb/taxonomy/services.json",
    "lexicon_matches": ROOT / "kb/taxonomy/out/lexicon_matches.parquet",
    "pair_features": ROOT / "model/proto/evidence/pair_features.parquet",
    "claims": ROOT / "derived/v1/claims.parquet",
    "specialties": ROOT / "derived/v1/specialties.parquet",
    "facility_location": ROOT / "derived/v1/facility_location.parquet",
    "facilities_raw": ROOT / "data/raw/facilities.parquet",
    "site_identity": WEB / "site_identity.parquet",
    "web_services": WEB / "web_services.parquet",
    "web_service_summary": WEB / "web_service_summary.parquet",
    "web_facility_details": WEB / "web_facility_details.parquet",
    "compare_by_service": WEB / "compare_by_service.csv",
    "web_qa": ROOT / "kb/web_evidence/qa/out/qa_results.json",
    "vf_details": ROOT / "kb/vf_details/out/facility_details.parquet",
    "opendata_facts": ROOT / "kb/opendata/vf_opendata_facts.parquet",
    "nabh_match": EXT / "nabh_accredited/nabh_vf_match.parquet",
    "nabh_stats": EXT / "nabh_accredited/match_stats.json",
    "erk_match": EXT / "eraktkosh_blood_centres/erk_vf_matches.parquet",
    "erk_stats": EXT / "eraktkosh_blood_centres/join_stats.json",
    "laqshya_match": EXT / "laqshya_master/laqshya_vf_matches.parquet",
    "laqshya_facilities": EXT / "laqshya_master/laqshya_facilities.parquet",
    "tcf_match": EXT / "mohfw_trauma_196/tcf_vf_matches.csv",
    "tcf_list": EXT / "mohfw_trauma_196/tcf_196.csv",
    "nmc_match": EXT / "nmc_colleges/nmc_vf_matches.parquet",
    "nmc_labels": EXT / "nmc_colleges/nmc_service_labels.parquet",
    "pmndp_states": EXT / "pmndp_counts_and_state_lists/pmndp_state_counts.csv",
}
# Filled by the notebook's config cell on Databricks, e.g. {"claims": "workspace.vf.claims"}.
UC_TABLES: dict[str, str] = {}


def rel(name: str) -> str:
    """Input path relative to the project root, for source notes on charts."""
    return str(INPUTS[name].relative_to(ROOT))


def read(name: str, columns=None):
    """Read one input as a DataFrame (or dict for .json), from Unity Catalog when mapped there."""
    if name in UC_TABLES:
        from pyspark.sql import SparkSession  # only on Databricks
        df = SparkSession.builder.getOrCreate().table(UC_TABLES[name])
        return (df.select(*columns) if columns else df).toPandas()
    p = INPUTS[name]
    if p.suffix == ".json":
        return json.loads(p.read_text())
    if p.suffix == ".csv":
        return pd.read_csv(p, keep_default_na=False, usecols=columns) if name == "specialty_map" else pd.read_csv(p, usecols=columns)
    return pd.read_parquet(p, columns=columns)


def service_ids() -> list[str]:
    return [s["id"] for c in read("services")["categories"] for s in c["services"]]


def facilities() -> pd.DataFrame:
    """One row per usable record (9,959): type, operator, beds, doctors, specialties count, state."""
    f = read("pair_features", ["unique_id", "name", "facility_type", "operator_public", "public_level", "beds",
                               "doctors", "n_specialties", "list_truncated"]).drop_duplicates("unique_id")
    loc = read("facility_location", ["unique_id", "state_final"])
    out = f.merge(loc, on="unique_id", how="left")
    assert len(out) == 9959 and out.unique_id.is_unique, len(out)
    return out


def raw_specialties() -> pd.DataFrame:
    """(unique_id, raw specialty string) pairs from the raw JSON arrays, usable records only."""
    raw = read("facilities_raw", ["unique_id", "specialties"]).drop_duplicates("unique_id")
    ok = set(facilities().unique_id)
    rows = []
    for u, s in zip(raw.unique_id, raw.specialties):
        if u not in ok or not isinstance(s, str) or not s.startswith("["):
            continue
        try:
            vals = json.loads(s)
        except ValueError:
            continue
        rows += [(u, v) for v in set(vals) if isinstance(v, str)]
    return pd.DataFrame(rows, columns=["unique_id", "specialty"])


def dataset_claims() -> pd.DataFrame:
    """Dataset claims per (record, service), same rule as kb/web_evidence/compare_dataset.py:
    text_pos = a claim sentence with no non-offer cue, not attributed to another facility, not a staff or
    directory line; spec = a raw specialties value mapped to the service; text_any = any matched sentence.
    """
    m = read("lexicon_matches")
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility")
            & ~m.kind.isin(["staff", "directory"])]
    smap = read("specialty_map", ["specialty", "service_id"])
    smap = smap.assign(service_id=smap.service_id.str.split(";")).explode("service_id")
    sp = raw_specialties().merge(smap, on="specialty")
    ids = set(service_ids())
    key = lambda df, col: set(zip(df.unique_id, df[col]))  # noqa: E731
    t_any, t_pos, spec = key(m, "service"), key(pos, "service"), key(sp, "service_id")
    allk = sorted(k for k in t_any | spec if k[1] in ids)
    return pd.DataFrame([{"unique_id": u, "service_id": s, "text_any": (u, s) in t_any, "text_pos": (u, s) in t_pos,
                          "spec": (u, s) in spec} for u, s in allk])


def rate_row(k, n) -> dict:
    p, lo, hi = S.wilson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": p, "lo": lo, "hi": hi}


def save_csv(df: pd.DataFrame, name: str) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    p = DATA / f"{name}.csv"
    df.to_csv(p, index=False)
    return p


def chart_path(name: str) -> Path:
    CHARTS.mkdir(parents=True, exist_ok=True)
    return CHARTS / name


def spearman_ci(x, y, n_boot=1000, seed=7):
    """Spearman rho with a percentile bootstrap 95% interval."""
    from scipy.stats import spearmanr
    x, y = np.asarray(x, float), np.asarray(y, float)
    rho = spearmanr(x, y).statistic
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), (n_boot, len(x)))
    boots = [spearmanr(x[i], y[i]).statistic for i in idx]
    return rho, float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
