"""Inputs and outputs for the "How wrong is the data?" stories.

Every story script reads its tables through load(key) so that notebook.py can
switch the source from local parquet (default) to Unity Catalog tables with
set_source("uc", spark, catalog, schema). Only the three raw tables exist in
the provided catalog today; the derived tables are read from local parquet
unless they have been uploaded under the same names.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "viz" / "trust"
OUT = HERE / "out"
sys.path.insert(0, str(ROOT / "viz"))

# key -> (local path relative to ROOT, Unity Catalog table name)
PATHS = {
    "facilities": ("data/raw/facilities.parquet", "facilities"),
    "pincode": ("data/raw/india_post_pincode_directory.parquet", "india_post_pincode_directory"),
    "claims": ("derived/v1/claims.parquet", "rs_claims"),
    "grades": ("derived/v1/grades.parquet", "rs_grades"),
    "location": ("derived/v1/facility_location.parquet", "rs_facility_location"),
    "record_trust": ("derived/v1/record_trust.parquet", "rs_record_trust"),
    "groups": ("derived/v1/facility_groups.parquet", "rs_facility_groups"),
    "merge_records": ("audit/merge/out/records_flagged.parquet", "rs_merge_records_flagged"),
    "merge_sentences": ("audit/merge/out/sentences_flagged.parquet", "rs_merge_sentences_flagged"),
    "merge_decisions": ("audit/merge/out/sentence_decisions.parquet", "rs_merge_sentence_decisions"),
    "pin_gaz": ("derived/v1/pin_gazetteer.parquet", "rs_pin_gazetteer"),
    "source_urls": ("derived/v1/source_urls.parquet", "rs_source_urls"),
    "page_checks": ("derived/v1/source_page_checks.parquet", "rs_source_page_checks"),
    "merge_rec": ("audit/merge/verify/out/rec.parquet", "rs_merge_rec"),
    "prov_sources": ("audit/provenance/q1_records.parquet", "rs_prov_q1_records"),
    "prov_desc": ("audit/provenance/q2_records.parquet", "rs_prov_q2_records"),
    "scale_flags": ("audit/scale/scale_flags.parquet", "rs_scale_flags"),
    "geo": ("audit/geo/facility_geo.parquet", "rs_facility_geo"),
}
JSON = {
    "circularity": "audit/claims/verify/out/v_grades.json",
    "measure": "cleaning/claims/out/measure.json",
    "profile": "data/raw/PROFILE.json",
}

_SRC = {"mode": "local", "spark": None, "catalog": None, "schema": None}


def set_source(mode="local", spark=None, catalog=None, schema=None):
    """mode 'local' reads parquet under ROOT; 'uc' reads <catalog>.<schema>.<table> via spark."""
    if mode not in ("local", "uc"):
        raise ValueError(f"unknown source mode {mode!r}")
    _SRC.update(mode=mode, spark=spark, catalog=catalog, schema=schema)


def set_root(path, out_dir=None):
    """Point local reads (and outputs) at another checkout, e.g. a Databricks Repo path."""
    global ROOT, HERE, OUT
    ROOT = Path(path)
    HERE = ROOT / "viz" / "trust"
    OUT = Path(out_dir) if out_dir else HERE / "out"
    sys.path.insert(0, str(ROOT / "viz"))


def load(key, columns=None):
    """Read one input table. In 'uc' mode a table missing from the catalog falls back to local parquet."""
    rel, table = PATHS[key]
    if _SRC["mode"] == "uc":
        name = f"{_SRC['catalog']}.{_SRC['schema']}.{table}"
        try:
            sdf = _SRC["spark"].table(name)
            df = (sdf.select(*columns) if columns else sdf).toPandas()
        except Exception as e:  # table not uploaded: say so, then read the local copy
            print(f"[trust_io] {name} not readable ({type(e).__name__}); using local {rel}")
        else:
            if key == "facilities":  # the warehouse stores every column as STRING
                for c in ("latitude", "longitude"):
                    if c in df:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
            return df
    return pd.read_parquet(ROOT / rel, columns=columns)


def load_json(key):
    return json.loads((ROOT / JSON[key]).read_text())


def src(key):
    """Citation string for a source note."""
    return PATHS[key][0] if key in PATHS else JSON[key]


def out(name):
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT / name


def write_csv(df, name):
    p = out(f"{name}.csv")
    df.to_csv(p, index=False)
    return p


def note(fig, text, width=175):
    """Wrapped source / method note at the bottom of a figure."""
    import textwrap

    import style as S

    S.source_note(fig, textwrap.fill(text, width))
