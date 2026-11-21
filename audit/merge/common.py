"""Shared loader: well-formed facility rows with parsed claim lists."""
import json, re
import pandas as pd

RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CLAIM_COLS = ["procedure", "equipment", "capability"]


def parse_list(v):
    if v is None or v in ("null", "NULL", ""):
        return []
    try:
        x = json.loads(v)
    except Exception:
        return []
    if not isinstance(x, list):
        return []
    return [s.strip() for s in x if isinstance(s, str) and s.strip()]


def load():
    df = pd.read_parquet(RAW)
    # well-formed rule from the snapshot profile: UUID id, source='kie'
    df = df[df.unique_id.fillna("").str.match(UUID) & (df.source == "kie")].copy()
    # 11 rows are byte-identical copies of another row (same unique_id); keep one
    df = df.drop_duplicates("unique_id").copy()
    for c in CLAIM_COLS + ["source_urls", "specialties"]:
        df[c + "_l"] = df[c].map(parse_list)
    return df.reset_index(drop=True)


def sentences(df):
    """One row per claim sentence: unique_id, field, idx, text. description split on '. '."""
    rows = []
    for r in df.itertuples():
        for c in CLAIM_COLS:
            for i, s in enumerate(getattr(r, c + "_l")):
                rows.append((r.unique_id, c, i, s))
        d = r.description if isinstance(r.description, str) and r.description != "null" else ""
        for i, s in enumerate(x.strip() for x in re.split(r"(?<=[.!?])\s+", d) if x.strip()):
            rows.append((r.unique_id, "description", i, s))
    return pd.DataFrame(rows, columns=["unique_id", "field", "idx", "text"])
