"""GEO-01/02/05/06 verification: facility coordinates vs PIN, state and city, with my own
centroids (v_pin.py) and the finder's, so the result can be checked for centroid sensitivity."""
import json
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, directory, facilities, hav, inbox, nn, pin_of

o = {}
f = facilities()
o["well_formed"] = len(f)
o["distinct_unique_id"] = int(f.unique_id.nunique())
dup = f[f.unique_id.duplicated(keep=False)]
o["dup_id_rows"] = len(dup)
# are duplicated ids full duplicate rows?
o["dup_ids_fully_identical"] = int(dup.groupby("unique_id").apply(lambda g: g.astype(str).nunique().max() == 1, include_groups=False).sum())
o["dup_ids_differing_cols"] = dup.groupby("unique_id").apply(lambda g: [c for c in g.columns if g[c].astype(str).nunique() > 1], include_groups=False).head(11).tolist()

f["pin"] = f.address_zipOrPostcode.map(pin_of)
o["pin_valid"] = int(f.pin.notna().sum())
raw = f.address_zipOrPostcode.astype(str).str.strip()
o["zip_null_like"] = int(f.address_zipOrPostcode.isna().sum() + raw.str.lower().isin(["null", "", "none"]).sum())
lat, lon = f.latitude, f.longitude
o["coord_null"] = int(lat.isna().sum())
o["zero"] = int(((lat == 0) & (lon == 0)).sum())
o["swapped"] = int((lat.between(68, 98) & lon.between(6, 38)).sum())
outb = lat.notna() & ~inbox(lat, lon)
o["outside_india"] = int(outb.sum())
o["outside_examples"] = f.loc[outb, ["unique_id", "name", "address_city", "latitude", "longitude"]].values.tolist()
cj = f.coordinates.map(lambda s: json.loads(s).get("coordinates") if isinstance(s, str) and s.startswith("{") else None)
mm = [c is not None and (abs(c[1] - a) > 1e-4 or abs(c[0] - b) > 1e-4) for c, a, b in zip(cj, lat, lon)]
o["coord_json_mismatch"] = int(sum(mm))
o["coord_json_parsed"] = int(cj.notna().sum())

# ---- distance to PIN centroids (three versions)
naive = pd.read_parquet(VER + "/v_pin_naive.parquet")
rob = pd.read_parquet(VER + "/v_pin_robust.parquet")
fin = pd.read_parquet(ROOT + "/audit/geo/pin_centroids.parquet").set_index("pincode")
ok = lat.notna() & ~outb
bins = [-0.01, 2, 10, 50, 100, 500, 1e5]
for k, t, a, b in [("naive", naive, "la", "lo"), ("robust", rob, "la", "lo"), ("finder", fin, "best_lat", "best_lon")]:
    j = t.reindex(f.pin)
    d = pd.Series(np.where(ok, hav(lat, lon, j[a].values, j[b].values), np.nan))
    f["d_" + k] = d
    v = d.dropna()
    o[f"dist_{k}"] = {"n": len(v), "gt50": int((v > 50).sum()), "gt100": int((v > 100).sum()),
                      "bins": pd.cut(v, bins).value_counts().sort_index().astype(int).rename(str).to_dict(),
                      "median": round(float(v.median()), 2), "p90": round(float(v.quantile(0.9)), 1)}
# finder centroid but excluding PINs whose point is a fallback (district/prefix median)
own = f.pin.map(fin.src).eq("pin_median")
v = f.d_finder[own]
o["finder_own_point_only"] = {"n": int(v.notna().sum()), "gt50": int((v > 50).sum())}

# ---- coordinate-side state/district: nearest geocoded office (robust offices only)
p = directory()
sw = p.la.between(68, 98) & p.lo.between(6, 38)
p.loc[sw, ["la", "lo"]] = p.loc[sw, ["lo", "la"]].values
q = p[p.la.notna() & inbox(p.la, p.lo) & ~p.la.between(15.5895, 15.5935) & p.statename.ne("NA")].copy()
q = q.join(rob[["la", "lo"]].rename(columns={"la": "cla", "lo": "clo"}), on="pincode")
q = q[hav(q.la, q.lo, q.cla, q.clo) <= 10].drop_duplicates(["la", "lo", "pincode"]).reset_index(drop=True)  # offices near their own PIN point
o["office_points_used_for_reverse_geocode"] = len(q)
idx = nn(lat[ok].values, lon[ok].values, q.la.values, q.lo.values)
for c in ["statename", "district", "pincode"]:
    f.loc[ok, "c_" + c] = q[c].values[idx]
f.loc[ok, "c_km"] = hav(lat[ok].values, lon[ok].values, q.la.values[idx], q.lo.values[idx])
dist = pd.read_parquet(VER + "/v_pin_district.parquet")
f["p_state"] = f.pin.map(dist.state)
f["p_district"] = f.pin.map(dist.district)

far = f.d_finder > 50
o["far_n"] = int(far.sum())
o["far_same_state_coordstate_eq_pinstate"] = int((far & (f.c_statename == f.p_state)).sum())
o["far_same_district"] = int((far & (f.c_district == f.p_district)).sum())
o["far_nearest_pin_same_prefix3"] = int((far & (f.c_pincode // 1000 == f.pin // 1000)).sum())
o["far_nearest_pin_same_prefix2"] = int((far & (f.c_pincode // 10000 == f.pin // 10000)).sum())

# ---- is the PIN centroid the problem? other facilities on the same PIN
f["pin_lat"] = f.pin.map(fin.best_lat)
f["pin_lon"] = f.pin.map(fin.best_lon)
grp = f[f.d_finder.notna()].groupby("pin")
res = []
for i in f.index[far]:
    sib = f[(f.pin == f.pin[i]) & (f.index != i) & f.d_finder.notna()]
    if len(sib) == 0:
        res.append("no_sibling")
        continue
    near_cen = (sib.d_finder <= 25).mean()
    near_me = (hav(sib.latitude, sib.longitude, lat[i], lon[i]) <= 25).mean()
    res.append("siblings_near_centroid" if near_cen >= 0.5 else ("siblings_near_this_point" if near_me >= 0.5 else "siblings_scattered"))
o["far_sibling_test"] = pd.Series(res).value_counts().to_dict()

# ---- state field
canon = {s for s in dist.state.unique()}
alias = {"TAMILNADU": "TAMIL NADU", "ORISSA": "ODISHA", "UP": "UTTAR PRADESH", "U P": "UTTAR PRADESH", "MP": "MADHYA PRADESH",
         "PONDICHERRY": "PUDUCHERRY", "NCT OF DELHI": "DELHI", "NEW DELHI": "DELHI", "CHATTISGARH": "CHHATTISGARH",
         "UTTARANCHAL": "UTTARAKHAND", "TELENGANA": "TELANGANA", "JAMMU KASHMIR": "JAMMU AND KASHMIR"}


def nstate(s):
    if not isinstance(s, str):
        return None
    t = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", s.upper().replace("&", " AND "))).strip()
    return t if t in canon else alias.get(t)


f["s_state"] = f.address_stateOrRegion.map(nstate)
o["state_resolved_simple"] = int(f.s_state.notna().sum())
o["state_exact_upper"] = int(f.address_stateOrRegion.map(lambda s: isinstance(s, str) and re.sub(r"\s+", " ", s.upper().replace("&", "AND")).strip() in canon).sum())
o["state_null_like"] = int(f.address_stateOrRegion.isna().sum() + f.address_stateOrRegion.astype(str).str.lower().isin(["null", ""]).sum())
o["state_unresolved_top"] = f.loc[f.s_state.isna(), "address_stateOrRegion"].value_counts().head(25).to_dict()
both = f.s_state.notna() & f.p_state.notna()
o["state_vs_pin"] = [int((both & (f.s_state != f.p_state)).sum()), int(both.sum())]
zone = {"1": "DELHI HARYANA PUNJAB HIMACHAL CHANDIGARH JAMMU LADAKH", "2": "UTTAR UTTARAKHAND", "3": "RAJASTHAN GUJARAT DADRA",
        "4": "MAHARASHTRA MADHYA GOA CHHATTISGARH", "5": "ANDHRA TELANGANA KARNATAKA", "6": "TAMIL KERALA PUDUCHERRY LAKSHADWEEP",
        "7": "BENGAL ODISHA ASSAM ARUNACHAL MANIPUR MEGHALAYA MIZORAM NAGALAND TRIPURA SIKKIM ANDAMAN", "8": "BIHAR JHARKHAND"}
hz = f.s_state.notna() & f.pin.notna()
zm = [not any(w in zone.get(str(int(pz))[0], "").split() for w in s.split() if len(w) >= 3 and w != "AND") for s, pz in zip(f.s_state[hz], f.pin[hz])]
o["zone_mismatch"] = [int(sum(zm)), int(hz.sum())]
o["zone_mismatch_examples"] = f[hz][zm][["unique_id", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode"]].head(30).values.tolist()
# state disagreement among far > 50 km
o["far_by_stated_state"] = {s: [int((far & (f.s_state == s)).sum()), int(((f.s_state == s) & f.d_finder.notna()).sum())]
                            for s in ["UTTAR PRADESH", "TAMIL NADU", "GUJARAT", "DELHI", "MAHARASHTRA", "KARNATAKA", "KERALA"]}

# ---- 2-decimal coordinates and shared points
c2 = ok & np.isclose(lat * 100, np.round(lat * 100), atol=1e-3, rtol=0) & np.isclose(lon * 100, np.round(lon * 100), atol=1e-3, rtol=0)
o["coords_le_2_decimals"] = int(c2.sum())
c3 = ok & np.isclose(lat * 1000, np.round(lat * 1000), atol=1e-3, rtol=0) & np.isclose(lon * 1000, np.round(lon * 1000), atol=1e-3, rtol=0)
o["coords_le_3_decimals"] = int(c3.sum())
key = lat.round(5).astype(str) + "," + lon.round(5).astype(str)
fd = f[ok].assign(k=key[ok], nm=f.name.str.lower().str.replace(r"[^a-z0-9]", "", regex=True))
g = fd.groupby("k").agg(n=("unique_id", "size"), ids=("unique_id", "nunique"), names=("nm", "nunique"))
o["shared_points"] = [int((g.n >= 2).sum()), int(g.n[g.n >= 2].sum())]
o["shared_points_one_id"] = int(((g.n >= 2) & (g.ids == 1)).sum())
o["shared_points_2plus_names"] = [int((g.names >= 2).sum()), int(g.n[g.names >= 2].sum())]
o["shared_points_3plus_names"] = [int((g.names >= 3).sum()), int(g.n[g.names >= 3].sum())]
# looser: facilities within 100 m of a facility with a different PIN and different name (grid 0.001 deg)
k3 = lat.round(3).astype(str) + "," + lon.round(3).astype(str)
g3 = f[ok].assign(k=k3[ok], nm=fd.nm).groupby("k").agg(n=("unique_id", "size"), names=("nm", "nunique"))
o["grid_0001_cells_3plus_names"] = [int((g3.names >= 3).sum()), int(g3.n[g3.names >= 3].sum())]

f.drop(columns=[c for c in f.columns if c not in {"unique_id", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode",
                                                  "latitude", "longitude", "pin", "d_naive", "d_robust", "d_finder", "c_statename",
                                                  "c_district", "c_pincode", "c_km", "p_state", "p_district", "s_state"}]).to_parquet(VER + "/v_fac.parquet")
json.dump(o, open(VER + "/v_fac_stats.json", "w"), indent=1, default=str)
print(json.dumps(o, indent=1, default=str))
