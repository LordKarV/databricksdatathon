"""Which records and pairs may be answered, shared by app/facts, app/packs and planner (#78, #77).

Each function returns a boolean mask aligned to the input index plus a dict of how many rows each condition removed
(or, for "unassessed", kept), and every build prints that dict.

- eligible_facilities(): drop records without usable coordinates and records the trust review marked
  "exclude_review" (12 today: animal-care hospitals, non-facilities). A record with no record_trust row is
  "unassessed" and kept: an exclusion is always explicit, so a missing row is not evidence of a problem.
- eligible_pairs(): drop (facility, service) claims graded attributed_elsewhere or counter_evidence, or verified
  false (moved verbatim from app/packs/build_packs.py).
- same_site_groups() + to_sites(): duplicate listings of one site become one facility. Only groups whose members
  agree on location (no group_location_disagrees, all within 1 km) collapse; branches stay separate. The site uses
  its canonical record's name, address and phone for every service, and each service's evidence is the union of
  the members' claims (each keeping its own claim_id), scored by the best-evidenced member (interim, v1).
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
SAME_SITE_KM = 1.0  # below the several-km PIN-centroid noise the geo audit measured: only truly the same site

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
    """facility_groups rows: unique_id, dup_group_id (None when ungrouped), is_canonical, group_location_disagrees."""
    return pd.read_parquet(v1 / "facility_groups.parquet",
                           columns=["unique_id", "dup_group_id", "is_canonical", "group_location_disagrees"])


def _km(lat1: pd.Series, lon1: pd.Series, lat2: pd.Series, lon2: pd.Series) -> pd.Series:
    la1, lo1, la2, lo2 = (np.radians(x.astype(float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def same_site_groups(grp: pd.DataFrame, locations: pd.DataFrame, km: float = SAME_SITE_KM,
                     lat: str = "loc_lat", lon: str = "loc_lon") -> tuple[pd.DataFrame, Counts]:
    """unique_id -> rep_id and listings for every record in `locations` (pass the eligible facilities only).

    dup_group_id mixes "the same record twice" with "the same organisation, another branch" (Fortis Ludhiana and
    Mohali). A group collapses onto its representative only when no member has group_location_disagrees and every
    eligible member is within `km` of the representative's point; other groups stay separate facilities. The
    representative is the canonical record (the most complete identity fields), else the smallest unique_id.
    """
    loc = locations[["unique_id", lat, lon]].rename(columns={lat: "_lat", lon: "_lon"})
    out = loc[["unique_id"]].assign(rep_id=loc.unique_id, listings=1).reset_index(drop=True)
    g = grp[grp.dup_group_id.notna()].merge(loc, on="unique_id", how="inner")
    g = g.sort_values(["dup_group_id", "is_canonical", "unique_id"], ascending=[True, False, True])
    g = g[g.groupby("dup_group_id").unique_id.transform("size") >= 2]
    head = g.drop_duplicates("dup_group_id").set_index("dup_group_id")
    g["rep_id"] = g.dup_group_id.map(head.unique_id)
    g["dist"] = _km(g._lat, g._lon, g.dup_group_id.map(head._lat), g.dup_group_id.map(head._lon))
    per = g.groupby("dup_group_id").agg(far=("dist", "max"), disagree=("group_location_disagrees", "any"),
                                        n=("unique_id", "size"))
    per["collapse"] = (per.far <= km) & ~per.disagree.fillna(False).astype(bool)
    col = g[g.dup_group_id.map(per.collapse)]
    rep = dict(zip(col.unique_id, col.rep_id, strict=True))
    n = dict(zip(col.unique_id, col.dup_group_id.map(per.n), strict=True))
    out["rep_id"] = [rep.get(u, u) for u in out.unique_id]
    out["listings"] = [int(n.get(u, 1)) for u in out.unique_id]
    return out, {"groups": len(per), "collapsed": int(per.collapse.sum()), "kept_separate": int((~per.collapse).sum()),
                 "records_merged": int(len(col) - per.collapse.sum())}


def to_sites(pairs: pd.DataFrame, sites: pd.DataFrame, score: str = "score",
             service: str = "service") -> tuple[pd.DataFrame, Counts]:
    """One row per (site representative, service): the best-scored member's row with unique_id set to the
    representative. Adds member_id (the record the row came from), members (records carrying the service, best
    first, for merging their evidence) and listings (records in the site). Index-free: returns a new frame."""
    p = pairs.merge(sites[["unique_id", "rep_id", "listings"]], on="unique_id", how="left")
    p["rep_id"] = p.rep_id.where(p.rep_id.notna(), p.unique_id)
    p["listings"] = p.listings.fillna(1).astype(int)
    p = p.sort_values(["rep_id", service, score, "unique_id"], ascending=[True, True, False, True], kind="stable")
    members = p.groupby(["rep_id", service], sort=False).unique_id.agg(list)
    best = p.drop_duplicates(["rep_id", service]).copy()
    best["member_id"] = best.unique_id
    best["unique_id"] = best.rep_id
    best["members"] = [members[k] for k in zip(best.rep_id, best[service], strict=True)]
    best = best.drop(columns="rep_id").reset_index(drop=True)
    return best, {"rows": len(pairs), "merged_into_site": len(pairs) - len(best), "kept": len(best),
                  "rep_is_not_best": int((best.member_id != best.unique_id).sum())}


def report(name: str, counts: Counts) -> None:
    print(f"eligibility[{name}]: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
