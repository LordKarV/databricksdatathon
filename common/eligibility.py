"""Which records and pairs may be answered, shared by app/facts, app/packs and planner (#78, #77).

Each function returns a boolean mask aligned to the input index plus a dict of how many rows each condition removed
(or, for "unassessed", kept), and every build prints that dict.

- eligible_facilities(): drop records without usable coordinates and records the trust review marked
  "exclude_review" (12 today: animal-care hospitals, non-facilities). A record with no record_trust row is
  "unassessed" and kept: an exclusion is always explicit, so a missing row is not evidence of a problem.
- eligible_pairs(): drop (facility, service) claims graded attributed_elsewhere or counter_evidence, or verified
  false (moved verbatim from app/packs/build_packs.py).
- representatives(): one record per (duplicate group, service), from derived/v1/facility_groups.dup_group_id: the
  group's canonical record when it carries the service, else the member with the smallest unique_id, so every build
  and every consumer picks the same one.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "derived" / "v1"
EXCLUDE_LEVELS = frozenset({"exclude_review"})
EXCLUDED_GRADES = frozenset({"attributed_elsewhere", "counter_evidence"})
EXCLUDED_STATUS = frozenset({"verified_false"})

Counts = dict[str, int]


def _usable(x: pd.Series, lo: float, hi: float) -> pd.Series:
    v = pd.to_numeric(x, errors="coerce")
    return v.notna() & np.isfinite(v) & v.between(lo, hi)


def eligible_facilities(df: pd.DataFrame, lat: str = "loc_lat", lon: str = "loc_lon",
                        trust_level: str = "trust_level") -> tuple[pd.Series, Counts]:
    """Mask of facilities that may be answered; df needs lat, lon and trust_level (NaN = unassessed)."""
    placed = _usable(df[lat], -90, 90) & _usable(df[lon], -180, 180)
    excluded = df[trust_level].isin(EXCLUDE_LEVELS)
    counts = {"rows": len(df), "no_coordinates": int((~placed).sum()),
              "exclude_review": int((placed & excluded).sum()),
              "unassessed_kept": int((placed & df[trust_level].isna()).sum())}
    mask = placed & ~excluded
    counts["kept"] = int(mask.sum())
    return mask, counts


def eligible_pairs(df: pd.DataFrame, grade: str = "grade", status: str = "status") -> tuple[pd.Series, Counts]:
    """Mask of (facility, service) claims that may be offered as an option."""
    bad_grade = df[grade].isin(EXCLUDED_GRADES)
    bad_status = df[status].isin(EXCLUDED_STATUS)
    mask = ~bad_grade & ~bad_status
    return mask, {"rows": len(df), "excluded_grade": int(bad_grade.sum()),
                  "verified_false": int((bad_status & ~bad_grade).sum()), "kept": int(mask.sum())}


def groups(v1: Path = V1) -> pd.DataFrame:
    """unique_id -> grp (dup_group_id, or the record's own id when it has no group) and canonical flag."""
    g = pd.read_parquet(v1 / "facility_groups.parquet", columns=["unique_id", "dup_group_id", "is_canonical"])
    g["grp"] = g.dup_group_id.where(g.dup_group_id.notna(), g.unique_id).astype(str)
    g["canonical"] = g.is_canonical.fillna(True).astype(bool)
    return g[["unique_id", "grp", "canonical"]]


def representatives(pairs: pd.DataFrame, grp: pd.DataFrame, service: str = "service") -> tuple[pd.Series, Counts]:
    """Mask keeping one record per (duplicate group, service); pairs needs unique_id and the service column."""
    m = pairs[["unique_id", service]].reset_index(names="_row").merge(grp, on="unique_id", how="left")
    m["grp"] = m.grp.fillna(m.unique_id)
    m["canonical"] = m.canonical.fillna(True)
    m = m.sort_values(["grp", service, "canonical", "unique_id"], ascending=[True, True, False, True])
    keep = set(m.drop_duplicates(["grp", service])["_row"])
    mask = pd.Series(pairs.index.isin(keep), index=pairs.index)
    return mask, {"rows": len(pairs), "duplicate_members": int((~mask).sum()), "kept": int(mask.sum())}


def report(name: str, counts: Counts) -> None:
    print(f"eligibility[{name}]: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
