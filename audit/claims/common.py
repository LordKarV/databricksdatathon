"""Shared loader for the service-claim audit. Local snapshot only, no warehouse calls."""
import json, os, re
import duckdb, pandas as pd

_ROOT = os.environ.get("DATATHON_ROOT", os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../..")))
_DATA = os.environ.get("DATATHON_DATA_ROOT", os.path.join(_ROOT, "data"))
RAW = os.path.join(_DATA, "raw/facilities.parquet")
TEXT_FIELDS = ["procedure", "equipment", "capability"]
UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def parse_list(v):
    """JSON-array string -> list of non-empty stripped strings. Null-likes -> []."""
    if v is None or v in ("null", "NULL", ""):
        return []
    try:
        x = json.loads(v)
    except Exception:
        return []
    if not isinstance(x, list):
        return []
    return [str(s).strip() for s in x if s is not None and str(s).strip()]


def to_num(v):
    if v is None:
        return None
    try:
        return float(json.loads(v))
    except Exception:
        try:
            return float(v)
        except Exception:
            return None


def load():
    """Well-formed rows only (UUID unique_id and source='kie'), per the snapshot profile."""
    df = duckdb.sql(f"""select * from '{RAW}'
        where regexp_matches(unique_id, '{UUID}') and source = 'kie'""").df()
    for f in TEXT_FIELDS + ["specialties", "source_urls"]:
        df[f + "_l"] = df[f].map(parse_list)
    df["description_s"] = df["description"].fillna("").map(lambda s: "" if s in ("null", "NULL") else s)
    df["ndoc"] = df["numberDoctors"].map(to_num)
    df["beds"] = df["capacity"].map(to_num)
    return df
