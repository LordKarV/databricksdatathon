"""Independent recomputation of story 2. Doctors and type from raw facilities.parquet (numberDoctors, facilityTypeId)
and cross-checked against model/proto/evidence/pair_features.parquet."""
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from vcommon import R, raw, claims, wil

rw = raw()
doc_raw = pd.to_numeric(rw.numberDoctors, errors="coerce")
rw = rw.assign(doc_raw=doc_raw.values)
pf = pd.read_parquet(R + "model/proto/evidence/pair_features.parquet", columns=["unique_id", "doctors", "beds", "facility_type"]).drop_duplicates("unique_id")
x = rw[["unique_id", "doc_raw", "facilityTypeId", "capacity"]].merge(pf, on="unique_id")
print("raw doctor stated (>0):", (x.doc_raw > 0).sum(), "pf doctors>0:", (x.doctors > 0).sum(),
      "agree where both:", ((x.doc_raw == x.doctors) | (x.doc_raw.isna() & x.doctors.isna())).mean().round(4))
print("type agree:", (x.facilityTypeId == x.facility_type).mean().round(4))
c = claims()
cl = c[c.text_pos | c.spec]
small = set(x[(x.doc_raw >= 1) & (x.doc_raw <= 2)].unique_id)
small_pf = set(x[(x.doctors >= 1) & (x.doctors <= 2)].unique_id)
print("small (raw)", len(small), "small (pf)", len(small_pf))
T = ["icu", "neurosurgery", "cardiac_surgery", "cath_lab_angioplasty", "kidney_transplant", "radiotherapy", "dialysis", "trauma_care"]
for S, lab in [(small_pf, "pf")]:
    g = cl[cl.unique_id.isin(S)]
    for t in T + ["ANY"]:
        h = g[g.service.isin(T)] if t == "ANY" else g[g.service == t]
        k = h.unique_id.nunique(); kt = h[h.text_pos].unique_id.nunique()
        print(lab, t, k, len(S), wil(k, len(S)), "text", kt)
# by-type, 1-doctor median services
ns = cl.groupby("unique_id").service.nunique()
x["nsv"] = x.unique_id.map(ns).fillna(0)
for ty in ["hospital", "clinic"]:
    for lo, hi in [(1, 1), (50, 1e9)]:
        g = x[(x.facility_type == ty) & (x.doctors >= lo) & (x.doctors <= hi)]
        print(ty, lo, hi, len(g), "median", g.nsv.median())
g = x[x.facility_type.isin(["hospital", "clinic"]) & (x.doctors > 0)]
print("spearman doctors", round(spearmanr(g.doctors, g.nsv).statistic, 3), len(g))
gb = x[x.facility_type.isin(["hospital", "clinic"]) & (x.beds > 0)]
print("spearman beds", round(spearmanr(gb.beds, gb.nsv).statistic, 3), len(gb))
print("no doctor count H+C:", (x.facility_type.isin(["hospital", "clinic"]) & ~(x.doctors > 0)).sum(),
      "of", x.facility_type.isin(["hospital", "clinic"]).sum())
# composition of 1-2 doctor records by type and how many are hospitals
sm = x[x.unique_id.isin(small_pf)]
print("small by type", sm.facility_type.value_counts().to_dict())
ty = x.set_index("unique_id").facility_type
g = cl[cl.unique_id.isin(small_pf) & (cl.service == "icu")]
print("ICU small by type", g.unique_id.map(ty).value_counts().to_dict())
g = cl[cl.unique_id.isin(small_pf) & cl.service.isin(T)]
print("ANY small by type", g.drop_duplicates("unique_id").unique_id.map(ty).value_counts().to_dict())
# does the claim rate among 1-2 doctor records differ from records with 10+ doctors? (context for 'inflation')
for lo, hi in [(1, 2), (3, 9), (10, 49), (50, 1e9)]:
    S = set(x[(x.doctors >= lo) & (x.doctors <= hi)].unique_id)
    k = cl[cl.unique_id.isin(S) & cl.service.isin(T)].unique_id.nunique()
    ki = cl[cl.unique_id.isin(S) & (cl.service == "icu")].unique_id.nunique()
    print("doctors", lo, hi, "any tertiary", k, len(S), wil(k, len(S)), "icu", ki, wil(ki, len(S)))
