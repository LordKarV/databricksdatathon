"""Inspect the e-RaktKosh pull and join it to the Virtue Foundation facilities.

Usage: python -I join.py <erk_dir> <facilities.parquet> <facility_location.parquet>

Writes <erk_dir>/erk_centres.parquet (one row per hospitalCode, no phones or
emails) and <erk_dir>/erk_vf_matches.parquet, prints the stats used in README.

Matching rule (per e-RaktKosh centre, best VF candidate):
  location gate: both have coordinates and are <= 5 km + VF loc_radius (cap 15 km) apart, or (no coords on
    either side) same state and same district name;
  name gate: rapidfuzz token_sort_ratio >= 85 on blood-word-stripped names, or
    token_set_ratio >= 90 AND the names share a distinctive (non-generic) token.
ponytail: O(n*m) scan inside each state, fine for 4k x 10k; use a BallTree if
it grows.
"""
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

BLOOD_WORDS = {"blood", "bank", "centre", "center", "bsu", "bcsu", "storage", "unit", "component",
               "separation", "bb", "bloodbank", "bloodcentre", "bloodcenter"}
GENERIC = {"hospital", "hospitals", "district", "govt", "government", "general", "civil", "medical",
           "college", "research", "institute", "sub", "subdivisional", "chc", "phc", "taluk", "taluka",
           "and", "of", "the", "multispeciality", "multi", "super", "speciality", "specialty", "pvt",
           "ltd", "private", "limited", "trust", "memorial", "charitable", "society", "care", "health",
           "clinic", "sciences", "science", "mch", "community", "primary", "area", "referral", "dist",
           "dh", "sdh", "gh", "mc", "rmc", "cottage", "nursing", "home", "centres", "services", "service",
           "rural", "urban", "new", "city", "red", "cross", "indian", "lions", "rotary", "voluntary",
           "foundation", "hosp", "main", "station", "national", "state", "municipal", "corporation",
           "cancer", "heart", "eye", "multispecialty", "superspeciality", "unit", "dr", "sri", "shri", "st"}
MAX_KM = 5.0
MAX_GATE_KM = 15.0
OLD_CITY = frozenset({"calcutta", "madras", "bombay", "bangalore", "bengaluru", "delhi", "poona", "baroda", "trivandrum",
                      "cochin", "mysore", "calicut", "mangalore", "benaras", "banaras", "gurgaon", "allahabad"})
BLOOD_RE = re.compile(r"blood\s*(?:bank|cent(?:re|er)|storage)|transfusion|bloodbank", re.I)


def norm(s: str) -> list[str]:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower().replace("&", " and "))
    return [t for t in s.split() if t not in BLOOD_WORDS]


def name_ok(a: list[str], b: list[str], places: frozenset = frozenset()) -> tuple[bool, float]:
    """Fuzzy score plus a distinctive-token test. Place names (district, city)
    and generic words do not count as distinctive, so "PSP Medical College
    Hospital" never matches "Meenakshi Medical College Hospital"."""
    sa, sb = " ".join(a), " ".join(b)
    if not sa or not sb:
        return False, 0.0
    da = {t for t in a if len(t) > 1 and t not in GENERIC and t not in places}
    db = {t for t in b if len(t) > 1 and t not in GENERIC and t not in places}
    shared = da & db
    # reject when both names carry distinctive words the other lacks ("Madras Egmore" vs "Madras ENT")
    if not shared or (da - shared and db - shared) or len(shared) / max(len(da), len(db)) < 0.5:
        return False, 0.0
    set_r = fuzz.token_set_ratio(sa, sb)
    return set_r >= 85, float(set_r)


def hav_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))


def dist_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").lower())


def load_erk(d: Path) -> pd.DataFrame:
    rows = pd.read_parquet(d / "state_mode_rows.parquet")
    dists = pd.read_parquet(d / "districts.parquet")
    coords = pd.read_parquet(d / "nearest_coords.parquet")
    # 46 rows have no hospitalCode (no camp/stock links); keep them, dedupe the rest
    rows = pd.concat([rows[rows.hospital_code.notna()].drop_duplicates("hospital_code"),
                      rows[rows.hospital_code.isna()]], ignore_index=True).assign(source="state_list")
    # /nearest also returns centres the state list omits (562 on 2026-11-21); keep them, flagged
    extra = coords[~coords.hospitalCode.isin(rows.hospital_code)].rename(columns={
        "hospitalCode": "hospital_code", "hospitalType": "category", "distId": "dist_id", "stateCode": "state_id"})
    extra = extra[["hospital_code", "name", "address", "category", "type", "dist_id", "state_id"]].assign(
        source="nearest_only", query_state_code=extra.state_id)
    rows = pd.concat([rows, extra], ignore_index=True)
    e = rows.merge(
        dists.rename(columns={"state_code": "state_id"}), on=["state_id", "dist_id"], how="left")
    c = coords.rename(columns={"hospitalCode": "hospital_code"})[["hospital_code", "latitude", "longitude"]]
    e = e.merge(c, on="hospital_code", how="left")
    e["category"] = e.category.str.strip()
    return e.drop(columns=["sno"])


def load_vf(fac_path: str, loc_path: str) -> pd.DataFrame:
    raw = pd.read_parquet(fac_path, columns=["unique_id", "specialties", "procedure", "equipment",
                                             "capability", "description", "facilityTypeId"])
    loc = pd.read_parquet(loc_path, columns=["unique_id", "name", "address_city", "state_final", "district",
                                             "loc_lat", "loc_lon", "loc_conf", "loc_radius"])
    v = loc.merge(raw, on="unique_id", how="left")
    text = v[["specialties", "procedure", "equipment", "capability", "description"]].fillna("").agg(" ".join, axis=1)
    v["vf_claims_blood"] = text.str.contains(BLOOD_RE)
    v["vf_blood_snippet"] = text.str.extract(r"([^.\"\]\[]{0,80}(?:[Bb]lood\s*(?:[Bb]ank|[Cc]ent(?:re|er)|[Ss]torage)|[Tt]ransfusion)[^.\"\]\[]{0,60})", expand=False)
    v["toks"] = v["name"].map(norm)
    v["dkey"] = v["district"].map(dist_key)
    return v


def state_names(e: pd.DataFrame, v: pd.DataFrame) -> dict:
    """e-RaktKosh state code -> VF state_final, by majority vote over VF rows
    whose district name appears in that state's e-RaktKosh district list."""
    out = {}
    for code, g in e.groupby("state_id"):
        hits = v[v.dkey.isin({dist_key(x) for x in g.district.dropna()})].state_final.dropna()
        if len(hits):
            out[code] = hits.mode().iat[0]
    return out


def match(e: pd.DataFrame, v: pd.DataFrame) -> pd.DataFrame:
    vlat, vlon = v.loc_lat.to_numpy(), v.loc_lon.to_numpy()
    # VF locations placed at a PIN centroid carry a radius; widen the gate by it, capped
    gate_km = np.minimum(MAX_KM + v.loc_radius.fillna(0).to_numpy(), MAX_GATE_KM)
    st = state_names(e, v)
    vstate = v.state_final.to_numpy()
    out = []
    for r in e.itertuples():
        et = norm(r.name)
        has_xy = not (pd.isna(r.latitude) or pd.isna(r.longitude))
        km = hav_km(r.latitude, r.longitude, vlat, vlon) if has_xy else np.full(len(v), np.nan)
        near = np.where(km <= gate_km)[0] if has_xy else np.array([], int)
        dk = dist_key(r.district)
        no_xy_pair = np.isnan(vlat) | (not has_xy)  # district gate only when distance is unknown
        same_d = np.where((v.dkey.to_numpy() == dk) & no_xy_pair & (vstate == st.get(r.state_id)))[0] if dk else np.array([], int)
        best = None
        for i in np.unique(np.concatenate([near, same_d])):
            places = frozenset(norm(r.district) + norm(v.address_city.iat[i]) + norm(v.district.iat[i])) | OLD_CITY
            ok, sc = name_ok(et, v.toks.iat[i], places)
            if ok and (best is None or (sc, -np.nan_to_num(km[i], nan=99)) > (best[1], -np.nan_to_num(km[best[0]], nan=99))):
                best = (i, sc)
        if best:
            i, sc = best
            out.append({"hospital_code": r.hospital_code, "erk_name": r.name, "erk_type": r.type,
                        "erk_category": r.category, "erk_district": r.district, "unique_id": v.unique_id.iat[i],
                        "vf_name": v.name.iat[i], "vf_city": v.address_city.iat[i], "vf_district": v.district.iat[i],
                        "score": sc, "km": None if math.isnan(km[i]) else round(float(km[i]), 2),
                        "gate": "distance" if i in set(near) else "district",
                        "vf_claims_blood": bool(v.vf_claims_blood.iat[i]), "vf_blood_snippet": v.vf_blood_snippet.iat[i]})
    return pd.DataFrame(out)


def selfcheck():
    assert norm("Goa Medical College, Blood Centre") == ["goa", "medical", "college"]
    assert name_ok(norm("District Hospital Peddem"), norm("District Hospital"))[0] is False
    assert name_ok(norm("Manipal Hospital, Blood Centre (Bcsu)"), norm("Manipal Hospital Goa"), frozenset({"goa"}))[0] is True
    assert name_ok(norm("Meenakshi Medical College Hospital"), norm("PSP Medical College Hospital"))[0] is False
    assert name_ok(norm("North Western Railway, Jaipur"), norm("Jaipur"), frozenset({"jaipur"}))[0] is False


def main(erk_dir, fac_path, loc_path):
    selfcheck()
    d = Path(erk_dir)
    e = load_erk(d)
    v = load_vf(fac_path, loc_path)
    e.to_parquet(d / "erk_centres.parquet", index=False)
    stats = {"erk_rows_state_mode": int(len(pd.read_parquet(d / "state_mode_rows.parquet"))),
             "erk_centres": int(len(e)),
             "erk_unique_hospital_codes": int(e.hospital_code.nunique()),
             "erk_without_hospital_code": int(e.hospital_code.isna().sum()),
                          "erk_at_india_centroid": int(((e.latitude.round(4) == 22.3511) & (e.longitude.round(4) == 78.6677)).sum()),
             "erk_by_source": e["source"].value_counts().to_dict(),
             "erk_by_type": e["type"].value_counts(dropna=False).to_dict(),
             "erk_by_category": e["category"].value_counts(dropna=False).to_dict(),
             "erk_with_coords": int(e.latitude.notna().sum()),
             "erk_with_district_name": int(e.district.notna().sum()),
             "erk_states": int(e.state_id.nunique()),
             "null_rate": {c: round(float((e[c].isna() | e[c].astype(str).str.strip().isin(["", "-", "nan", "None"])).mean()), 4)
                           for c in ["name", "address", "category", "type", "hospital_code", "dist_id", "latitude"]},
             "erk_coords_outside_india_bbox": int((~e.latitude.between(6, 37.5) | ~e.longitude.between(68, 98))[e.latitude.notna()].sum()),
             "erk_duplicate_coords": int(e[e.latitude.notna()].duplicated(["latitude", "longitude"], keep=False).sum()),
             "vf_rows_with_location": int(v.loc_lat.notna().sum()), "vf_rows": int(len(v)),
             "vf_claims_blood": int(v.vf_claims_blood.sum())}
    m = match(e, v)
    m.to_parquet(d / "erk_vf_matches.parquet", index=False)
    vf_matched = m.drop_duplicates("unique_id")
    stats.update({
        "matched_erk_centres": int(len(m)), "match_rate_over_erk": round(len(m) / len(e), 4),
        "matched_by_gate": m.gate.value_counts().to_dict(),
        "matched_by_type": m.erk_type.value_counts().to_dict(),
        "distinct_vf_matched": int(len(vf_matched)),
        "vf_matched_claims_blood": int(vf_matched.vf_claims_blood.sum()),
        "vf_matched_no_blood_claim": int((~vf_matched.vf_claims_blood).sum()),
        "vf_hospitals": int((v.facilityTypeId == "hospital").sum()),
        "vf_blood_claimers_matched": int(vf_matched.vf_claims_blood.sum()),
        "vf_blood_claimers_total": int(v.vf_claims_blood.sum()),
    })
    print(json.dumps(stats, indent=1, default=str))
    (d / "join_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    sample = m.sample(min(20, len(m)), random_state=7)
    pd.set_option("display.width", 250)
    print(sample[["hospital_code", "erk_name", "erk_district", "vf_name", "vf_city", "score", "km", "gate",
                  "vf_claims_blood"]].to_string(index=False))
    sample.to_csv(Path(__file__).with_name("handcheck_sample.csv"), index=False)


if __name__ == "__main__":
    main(*sys.argv[1:4])
