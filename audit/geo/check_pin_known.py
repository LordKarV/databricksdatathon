"""Spot-check cleaned PIN centroids against well-known city-centre coordinates (from general knowledge, approx +-3 km)."""
import sys
import pandas as pd
sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from pin_centroids import hav_km

KNOWN = {110001: (28.632, 77.219), 400001: (18.938, 72.835), 560001: (12.975, 77.605), 600001: (13.090, 80.285),
         700001: (22.572, 88.351), 302001: (26.920, 75.820), 226001: (26.848, 80.946), 800001: (25.611, 85.144),
         500001: (17.385, 78.475), 380001: (23.025, 72.585), 682001: (9.966, 76.243), 695001: (8.500, 76.950),
         411001: (18.520, 73.856), 141001: (30.900, 75.850), 462001: (23.260, 77.410), 751001: (20.270, 85.840),
         781001: (26.180, 91.750), 248001: (30.320, 78.030), 834001: (23.350, 85.330), 492001: (21.250, 81.630)}
c = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/geo/pin_centroids.parquet").set_index("pincode")
rows = []
for pin, (la, lo) in KNOWN.items():
    r = c.loc[pin]
    rows.append((pin, r.state, r.district, r.n_offices, r.n_used, r.src, round(float(hav_km(la, lo, r.best_lat, r.best_lon)), 1)))
df = pd.DataFrame(rows, columns=["pin", "state", "district", "n_off", "n_used", "src", "err_km"])
print(df.to_string())
print("within 10 km:", (df.err_km <= 10).sum(), "of", len(df))
