"""Check the raster travel-time solver against measured road routes.

Input: geo/out/road_factor_pairs.csv (3,790 origin -> facility pairs with an OSRM free-flow route,
written by geo/measure_road_factor.py). For a seeded sample of origins we run one Dijkstra per origin
over the MAP friction graph (common._graph) and read the minutes at each paired facility cell.
Output: data/travel_check.csv, data/travel_check_numbers.json.
"""
import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra

import common as C

N_ORIGINS = 150
SEED = 11


def main():
    p = pd.read_csv(C.P["osrm_pairs"])
    G = C.build_grid()
    g, node = C._graph()
    origins = p[["pin", "o_lat", "o_lon"]].drop_duplicates("pin").sample(N_ORIGINS, random_state=SEED)
    s = p[p.pin.isin(origins.pin)].copy()
    orow, ocol = C.cell_of(s.o_lat, s.o_lon, G["transform"])
    frow, fcol = C.cell_of(s.f_lat, s.f_lon, G["transform"])
    H, W = node.shape
    ok = (orow >= 0) & (orow < H) & (frow >= 0) & (frow < H) & (ocol >= 0) & (ocol < W) & (fcol >= 0) & (fcol < W)
    s = s[ok]
    s["o_node"] = node[orow[ok], ocol[ok]]
    s["f_node"] = node[frow[ok], fcol[ok]]
    s = s[(s.o_node >= 0) & (s.f_node >= 0)]
    out = []
    for o, grp in s.groupby("o_node"):
        dist = dijkstra(g, directed=False, indices=int(o), limit=900)
        out.append(grp.assign(raster_min=dist[grp.f_node.to_numpy()]))
    r = pd.concat(out)
    r = r[np.isfinite(r.raster_min)]
    r["ratio"] = r.osrm_min / r.raster_min.clip(lower=1)
    big = r[r.osrm_min >= 10]
    rho = big[["osrm_min", "raster_min"]].corr(method="spearman").iloc[0, 1]
    within60 = r.osrm_min <= 60
    pred60 = r.raster_min <= 60
    numbers = {
        "pairs": int(len(r)), "origins": int(r.pin.nunique()), "pairs_osrm_ge_10min": int(len(big)),
        "spearman_ge_10": float(rho),
        "median_ratio_osrm_over_raster": float(big.ratio.median()),
        "ratio_p10": float(big.ratio.quantile(0.1)), "ratio_p90": float(big.ratio.quantile(0.9)),
        "median_ratio_rural": float(big[big.stratum == "rural"].ratio.median()),
        "median_ratio_urban": float(big[big.stratum == "urban"].ratio.median()),
        "agree_60min_class": float((within60 == pred60).mean()),
        "raster_le60_but_osrm_gt60": int((pred60 & ~within60).sum()),
        "raster_gt60_but_osrm_le60": int((~pred60 & within60).sum()),
    }
    C.save_csv(r[["pin", "state", "stratum", "facility_id", "hav_km", "road_km", "osrm_min", "raster_min", "ratio"]],
               "travel_check")
    C.save_numbers("travel_check", numbers)
    for k, v in numbers.items():
        print(f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}")


if __name__ == "__main__":
    main()
