"""Independent loader for the identity-audit verification. Local snapshot only."""
import json, re
import duckdb, pandas as pd, numpy as np

RAW = "/Users/karthikvattem/projects/datathon/data/raw/"
NULLISH = {"", "null", "NULL", "[]", '[""]', "[null]", "None"}


def raw():
    return pd.read_parquet(RAW + "facilities.parquet")


def wellformed(df):
    ok = df.unique_id.fillna("").str.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    return df[ok & (df.source == "kie")].copy()


def nul(v):
    return v is None or (isinstance(v, float) and np.isnan(v)) or (isinstance(v, str) and v.strip() in NULLISH)


def jlist(v):
    if nul(v):
        return []
    try:
        x = json.loads(v)
    except Exception:
        return [v]
    x = x if isinstance(x, list) else [x]
    return [str(s).strip() for s in x if s is not None and str(s).strip() and str(s).strip().lower() != "null"]


def digits(p):
    d = re.sub(r"\D", "", str(p))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return d


def dedup(df):
    return df.drop_duplicates("unique_id").reset_index(drop=True)
