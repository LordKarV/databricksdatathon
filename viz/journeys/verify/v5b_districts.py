"""Story 5, district level and road-factor sensitivity, from verify/out/v5_pixels.parquet (1 km pixels).
LGD district polygons are used only to assign pixels to districts; nothing is drawn."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
c = pd.read_parquet(Path(__file__).resolve().parent / "out/v5_pixels.parquet")
pop = c["pop"].values
# sensitivity: uniform road factor at the stated p10 (1.14) and p90 (2.01) instead of the measured band factor
for t in ["claimed", "corroborated"]:
    wk = c[f"wk_{t}"].values
    base_f = 1.30  # ponytail: approx mean band factor; ratio rescale is a bracket, not a model
    for fct in (1.14, 2.01):
        x = wk / base_f * fct
        print(f"sensitivity {t} factor {fct}: 300+ {pop[x >= 300].sum()/pop.sum():.3f} 600+ {pop[x >= 600].sum()/pop.sum():.3f}")
d = gpd.read_parquet(R / "data/external/lgd_district_polygons/LGD_Districts.parquet", columns=["stname", "dtname", "dist_lgd", "geometry"])
pts = gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.lon, c.lat), crs=d.crs)
j = gpd.sjoin(pts, d, how="left", predicate="within")
j = j[~j.index.duplicated()]
print(f"pixels without district: {j.dist_lgd.isna().mean():.4f} of pixels, {j.loc[j.dist_lgd.isna(), 'pop'].sum()/pop.sum():.4f} of people")


def wmed(x, w):
    o = np.argsort(x)
    cw = np.cumsum(w[o])
    return x[o][np.searchsorted(cw, cw[-1] / 2)]


rows = []
for (s, dt), g in j.dropna(subset=["dist_lgd"]).groupby(["stname", "dtname"]):
    rows.append({"state": s, "district": dt, "pop": g["pop"].sum(),
                 "med_corr": wmed(g.wk_corroborated.values, g["pop"].values),
                 "med_claim": wmed(g.wk_claimed.values, g["pop"].values)})
t = pd.DataFrame(rows)
isl = t.state.str.upper().str.contains("ANDAMAN|LAKSHADWEEP")
m = t[~isl]
print("districts", len(t), "mainland", len(m))
for col in ["med_corr", "med_claim"]:
    k = m[m[col] >= 600]
    print(col, "districts 600+:", len(k), f"people {k['pop'].sum()/1e6:.0f} M")
big = m[m["pop"] >= 1e6].sort_values("med_corr", ascending=False).head(5)
print(big.to_string())
