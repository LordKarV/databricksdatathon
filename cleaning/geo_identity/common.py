"""Shared paths and loaders for the location and identity cleaning prototype.

Reuses the audit helpers (audit/geo/geo_common.py, audit/identity/common.py) instead of copying them.
Everything is plain pandas/numpy (+ rapidfuzz), so it runs unchanged in a Databricks serverless
notebook on the driver: the largest table is the 165,627-row PIN directory.
"""
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(os.environ.get("DATATHON_ROOT", Path(__file__).resolve().parents[2]))
OUT = ROOT / "cleaning/geo_identity"
AUDIT_GEO = ROOT / "audit/geo"
sys.path.insert(0, str(AUDIT_GEO))
sys.path.insert(0, str(ROOT / "audit/identity"))

from geo_common import hav_km, load_facilities, nearest, norm, parse_pin  # noqa: E402,F401


def facilities() -> pd.DataFrame:
    """9,959 records: well-formed rows minus the 11 byte-identical duplicate rows (GEO-06, F7, ID1)."""
    return load_facilities().drop_duplicates("unique_id").reset_index(drop=True)
