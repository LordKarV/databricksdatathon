"""Inspect WorldPop R2025A India 1 km grids and join them to facilities and districts.

Usage (run with -I; the venv needs rasterio, numpy, pandas, pyarrow, scipy):
  python -I join_test.py <worldpop_dir> <facilities.parquet> <pincode.parquet> \
      <district_nfhs_map.csv> <out_dir>

Writes to out_dir:
  inspect.json               per-band stats (cells, nodata, sum, max)
  facility_population.parquet one row per facility with coordinates: people in the
                             facility's cell and within 5/10/25 km, plus women 15-49
                             and children under 5 within 10/25 km
  district_population.csv    zonal sums per India Post district (cells assigned to the
                             nearest post office), with the NFHS district key
  hand_check.csv             20 random facilities for manual review
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.spatial import cKDTree

TAG = "2025_CN_1km_R2025A_UA_v1.tif"
BANDS = {
    "pop": [f"ind_pop_{TAG}"],
    "wra": [f"ind_f_{a}_{TAG}" for a in (15, 20, 25, 30, 35, 40, 45)],  # women 15-49
    "u5": [f"ind_t_{a}_{TAG}" for a in ("00", "01")],  # age 0-12 months + 1-4 years
}
RADII_KM = (5, 10, 25)
INDIA_BOX = (6.0, 38.0, 68.0, 98.0)  # lat min, lat max, lon min, lon max
EARTH_KM = 6371.0088
MAX_PO_FROM_DISTRICT_MEDIAN_KM = 100


def read_band(path):
    with rasterio.open(path) as r:
        a = r.read(1).astype(np.float64)
        nodata = a == r.nodata
        a[nodata] = 0.0
        return a, nodata, r.transform, r.shape


def load_grids(wp_dir):
    grids, stats, ref = {}, {}, None
    for key, files in BANDS.items():
        total = None
        for f in files:
            a, nodata, tf, shape = read_band(wp_dir / f)
            if ref is None:
                ref = (tf, shape, nodata)
            assert (tf, shape) == ref[:2], f"grid mismatch in {f}"
            stats[f] = {
                "cells": int(a.size), "nodata": int(nodata.sum()),
                "nodata_differs_from_total": int((nodata != ref[2]).sum()),
                "zero_valid": int(((a == 0) & ~nodata).sum()), "negative": int((a < 0).sum()),
                "sum": round(float(a.sum())), "max": round(float(a.max()), 1),
            }
            total = a if total is None else total + a
        grids[key] = total
    return grids, ref, stats


def cell_centres(tf, shape):
    rows, cols = np.arange(shape[0]), np.arange(shape[1])
    lat = tf.f + (rows + 0.5) * tf.e
    lon = tf.c + (cols + 0.5) * tf.a
    return lat, lon


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(a))


def facility_sums(fac, grids, tf, shape):
    """Sum each grid over cells whose centre lies within r km of the facility.

    ponytail: per-facility window loop, about 10k x 110x110 cells; fine for one batch run.
    """
    clat, clon = cell_centres(tf, shape)
    rmax = max(RADII_KM)
    out = []
    for lat, lon in zip(fac.latitude.to_numpy(), fac.longitude.to_numpy()):
        r, c = int((lat - tf.f) / tf.e), int((lon - tf.c) / tf.a)
        row = {"row": r, "col": c, "in_grid": 0 <= r < shape[0] and 0 <= c < shape[1]}
        if not row["in_grid"]:
            out.append(row)
            continue
        row["pop_cell"] = grids["pop"][r, c]
        dr = int(np.ceil(rmax / (abs(tf.e) * 111.0))) + 1
        dc = int(np.ceil(rmax / (tf.a * 111.0 * np.cos(np.radians(lat))))) + 1
        r0, r1, c0, c1 = max(r - dr, 0), min(r + dr + 1, shape[0]), max(c - dc, 0), min(c + dc + 1, shape[1])
        d = hav_km(lat, lon, clat[r0:r1, None], clon[None, c0:c1])
        for rad in RADII_KM:
            m = d <= rad
            row[f"pop_{rad}km"] = grids["pop"][r0:r1, c0:c1][m].sum()
            if rad >= 10:
                row[f"wra_{rad}km"] = grids["wra"][r0:r1, c0:c1][m].sum()
                row[f"u5_{rad}km"] = grids["u5"][r0:r1, c0:c1][m].sum()
        out.append(row)
    return pd.concat([fac.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def load_post_offices(path):
    po = pd.read_parquet(path, columns=["pincode", "district", "statename", "latitude", "longitude"])
    po = po.assign(lat=pd.to_numeric(po.latitude, errors="coerce"), lon=pd.to_numeric(po.longitude, errors="coerce"))
    lo_lat, hi_lat, lo_lon, hi_lon = INDIA_BOX
    ok = po.lat.between(lo_lat, hi_lat) & po.lon.between(lo_lon, hi_lon) & po.district.notna() & po.statename.notna()
    # Directory coordinates are noisy (a Jaunpur office sits at lon 25.4); a stray office
    # would capture another district's cells, so drop offices far from their district median.
    g = po[ok].groupby(["statename", "district"])
    d = hav_km(po.lat, po.lon, g.lat.transform("median").reindex(po.index), g.lon.transform("median").reindex(po.index))
    ok &= d <= MAX_PO_FROM_DISTRICT_MEDIAN_KM
    return po[ok].reset_index(drop=True), int((~ok).sum())


def district_sums(grids, tf, shape, nodata, po):
    """Assign every valid cell to its nearest post office's district, then sum.

    ponytail: nearest-post-office Voronoi stands in for district polygons; swap in
    official boundaries (e.g. a district shapefile) for exact zonal sums.
    """
    clat, clon = cell_centres(tf, shape)
    rr, cc = np.nonzero(~nodata)
    k = np.cos(np.radians(22.0))  # rough lon scaling for India
    tree = cKDTree(np.c_[po.lat.to_numpy(), po.lon.to_numpy() * k])
    dist, idx = tree.query(np.c_[clat[rr], clon[cc] * k])
    key = po.statename.str.upper().str.strip() + "|" + po.district.str.upper().str.strip()
    cell_key = key.to_numpy()[idx]
    df = pd.DataFrame({"key": cell_key, **{b: g[rr, cc] for b, g in grids.items()}, "far": dist * 111.0 > 25})
    agg = df.groupby("key").agg(pop=("pop", "sum"), wra=("wra", "sum"), u5=("u5", "sum"),
                                cells=("pop", "size"), cells_far_from_po=("far", "sum")).reset_index()
    agg[["state", "district"]] = agg.key.str.split("|", n=1, expand=True)
    return agg.drop(columns="key")


def main(wp_dir, fac_path, pin_path, map_path, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    grids, (tf, shape, nodata), stats = load_grids(wp_dir)
    stats["_combined"] = {b: round(float(g.sum())) for b, g in grids.items()}
    stats["_combined"]["valid_cells"] = int((~nodata).sum())
    stats["_combined"]["wra_gt_pop_cells"] = int((grids["wra"] > grids["pop"] + 1e-3).sum())

    fac = pd.read_parquet(fac_path, columns=["unique_id", "name", "address_city", "address_stateOrRegion",
                                             "address_zipOrPostcode", "latitude", "longitude"])
    stats["_facilities"] = {"rows": len(fac), "with_coords": int(fac.latitude.notna().sum())}
    fp = facility_sums(fac[fac.latitude.notna() & fac.longitude.notna()], grids, tf, shape)
    fp.to_parquet(out_dir / "facility_population.parquet", index=False)
    stats["_facilities"].update({
        "in_grid": int(fp.in_grid.sum()),
        "on_valid_cell": int((fp.in_grid & fp.pop_cell.notna() & (fp.pop_cell > 0)).sum()),
        "pop_cell_zero_or_nodata": int((fp.in_grid & ~(fp.pop_cell > 0)).sum()),
        "pop_10km_zero": int((fp.in_grid & (fp.pop_10km == 0)).sum()),
        "pop_10km_quantiles": fp.pop_10km.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).round().to_dict(),
    })

    po, po_dropped = load_post_offices(pin_path)
    ds = district_sums(grids, tf, shape, nodata, po)
    m = pd.read_csv(map_path)[["state", "district", "final_dn"]]
    ds = ds.merge(m, on=["state", "district"], how="left").rename(columns={"final_dn": "nfhs_district_norm"})
    ds.round(0).to_csv(out_dir / "district_population.csv", index=False)
    stats["_districts"] = {"post_offices_used": len(po), "post_offices_dropped": po_dropped,
                           "districts": len(ds), "with_nfhs_key": int(ds.nfhs_district_norm.notna().sum()),
                           "pop_sum": round(float(ds["pop"].sum()))}

    hc = fp[fp.in_grid].sample(20, random_state=7)
    hc[["unique_id", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode", "latitude",
        "longitude", "pop_cell", "pop_5km", "pop_10km", "wra_10km", "u5_10km"]].round(4).to_csv(
        out_dir / "hand_check.csv", index=False)
    (out_dir / "inspect.json").write_text(json.dumps(stats, indent=1, default=float))
    print(json.dumps({k: v for k, v in stats.items() if k.startswith("_")}, indent=1, default=float))


if __name__ == "__main__":
    a = [Path(x) for x in sys.argv[1:]]
    if len(a) != 5:
        sys.exit(__doc__)
    main(*a)
