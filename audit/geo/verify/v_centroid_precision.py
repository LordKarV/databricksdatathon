"""Independent precision estimate for the finder's PIN centroids: for PINs with >= 3 facilities,
distance from the centroid to the median facility coordinate (facility consensus point)."""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, hav

v = pd.read_parquet(VER + "/v_fac.parquet").drop_duplicates("unique_id")
v = v[v.d_finder.notna()]
cen = pd.read_parquet(ROOT + "/audit/geo/pin_centroids.parquet").set_index("pincode")
g = v.groupby("pin").agg(n=("unique_id", "size"), la=("latitude", "median"), lo=("longitude", "median"))
g = g[g.n >= 3].join(cen[["best_lat", "best_lon", "n_used", "spread_km_p90", "src"]])
g["d"] = hav(g.la, g.lo, g.best_lat, g.best_lon)
o = {"pins_with_3plus_facilities": len(g), "facilities_on_them": int(g.n.sum()),
     "consensus_vs_centroid_km_quantiles_50_75_90": np.round(g.d.quantile([0.5, 0.75, 0.9]).values, 1).tolist(),
     "gt10km": int((g.d > 10).sum()), "gt25km": int((g.d > 25).sum()),
     "gt25km_single_office_centroid": int(((g.d > 25) & (g.n_used == 1)).sum()),
     "spread_p90_claimed_quantiles_50_90": np.round(cen.spread_km_p90.quantile([0.5, 0.9]).values, 1).tolist(),
     "gt25_examples": g[g.d > 25].sort_values("n", ascending=False).head(8).reset_index()[["pin", "n", "d", "n_used", "src"]].round(1).values.tolist()}
json.dump(o, open(VER + "/v_centroid_precision.json", "w"), indent=1)
print(json.dumps(o, indent=1))

# how many GEO-01 'far' facilities are explained by a bad centroid: on a PIN whose centroid is > 25 km
# from the facility consensus, and the facility itself within 10 km of that consensus
bad = g[g.d > 25]
v2 = v.join(bad[["la", "lo"]].rename(columns={"la": "cla", "lo": "clo"}), on="pin")
v2["d_cons"] = hav(v2.latitude, v2.longitude, v2.cla, v2.clo)
far = v2.d_finder > 50
o2 = {"far_total": int(far.sum()), "far_on_bad_centroid_pins": int((far & v2.cla.notna()).sum()),
      "far_on_bad_centroid_pins_and_near_consensus_10km": int((far & (v2.d_cons <= 10)).sum()),
      "mid_10_50_on_bad_centroid_pins_near_consensus": int((v2.d_finder.between(10, 50) & (v2.d_cons <= 10)).sum())}
json.dump({**o, **o2}, open(VER + "/v_centroid_precision.json", "w"), indent=1)
print(json.dumps(o2, indent=1))
