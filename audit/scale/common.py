"""Shared loader for the scale/metadata audit. Local snapshot only."""
import json
import duckdb

RAW = "/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet"
UUID_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
NULLS = {None, "", "null", "NULL", "[]", '[""]', "[null]"}


def con():
    c = duckdb.connect()
    c.sql(f"create view raw as select * from '{RAW}'")
    # well-formed rule from the snapshot profile: UUID id and source='kie' (9970 rows)
    c.sql(f"create view f as select * from raw where source='kie' and regexp_matches(unique_id,'{UUID_RE}')")
    return c


def df():
    return con().sql("select * from f").df()


def jlist(v):
    """Parse a JSON-array string into a list of non-empty strings; [] on null-like."""
    if v in NULLS:
        return []
    try:
        x = json.loads(v)
    except (ValueError, TypeError):
        return []
    if not isinstance(x, list):
        return []
    return [s for s in x if isinstance(s, str) and s.strip()]


def num(v):
    """Integer value of a numeric string field, None when null-like or unparseable."""
    if v in NULLS:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None
