"""Join PMNDP state counts and the Goa centre list to the Virtue Foundation facilities.

Usage: python -I join_test.py <facilities.parquet> <pincode_directory.parquet> <pmndp_data_dir>
Writes <pmndp_data_dir>/join_state_supply.csv, goa_matches.csv, district_hospital_candidates.csv.
"""
import math
import re
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

FAC, PIN, D = (Path(a) for a in sys.argv[1:4])
sys.path.insert(0, str(Path(__file__).parent))
from parse import norm_state  # noqa: E402

DIALYSIS = re.compile(r"dialys|haemodialy|hemodialy|nephrolog|renal replacement", re.I)
TEXT_COLS = ["specialties", "procedure", "equipment", "capability", "description"]
# ponytail: regex name heuristic for "district-level public hospital"; precision hand-checked below.
DH_NAME = re.compile(r"\b(?:district|sadar|civil|general|zilla|zila|jilla) hospital\b|\bdistrict headquarters? hospital\b", re.I)
ABBR = {"chc": "community health centre", "phc": "primary health centre", "sdh": "sub district hospital",
        "gmc": "goa medical college", "dh": "district hospital"}
MATCH_SCORE, MAX_KM = 85, 10


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return " ".join(ABBR.get(w, w) for w in s.split())


def km(a1, o1, a2, o2) -> float:
    if any(pd.isna(x) for x in (a1, o1, a2, o2)):
        return float("nan")
    a1, o1, a2, o2 = map(math.radians, (a1, o1, a2, o2))
    h = math.sin((a2 - a1) / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin((o2 - o1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def load_facilities() -> pd.DataFrame:
    f = pd.read_parquet(FAC)
    f = f.assign(
        state_key=f.address_stateOrRegion.fillna("").map(norm_state),
        pin=f.address_zipOrPostcode.fillna("").str.replace(r"\D", "", regex=True).str[:6],
        lat=pd.to_numeric(f.latitude, errors="coerce"), lon=pd.to_numeric(f.longitude, errors="coerce"),
        claims_dialysis=f[TEXT_COLS].fillna("").astype(str).agg(" ".join, axis=1).str.contains(DIALYSIS),
        nname=f.name.map(norm_name),
    )
    return f


def state_join(f: pd.DataFrame, s: pd.DataFrame) -> None:
    keys = set(s.state_key)
    print(f"VF rows whose state string joins to a PMNDP state: {f.state_key.isin(keys).sum()} / {len(f)}")
    g = f[f.state_key.isin(keys)].groupby("state_key").agg(
        vf_rows=("name", "size"), vf_claim_dialysis=("claims_dialysis", "sum"),
        vf_public_claim_dialysis=("claims_dialysis", lambda x: (x & (f.loc[x.index, "operatorTypeId"] == "public")).sum()))
    out = s.merge(g, on="state_key", how="left").fillna({"vf_rows": 0, "vf_claim_dialysis": 0, "vf_public_claim_dialysis": 0})
    print(f"PMNDP states with >=1 VF row: {(out.vf_rows > 0).sum()} / {len(out)}")
    out.to_csv(D / "join_state_supply.csv", index=False)
    print(out[["state_raw", "nhsrc_functional_centres", "vf_rows", "vf_claim_dialysis", "vf_public_claim_dialysis"]].to_string())


def goa_match(f: pd.DataFrame, pins: pd.DataFrame) -> None:
    goa = pd.read_csv(D / "goa_pmndp_centres_2020.csv", dtype={"pincode": str})
    cand = f[(f.state_key == "goa") | f.pin.str.startswith("403")]
    rows = []
    for _, g in goa.iterrows():
        pc = pins[pins.pincode == g.pincode]
        glat, glon = pc.lat.median(), pc.lon.median()
        sc = cand.assign(score=cand.nname.map(lambda n: fuzz.token_set_ratio(norm_name(g.centre_name), n)),
                         dist_km=[km(glat, glon, a, o) for a, o in zip(cand.lat, cand.lon)])
        b = sc.sort_values("score", ascending=False).iloc[0]
        ok = b.score >= MATCH_SCORE and (b.pin == g.pincode or b.dist_km <= MAX_KM)
        rows.append({"pmndp_name": g.centre_name, "pmndp_pin": g.pincode, "vf_name": b["name"], "vf_pin": b.pin,
                     "vf_unique_id": b.unique_id, "score": b.score, "dist_km": round(b.dist_km, 1), "matched": ok,
                     "vf_claims_dialysis": bool(b.claims_dialysis) if ok else None})
    m = pd.DataFrame(rows)
    m.to_csv(D / "goa_matches.csv", index=False)
    print(f"\nGoa list matched: {m.matched.sum()} / {len(m)} (candidates in Goa: {len(cand)})")
    print(m.to_string())


def district_hospitals(f: pd.DataFrame) -> None:
    dh = f[f.name.fillna("").str.contains(DH_NAME) & (f.operatorTypeId.isin(["public", "government"]) | f.name.str.contains("Government|Govt", case=False, na=False))]
    print(f"\nPublic district-level hospitals by name: {len(dh)}; claiming dialysis: {dh.claims_dialysis.sum()}")
    dh[["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "operatorTypeId", "claims_dialysis"]].to_csv(
        D / "district_hospital_candidates.csv", index=False)
    print(dh.sample(20, random_state=0)[["name", "address_city", "address_stateOrRegion", "operatorTypeId", "claims_dialysis"]].to_string())


def main() -> None:
    f = load_facilities()
    pins = pd.read_parquet(PIN).assign(lat=lambda p: pd.to_numeric(p.latitude, errors="coerce"),
                                       lon=lambda p: pd.to_numeric(p.longitude, errors="coerce"))
    # Some post-office rows have lat/lon swapped or out of India; keep only plausible ones for PIN centroids.
    pins = pins.assign(pincode=pins.pincode.astype(str))
    pins = pins[pins.lat.between(6, 38) & pins.lon.between(68, 98)]
    state_join(f, pd.read_csv(D / "pmndp_state_counts.csv"))
    goa_match(f, pins)
    district_hospitals(f)


if __name__ == "__main__":
    main()
