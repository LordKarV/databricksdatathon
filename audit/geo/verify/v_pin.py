"""GEO-04 verification: independent cleaning counts on the India Post directory, plus two
independent PIN centroid tables (naive and robust) written to verify/ for the facility checks."""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER, directory, hav, inbox

p = directory()
o = {"rows": len(p), "pins": int(p.pincode.nunique())}
bad = p.la.isna() | p.lo.isna()
o["unparseable"] = int(bad.sum())
o["literal_NA_either"] = int((p.latitude.eq("NA") | p.longitude.eq("NA")).sum())
o["unparseable_not_NA_examples"] = p.loc[bad & ~(p.latitude.eq("NA") | p.longitude.eq("NA")), ["latitude", "longitude"]].head(5).values.tolist()
z = ~bad & ((p.la == 0) | (p.lo == 0))
o["zero"] = int(z.sum())
sw = ~bad & ~z & p.la.between(68, 98) & p.lo.between(6, 38)
o["swapped"] = int(sw.sum())
p.loc[sw, ["la", "lo"]] = p.loc[sw, ["lo", "la"]].values
out = ~bad & ~z & ~inbox(p.la, p.lo)
o["outside_box_after_swap"] = int(out.sum())
o["at_1_1"] = int(((p.la == 1) & (p.lo == 1)).sum())
o["lat_228"] = int((p.la > 200).sum())
# placeholder latitude: count lat in 15.5895..15.5935 by state
ph = ~bad & ~z & ~out & p.la.between(15.5895, 15.5935)
o["lat_15_59_all"] = int(ph.sum())
o["lat_15_59_by_state"] = p.loc[ph].statename.value_counts().head(12).to_dict()
o["lat_15_59_top_values"] = p.loc[ph].latitude.value_counts().head(5).to_dict()
# most repeated latitude strings overall (are there other placeholders?)
good = ~bad & ~z & ~out
o["top_repeated_points"] = p[good].groupby(["la", "lo"]).size().sort_values(ascending=False).head(8).reset_index().values.tolist()
plaus = {"GOA", "KARNATAKA", "ANDHRA PRADESH", "MAHARASHTRA"}
ph_drop = ph & ~p.statename.isin(plaus)
o["lat_15_59_implausible_state"] = int(ph_drop.sum())

g = p[good & ~ph_drop].copy()
# naive centroid: per-PIN median of everything in the box (no further cleaning)
naive = g.groupby("pincode")[["la", "lo"]].median()
# robust centroid: median, drop > 50 km, median again
g = g.join(naive.rename(columns={"la": "m1", "lo": "n1"}), on="pincode")
g["d1"] = hav(g.la, g.lo, g.m1, g.n1)
o["far_gt50_from_first_median"] = int((g.d1 > 50).sum())
g2 = g[g.d1 <= 50]
robust = g2.groupby("pincode")[["la", "lo"]].median()
o["kept_after_50km"] = len(g2)
o["pins_with_point_naive"] = len(naive)
o["pins_with_point_robust"] = len(robust)
o["dropped_total"] = o["rows"] - len(g2)
o["dropped_plus_swaps"] = o["dropped_total"] + o["swapped"]

# district majority for each PIN; then a district-median sanity check on the robust centroid
dist = p[p.district.ne("NA")].groupby("pincode").agg(state=("statename", lambda s: s.mode().iloc[0]),
                                                      district=("district", lambda s: s.mode().iloc[0]))
r = robust.join(dist)
dmed = r.groupby(["state", "district"])[["la", "lo"]].median().set_axis(["dla", "dlo"], axis=1)
r = r.join(dmed, on=["state", "district"])
r["d_dist"] = hav(r.la, r.lo, r.dla, r.dlo)
o["robust_pins_gt150km_from_district_median"] = int((r.d_dist > 150).sum())
r["la_fix"] = np.where(r.d_dist > 150, r.dla, r.la)
r["lo_fix"] = np.where(r.d_dist > 150, r.dlo, r.lo)

# known city-centre points (my own reference values, GPO/HO area, approx)
known = {110001: (28.632, 77.219), 400001: (18.938, 72.836), 600001: (13.090, 80.287), 700001: (22.572, 88.351),
         560001: (12.976, 77.603), 500001: (17.385, 78.475), 380001: (23.026, 72.587), 302001: (26.920, 75.823),
         226001: (26.850, 80.946), 411001: (18.520, 73.856), 800001: (25.612, 85.144), 695001: (8.488, 76.950),
         641001: (11.000, 76.962), 452001: (22.719, 75.857), 462001: (23.259, 77.401), 751001: (20.270, 85.840),
         781001: (26.184, 91.745), 160017: (30.741, 76.779), 208001: (26.460, 80.330), 440001: (21.150, 79.090),
         530001: (17.700, 83.290), 520001: (16.510, 80.620), 230001: (25.900, 81.950), 799001: (23.835, 91.280)}
fin = pd.read_parquet(VER + "/../pin_centroids.parquet").set_index("pincode")
rows = []
for pin, (a, b) in known.items():
    def d(df, la, lo):
        return round(float(hav(a, b, df.loc[pin, la], df.loc[pin, lo])), 1) if pin in df.index else None
    rows.append([pin, d(naive, "la", "lo"), d(r, "la", "lo"), d(r, "la_fix", "lo_fix"), d(fin, "best_lat", "best_lon")])
o["known_pins_km_naive_robust_fixed_finder"] = rows
for i, k in [(1, "naive"), (2, "robust"), (3, "fixed"), (4, "finder")]:
    v = [x[i] for x in rows if x[i] is not None]
    o[f"known_within_10km_{k}"] = f"{sum(x <= 10 for x in v)}/{len(v)}"

# finder's misplaced PIN examples
for pin in (230141, 799001, 686587):
    o[f"pin_{pin}"] = {"offices": p.loc[p.pincode == pin, ["officename", "district", "statename", "latitude", "longitude"]].head(14).values.tolist(),
                       "finder": fin.loc[pin, ["state", "state_raw", "district", "best_lat", "best_lon", "src", "misplaced"]].astype(str).tolist()}
# how different are my robust/fixed centroids from the finder's?
cmp = r.join(fin[["best_lat", "best_lon"]], how="inner")
dd = hav(cmp.la_fix, cmp.lo_fix, cmp.best_lat, cmp.best_lon)
o["mine_vs_finder_centroid_km_quantiles"] = np.round(np.quantile(dd, [0.5, 0.9, 0.99, 0.999]), 2).tolist()
o["mine_vs_finder_gt25km"] = int((dd > 25).sum())
o["finder_src_counts"] = fin.src.value_counts(dropna=False).astype(int).to_dict()
o["finder_misplaced"] = int(fin.misplaced.sum())

naive.to_parquet(VER + "/v_pin_naive.parquet")
r[["state", "district", "la", "lo", "la_fix", "lo_fix", "d_dist"]].to_parquet(VER + "/v_pin_robust.parquet")
dist.to_parquet(VER + "/v_pin_district.parquet")
(json.dump(o, open(VER + "/v_pin_stats.json", "w"), indent=1, default=str))
print(json.dumps(o, indent=1, default=str))
