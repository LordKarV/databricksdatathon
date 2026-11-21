"""Proxy precision for the '>50 km from PIN median' office drop: where do dropped offices land?
If a dropped office's coordinate is nearest to a PIN centroid of its own district, the drop may be a
false positive (large rural PIN); if it lands in another district or state, the office point was wrong."""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import GEO, PIN_DIR, hav_km, nearest

p = pd.read_parquet(PIN_DIR)
p["lat"], p["lon"] = pd.to_numeric(p.latitude, errors="coerce"), pd.to_numeric(p.longitude, errors="coerce")
c = pd.read_parquet(GEO / "pin_centroids.parquet").dropna(subset=["best_lat"]).reset_index(drop=True)
p = p.merge(c[["pincode", "best_lat", "best_lon"]], on="pincode")
p = p[p.lat.between(6, 37.6) & p.lon.between(68, 97.6)]
p["d"] = hav_km(p.lat, p.lon, p.best_lat, p.best_lon)
x = p[p.d > 50].reset_index(drop=True)
idx, dist = nearest(x.lat.values, x.lon.values, c.best_lat.values, c.best_lon.values)
x["near_state"], x["near_district"] = c.state.values[idx], c.district.values[idx]
same_d = (x.near_district == x.district) & (x.near_state == x.statename)
same_s = x.near_state == x.statename
print("offices > 50 km from their final PIN point:", len(x))
print("  land nearest a PIN of their own district:", int(same_d.sum()))
print("  land in own state, other district:", int((same_s & ~same_d).sum()))
print("  land in another state:", int((~same_s).sum()))
print("  distance quantiles km:", np.quantile(x.d, [0.25, 0.5, 0.75]).round(0).tolist())
