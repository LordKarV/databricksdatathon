"""Join test: Virtue Foundation (VF) facilities -> HOT OSM health facilities export.

Run: .venv/bin/python -I match.py <osm.parquet> <vf facilities.parquet> <audit facility_geo.parquet>
                                  <audit grades.parquet> <out_dir>

Matcher: for each VF row, candidate OSM features within MAX_KM of either anchor
(the VF coordinate, or the VF PIN centroid computed by the geo audit), scored by
rapidfuzz token_set_ratio on normalised names. A pair is accepted when the name
score and distance pass the tier rules in tier(). Generic names ("Government
Hospital") must sit much closer, because token_set_ratio rates any subset as 100.
"""
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict

import duckdb
import numpy as np
import pandas as pd
from rapidfuzz import fuzz

MAX_KM = 10.0
CONFLICT_KM = 25.0  # OSM point this far from the VF PIN centroid = location conflict
CELL = 0.1  # degrees, about 11 km; 3x3 neighbourhood covers MAX_KM

# Words that say what kind of place it is, not which place it is.
GENERIC = set("""hospital hospitals hosp clinic clinics polyclinic centre center centers centres medical
medicals health healthcare care nursing home homes multispeciality multispecialty multi speciality specialty
specialities super superspeciality and of the pvt ltd private limited p llp institute institution sciences
research trust foundation unit dr doctor doctors dispensary pharmacy chemist chemists druggist
""".split())
# Admin words that also do not identify a place on their own.
ADMIN = set("""government govt gov civil district city general primary community sub urban rural esi esic
referral area new old main state national sadar""".split())
# Service words: "Dental Clinic" or "Eye Care" names a kind of place, not one place.
DESCRIPTIVE = set("""dental dentist dentistry dentists implant implants smile tooth teeth eye eyes vision ent
child children kids paediatric pediatric maternity women woman mother mothers kidney heart cardiac cancer
skin ortho orthopaedic orthopedic bone joint diabetes diabetic physiotherapy physio homeo homoeo homeopathy
ayurveda ayurvedic lab labs laboratory scan scans imaging fertility ivf test tube baby nursing diagnostic
diagnostics pathology surgical surgery critical icu trauma emergency""".split())


def norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bsuper[- ]?speciality\b|\bmulti[- ]?speciality\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def core(n):
    """Name minus kind-of-place and service words; what is left should identify the place."""
    return " ".join(t for t in n.split() if t not in GENERIC and t not in DESCRIPTIVE)


def distinctive(c, places=""):
    """True if the core name has a word that is not admin, service or place vocabulary."""
    skip = ADMIN | set(norm(places).split())
    return any(t not in skip and len(t) > 2 for t in c.split())


def hav(lat1, lon1, lat2, lon2):
    r = math.pi / 180
    a = (np.sin((lat2 - lat1) * r / 2) ** 2
         + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2)
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def name_score(a, b):
    full = fuzz.token_set_ratio(a["n"], b["n"])
    ca, cb = a["c"], b["c"]
    if ca and cb:  # both have non-generic words: those must agree too
        return min(full, fuzz.token_set_ratio(ca, cb))
    return full * 0.85  # one side is only generic words ("Hospital"): below every tier


def tier(score, km, is_distinctive, balance):
    """strong / weak / None. Thresholds were set by reading samples, see README.
    balance = token_sort_ratio of the cores; low means one name is a small subset of the
    other ("Siva" vs "Siva Head and Neck Hospital"), tolerated only at short distance."""
    if not is_distinctive:
        return "strong" if score >= 95 and km <= 0.5 else ("weak" if score >= 90 and km <= 1.5 else None)
    if (score >= 90 and km <= 2) or (score >= 95 and km <= 5):
        return "strong"
    if balance >= 60 and ((score >= 85 and km <= 5) or (score >= 95 and km <= MAX_KM)):
        return "weak"
    return None


def load(osm_p, vf_p, geo_p):
    con = duckdb.connect()
    osm = con.execute(f"""
        select id osm_id, coalesce(name_latin, name) name, name raw_name, amenity, healthcare,
               healthcare_speciality, operator_type, addr_full, addr_city, adm1_name, adm2_name,
               (bbox.ymin + bbox.ymax) / 2 lat, (bbox.xmin + bbox.xmax) / 2 lon
               ,coalesce(amenity, healthcare) = 'pharmacy' is_pharmacy
        from read_parquet('{osm_p}') where coalesce(name_latin, name) is not null""").df()
    vf = con.execute(f"""
        select v.unique_id, v.name, v.facilityTypeId, v.address_city, v.address_stateOrRegion,
               v.address_zipOrPostcode, g.latitude lat, g.longitude lon, g.pin_lat, g.pin_lon,
               g.coord_zero, g.coord_outside, g.geo_conflict, g.pin_district
        from (select * from read_parquet('{vf_p}') qualify row_number() over (partition by unique_id) = 1) v
        left join (select * from read_parquet('{geo_p}') qualify row_number() over (partition by unique_id) = 1) g
        using (unique_id)""").df()  # ponytail: 11 unique_ids repeat in the raw file; keep one each
    return osm, vf


def build_index(osm):
    idx = defaultdict(list)
    for i, (la, lo) in enumerate(zip(osm.lat.values, osm.lon.values)):
        idx[(int(la // CELL), int(lo // CELL))].append(i)
    return idx


def candidates(idx, la, lo):
    cy, cx = int(la // CELL), int(lo // CELL)
    return [i for dy in (-1, 0, 1) for dx in (-1, 0, 1) for i in idx.get((cy + dy, cx + dx), [])]


def anchors(r):
    out = []
    ok_coord = pd.notna(r.lat) and not r.coord_zero and not r.coord_outside
    if ok_coord:
        out.append(("coord", r.lat, r.lon))
    if pd.notna(r.pin_lat):
        out.append(("pin", r.pin_lat, r.pin_lon))
    return out


def match_one(r, osm, on, oc, idx):
    a = {"n": norm(r.name)}
    a["c"] = core(a["n"])
    is_pharm = osm.is_pharmacy.values
    want_pharm = r.facilityTypeId in ("pharmacy", "farmacy")
    if not a["n"]:
        return None
    best = None
    for kind, la, lo in anchors(r):
        cand = candidates(idx, la, lo)
        if not cand:
            continue
        cand = np.array(cand)
        km = hav(la, lo, osm.lat.values[cand], osm.lon.values[cand])
        for i, d in zip(cand[km <= MAX_KM], km[km <= MAX_KM]):
            if is_pharm[i] and not want_pharm:  # same-brand pharmacies sit next to hospitals
                continue
            s = name_score(a, {"n": on[i], "c": oc[i]})
            key = (s, -d)
            if best is None or key > best[0]:
                best = (key, i, d, kind, s)
    if best is None:
        return None
    _, i, d, kind, s = best
    o = osm.iloc[i]
    places = " ".join(str(x) for x in (r.address_city, o.adm2_name, o.addr_city) if isinstance(x, str))
    is_dist = distinctive(a["c"], places) and distinctive(oc[i], places)
    return dict(osm_idx=int(i), score=round(s, 1), km=round(float(d), 3), anchor=kind,
                distinctive=is_dist, tier=tier(s, d, is_dist, fuzz.token_sort_ratio(a["c"], oc[i])))


def coord_vs_osm_km(r, o):
    if pd.isna(r.lat) or r.coord_zero or r.coord_outside:
        return None
    return float(hav(r.lat, r.lon, o.lat, o.lon))


def main(osm_p, vf_p, geo_p, grades_p, out):
    osm, vf = load(osm_p, vf_p, geo_p)
    on = [norm(x) for x in osm.name]
    oc = [core(x) for x in on]
    idx = build_index(osm)
    rows = []
    for r in vf.itertuples(index=False):
        m = match_one(r, osm, on, oc, idx) if anchors(r) else None
        rows.append({"unique_id": r.unique_id, **(m or {})})
    res = vf.merge(pd.DataFrame(rows), on="unique_id")
    sel = res.osm_idx.notna()
    o = osm.iloc[res.loc[sel, "osm_idx"].astype(int)].reset_index(drop=True).add_prefix("osm_")
    res = pd.concat([res[sel].reset_index(drop=True), o], axis=1).pipe(
        lambda m: pd.concat([m, res[~sel]], ignore_index=True))
    res["vf_coord_to_osm_km"] = [coord_vs_osm_km(r, pd.Series({"lat": r.osm_lat, "lon": r.osm_lon}))
                                 if pd.notna(r.osm_lat) else None for r in res.itertuples()]
    res["pin_to_osm_km"] = hav(res.pin_lat, res.pin_lon, res.osm_lat, res.osm_lon)
    # A name match whose OSM point is far from the VF PIN centroid: same-name facility in
    # another town, or a wrong VF PIN/coordinate. Either way the app should show it as unresolved.
    res["location_conflict"] = res.pin_to_osm_km > CONFLICT_KM
    res.drop(columns=["osm_idx"]).to_parquet(f"{out}/vf_osm_matches.parquet")
    stats = summarise(res, vf, osm, grades_p)
    json.dump(stats, open(f"{out}/match_stats.json", "w"), indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


SERVICE_TAG = {  # OSM healthcare:speciality / healthcare values that hint at each VF service
    "dialysis": r"nephro|dialy|renal",
    "csection": r"gyn|obstet|matern",
    "nicu": r"neonat|paed|pedia",
    "cardiac_surgery": r"cardi",
    "mri": r"radiol",
    "trauma": r"trauma|emergency|orthop",
    "burns": r"burn|plastic",
}


def summarise(res, vf, osm, grades_p):
    acc = res[res.tier.isin(["strong", "weak"])]
    n_vf = len(vf)
    n_anch = int(sum(1 for r in vf.itertuples() if anchors(r)))
    s = dict(osm_rows=len(osm), vf_rows=n_vf, vf_with_anchor=n_anch,
             matched_strong=int((acc.tier == "strong").sum()), matched_weak=int((acc.tier == "weak").sum()))
    s["match_rate_all_vf"] = round(len(acc) / n_vf, 4)
    s["match_rate_vf_with_anchor"] = round(len(acc) / n_anch, 4)
    s["strong_rate_vf_with_anchor"] = round(s["matched_strong"] / n_anch, 4)
    s["by_vf_type"] = {k: dict(n=int((vf.facilityTypeId == k).sum()), matched=int((acc.facilityTypeId == k).sum()))
                       for k in ["hospital", "clinic", "dentist"]}
    s["matched_by_anchor"] = acc.anchor.value_counts().to_dict()
    s["osm_ids_used_by_more_than_one_vf"] = int((acc.osm_osm_id.value_counts() > 1).sum())
    d = acc.vf_coord_to_osm_km.dropna()
    s["vf_coord_to_osm_km_quantiles"] = {q: round(float(d.quantile(q)), 3) for q in (0.25, 0.5, 0.75, 0.9, 0.95)}
    s["matched_vf_coord_over_5km_from_osm"] = int((d > 5).sum())
    s["matched_location_conflict_pin_over_25km"] = int(acc.location_conflict.fillna(False).sum())
    s["matched_without_conflict"] = int((~acc.location_conflict.fillna(False)).sum())
    s["matched_with_vf_geo_conflict"] = int(acc.geo_conflict.fillna(False).sum())
    s["by_state_top"] = acc.osm_adm1_name.value_counts().head(12).to_dict()
    s["osm_tag_coverage_on_matched"] = {c: int(acc[f"osm_{c}"].notna().sum())
                                        for c in ["amenity", "healthcare", "healthcare_speciality", "operator_type"]}
    s["operator_type_on_matched"] = acc.osm_operator_type.value_counts().to_dict()
    s["services"] = service_crosstab(acc, grades_p)
    return s


def service_crosstab(acc, grades_p):
    g = pd.read_parquet(grades_p)[["unique_id", "service", "grade"]]
    spec = acc.osm_healthcare_speciality.fillna("").str.lower()
    out = {}
    for svc, pat in SERVICE_TAG.items():
        tagged = acc[spec.str.contains(pat)]
        claims = g[(g.service == svc) & g.grade.isin(["strong", "medium", "weak", "enum_only"])]
        claim_ids = set(claims.unique_id)
        out[svc] = dict(osm_tagged=len(tagged), vf_claims=int(tagged.unique_id.isin(claim_ids).sum()),
                        vf_no_claim=int((~tagged.unique_id.isin(claim_ids)).sum()),
                        vf_claimants_among_matched=int(acc.unique_id.isin(claim_ids).sum()))
    return out


if __name__ == "__main__":
    main(*sys.argv[1:6])
