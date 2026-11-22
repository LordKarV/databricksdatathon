"""Independent travel-time recomputation for s2 (dialysis access), s4 (golden hour), s5 (urban-rural).

Own solver, built differently from common.py on purpose:
- runs on MAP's native friction grid (3840 x 3600, 1/120 degree), not the WorldPop grid, and does not
  restrict routes to Indian cells (a road through a neighbouring country's cell is allowed);
- edges: 8 neighbours, cost = great-circle-ish metres (111,320 m per degree, lon scaled by cos lat at the
  edge midpoint) x mean friction of the two cells (min per metre), the accCost rule;
- facility source cell = MAP cell under (loc_lat, loc_lon), snapped to the nearest cell with friction;
- one multi-source Dijkstra (scipy, min_only) per facility set.
Population (WorldPop 2025) is shifted onto the MAP grid by its whole-cell offset, computed here from the
two geotransforms. Degree of Urbanisation re-implemented from the GHSL thresholds.
Writes verify/out/travel_numbers.json.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from scipy import ndimage, sparse
from scipy.sparse.csgraph import dijkstra

import v_base as B
from v_stories import NCD, nfhs_by_district

MAPDIR = B.ROOT / "data/external/map_travel_time_healthcare_2020/raw"
FRICTION = MAPDIR / "india_Accessibility__202001_Global_Motorized_Friction_Surface.tif"
MAP_TT = MAPDIR / "india_Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare.tif"
M_PER_DEG = 111_320.0


def load():
    with rasterio.open(FRICTION) as r:
        fr = r.read(1).astype(np.float64)
        ftr, fnd = r.transform, r.nodata
    fr[(fr == fnd) | ~np.isfinite(fr) | (fr <= 0)] = np.nan
    with rasterio.open(MAP_TT) as r:
        mtt = r.read(1).astype(np.float64)
        mtt[(mtt == r.nodata) | ~np.isfinite(mtt)] = np.inf
    pop_wp, wra, valid, wtr = B.wp_arrays()
    r0 = round((ftr.f - wtr.f) / -ftr.e)
    c0 = round((wtr.c - ftr.c) / ftr.a)
    assert abs((ftr.f - wtr.f) / -ftr.e - r0) < 1e-3 and abs((wtr.c - ftr.c) / ftr.a - c0) < 1e-3
    pop = np.zeros_like(fr)
    pop[r0:r0 + pop_wp.shape[0], c0:c0 + pop_wp.shape[1]] = pop_wp
    return fr, ftr, mtt, pop, (r0, c0), wtr, pop_wp, valid


def graph(fr, ftr):
    H, W = fr.shape
    ok = np.isfinite(fr)
    node = np.full((H, W), -1, np.int64)
    node[ok] = np.arange(ok.sum())
    lat = ftr.f + (np.arange(H) + 0.5) * ftr.e
    dy = abs(ftr.e) * M_PER_DEG
    parts = []
    for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = (slice(0, H - di), slice(max(0, -dj), W - max(0, dj)))
        b = (slice(di, H), slice(max(0, dj), W - max(0, -dj)))
        na, nb = node[a], node[b]
        m = (na >= 0) & (nb >= 0)
        latm = (lat[:H - di] + lat[di:]) / 2 if di else lat
        dx = abs(ftr.a) * M_PER_DEG * np.cos(np.radians(latm))[:, None] * dj
        dist = np.sqrt(dx ** 2 + (dy * di) ** 2) * np.ones(na.shape)
        cost = dist * 0.5 * (fr[a] + fr[b])
        parts.append((na[m], nb[m], cost[m]))
    s, t, w = (np.concatenate(x) for x in zip(*parts))
    n = int(ok.sum())
    return sparse.csr_matrix((w, (s, t)), shape=(n, n)), node


def source_nodes(lat, lon, ftr, node):
    r = np.floor((np.asarray(lat) - ftr.f) / ftr.e).astype(int)
    c = np.floor((np.asarray(lon) - ftr.c) / ftr.a).astype(int)
    _, (ir, ic) = ndimage.distance_transform_edt(node < 0, return_indices=True)
    return np.unique(node[ir[r, c], ic[r, c]])


def minutes(g, node, src):
    out = np.full(node.shape, np.inf)
    out[node >= 0] = dijkstra(g, directed=False, indices=src, min_only=True)
    return out


def share(tt, pop, mask=None, limit=60.0):
    m = np.ones(pop.shape, bool) if mask is None else mask
    return float((pop * (tt <= limit))[m].sum() / pop[m].sum())


def wmedian(v, w):
    o = np.argsort(v)
    cw = np.cumsum(w[o])
    return float(v[o][np.searchsorted(cw, cw[-1] / 2)])


def degurba(pop_wp, valid, wtr):
    lat = wtr.f + (np.arange(pop_wp.shape[0]) + 0.5) * wtr.e
    km2 = (abs(wtr.a) * 111.32 * np.cos(np.radians(lat)))[:, None] * (abs(wtr.e) * 111.32)
    dens = np.where(valid, pop_wp / km2, 0)
    cls = valid.astype(np.int8)
    lab, n = ndimage.label(dens >= 300, structure=np.ones((3, 3)))
    big = np.r_[False, ndimage.sum(pop_wp, lab, np.arange(1, n + 1)) >= 5000]
    cls[big[lab]] = 2
    lab, n = ndimage.label(dens >= 1500)  # default structure = 4-connectivity
    big = np.r_[False, ndimage.sum(pop_wp, lab, np.arange(1, n + 1)) >= 50000]
    cls[big[lab]] = 3
    return cls


def lgd_raster(wtr, shape):
    import geopandas as gpd
    g = gpd.read_parquet(B.LGD)[["dist_lgd", "stname", "geometry"]]
    g["geometry"] = g.geometry.make_valid()
    ras = features.rasterize(zip(g.geometry, g.dist_lgd.astype(int)), out_shape=shape, transform=wtr, fill=0,
                             dtype="int32")
    return ras, g[["dist_lgd", "stname"]]


def main():
    fr, ftr, mtt, pop, (r0, c0), wtr, pop_wp, valid = load()
    g, node = graph(fr, ftr)
    d = B.records()
    sets = {"any": d.index == d.index, "trauma_claim": d.trauma_claim, "trauma_conf": d.trauma_conf,
            "dialysis_conf": d.dialysis_conf, "csection_conf": d.csection_conf}
    sl = (slice(r0, r0 + pop_wp.shape[0]), slice(c0, c0 + pop_wp.shape[1]))
    tt = {k: minutes(g, node, source_nodes(d.loc_lat[m], d.loc_lon[m], ftr, node))[sl] for k, m in sets.items()}
    tt["map"] = mtt[sl]
    P = pop_wp
    out = {"india_share60": {k: share(v, P) for k, v in tt.items()}}
    out["trauma_conf_share_at"] = {str(t): share(tt["trauma_conf"], P, limit=t) for t in (34.41, 85.15)}
    out["people_outside_trauma_conf_m"] = (1 - out["india_share60"]["trauma_conf"]) * P.sum() / 1e6
    dist, lgd = lgd_raster(wtr, P.shape)
    st_of = dict(zip(lgd.dist_lgd.astype(int), lgd.stname))
    st_ras = np.vectorize(lambda x: st_of.get(x, ""))(np.unique(dist))
    st_lut = dict(zip(np.unique(dist), st_ras))
    states = {}
    for s in ("BIHAR", "MADHYA PRADESH", "ODISHA", "ARUNACHAL PRADESH", "MIZORAM"):
        m = np.isin(dist, [k for k, v in st_lut.items() if v == s])
        states[s] = dict(map=share(tt["map"], P, m), conf=share(tt["trauma_conf"], P, m),
                         conf_lo=share(tt["trauma_conf"], P, m, 34.41), conf_hi=share(tt["trauma_conf"], P, m, 85.15),
                         outside_conf_m=float((P * (tt["trauma_conf"] > 60))[m].sum() / 1e6))
    out["states"] = states
    out["s5"] = s5(degurba(pop_wp, valid, wtr), d, wtr, P, tt)
    out["s2"] = s2_hot(dist, tt["dialysis_conf"], P)
    (B.OUT / "travel_numbers.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))


def s5(cls, d, wtr, P, tt):
    r = np.floor((d.loc_lat - wtr.f) / wtr.e).astype(int).clip(0, P.shape[0] - 1)
    c = np.floor((d.loc_lon - wtr.c) / wtr.a).astype(int).clip(0, P.shape[1] - 1)
    rec_cls = cls[r, c]
    res = {}
    for code, name in ((3, "urban"), (2, "town"), (1, "rural")):
        m = cls == code
        res[name] = dict(pop_share=float(P[m].sum() / P.sum()), records=int((rec_cls == code).sum()),
                         **{f"{k}_60": share(tt[k], P, m) for k in ("trauma_conf", "dialysis_conf", "csection_conf")})
    res["records_on_class0"] = int((rec_cls == 0).sum())
    return res


def s2_hot(dist, tt, P):
    nf, link = nfhs_by_district(NCD)
    nf["ncd"] = nf[NCD].mean(axis=1, skipna=False)
    nf = nf.dropna(subset=["ncd"]).reset_index(drop=True)
    l2 = link.dropna(subset=["nfhs_district"])
    code = {k: i + 1 for i, k in enumerate(zip(nf.nfhs_state, nf.nfhs_district))}
    lut = np.zeros(int(dist.max()) + 1, np.int32)
    for dl, s, n in zip(l2.dist_lgd.astype(int), l2.nfhs_state, l2.nfhs_district):
        lut[dl] = code.get((s, n), 0)
    cell = lut[dist].ravel()
    p = P.ravel()
    n = len(code) + 1
    within = np.bincount(cell, p * (tt.ravel() <= 60), n)
    den = np.bincount(cell, p, n)
    nf["share60"] = within[1:] / np.where(den[1:] > 0, den[1:], np.nan)
    nf["pop_r"] = den[1:]
    q75 = nf.ncd.quantile(0.75)
    hot = nf[(nf.ncd >= q75) & (nf.share60 < 0.5)]
    eg = code[("Andhra Pradesh", "East Godavari")]
    m = cell == eg
    from scipy.stats import spearmanr
    return dict(hot_districts=len(hot), hot_pop_m=float(hot.pop_r.sum() / 1e6),
                hot_states_m=(hot.groupby("nfhs_state").pop_r.sum() / 1e6).nlargest(4).to_dict(),
                rho_ncd_share60=float(spearmanr(nf.ncd, nf.share60, nan_policy="omit").statistic),
                q4_share60=float(np.average(nf[nf.ncd >= q75].share60, weights=nf[nf.ncd >= q75].pop_r)),
                q1_share60=float(np.average(nf[nf.ncd <= nf.ncd.quantile(0.25)].share60,
                                            weights=nf[nf.ncd <= nf.ncd.quantile(0.25)].pop_r)),
                east_godavari=dict(share60=float(within[eg] / den[eg]), pop_m=float(den[eg] / 1e6),
                                   median_min=wmedian(np.minimum(tt.ravel()[m], 1e4), p[m])))


if __name__ == "__main__":
    main()
