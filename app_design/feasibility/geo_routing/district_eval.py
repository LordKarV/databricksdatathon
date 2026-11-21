"""Score offline reverse geocoding (nearest PIN centroid, nearest post office) against district polygons.

Ground truth: geoBoundaries IND ADM2 simplified (736 districts, 2021, ODbL,
https://www.geoboundaries.org/api/current/gbOpen/IND/ADM2/), point in polygon.
Name matching is avoided: each India Post district name is mapped to the polygon that holds the
majority of its PIN centroids, then a method is right when the district it returns maps to the
polygon that contains the query point.

Query points: 2,000 random post offices across India, each jittered 0 to 5 km in a random direction
(a proxy for "a person in or near a village"), seed 7. Also scores the 5 Nominatim test points.
Writes out/district_eval.json.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from geocode_test import OUT, offline_tables
from geo_common import hav_km

HERE = Path(__file__).parent
GJ = HERE / "ext_geoboundaries/IND_ADM2_simplified.geojson"
N, JITTER_KM, SEED = 2000, 5.0, 7


def rings_of(geom):
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [[np.asarray(r, dtype=float) for r in p] for p in polys]


def in_ring(x, y, ring):
    """Vectorised even-odd ray casting; x=lon, y=lat arrays."""
    x1, y1 = ring[:-1, 0], ring[:-1, 1]
    x2, y2 = ring[1:, 0], ring[1:, 1]
    X, Y = x[:, None], y[:, None]
    cross = ((y1 <= Y) != (y2 <= Y)) & (X < (x2 - x1) * (Y - y1) / np.where(y2 == y1, 1e-12, y2 - y1) + x1)
    return cross.sum(axis=1) % 2 == 1


def locate(lat, lon, polys):
    """Index of the containing polygon for each point, -1 if none."""
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    out = np.full(len(lat), -1)
    for k, (bbox, parts) in enumerate(polys):
        m = (out == -1) & (lon >= bbox[0]) & (lon <= bbox[2]) & (lat >= bbox[1]) & (lat <= bbox[3])
        idx = np.where(m)[0]
        if not len(idx):
            continue
        hit = np.zeros(len(idx), bool)
        for rings in parts:
            inside = in_ring(lon[idx], lat[idx], rings[0])
            for hole in rings[1:]:
                inside &= ~in_ring(lon[idx], lat[idx], hole)
            hit |= inside
        out[idx[hit]] = k
    return out


def nearest_idx(qlat, qlon, lat, lon, chunk=200):
    res = np.empty(len(qlat), int)
    dist = np.empty(len(qlat))
    for s in range(0, len(qlat), chunk):
        d = hav_km(qlat[s:s + chunk, None], qlon[s:s + chunk, None], lat[None, :], lon[None, :])
        res[s:s + chunk] = d.argmin(axis=1)
        dist[s:s + chunk] = d.min(axis=1)
    return res, dist


def main():
    g = json.loads(GJ.read_text())
    names = [f["properties"]["shapeName"] for f in g["features"]]
    polys = []
    for f in g["features"]:
        parts = rings_of(f["geometry"])
        allpts = np.vstack([p[0] for p in parts])
        polys.append(((allpts[:, 0].min(), allpts[:, 1].min(), allpts[:, 0].max(), allpts[:, 1].max()), parts))

    cen, off = offline_tables()
    cen["poly"] = locate(cen.best_lat, cen.best_lon, polys)
    dmap = (cen[cen.poly >= 0].groupby(["state", "district"]).poly
            .agg(lambda s: s.value_counts().index[0]).to_dict())
    share = (cen[cen.poly >= 0].groupby(["state", "district"]).poly
             .agg(lambda s: s.value_counts(normalize=True).iloc[0]))

    rng = np.random.default_rng(SEED)
    seed_off = off.sample(N, random_state=SEED).reset_index(drop=True)
    r = JITTER_KM * np.sqrt(rng.uniform(0, 1, N))
    th = rng.uniform(0, 2 * np.pi, N)
    qlat = seed_off.lat.values + (r * np.cos(th)) / 111.0
    qlon = seed_off.lon.values + (r * np.sin(th)) / (111.0 * np.cos(np.radians(seed_off.lat.values)))
    truth = locate(qlat, qlon, polys)
    keep = truth >= 0

    ic, dc = nearest_idx(qlat, qlon, cen.best_lat.values, cen.best_lon.values)
    io, do = nearest_idx(qlat, qlon, off.lat.values, off.lon.values)
    pc = [dmap.get((cen.state[i], cen.district[i]), -2) for i in ic]
    po = [dmap.get((off.statename[i], off.district[i]), -2) for i in io]
    ok_c = (np.array(pc) == truth)[keep]
    ok_o = (np.array(po) == truth)[keep]
    st_c = (cen.state.values[ic] == seed_off.statename.values)[keep]

    # distance of each query point to the nearest district boundary vertex, to show where errors happen
    def boundary_km(i):
        parts = polys[truth[i]][1]
        v = np.vstack([p[0] for p in parts])
        return float(hav_km(qlat[i], qlon[i], v[:, 1], v[:, 0]).min())
    bk = np.array([boundary_km(i) for i in np.where(keep)[0]])
    near = bk < 5
    # restrict to points whose true polygon is the clean majority target of some directory district (share >= 0.8)
    clean_polys = {dmap[k] for k, v in share.items() if v >= 0.8}
    clean = np.isin(truth[keep], list(clean_polys))

    res = {
        "n_query": int(keep.sum()), "n_outside_polygons": int((~keep).sum()), "jitter_km_max": JITTER_KM,
        "nearest_pin_centroid_district_accuracy": round(float(ok_c.mean()), 4),
        "nearest_office_district_accuracy": round(float(ok_o.mean()), 4),
        "nearest_pin_state_matches_seed_office_state": round(float(st_c.mean()), 4),
        "share_points_within_5km_of_district_boundary": round(float(near.mean()), 4),
        "pin_centroid_accuracy_within_5km_of_boundary": round(float(ok_c[near].mean()), 4),
        "pin_centroid_accuracy_farther_than_5km": round(float(ok_c[~near].mean()), 4),
        "office_accuracy_within_5km_of_boundary": round(float(ok_o[near].mean()), 4),
        "office_accuracy_farther_than_5km": round(float(ok_o[~near].mean()), 4),
        "n_query_in_clean_districts": int(clean.sum()),
        "pin_centroid_accuracy_clean_districts": round(float(ok_c[clean].mean()), 4),
        "office_accuracy_clean_districts": round(float(ok_o[clean].mean()), 4),
        "nearest_pin_centroid_km_median_p90": [round(float(np.median(dc[keep])), 2), round(float(np.quantile(dc[keep], .9)), 2)],
        "nearest_office_km_median_p90": [round(float(np.median(do[keep])), 2), round(float(np.quantile(do[keep], .9)), 2)],
        "directory_districts_mapped": len(dmap),
        "directory_districts_majority_share_below_0.8": int((share < 0.8).sum()),
        "caveat": "polygons are simplified 2021 districts; directory districts created or split later map to one polygon",
    }
    pts = json.loads((OUT / "geocode_results.json").read_text())
    t5 = locate([p["lat"] for p in pts], [p["lon"] for p in pts], polys)
    res["test_points_polygon_district"] = {p["point"]: (names[k] if k >= 0 else None) for p, k in zip(pts, t5)}
    (OUT / "district_eval.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))

    # self-check of the point-in-polygon code on a unit square with a hole
    sq = [np.array([[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], float), np.array([[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]], float)]
    t = locate([0.5, 1.5, 3.0, 5.0], [0.5, 1.5, 3.0, 5.0], [((0, 0, 4, 4), [sq])])
    assert t.tolist() == [0, -1, 0, -1], t


if __name__ == "__main__":
    main()
