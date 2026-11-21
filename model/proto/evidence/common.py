"""Shared paths, constants and small helpers for the evidence layer (MODEL_SPEC_v1 section 4).

Everything here is numpy/pandas only, so the same code runs on a Databricks serverless driver.
"""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = Path(__file__).resolve().parent
RAW = ROOT / "data/raw/facilities.parquet"
CLAIMS = ROOT / "cleaning/claims/out"
MERGE = ROOT / "audit/merge/out"
GEOI = ROOT / "cleaning/geo_identity"
GEO = ROOT / "audit/geo"
IDENT = ROOT / "audit/identity/out"

INPUTS = {
    "claims": CLAIMS / "claims.parquet",
    "grades": CLAIMS / "grades.parquet",
    "specialties": CLAIMS / "specialties.parquet",
    "lexicon": CLAIMS / "service_lexicon.csv",
    "sentence_decisions": MERGE / "sentence_decisions.parquet",
    "record_scores": MERGE / "record_scores.parquet",
    "facility_location": GEOI / "facility_location.parquet",
    "pin_gazetteer": GEOI / "pin_gazetteer.parquet",
    "place_gazetteer": GEOI / "place_gazetteer.parquet",
    "facility_geo": GEO / "facility_geo.parquet",
    "existence_signals": IDENT / "existence_signals.csv",
    "shared_phones": IDENT / "shared_phones.csv",
    "shared_domains": IDENT / "shared_domains.csv",
    "dup_groups": IDENT / "dup_groups.csv",
    "chain_membership": IDENT / "chain_membership.csv",
    "raw_facilities": RAW,
}

# claims.services keys -> the 7 gold keys (icu is prerequisite-only, never an atom)
SVC_MAP = {"dialysis": "dialysis", "csection": "emergency_csection", "nicu": "nicu",
           "cardiac_surgery": "cardiac_surgery", "mri": "mri", "burns": "burn_care", "trauma": "trauma_emergency"}
GOLD_SERVICES = list(SVC_MAP.values())
LEX_KEY = {v: k for k, v in SVC_MAP.items()}

# cleaning/claims lexicon module (read-only import): prereq tag sets, scope rule, specialty core tags
sys.path.append(str(ROOT / "cleaning/claims"))  # append: that folder also has an evaluate.py
import lexicon as LEX  # noqa: E402

OWN_CLASSES = ("own_anchored", "unanchored")
COUNTING_ROLES = ("offer", "unit_or_equipment", "quantity")
# rejected for ownership: these drive family C
# ambiguous_reference added after the dev sentence check (7 of 10 dev ambiguous sentences were about another facility)
OWNERSHIP_REJECT = ("names_other_facility", "other_state_place", "other_district_place", "quarantined_merge", "sibling_branch",
                    "ambiguous_reference")


def sha256_file(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def wilson(k, n, z=1.959964):
    """95% Wilson interval; (nan, nan) when n == 0."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(c - h, 4), round(c + h, 4))


def fmt_ci(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({lo:.2f} to {hi:.2f})" if n else "0/0"


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def norm(s) -> str:
    """Same normalisation as audit/geo/geo_common.norm (kept local to avoid sys.path coupling)."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower().replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def norm_text(s: str) -> str:
    """Echo-collapse normalisation: lower case, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def jlist(s):
    """Parse a JSON-array string column; [] for null, 'null' or malformed values."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return []
    try:
        v = json.loads(s)
    except (TypeError, ValueError):
        return []
    return v if isinstance(v, list) else []


def split_cell(s) -> list:
    """claims.parquet stores multi-values as 'a|b'."""
    return [x for x in str(s).split("|") if x] if isinstance(s, str) and s else []


def sid(text: str, n=12) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]
