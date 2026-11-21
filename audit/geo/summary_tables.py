"""Cross-tabs quoted in FINDINGS.md (reads facility_geo.parquet)."""
import pandas as pd

g = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/geo/facility_geo.parquet")
g["band"] = pd.cut(g.d_pin_km, [-1, 10, 25, 50, 100, 5000], labels=["<=10", "10-25", "25-50", "50-100", ">100"])
g["city_agrees_with"] = (g.city_match_pin.map({True: "pin", False: ""}) + g.city_match_near.map({True: "+coords", False: ""})).replace({"": "neither", "+coords": "coords_only", "pin+coords": "both", "pin": "pin_only"})
print(pd.crosstab(g.band, g.city_agrees_with, margins=True).to_string())
far = g[g.d_pin_km > 50]
print("\nfar >50 km:", len(far), "same state (pin vs coords):", int((far.pin_state == far.near_state).sum()))
print("\nfar rate by stated state (n>=100):")
r = g.dropna(subset=["d_pin_km"]).groupby("state_n").d_pin_km.agg(n="size", far=lambda s: (s > 50).sum())
r = r[r.n >= 100].assign(rate=lambda d: (d.far / d.n).round(3)).sort_values("rate", ascending=False)
print(r.to_string())

# shared coordinate points: same-name duplicates vs distinct names
d = g[g.coord_dup_n >= 2].copy()
pts = d.groupby("coord_key").agg(n=("unique_id", "size"), ids=("unique_id", "nunique"), names=("coord_dup_names", "first"), pins=("pin", "nunique"))
print("\nshared points:", len(pts), "facility rows:", int(pts.n.sum()))
print("points where all rows share one unique_id (duplicated key):", int((pts.ids == 1).sum()))
print("points with one normalised name but several ids:", int(((pts.names == 1) & (pts.ids > 1)).sum()))
print("points with >=2 distinct names:", int((pts.names >= 2).sum()), "rows:", int(pts[pts.names >= 2].n.sum()))
print("points with >=3 distinct names:", int((pts.names >= 3).sum()), "rows:", int(pts[pts.names >= 3].n.sum()))

# coarse coordinates: both lat and lon have at most 2 decimals (float32 storage, so tolerance 1e-5)
import numpy as np
c2 = (np.abs(g.latitude * 100 - np.round(g.latitude * 100)) < 1e-3) & (np.abs(g.longitude * 100 - np.round(g.longitude * 100)) < 1e-3)
print("\ncoords with <=2 decimals:", int(c2.sum()), "of", len(g), "| of those >50 km from PIN:", int((c2 & (g.d_pin_km > 50)).sum()))
print(g[c2][["unique_id", "name", "address_city", "latitude", "longitude", "d_pin_km"]].head(12).round(3).to_string())
