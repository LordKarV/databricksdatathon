"""Join test: Virtue Foundation facilities -> HMIS district / sub-district service volumes.

HMIS is aggregate (no facility rows), so the join is geographic:
  facility PIN -> LGD district (reused from external/lgd_archive_parquet, derived/facility_lgd.parquet)
  facility PIN -> LGD sub-district(s) via LGD pincode_villages; urban PINs -> HMIS 'Others' (9999) bucket
  fallback: India Post district name -> HMIS district name, rapidfuzz within state
Then counts how many matched facilities claim a service that HMIS reports zero of in their district.

Usage: python -I join_test.py HMIS_CSV FACILITIES_PARQUET LGD_DIR OUT_DIR
"""
import json
import re
import sys

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process

hmis_csv, fac_pq, lgd_dir, out_dir = sys.argv[1:5]
FUZZ_MIN = 88  # district-name fallback threshold (fuzz.ratio on normalized names)
YEAR = "2019"  # only calendar year with full sub-district coverage (4,306 sub-districts, 700 districts)
SEED = 11

# Service -> (regex over VF free text, HMIS columns summed for the district, sector filter)
SERVICES = {
    "c_section": (r"caesar|cesar|c-section|c section|lscs", "csec_total"),
    "nicu_sncu": (r"\bnicu\b|neonatal intensive|\bsncu\b|newborn intensive", "sncu_inborn_m + sncu_inborn_f + outborn_male + outborn_female"),
    "trauma_emergency": (r"trauma|accident|casualty", "emer_trauma_acc_poison"),
    "burn_care": (r"\bburns?\b", "emer_burn"),
    "cardiac": (r"cardiac|cardiolog|angioplast|bypass|cabg", "emer_cardiac"),
    "major_surgery": (r"general surgery|laparoscop|major surg", "major_surg_nonobgyn"),
    "xray": (r"x-ray|xray|radiograph", "xray_tests"),
    "ultrasound": (r"ultrasound|ultrasonograph|\busg\b|sonograph", "usg_tests"),
}
TEXT_COLS = ["specialties", "procedure", "equipment", "capability", "description"]


def norm(s: object) -> str:
    s = re.sub(r"[^a-z ]+", " ", str(s or "").lower().replace("&", " and "))
    return " ".join(re.sub(r"\b(district|dist|the)\b", " ", s).split())


c = duckdb.connect()
c.execute(f"create view h as select * from read_csv('{hmis_csv}', header=true) where strftime(date,'%Y')='{YEAR}'")
c.execute(f"create view f as select *, row_number() over () rn from '{fac_pq}'")
# facility_lgd rows are in the same order as facilities.parquet (checked); unique_id has 11 duplicates, so join by row.
c.execute(f"create view fl as select *, row_number() over () rn from '{lgd_dir}/derived/facility_lgd.parquet'")
c.execute(f"create view pv as select distinct pincode::varchar pin, subdistrict_code::int sc, district_code::int dc from '{lgd_dir}/pincode_villages.parquet'")

# District level annual volumes per sector (Public/Private/Total).
svc_sql = ", ".join(f"sum({expr}) as {k}" for k, (_, expr) in SERVICES.items())
dist = c.execute(f"select district_code::int dc, any_value(district_name) dn, any_value(state_name) sn, sector, {svc_sql}, count(distinct date) as n_months from h group by dc, sector").df()
hmis_dc = set(dist.dc)

fac = c.execute("""select f.unique_id, f.name, f.address_city, f.address_stateOrRegion state, f.address_zipOrPostcode zip,
       f.operatorTypeId op, f.rn, fl.pin, fl.lgd_district_code::int lgd_dc, fl.lgd_district, fl.n_districts, fl.has_urban,
       fl.ip_district, fl.ip_state, """ + ", ".join(f"f.{t}" for t in TEXT_COLS) + """
  from f left join fl using (rn)""").df()
n_all = len(fac)

# Step 1: LGD district code from PIN. Step 2: India Post district name fuzzy to HMIS district within state.
hd = dist[["dc", "dn", "sn"]].drop_duplicates()
by_state = {s: g for s, g in hd.groupby(hd.sn.str.lower())}
st_alias = {"orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand"}


def fallback(row):
    st = st_alias.get(str(row.ip_state or "").lower(), str(row.ip_state or "").lower())
    g = by_state.get(st)
    if g is None or not row.ip_district:
        return None, 0
    names = [norm(x) for x in g.dn]
    best = process.extractOne(norm(row.ip_district), names, scorer=fuzz.ratio)
    return (int(g.dc.iloc[best[2]]), best[1]) if best and best[1] >= FUZZ_MIN else (None, best[1] if best else 0)


fac["hmis_dc"] = fac.lgd_dc.where(fac.lgd_dc.isin(hmis_dc))
fac["dc_method"] = fac.hmis_dc.notna().map({True: "lgd_pin", False: None})
need = fac.hmis_dc.isna() & fac.ip_district.notna()
fb = fac[need].apply(fallback, axis=1, result_type="expand")
if len(fb):
    fac.loc[need, "hmis_dc"] = fb[0]
    fac.loc[need & fb[0].notna().reindex(fac.index, fill_value=False), "dc_method"] = "ip_name_fuzzy"
fac = fac.merge(hd.rename(columns={"dc": "hmis_dc", "dn": "hmis_district", "sn": "hmis_state"}), on="hmis_dc", how="left")

# Sub-district: rural PIN villages -> LGD sub-district codes present in HMIS for that district.
hs = c.execute("select distinct subdistrict_code::int sc, district_code::int dc, subdistrict_name sn from h where subdistrict_code<>'9999'").df()
pv = c.execute("select * from pv").df().merge(hs[["sc", "dc"]].drop_duplicates(), on=["sc", "dc"])
pin_sc = pv.groupby(["pin", "dc"]).sc.apply(lambda s: sorted(set(s))).reset_index().rename(columns={"dc": "hmis_dc"})
fac = fac.merge(pin_sc, on=["pin", "hmis_dc"], how="left")
fac["n_sc"] = fac.sc.apply(lambda v: len(v) if isinstance(v, list) else 0)
fac["sub_level"] = "none"
fac.loc[fac.hmis_dc.notna() & (fac.has_urban == True), "sub_level"] = "urban_others_bucket"  # noqa: E712
fac.loc[fac.n_sc == 1, "sub_level"] = "single_subdistrict"
fac.loc[fac.n_sc > 1, "sub_level"] = "multi_subdistrict"

# Service claims in VF text.
txt = fac[TEXT_COLS].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
for k, (rx, _) in SERVICES.items():
    fac[f"claims_{k}"] = txt.str.contains(rx, regex=True)

piv = dist.pivot(index="dc", columns="sector", values=list(SERVICES)).reset_index()
piv.columns = ["hmis_dc"] + [f"{a}__{b}" for a, b in piv.columns[1:]]
m = fac[fac.hmis_dc.notna()].merge(piv, on="hmis_dc", how="left")
matched = len(m)
svc_stats = {}
for k in SERVICES:
    claim = m[f"claims_{k}"]
    tot = m.get(f"{k}__Total")
    priv = m.get(f"{k}__Private")
    svc_stats[k] = {
        "matched_facilities_claiming": int(claim.sum()),
        "matched_facilities_not_claiming": int((~claim).sum()),
        "claiming_in_district_with_zero_total": int((claim & (tot == 0)).sum()),
        "private_claiming_in_district_with_zero_private": int((claim & (m.op == "private") & (priv == 0)).sum()),
        "districts_with_zero_total": int((piv[f"{k}__Total"] == 0).sum()),
        "districts_with_zero_private": int((piv[f"{k}__Private"] == 0).sum()),
        "districts": int(len(piv)),
    }

stats = {
    "hmis_year_used": YEAR,
    "facilities": n_all,
    "district_matched": matched,
    "district_match_rate": round(matched / n_all, 4),
    "by_method": fac.dc_method.value_counts(dropna=False).to_dict(),
    "lgd_dc_not_in_hmis": int((fac.lgd_dc.notna() & ~fac.lgd_dc.isin(hmis_dc)).sum()),
    "subdistrict_level": fac.sub_level.value_counts().to_dict(),
    "hmis_districts_reached": int(m.hmis_dc.nunique()),
    "hmis_districts_total": len(hmis_dc),
    "services": svc_stats,
}
json.dump(stats, open(f"{out_dir}/join_stats.json", "w"), indent=1, default=str)
print(json.dumps(stats, indent=1, default=str))

keep = ["unique_id", "name", "address_city", "state", "zip", "op", "hmis_dc", "hmis_district", "hmis_state", "dc_method", "sub_level", "sc"] + [f"claims_{k}" for k in SERVICES]
out = m[keep].copy()
out["sc"] = out.sc.apply(lambda v: ";".join(map(str, v)) if isinstance(v, list) else "")
out.to_parquet(f"{out_dir}/facility_hmis_district.parquet", index=False)
sample = m[m.name.notna()].sample(20, random_state=SEED)
sample = sample.assign(sc_names=sample.apply(lambda r: ";".join(hs[(hs.dc == r.hmis_dc) & hs.sc.isin(r.sc if isinstance(r.sc, list) else [])].sn.unique()), axis=1))
sample[["name", "address_city", "state", "zip", "hmis_district", "hmis_state", "dc_method", "sub_level", "sc_names"]].to_csv(f"{out_dir}/handcheck_20.csv", index=False)
print(sample[["name", "address_city", "state", "zip", "hmis_district", "hmis_state", "dc_method", "sub_level", "sc_names"]].to_string())

# Flag examples: claims C-section or NICU, district HMIS reports zero.
for k in ("c_section", "nicu_sncu", "burn_care"):
    ex = m[m[f"claims_{k}"] & (m[f"{k}__Total"] == 0)][["name", "address_city", "hmis_district", "hmis_state"]].head(5)
    print(f"\n{k} claimed where district Total=0 in {YEAR}:\n{ex.to_string()}")
