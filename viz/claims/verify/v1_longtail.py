"""Independent recomputation of story 1 from data/raw/facilities.parquet + kb/taxonomy/specialty_map.csv.
Universe = derived/v1/facility_location.parquet (9,959 usable records). Facility type from raw facilityTypeId."""
import json, numpy as np, pandas as pd
R = "/Users/karthikvattem/projects/datathon/"
ok = set(pd.read_parquet(R + "derived/v1/facility_location.parquet", columns=["unique_id"]).unique_id)
raw = pd.read_parquet(R + "data/raw/facilities.parquet", columns=["unique_id", "specialties", "facilityTypeId"])
print("raw rows", len(raw), "unique ids", raw.unique_id.nunique(), "usable", len(ok))
raw = raw[raw.unique_id.isin(ok)].drop_duplicates("unique_id")
pairs = set()
nbad = 0
for u, s in zip(raw.unique_id, raw.specialties):
    try:
        v = json.loads(s) if isinstance(s, str) else []
    except Exception:
        nbad += 1; v = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, str) and x.strip():
            pairs.add((u, x))
p = pd.DataFrame(sorted(pairs), columns=["u", "v"])
cnt = p.v.value_counts()
print("unparsable", nbad, "distinct non-empty", len(cnt), "mentions", len(p))
print("singletons", (cnt == 1).sum(), f"{(cnt==1).mean():.3f}", "le2", (cnt <= 2).sum(), "top10 share", round(cnt.head(10).sum() / len(p), 3))
r = np.arange(1, len(cnt) + 1)
print("slope", round(np.polyfit(np.log10(r), np.log10(cnt.values), 1)[0], 3))
print(cnt.head(5).to_dict())
m = pd.read_csv(R + "kb/taxonomy/specialty_map.csv", keep_default_na=False)
print("map rows", len(m), "empty", (m.specialty == "").sum())
# compare map n_facilities to my counts
mm = m.set_index("specialty").n_facilities
diff = (cnt - mm.reindex(cnt.index)).abs()
print("values where my count != map n_facilities:", (diff > 0).sum(), "missing from map:", mm.reindex(cnt.index).isna().sum())
kind = m.set_index("specialty").service_id.map(lambda s: s if s in ("too_general", "out_of_scope", "not_a_service") else "service")
k = kind.reindex(cnt.index)
for kk in ["service", "too_general", "not_a_service", "out_of_scope"]:
    sel = k == kk
    print(kk, "values", sel.sum(), f"{sel.mean():.3f}", "mentions", cnt[sel].sum(), f"{cnt[sel].sum()/len(p):.3f}")
svcs = {s for v in m.service_id[~m.service_id.isin(["too_general","out_of_scope","not_a_service",""])] for s in v.split(";")}
allsv = [s["id"] for c in json.load(open(R + "kb/taxonomy/services.json"))["categories"] for s in c["services"]]
print("services reached", len(svcs & set(allsv)), "of", len(allsv), "extra ids", svcs - set(allsv))
print("method counts", m[m.specialty != ""].method.value_counts().to_dict())
# defaults by raw type
t = raw.set_index("unique_id").facilityTypeId
p["t"] = p.u.map(t)
nt = t.value_counts()
print("types", nt.to_dict())
from math import sqrt
def wil(k, n, z=1.96):
    ph = k / n; d = 1 + z*z/n; c = (ph + z*z/(2*n))/d; h = z*sqrt(ph*(1-ph)/n + z*z/(4*n*n))/d; return round(ph,4), round(c-h,4), round(c+h,4)
for ty, v in [("hospital","internalMedicine"),("clinic","familyMedicine"),("dentist","dentistry"),("dentist","familyMedicine"),("hospital","dentistry")]:
    kk = ((p.t == ty) & (p.v == v)).sum(); print(ty, v, kk, nt[ty], wil(kk, nt[ty]))
# truncation check: arrays with exactly 50 items
n50 = sum(1 for s in raw.specialties if isinstance(s, str) and s.startswith("[") and len(json.loads(s)) >= 50)
print("records with >=50 specialties", n50)
