"""Probe: are far-off coordinates the location of a same-named facility elsewhere (name-based geocoding)?
For each facility whose coords are > 50 km from its PIN, look for another facility within 2 km of its
coordinates that has a similar name (rapidfuzz token_set_ratio >= 85). Compare with a control group."""
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import GEO, hav_km, norm

g = pd.read_parquet(GEO / "facility_geo.parquet")
g = g[~g.coord_outside].reset_index(drop=True)
lat, lon = g.latitude.values, g.longitude.values
names = g.name.map(norm).values


def has_namesake(i):
    d = hav_km(lat[i], lon[i], lat, lon)
    cand = np.where((d < 2.0) & (np.arange(len(g)) != i))[0]
    return any(fuzz.token_set_ratio(names[i], names[j]) >= 85 for j in cand)


far = g.index[g.d_pin_km > 50]
ctrl = g.index[g.d_pin_km <= 5].to_series().sample(len(far), random_state=1).values
hf = np.mean([has_namesake(i) for i in far])
hc = np.mean([has_namesake(i) for i in ctrl])
print(f"far (>50 km) n={len(far)} share with same-name facility within 2 km: {hf:.3f}")
print(f"control (<=5 km) n={len(ctrl)} share: {hc:.3f}")
