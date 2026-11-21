"""Inspect the NMC college dump and join it to the Virtue Foundation facilities.

Usage: python -I join.py <nmc_data_dir> <project_root>

Reads <nmc_data_dir>/details.jsonl and list.json (from fetch.py), writes
nmc_colleges.parquet, nmc_courses.parquet, nmc_vf_matches.parquet,
nmc_service_labels.parquet and join_stats.json into <nmc_data_dir>.
Uses audit outputs read-only: audit/geo/pin_centroids.parquet (PIN centroids)
and audit/claims/out/grades.parquet (which VF facilities claim which service).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

RADIUS_KM = 10.0      # geo gate: same PIN, or within this distance
NAME_MIN = 88         # WRatio on normalized names, with a geo match
NAME_MIN_NOGEO = 95   # WRatio when NMC has no usable PIN: same state only
CORE_MIN = 80         # token_set_ratio on names minus generic words
SEED = 7

# NMC course -> service. strong = a department that by regulation runs the
# service; support = weaker proxy. ponytail: regex on course_name, extend if
# new course names appear.
COURSE_SERVICE = {
    "dialysis": (r"D\.M\. Nephrology", None),
    "cardiac_surgery": (r"Cardio ?(?:Vascular|Thoracic)", r"D\.M\. Cardiology"),
    "nicu": (r"Neonatology", r"M\.D\. Paediatrics"),
    "csection": (r"Obstetrics and Gynaecology", None),
    "trauma": (r"Emergency Medicine|M\.Ch\. Neurosurgery", r"M\.S\. Orthopaedics"),
    "mri": (None, r"Radio-?diagnosis"),
    "burns": (r"Plastic", None),
    "icu": (r"Critical Care", r"Anaesthesiology"),
}

ALIAS = {
    r"\baiims\b": "all india institute of medical sciences",
    r"\bpgimer\b": "postgraduate institute of medical education and research",
    r"\bjipmer\b": "jawaharlal institute of postgraduate medical education and research",
    r"\bgovt\b": "government", r"\bgmc\b": "government medical college",
    r"\bhosp\b": "hospital", r"\binst\b": "institute", r"\bmed\b": "medical",
    r"\bsciences\b": "science", r"\bcentre\b": "center", r"\bdr\b": "",
}
STOP = r"\b(the|and|of|for|in|at|ltd|pvt|private|limited)\b"


def norm(s):
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"\([^)]*\)", " ", s)          # drop "(AN/001/G/1)" style codes
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    for k, v in ALIAS.items():
        s = re.sub(k, v, s)
    s = re.sub(STOP, " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Words every medical college or hospital shares. Requiring the remaining
# "core" tokens to agree stops "X Medical College & Hospital" matching a
# nearby "City Hospital" on the shared word alone.
GENERIC = set("medical college hospital hospitals institute science research center government health care "
              "foundation teaching general district multispeciality multi speciality super specialty trust "
              "education postgraduate academy school campus india".split())


def core(n):
    return " ".join(t for t in n.split() if t not in GENERIC and not t.isdigit())


def name_ok(a, b, full_min):
    ca, cb = core(a), core(b)
    return bool(ca and cb) and fuzz.WRatio(a, b) >= full_min and fuzz.token_set_ratio(ca, cb) >= CORE_MIN


def state_key(s):
    return re.sub(r"[^a-z]", "", str(s or "").lower()).replace("and", "")


def haversine(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


def pin_int(x):
    m = re.search(r"\b(\d{6})\b", str(x or ""))
    return int(m.group(1)) if m else None


def load_nmc(d):
    recs = [json.loads(l) for l in (d / "details.jsonl").read_text().splitlines() if l.strip()]
    lst = pd.DataFrame(json.loads((d / "list.json").read_text()))
    cols = pd.DataFrame([{k: v for k, v in r.items() if k != "courses"} for r in recs])
    cols = cols.rename(columns={"id": "college_id"})
    mbbs = lst[["college_id", "approved_seat", "approval_date", "updated_date", "lop_date"]]
    cols = cols.merge(mbbs.rename(columns={"approved_seat": "mbbs_seats"}), on="college_id", how="left")
    courses = pd.DataFrame([dict(college_id=r["id"], **c) for r in recs for c in r["courses"]])
    return cols, courses, lst


def inspect(cols, courses, lst, pins):
    stats = {"list_rows": len(lst), "detail_rows": len(cols), "course_rows": len(courses)}
    stats["null_rate"] = {c: round(float(cols[c].isna().mean() + (cols[c].astype(str).str.strip() == "").mean()), 3)
                          for c in cols.columns}
    cols["pin_from_address"] = cols["address"].map(pin_int)
    cols["pin"] = cols["pincode"].map(pin_int).fillna(cols["pin_from_address"])
    pin_ok = cols["pin"].isin(pins["pincode"])
    stats["pin_valid_6digit"] = int(cols["pin"].notna().sum())
    stats["pin_in_directory"] = int(pin_ok.sum())
    stats["pin_address_disagree"] = int(((cols["pin_from_address"].notna()) & (cols["pin"].notna())
                                         & (cols["pin"] != cols["pin_from_address"])).sum())
    g = cols.merge(pins[["pincode", "state"]], left_on="pin", right_on="pincode", how="left", suffixes=("", "_pin"))
    bad_state = g["state"].notna() & (g["state_name"].map(state_key) != g["state"].map(state_key))
    stats["pin_state_disagree"] = int(bad_state.sum())
    stats["pin_state_disagree_examples"] = g.loc[bad_state, ["college_name", "state_name", "pincode", "state"]].head(15).values.tolist()
    stats["courses_by_type"] = courses["course_type"].value_counts().to_dict()
    stats["approval_date_range"] = [str(lst["approval_date"].min()), str(lst["approval_date"].max())]
    stats["updated_date_counts"] = lst["updated_date"].value_counts().head(5).to_dict()
    stats["management_type"] = cols["management_type"].value_counts().to_dict()
    stats["dup_college_names"] = int(cols["college_name"].map(norm).duplicated().sum())
    stats["total_mbbs_seats"] = int(lst["approved_seat"].sum())
    stats["courses_zero_seats"] = int((courses["approved_seat"].fillna(0) == 0).sum())
    return cols, stats


def match(cols, vf, pins):
    pc = pins.set_index("pincode")[["best_lat", "best_lon"]]
    cols = cols.join(pc, on="pin")
    vf = vf.join(pc.rename(columns={"best_lat": "plat", "best_lon": "plon"}), on="vpin")
    vlat, vlon = vf["latitude"].to_numpy(float), vf["longitude"].to_numpy(float)
    plat, plon = vf["plat"].to_numpy(float), vf["plon"].to_numpy(float)
    vstate = vf["address_stateOrRegion"].map(state_key).to_numpy()
    vnorm = vf["name"].map(norm).tolist()
    out = []
    for r in cols.itertuples():
        n = norm(r.college_name)
        if pd.notna(r.best_lat):
            same_pin = (vf["vpin"] == r.pin).to_numpy()
            dist = np.fmin(haversine(r.best_lat, r.best_lon, vlat, vlon), haversine(r.best_lat, r.best_lon, plat, plon))
            cand, full_min, gate = np.where(same_pin | (dist <= RADIUS_KM))[0], NAME_MIN, "geo"
        else:  # no usable NMC PIN: same state plus a stricter name score
            same_pin, dist = np.zeros(len(vf), bool), np.full(len(vf), np.nan)
            cand, full_min, gate = np.where(vstate == state_key(r.state_name))[0], NAME_MIN_NOGEO, "state"
        for i in cand:
            if name_ok(n, vnorm[i], full_min):
                out.append(dict(college_id=r.college_id, college_name=r.college_name, nmc_pin=r.pin,
                                nmc_state=r.state_name, unique_id=vf.at[i, "unique_id"], vf_name=vf.at[i, "name"],
                                vf_city=vf.at[i, "address_city"], vf_pin=vf.at[i, "vpin"], gate=gate,
                                same_pin=bool(same_pin[i]), dist_km=round(float(dist[i]), 2),
                                score=round(fuzz.WRatio(n, vnorm[i]), 1)))
    return pd.DataFrame(out)


def service_labels(courses):
    rows = []
    for svc, (strong, support) in COURSE_SERVICE.items():
        for tier, pat in (("strong", strong), ("support", support)):
            if not pat:
                continue
            hit = courses[courses["course_name"].str.contains(pat, regex=True, na=False)]
            g = hit.groupby("college_id").agg(courses=("course_name", lambda x: sorted(set(x))),
                                              seats=("approved_seat", "sum")).reset_index()
            rows.append(g.assign(service=svc, tier=tier))
    lab = pd.concat(rows, ignore_index=True)
    # keep the best tier per (college, service)
    lab["rank"] = lab["tier"].map({"strong": 0, "support": 1})
    return lab.sort_values("rank").drop_duplicates(["college_id", "service"]).drop(columns="rank")


def main():
    d, root = Path(sys.argv[1]), Path(sys.argv[2])
    pins = pd.read_parquet(root / "audit/geo/pin_centroids.parquet")
    vf = pd.read_parquet(root / "data/raw/facilities.parquet")
    vf["latitude"] = pd.to_numeric(vf["latitude"], errors="coerce")
    vf["longitude"] = pd.to_numeric(vf["longitude"], errors="coerce")
    vf["vpin"] = vf["address_zipOrPostcode"].map(pin_int)
    grades = pd.read_parquet(root / "audit/claims/out/grades.parquet")

    cols, courses, lst = load_nmc(d)
    cols, stats = inspect(cols, courses, lst, pins)
    cols.to_parquet(d / "nmc_colleges.parquet")
    courses.to_parquet(d / "nmc_courses.parquet")

    m = match(cols, vf, pins)
    m.to_parquet(d / "nmc_vf_matches.parquet")
    best = m.sort_values(["score", "dist_km"], ascending=[False, True]).drop_duplicates("college_id")
    stats["match"] = {"nmc_colleges": len(cols), "nmc_with_pin_centroid": int(cols["pin"].isin(pins["pincode"]).sum()),
                      "nmc_matched": int(m["college_id"].nunique()), "vf_rows_matched": int(m["unique_id"].nunique()),
                      "pairs": len(m), "vf_rows_hit_by_2plus_colleges": int((m.groupby("unique_id")["college_id"].nunique() > 1).sum())}
    stats["match"]["match_rate"] = round(stats["match"]["nmc_matched"] / len(cols), 3)
    is_mc = vf["name"].str.contains(r"medical college|institute of medical|aiims|medical sciences", case=False, na=False) \
        & ~vf["name"].str.contains(r"dental|ayurved|homoeo|homeo|unani|siddha|nursing|veterinary", case=False, na=False)
    stats["match"]["vf_medical_college_named_rows"] = int(is_mc.sum())
    stats["match"]["vf_medical_college_named_matched"] = int(vf.loc[is_mc, "unique_id"].isin(m["unique_id"]).sum())

    lab = service_labels(courses)
    lab.to_parquet(d / "nmc_service_labels.parquet")
    claims = grades[grades["grade"] != "non_offer_only"][["unique_id", "service", "grade"]]
    pairs = m[["college_id", "unique_id"]].drop_duplicates()
    svc = {}
    for s in COURSE_SERVICE:
        ls = lab[lab["service"] == s]
        mp = pairs.merge(ls[["college_id", "tier"]], on="college_id")
        cl = claims[claims["service"] == s]
        mp = mp.merge(cl[["unique_id", "grade"]], on="unique_id", how="left")
        mp["grade"] = mp["grade"].notna()
        per_college = mp.groupby(["college_id", "tier"])["grade"].any().reset_index()
        svc[s] = {t: {"matched_colleges_with_course": int((per_college["tier"] == t).sum()),
                      "vf_claims": int(per_college.loc[per_college["tier"] == t, "grade"].sum()),
                      "vf_silent": int((~per_college.loc[per_college["tier"] == t, "grade"]).sum())}
                  for t in ("strong", "support")}
        svc[s]["nmc_colleges_with_strong_course_all"] = int((ls["tier"] == "strong").sum())
    stats["service_vs_vf"] = svc
    (d / "join_stats.json").write_text(json.dumps(stats, indent=1, default=str))

    sample = best.sample(min(20, len(best)), random_state=SEED)
    print(sample[["college_name", "nmc_pin", "vf_name", "vf_city", "vf_pin", "dist_km", "score"]].to_string())
    print(json.dumps({k: stats[k] for k in ("match", "service_vs_vf")}, indent=1))


if __name__ == "__main__":
    main()
