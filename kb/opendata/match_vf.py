"""Match Virtue Foundation (VF) facilities to OSM and Wikidata facilities.

Run:
  .venv-kb2/bin/python -I kb/opendata/match_vf.py candidates   # best candidate per VF x source + samples
  (hand-label kb/opendata/handcheck_matches.csv and handcheck_near_misses.csv: column verdict)
  .venv-kb2/bin/python -I kb/opendata/match_vf.py finalize     # precision, tiers, outputs

Candidate search: every OSM / Wikidata point within MAX_KM of the cleaned VF location
(facility_location loc_lat/loc_lon) or its alternative point (alt_lat/alt_lon). Name score is
the existing HOT join scorer (external/hotosm_ind_health_facilities/match.py: min of
token_set_ratio on full and core names; generic-only names penalised), imported, not copied.
Agreement signals that do not come from the coordinate: PIN equality, city or district name,
a shared 10-digit phone, the same website domain. VF coordinates are often geocoded from the
name, so distance alone is weak evidence (see that README).
"""
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

ROOT = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(ROOT / "external/hotosm_ind_health_facilities"))
from match import core, distinctive, hav, name_score, norm  # noqa: E402

OUT = ROOT / "kb/opendata"
MAX_KM = 10.0
CELL = 0.1
CONFLICT_KM = 25.0
SEED = 7


def digits(p: str) -> str | None:
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else None


def domain(u: str | None) -> str | None:
    if not isinstance(u, str) or not u.strip():
        return None
    h = re.sub(r"^[a-z]+://", "", u.strip().lower()).split("/")[0].split(":")[0]
    h = re.sub(r"^www\d?\.", "", h)
    # ponytail: shared hosts (facebook, google sites, practo, justdial) are not identity evidence
    if any(s in h for s in ("facebook.", "google.", "practo.", "justdial.", "instagram.", "wa.me", "linktr.ee")):
        return None
    return h or None


def load_vf() -> pd.DataFrame:
    loc = pd.read_parquet(ROOT / "cleaning/geo_identity/facility_location.parquet")
    tr = pd.read_parquet(ROOT / "cleaning/geo_identity/record_trust.parquet",
                         columns=["unique_id", "display_phones", "website_domain"])
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet",
                          columns=["unique_id", "facilityTypeId", "address_line1", "address_line2"])
    raw = raw.drop_duplicates("unique_id")
    pins = pd.read_parquet(ROOT / "cleaning/geo_identity/pin_gazetteer.parquet", columns=["pin", "lat", "lon"])
    pins = pins.rename(columns={"lat": "pin_lat", "lon": "pin_lon"}).astype({"pin": float})
    vf = loc.merge(tr, on="unique_id", how="left").merge(raw, on="unique_id", how="left")
    return vf.merge(pins, on="pin", how="left")


def load_pool() -> pd.DataFrame:
    osm = pd.read_parquet(OUT / "osm_health_facilities.parquet")
    osm = osm.assign(source="osm", source_id=osm.osm_id, postcode=osm.addr_postcode,
                     place=osm[["addr_city", "addr_district", "addr_full"]].fillna("").agg(" ".join, axis=1))
    wd = pd.read_parquet(OUT / "wikidata_medical_facilities.parquet")
    wd = wd.assign(source="wikidata", source_id=wd.qid, phone=None,
                   place=[" ".join(v) if v is not None else "" for v in wd.located_in])
    cols = ["source", "source_id", "name", "lat", "lon", "kind", "postcode", "place", "phone", "website", "district"]
    pool = pd.concat([osm[cols], wd[cols]], ignore_index=True)
    pool = pool[pool.name.notna() & pool.lat.notna()].reset_index(drop=True)
    pool["n"] = [norm(x) for x in pool.name]
    pool["c"] = [core(x) for x in pool.n]
    pool["dom"] = [domain(x) for x in pool.website]
    pool["ph"] = [digits(x) for x in pool.phone]
    return pool


def place_agree(vf_r, cand) -> bool:
    """VF city or district appears in the candidate's OWN address fields (not a district derived
    from the candidate's coordinate, which agrees with any nearby VF point by construction)."""
    hay = norm(cand.place)
    for v in (vf_r.address_city, vf_r.district):
        v = norm(v)
        if len(v) >= 4 and len(hay) >= len(v) and (v in hay or fuzz.partial_ratio(v, hay) >= 92):
            return True
    return False


def best_candidates(vf: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    idx = defaultdict(list)
    for i, (la, lo) in enumerate(zip(pool.lat.values, pool.lon.values)):
        idx[(int(la // CELL), int(lo // CELL))].append(i)
    src = pool.source.values
    rows = []
    for r in vf.itertuples(index=False):
        a = {"n": norm(r.name)}
        a["c"] = core(a["n"])
        anchors = [(k, la, lo) for k, la, lo in (("loc", r.loc_lat, r.loc_lon), ("alt", r.alt_lat, r.alt_lon))
                   if pd.notna(la)]
        if not a["n"] or not anchors:
            continue
        best: dict = {}
        for kind, la, lo in anchors:
            cy, cx = int(la // CELL), int(lo // CELL)
            cand = np.array([i for dy in (-1, 0, 1) for dx in (-1, 0, 1) for i in idx.get((cy + dy, cx + dx), [])])
            if not len(cand):
                continue
            km = hav(la, lo, pool.lat.values[cand], pool.lon.values[cand])
            for i, d in zip(cand[km <= MAX_KM], km[km <= MAX_KM]):
                s = name_score(a, {"n": pool.n.values[i], "c": pool.c.values[i]})
                key = (s, -d)
                if src[i] not in best or key > best[src[i]][0]:
                    best[src[i]] = (key, i, d, kind, s)
        vph = {digits(p) for p in (r.display_phones if r.display_phones is not None else [])} - {None}
        vdom = domain(r.website_domain)
        for source, (_, i, d, kind, s) in best.items():
            c = pool.iloc[i]
            places = " ".join(x for x in (r.address_city, r.district) if isinstance(x, str))
            pin_to = (float(hav(r.pin_lat, r.pin_lon, c.lat, c.lon)) if pd.notna(r.pin_lat) else None)
            rows.append(dict(
                unique_id=r.unique_id, vf_name=r.name, vf_type=r.facilityTypeId, vf_city=r.address_city,
                vf_district=r.district, vf_state=r.state_final, vf_pin=r.pin, vf_loc_conf=r.loc_conf,
                vf_address=" ".join(x for x in (r.address_line1, r.address_line2) if isinstance(x, str)),
                source=source, source_id=c.source_id, cand_name=c["name"], cand_kind=c.kind,
                cand_place=c.place.strip() or None, cand_postcode=c.postcode, cand_lat=c.lat, cand_lon=c.lon,
                score=round(float(s), 1), km=round(float(d), 3), anchor=kind,
                is_distinctive=bool(distinctive(a["c"], places) and distinctive(c.c, places)),
                balance=round(fuzz.token_sort_ratio(a["c"], c.c), 1),
                pin_agree=bool(pd.notna(r.pin) and isinstance(c.postcode, str)
                               and c.postcode.strip()[:6] == str(int(r.pin))),
                place_agree=place_agree(r, c),
                phone_agree=bool(c.ph and c.ph in vph), web_agree=bool(vdom and c.dom and vdom == c.dom),
                pin_to_cand_km=None if pin_to is None else round(pin_to, 2),
                location_conflict=bool(pin_to is not None and pin_to > CONFLICT_KM)))
    return pd.DataFrame(rows)


def tier(r) -> str | None:
    """high / medium = same facility, usable as evidence; conflict = same name, but the open-data
    point is more than 25 km from the VF PIN centre (show as a warning, never as evidence).
    Rules set from the 40-match and 20-near-miss hand-check, then revised once after the
    validation sample (conflict cases were 2 of 9 correct there). See OPENDATA.md, 'Thresholds'.
    Website agreement alone is not used: chains share one domain across branches."""
    if r.score >= 85 and r.phone_agree:
        return "high"
    if r.location_conflict and r.score >= 85:
        return "conflict"
    if not r.is_distinctive:  # "Government Hospital", "City Clinic": only a same-spot, same-PIN match
        return "medium" if r.score >= 95 and r.km <= 0.5 and r.pin_agree else None
    if r.score >= 90 and (r.km <= 1 or r.pin_agree):
        return "high"
    if r.score >= 90 and r.km <= 3 and r.balance >= 60:
        return "medium"
    # near-miss rescue: spelling variant at the same spot with a shared phone or own domain
    if r.score >= 70 and r.km <= 0.5 and r.web_agree:
        return "medium"
    return None


def candidates() -> None:
    vf, pool = load_vf(), load_pool()
    bc = best_candidates(vf, pool)
    bc["tier"] = [tier(r) for r in bc.itertuples()]
    bc.to_parquet(OUT / "vf_candidates.parquet", index=False)
    # Hand-check samples, OSM and Wikidata together. Matches: stratified by distance band among
    # distinctive pairs with score >= 85 (the region where a threshold has to be drawn).
    pairs = bc[bc.is_distinctive & (bc.score >= 85)]
    bands = [(0, 1, 15), (1, 3, 13), (3, MAX_KM, 12)]
    m = pd.concat([pairs[(pairs.km > lo) & (pairs.km <= hi) | ((lo == 0) & (pairs.km == 0))]
                   .sample(k, random_state=SEED) for lo, hi, k in bands])
    near = bc[(bc.score >= 70) & (bc.score < 85) & (bc.km <= 3)].sample(20, random_state=SEED)
    keep = ["unique_id", "source", "source_id", "vf_name", "cand_name", "score", "km", "is_distinctive", "balance",
            "pin_agree", "place_agree", "phone_agree", "web_agree", "location_conflict", "tier", "vf_city",
            "vf_district", "vf_pin", "vf_address", "cand_place", "cand_postcode", "cand_kind"]
    for df, f in ((m, "handcheck_matches.csv"), (near, "handcheck_near_misses.csv")):
        p = OUT / f
        if p.exists():
            print("kept existing", f)
            continue
        df[keep].assign(verdict="", note="").to_csv(p, index=False)
    p = OUT / "handcheck_validation.csv"
    if not p.exists():
        used = set(pd.read_csv(OUT / "handcheck_matches.csv").unique_id) | set(
            pd.read_csv(OUT / "handcheck_near_misses.csv").unique_id)
        fresh = bc[~bc.unique_id.isin(used)]
        v = pd.concat([fresh[fresh.tier == "high"].sample(20, random_state=SEED + 1),
                       fresh[fresh.tier == "medium"].sample(15, random_state=SEED + 1)])
        v[keep].assign(verdict="", note="").to_csv(p, index=False)
    print(bc.groupby("source").tier.value_counts(dropna=False))


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan")] * 2
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(c - h, 3), round(c + h, 3)]


if __name__ == "__main__":
    assert wilson(15, 20) == [0.531, 0.888], wilson(15, 20)
    assert digits("+91 98765-43210") == "9876543210" and domain("https://www.abc.in/x") == "abc.in"
    {"candidates": candidates}[sys.argv[1]]()
