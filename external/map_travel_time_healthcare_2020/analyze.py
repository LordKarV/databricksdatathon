"""Inspect the MAP 2020 India raster clips and join them to our tables.

Usage (run with -I, paths as arguments):
  python -I analyze.py RAW_DIR FACILITIES_PARQUET PIN_PARQUET AUDIT_GEO_DIR OUT_DIR

Writes to OUT_DIR: stats.json, facility_access.parquet, pin_access.parquet,
district_access.parquet, handcheck_20.csv, routing_check.csv, routing_demo.csv.
"""
import heapq
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tiff_np  # noqa: E402

COV = {
    "tt_motor": "Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare",
    "tt_walk": "Accessibility__202001_Global_Walking_Only_Travel_Time_To_Healthcare",
    "friction": "Accessibility__202001_Global_Motorized_Friction_Surface",
}
NODATA = -9999.0
SEED = 7


def load(raw: Path) -> tuple[dict, tuple]:
    rasters, geo = {}, None
    for k, c in COV.items():
        a, g = tiff_np.read(raw / f"india_{c}.tif")
        a = np.where(a <= NODATA + 1, np.nan, a).astype(np.float32)
        rasters[k], geo = a, g
    return rasters, geo


def rc(lat: np.ndarray, lon: np.ndarray, geo: tuple, shape: tuple) -> tuple:
    lon0, lat0, dx, dy = geo
    r = np.floor(np.nan_to_num((lat0 - lat) / dy, nan=-1)).astype("int64")
    c = np.floor(np.nan_to_num((lon - lon0) / dx, nan=-1)).astype("int64")
    ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1]) & np.isfinite(lat) & np.isfinite(lon)
    return np.where(ok, r, 0), np.where(ok, c, 0), ok


def sample(rasters: dict, geo: tuple, lat, lon) -> pd.DataFrame:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    shape = rasters["tt_motor"].shape
    r, c, ok = rc(lat, lon, geo, shape)
    out = {"in_clip": ok}
    for k, a in rasters.items():
        out[k] = np.where(ok, a[r, c], np.nan)
    return pd.DataFrame(out)


def raster_stats(rasters: dict, india_mask: np.ndarray) -> dict:
    s = {}
    for k, a in rasters.items():
        v = a[india_mask]
        fin = v[np.isfinite(v)]
        s[k] = {
            "cells_total": int(a.size),
            "nodata_share_total": round(float(np.isnan(a).mean()), 4),
            "cells_in_india_mask": int(india_mask.sum()),
            "nodata_share_in_india_mask": round(float(np.isnan(v).mean()), 4),
            "min": float(fin.min()), "max": float(fin.max()),
            "quantiles_in_mask": {q: round(float(np.quantile(fin, q)), 3) for q in (0.5, 0.9, 0.99, 0.999)},
            "negative_cells": int((fin < 0).sum()),
        }
    return s


def india_mask_from_pins(pins: pd.DataFrame, geo: tuple, shape: tuple, radius: int = 6) -> np.ndarray:
    """ponytail: India land mask = cells within ~5 km of any post office; no boundary file needed."""
    m = np.zeros(shape, bool)
    r, c, ok = rc(pins.lat.values, pins.lon.values, geo, shape)
    m[r[ok], c[ok]] = True
    grown = m.copy()
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            grown |= np.roll(np.roll(m, dr, 0), dc, 1)
    return grown


def dijkstra(fr: np.ndarray, geo: tuple, r0: int, c0: int, half: int) -> tuple[np.ndarray, int, int]:
    """Least-cost minutes from one cell over a (2*half+1)^2 window, 8-neighbour,
    edge cost = metres * mean friction (min/m), same idea as gdistance accCost
    used by Weiss et al. ponytail: pure-Python heap, about 2-10 s per window;
    move to scikit-image MCP_Geometric on Databricks if this is too slow."""
    R0, C0 = max(r0 - half, 0), max(c0 - half, 0)
    sub = fr[R0:r0 + half + 1, C0:c0 + half + 1]
    h, w = sub.shape
    _, lat0, dx, dy = geo
    dist = np.full(sub.shape, np.inf)
    sr, sc = r0 - R0, c0 - C0
    dist[sr, sc] = 0.0
    heap = [(0.0, sr, sc)]
    steps = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    while heap:
        d, i, j = heapq.heappop(heap)
        if d > dist[i, j] or not np.isfinite(sub[i, j]):
            continue
        lat = lat0 - (R0 + i + 0.5) * dy
        mx, my = dx * 111320.0 * math.cos(math.radians(lat)), dy * 110574.0
        for di, dj in steps:
            a, b = i + di, j + dj
            if 0 <= a < h and 0 <= b < w and np.isfinite(sub[a, b]):
                nd = d + math.hypot(di * my, dj * mx) * 0.5 * (sub[i, j] + sub[a, b])
                if nd < dist[a, b]:
                    dist[a, b] = nd
                    heapq.heappush(heap, (nd, a, b))
    return dist, R0, C0


def haversine_km(lat1, lon1, lat2, lon2):
    p = np.radians
    a = np.sin(p(lat2 - lat1) / 2) ** 2 + np.cos(p(lat1)) * np.cos(p(lat2)) * np.sin(p(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def routing_check(rasters: dict, geo: tuple, pins: pd.DataFrame, n: int = 12, half: int = 60) -> pd.DataFrame:
    """Reproduce MAP travel time at random PIN points from the friction surface:
    estimate = min over cells c in window with TT(c) < 1 min of D(user->c) + TT(c)."""
    tt, fr = rasters["tt_motor"], rasters["friction"]
    rows = []
    for _, p in pins.sample(n, random_state=SEED).iterrows():
        r, c, ok = rc(np.array([p.lat]), np.array([p.lon]), geo, tt.shape)
        if not ok[0]:
            continue
        r, c = int(r[0]), int(c[0])
        dist, R0, C0 = dijkstra(fr, geo, r, c, half)
        win = tt[R0:R0 + dist.shape[0], C0:C0 + dist.shape[1]]
        sel = (win < 1.0) & np.isfinite(dist)
        est = float((dist[sel] + win[sel]).min()) if sel.any() else np.nan
        rows.append({"pincode": p.pincode, "district": p.district, "lat": p.lat, "lon": p.lon,
                     "map_tt_motor_min": round(float(tt[r, c]), 1), "dijkstra_est_min": round(est, 1)})
    return pd.DataFrame(rows)


def routing_demo(rasters: dict, geo: tuple, fac: pd.DataFrame, user: tuple, label: str, half: int = 150) -> pd.DataFrame:
    """Facility-specific travel time from a user point to VF facilities that claim dialysis."""
    fr = rasters["friction"]
    r, c, _ = rc(np.array([user[0]]), np.array([user[1]]), geo, fr.shape)
    dist, R0, C0 = dijkstra(fr, geo, int(r[0]), int(c[0]), half)
    text = (fac["procedure"].fillna("") + " " + fac["specialties"].fillna("") + " " + fac["capability"].fillna("")).str.lower()
    cand = fac[text.str.contains("dialysis") & fac.latitude.notna()].copy()
    fr_r, fr_c, ok = rc(cand.latitude.values, cand.longitude.values, geo, fr.shape)
    ii, jj = fr_r - R0, fr_c - C0
    inwin = ok & (ii >= 0) & (ii < dist.shape[0]) & (jj >= 0) & (jj < dist.shape[1])
    cand = cand[inwin].assign(
        drive_min=dist[ii[inwin], jj[inwin]].round(1),
        straight_km=haversine_km(user[0], user[1], cand.latitude.values[inwin], cand.longitude.values[inwin]).round(1),
    )
    cand["user"] = label
    return cand.sort_values("drive_min")[["user", "name", "address_city", "address_zipOrPostcode", "straight_km", "drive_min"]].head(8)


def main(raw, fac_path, pin_path, audit_geo, out):
    raw, out, audit_geo = Path(raw), Path(out), Path(audit_geo)
    out.mkdir(parents=True, exist_ok=True)
    rasters, geo = load(raw)
    stats = {"geo": geo, "shape": rasters["tt_motor"].shape}

    pins_raw = pd.read_parquet(pin_path)
    pins = pins_raw.assign(lat=pd.to_numeric(pins_raw.latitude, errors="coerce"),
                           lon=pd.to_numeric(pins_raw.longitude, errors="coerce"))
    pins = pins[pins.lat.between(6, 38) & pins.lon.between(68, 98)]
    mask = india_mask_from_pins(pins, geo, rasters["tt_motor"].shape)
    stats["raster"] = raster_stats(rasters, mask)

    # Facilities
    fac = pd.read_parquet(fac_path)
    fs = sample(rasters, geo, fac.latitude, fac.longitude)
    fa = pd.concat([fac[["unique_id", "name", "address_city", "address_stateOrRegion", "address_zipOrPostcode", "latitude", "longitude"]].reset_index(drop=True), fs], axis=1)
    has_coord = fa.latitude.notna() & fa.longitude.notna()
    hit = fa.tt_motor.notna()
    stats["facilities"] = {
        "rows": int(len(fa)), "with_coords": int(has_coord.sum()), "in_clip": int(fa.in_clip.sum()),
        "valid_tt_motor": int(hit.sum()), "valid_tt_walk": int(fa.tt_walk.notna().sum()),
        "match_rate_of_rows": round(hit.sum() / len(fa), 4), "match_rate_of_with_coords": round(hit.sum() / has_coord.sum(), 4),
        "tt_motor_quantiles": {q: round(float(fa.tt_motor.quantile(q)), 2) for q in (0.5, 0.75, 0.9, 0.95, 0.99, 1.0)},
        "tt_walk_quantiles": {q: round(float(fa.tt_walk.quantile(q)), 2) for q in (0.5, 0.75, 0.9, 0.95, 0.99, 1.0)},
        "tt_motor_gt_30": int((fa.tt_motor > 30).sum()), "tt_motor_gt_60": int((fa.tt_motor > 60).sum()),
    }
    g = pd.read_parquet(audit_geo / "facility_geo.parquet", columns=["unique_id", "d_pin_km", "geo_conflict", "pin_district", "near_district", "near_km"])
    n_before = len(fa)
    fa = fa.merge(g.drop_duplicates("unique_id"), on="unique_id", how="left")
    assert len(fa) == n_before
    both = fa.tt_motor.notna() & fa.d_pin_km.notna()
    far = fa.d_pin_km > 25
    stats["facilities"]["tt_motor_median_by_pin_distance"] = {
        "d_pin_km<=25": round(float(fa.loc[both & ~far, "tt_motor"].median()), 2),
        "d_pin_km>25": round(float(fa.loc[both & far, "tt_motor"].median()), 2),
        "n_le25": int((both & ~far).sum()), "n_gt25": int((both & far).sum()),
    }
    fa.to_parquet(out / "facility_access.parquet", index=False)

    # PIN points and district summaries (post offices as an unweighted settlement proxy)
    ps = sample(rasters, geo, pins.lat, pins.lon)
    pa = pd.concat([pins[["pincode", "officename", "district", "statename", "lat", "lon"]].reset_index(drop=True), ps], axis=1)
    pa.to_parquet(out / "pin_access.parquet", index=False)
    stats["pins"] = {"rows_raw": int(len(pins_raw)), "rows_with_coords_in_bbox": int(len(pins)),
                     "valid_tt_motor": int(pa.tt_motor.notna().sum()),
                     "tt_motor_quantiles": {q: round(float(pa.tt_motor.quantile(q)), 2) for q in (0.5, 0.9, 0.99)}}
    d = (pa.dropna(subset=["tt_motor"]).groupby(["statename", "district"])
         .agg(n_offices=("tt_motor", "size"), tt_motor_median=("tt_motor", "median"),
              tt_motor_p90=("tt_motor", lambda s: s.quantile(0.9)), tt_walk_median=("tt_walk", "median"),
              share_offices_gt_60min_motor=("tt_motor", lambda s: (s > 60).mean()))
         .reset_index())
    m = pd.read_csv(audit_geo / "district_nfhs_map.csv")
    m = m.assign(state_u=m.state.str.upper(), district_u=m.district.str.upper())
    d = d.assign(state_u=d.statename.str.upper(), district_u=d.district.str.upper())
    d = d.merge(m[["state_u", "district_u", "final_dn"]], on=["state_u", "district_u"], how="left").drop(columns=["state_u", "district_u"])
    d.to_parquet(out / "district_access.parquet", index=False)
    stats["districts"] = {"pin_districts": int(len(d)), "mapped_to_nfhs": int(d.final_dn.notna().sum()),
                          "distinct_nfhs_districts_covered": int(d.final_dn.nunique()),
                          "top10_remote_by_median": d.nlargest(10, "tt_motor_median")[["statename", "district", "n_offices", "tt_motor_median"]].round(1).to_dict("records")}

    # Hand-check sample: 20 random facilities with a raster value
    hc = fa[fa.tt_motor.notna()].sample(20, random_state=SEED)[["name", "address_city", "address_stateOrRegion", "address_zipOrPostcode", "latitude", "longitude", "pin_district", "near_district", "near_km", "d_pin_km", "tt_motor", "tt_walk"]]
    hc.round(3).to_csv(out / "handcheck_20.csv", index=False)
    # Plus the facilities sitting where MAP says a clinic is > 60 min away
    fa[fa.tt_motor > 60].sort_values("tt_motor", ascending=False)[["name", "address_city", "address_stateOrRegion", "latitude", "longitude", "d_pin_km", "geo_conflict", "tt_motor"]].round(2).to_csv(out / "facilities_tt_gt60.csv", index=False)

    rc_df = routing_check(rasters, geo, pins)
    rc_df.to_csv(out / "routing_check.csv", index=False)
    err = (rc_df.dijkstra_est_min - rc_df.map_tt_motor_min).abs()
    stats["routing_check"] = {"n": int(len(rc_df)), "abs_err_median_min": round(float(err.median()), 2), "abs_err_max_min": round(float(err.max()), 2)}

    demo = pd.concat([
        routing_demo(rasters, geo, fac, (25.98, 86.95), "rural Saharsa district, Bihar (25.98N 86.95E)"),
        routing_demo(rasters, geo, fac, (19.91, 79.30), "rural Chandrapur district, Maharashtra (19.91N 79.30E)"),
    ])
    demo.to_csv(out / "routing_demo.csv", index=False)
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:6])
