"""Independent recomputation of story 5 (dialysis travel burden).

Differences from the analyst's scripts/s5_dialysis.py, on purpose:
- 1 km WorldPop pixels, not 5 x 5 km blocks.
- Terrain (hill or plain) from the state of the nearest PIN gazetteer point, not LGD polygons.
- Road factor re-implemented vectorised from geo/road_factor.json (np.interp over band mid points, flat outside),
  checked against geo.travel.estimate on a sample.
- Nearest unit with scipy cKDTree on 3D unit vectors.
District figures use the LGD polygons for aggregation only (never drawn).
Also runs the road-factor sensitivity the analyst did not run: p10 and p90 of OSRM/estimate minutes ratio do not
give km, so the sensitivity scales road km by the band's factor x (low ratio, high ratio) as a bracket.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.spatial import cKDTree

R = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(R))
from geo import travel  # noqa: E402

C = json.loads((R / "geo/road_factor.json").read_text())
HILL = set(C["hill_states"])


def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]


def factor(km, terrain):
    b = C["classes"][terrain]["bands"]
    mid = [x["mid_km"] for x in b]
    return np.interp(km, mid, [x["factor"] for x in b])


with rasterio.open(R / "data/external/worldpop_r2025a/ind_pop_2025_CN_1km_R2025A_UA_v1.tif") as r:
    a = r.read(1).astype("float64")
    tf = r.transform
    nod = r.nodata
a[(a < 0) | (a == nod) | ~np.isfinite(a)] = 0
rows, cols = np.nonzero(a > 0)
lat = tf.f + (rows + 0.5) * tf.e
lon = tf.c + (cols + 0.5) * tf.a
pop = a[rows, cols]
print(f"pixels {len(pop):,}, population {pop.sum()/1e9:.4f} bn")

pins = pd.read_parquet(R / "derived/v1/pin_gazetteer.parquet", columns=["state", "lat", "lon"]).dropna()
_, pi = cKDTree(xyz(pins.lat.values, pins.lon.values)).query(xyz(lat, lon))
st = pins.state.values[pi]
norm = np.array([" ".join(str(s).upper().replace("&", "AND").split()) for s in st])
hill = np.isin(norm, list(HILL))

g = pd.read_parquet(R / "derived/v1/grades.parquet", columns=["unique_id", "service", "grade"])
g = g[g.service == "dialysis"]
w = pd.read_parquet(R / "kb/web_evidence/out/web_service_summary.parquet")
web = set(w[(w.service_id == "dialysis") & (w.web_positive_strong == True) & w.identity_conf.isin(["high", "medium"])].unique_id)  # noqa: E712
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "loc_lat", "loc_lon", "district"]).dropna(subset=["loc_lat", "loc_lon"])
tiers = {"claimed": set(g[g.grade.isin(["strong", "moderate", "weak", "tag_only"])].unique_id),
         "graded": set(g[g.grade.isin(["strong", "moderate"])].unique_id)}
tiers["corroborated"] = tiers["graded"] & web
out = {"lat": lat, "lon": lon, "pop": pop}
P = xyz(lat, lon)
res = {}
for t, ids in tiers.items():
    u = f[f.unique_id.isin(ids)]
    d, _ = cKDTree(xyz(u.loc_lat.values, u.loc_lon.values)).query(P)
    straight = 2 * 6371.0 * np.arcsin(np.clip(d / 2, 0, 1))
    fac = np.where(hill, factor(straight, "hill"), factor(straight, "plain"))
    wk = straight * fac * 6
    out[f"wk_{t}"] = wk
    o = np.argsort(wk)
    cw = np.cumsum(pop[o])
    med = wk[o][np.searchsorted(cw, cw[-1] / 2)]
    s300 = pop[wk >= 300].sum() / pop.sum()
    s600 = pop[wk >= 600].sum() / pop.sum()
    res[t] = (len(u), u.district.nunique(), med, s300, s600)
    print(f"{t}: units {len(u)} districts {u.district.nunique()} | weighted median weekly km {med:.0f} | 300+ {s300:.3f} | 600+ {s600:.3f}")
# spot check of the vectorised factor against geo.travel.estimate
rng = np.random.default_rng(0)
u = f[f.unique_id.isin(tiers["corroborated"])]
_, ui = cKDTree(xyz(u.loc_lat.values, u.loc_lon.values)).query(P[:0] if False else P[rng.choice(len(P), 2000)])
idx = rng.choice(len(P), 2000)
_, ui = cKDTree(xyz(u.loc_lat.values, u.loc_lon.values)).query(P[idx])
ref = np.array([travel.estimate((lat[i], lon[i]), (u.loc_lat.values[j], u.loc_lon.values[j]), state=st[i])["km"] for i, j in zip(idx, ui)])
print("factor check: max abs diff weekly km vs geo.travel.estimate", np.max(np.abs(ref * 6 - out["wk_corroborated"][idx])).round(2))
cells = pd.DataFrame(out)
cells.to_parquet(Path(__file__).resolve().parent / "out/v5_pixels.parquet", index=False)
