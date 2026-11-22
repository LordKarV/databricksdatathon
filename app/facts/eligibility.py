"""One rule for which records may be answered, and one per real facility (issue #78; the planner uses it too, #77).

- eligible(): the record has map coordinates and its trust level is not "exclude_review" (12 records today:
  animal-care hospitals, non-facilities and the like, per derived/v1/record_trust.trust_reasons).
- representatives(): for each service, one record per duplicate group (derived/v1/facility_groups.dup_group_id).
  The group's canonical record when it carries the service; otherwise the member with the smallest unique_id, so
  the choice is the same on every build and in every consumer (facts engine, offline packs, planner).
Both take plain DataFrames and return boolean masks aligned to the input index.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "derived" / "v1"
EXCLUDE_LEVELS = frozenset({"exclude_review"})


def eligible(df: pd.DataFrame, lat: str = "loc_lat", lon: str = "loc_lon",
             trust_level: str = "trust_level") -> pd.Series:
    """True where the record has coordinates and is not excluded by the trust review."""
    return df[lat].notna() & df[lon].notna() & ~df[trust_level].isin(EXCLUDE_LEVELS)


def trust_levels(v1: Path = V1) -> pd.DataFrame:
    return pd.read_parquet(v1 / "record_trust.parquet", columns=["unique_id", "trust_level"])


def groups(v1: Path = V1) -> pd.DataFrame:
    """unique_id -> grp (dup_group_id, or the record's own id when it has no group) and canonical flag."""
    g = pd.read_parquet(v1 / "facility_groups.parquet", columns=["unique_id", "dup_group_id", "is_canonical"])
    g["grp"] = g.dup_group_id.where(g.dup_group_id.notna(), g.unique_id).astype(str)
    g["canonical"] = g.is_canonical.fillna(True).astype(bool)
    return g[["unique_id", "grp", "canonical"]]


def representatives(pairs: pd.DataFrame, grp: pd.DataFrame, service: str = "service") -> pd.Series:
    """True for the one record per (duplicate group, service) that may be shown; pairs needs unique_id + service."""
    m = pairs[["unique_id", service]].reset_index().merge(grp, on="unique_id", how="left")
    m["grp"] = m.grp.fillna(m.unique_id)
    m["canonical"] = m.canonical.fillna(True)
    m = m.sort_values(["grp", service, "canonical", "unique_id"], ascending=[True, True, False, True])
    keep = m.drop_duplicates(["grp", service])["index"]
    return pairs.index.to_series().isin(set(keep)).reindex(pairs.index)
