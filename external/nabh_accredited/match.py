"""Join NABH listings to Virtue Foundation facilities.

Usage: python -I match.py NABH_DIR FACILITIES_PARQUET FACILITY_GEO_PARQUET PIN_CENTROIDS_PARQUET
Writes NABH_DIR/nabh_vf_match.parquet, NABH_DIR/match_stats.json, NABH_DIR/handcheck_sample.csv
and NABH_DIR/nabh_geo_qc.parquet.

Blocking: same 6-digit PIN, or both coordinates within BLOCK_KM.
Accept: name score >= NAME_MIN, or name score >= NAME_MIN_CLOSE when the pair is
both same-PIN and within CLOSE_KM. Best NABH record per VF facility wins.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

BLOCK_KM = 2.0
CLOSE_KM = 0.5
NAME_MIN = 90
NAME_MIN_CLOSE = 80
# Generic words carry no identity; removing them stops "X Hospital" matching "Y Hospital".
GENERIC = set("""hospital hospitals pvt private ltd limited the and of a unit centre center clinic clinics
multispeciality multi speciality specialty super superspeciality health healthcare care medical
institute research nursing home trust llp co
path pathology lab labs laboratory imaging diagnostic diagnostics scan scans polyclinic""".split())

# NABH specialty filter code -> regex over VF free text (specialties/procedure/capability/description).
SERVICE_RE = {
    "DIA": r"dialys|haemodialys|hemodialys",
    "NPH": r"nephrolog|kidney",
    "OBG": r"obstet|gynec|gynaec|maternity|deliver|c-section|caesar|cesarean",
    "ICU": r"\bicu\b|intensive care|critical care|nicu|picu|ccu",
    "EMD": r"emergency|casualty|trauma",
    "CAR": r"cardio|cardiac|heart|cath ?lab|angio",
    "IMG": r"\bmri\b|\bct\b|ct scan|radiolog|imaging|x-ray|ultrasound|sonograph",
    "ONC": r"oncolog|cancer|chemotherap|radiotherap",
    "TRN": r"transplant",
    "NEU": r"neurolog|neurosurg|neuro",
    "PED": r"pediatr|paediatr|neonat|child",
    "ORT": r"orthop|joint replacement|fracture",
    "SUR": r"surg",
    "BLO": r"blood bank|blood centre|blood center",
}


def norm_name(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", str(s).lower())  # drop "(a unit of ...)"
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in GENERIC)


def name_score(a: str, b: str) -> float:
    """token_sort on generic-stripped names; token_set (subset match) only when both keep 2+ tokens,
    otherwise "Aditya Dental" would score 100 against "Aditya"."""
    if not a or not b:
        return 0.0
    s = fuzz.token_sort_ratio(a, b)
    if min(len(a.split()), len(b.split())) >= 2:
        s = max(s, fuzz.token_set_ratio(a, b))
    return s


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def candidates(vf: pd.DataFrame, nb: pd.DataFrame) -> pd.DataFrame:
    by_pin = vf.dropna(subset=["pin"]).merge(nb.dropna(subset=["pin"]), on="pin", suffixes=("_vf", "_nb"))
    by_pin["pin_vf"] = by_pin["pin_nb"] = by_pin["pin"]
    # ponytail: 0.05 deg grid buckets for the distance block, fine at 10k x 21k
    v = vf.dropna(subset=["lat", "lon"]).assign(cell=lambda d: list(zip((d.lat / 0.05).astype(int), (d.lon / 0.05).astype(int))))
    n = nb.dropna(subset=["lat", "lon"])
    near = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            nn = n.assign(cell=list(zip((n.lat / 0.05).astype(int) + dx, (n.lon / 0.05).astype(int) + dy)))
            near.append(v.merge(nn, on="cell", suffixes=("_vf", "_nb")))
    near = pd.concat(near, ignore_index=True).drop(columns="cell")
    pairs = pd.concat([by_pin.drop(columns="pin"), near], ignore_index=True)
    pairs = pairs.drop_duplicates(subset=["unique_id", "nabh_id"])
    pairs["dist_km"] = haversine_km(pairs.lat_vf, pairs.lon_vf, pairs.lat_nb, pairs.lon_nb)
    pairs["same_pin"] = pairs.pin_vf.notna() & (pairs.pin_vf == pairs.pin_nb)
    return pairs[pairs.same_pin | (pairs.dist_km <= BLOCK_KM)].copy()


def score(pairs: pd.DataFrame) -> pd.DataFrame:
    pairs["name_score"] = [name_score(a, b) for a, b in zip(pairs.norm_vf, pairs.norm_nb)]
    pairs["raw_score"] = [fuzz.WRatio(a, b) for a, b in zip(pairs.name_vf, pairs.name_nb)]
    close = pairs.same_pin & (pairs.dist_km <= CLOSE_KM)
    pairs["accept"] = (pairs.name_score >= NAME_MIN) | (close & (pairs.name_score >= NAME_MIN_CLOSE))
    return pairs


def load_vf(fac_path: str, geo_path: str) -> pd.DataFrame:
    geo = pd.read_parquet(geo_path, columns=["unique_id", "name", "pin", "latitude", "longitude", "geo_conflict"])
    geo = geo.rename(columns={"latitude": "lat", "longitude": "lon"})
    geo["pin"] = geo.pin.map(lambda p: str(int(p)) if pd.notna(p) else None)
    fac = pd.read_parquet(fac_path, columns=["unique_id", "specialties", "procedure", "capability", "description",
                                             "equipment"])
    fac["text"] = fac[["specialties", "procedure", "capability", "description", "equipment"]].fillna("").agg(" ".join, axis=1)
    vf = geo.merge(fac[["unique_id", "text"]], on="unique_id", how="left")
    vf["claims_nabh"] = vf.text.str.contains("nabh", case=False) | vf.name.str.contains("nabh", case=False)
    vf["norm"] = vf.name.map(norm_name)
    return vf


def load_nabh(d: Path) -> pd.DataFrame:
    nb = pd.read_parquet(d / "nabh_hco.parquet").rename(columns={"lng": "lon"})
    nb["nabh_id"] = np.arange(len(nb))
    nb["norm"] = nb.name.map(norm_name)
    return nb


def geo_qc(nb: pd.DataFrame, pin_path: str) -> pd.DataFrame:
    pc = pd.read_parquet(pin_path, columns=["pincode", "best_lat", "best_lon", "state"])
    pc["pin"] = pc.pincode.astype(str)
    q = nb.merge(pc[["pin", "best_lat", "best_lon", "state"]], on="pin", how="left")
    q["d_pin_km"] = haversine_km(q.lat, q.lon, q.best_lat, q.best_lon)
    return q[["nabh_id", "acc_no", "pin", "lat", "lon", "d_pin_km", "state"]]


def main(nabh_dir, fac_path, geo_path, pin_path):
    d = Path(nabh_dir)
    vf, nb = load_vf(fac_path, geo_path), load_nabh(d)
    cols_nb = ["nabh_id", "name", "norm", "pin", "lat", "lon", "acc_no", "status", "prefix", "address", "cert_url"]
    pairs = score(candidates(vf[["unique_id", "name", "norm", "pin", "lat", "lon"]], nb[cols_nb]))
    best = (pairs[pairs.accept].sort_values(["name_score", "raw_score", "dist_km"], ascending=[False, False, True])
            .drop_duplicates("unique_id"))
    best = best.merge(vf[["unique_id", "claims_nabh", "text", "geo_conflict"]], on="unique_id")
    spec_path = d / "nabh_hco_specialty.parquet"
    if spec_path.exists():
        sp = pd.read_parquet(spec_path)
        codes = sp.groupby("acc_no").spec_code.agg(lambda s: sorted(set(s))).rename("nabh_specs")
        best = best.merge(codes, left_on="acc_no", right_index=True, how="left")
    best.drop(columns="text").to_parquet(d / "nabh_vf_match.parquet", index=False)

    qc = geo_qc(nb, pin_path)
    qc.to_parquet(d / "nabh_geo_qc.parquet", index=False)
    stats = {
        "vf_rows": int(len(vf)),
        "vf_matched": int(best.unique_id.nunique()),
        "vf_match_rate": round(best.unique_id.nunique() / len(vf), 4),
        "vf_claims_nabh": int(vf.claims_nabh.sum()),
        "vf_claims_nabh_matched": int(best.claims_nabh.sum()),
        "vf_claims_nabh_match_rate": round(best.claims_nabh.sum() / max(vf.claims_nabh.sum(), 1), 4),
        "matched_without_nabh_claim": int((~best.claims_nabh).sum()),
        "nabh_rows": int(len(nb)),
        "nabh_rows_matched": int(best.nabh_id.nunique()),
        "candidate_pairs": int(len(pairs)),
        "matched_status": best.status.value_counts(dropna=False).to_dict(),
        "matched_prefix": best.prefix.value_counts(dropna=False).head(15).to_dict(),
        "nabh_geo_d_pin_km_quantiles": qc.d_pin_km.quantile([0.5, 0.9, 0.95, 0.99]).round(2).to_dict(),
        "nabh_geo_far_gt_25km": int((qc.d_pin_km > 25).sum()),
        "nabh_geo_with_both": int(qc.d_pin_km.notna().sum()),
    }
    if "nabh_specs" in best:
        svc = {}
        for code, rx in SERVICE_RE.items():
            has = best.nabh_specs.map(lambda s: isinstance(s, list) and code in s)
            claims = best.text.fillna("").str.contains(rx, case=False, regex=True)
            if has.any():
                svc[code] = {"nabh_lists": int(has.sum()), "vf_claims_too": int((has & claims).sum()),
                             "vf_silent": int((has & ~claims).sum()),
                             "vf_claims_not_nabh_listed": int((~has & claims).sum())}
        stats["service_agreement_matched"] = svc
    (d / "match_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps(stats, indent=1, default=str))
    cols = ["name_vf", "name_nb", "pin_vf", "pin_nb", "dist_km", "name_score", "acc_no", "status", "address"]
    best.sample(min(20, len(best)), random_state=7)[cols].to_csv(d / "handcheck_sample.csv", index=False)


def _selfcheck() -> None:
    assert norm_name("Aditya Ashwini Hospital (Unit of Cuttack Hospital Pvt. Ltd.)") == "aditya ashwini"
    assert name_score(norm_name("Aditya Dental Clinic"), norm_name("Aditya Multispeciality Hospital")) < NAME_MIN
    assert name_score(norm_name("Ahana Hospitals"), norm_name("Ahana Hospitals LLP")) == 100
    assert name_score(norm_name("Multispeciality Hospital"), norm_name("Care Hospital")) == 0
    assert abs(haversine_km(28.6, 77.2, 28.6, 77.3) - 9.76) < 0.1


if __name__ == "__main__":
    _selfcheck()
    main(*sys.argv[1:5])
