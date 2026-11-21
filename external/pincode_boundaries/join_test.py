"""Inspect the data.gov.in PIN boundary GeoParquet and join-test it against facilities.

Usage: python -I join_test.py <boundaries.parquet> <facilities.parquet> <pin_directory.parquet> <out_dir>

No shapely/geopandas in the venv, so WKB parsing and point-in-polygon are done here in numpy.
ponytail: even-odd ray casting over all rings, bbox prefilter; O(polys x points) bbox scan,
fine for 19k x 10k, switch to an R-tree (or Databricks ST_ functions) if it ever needs to scale.
"""
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

KM_PER_DEG = 111.32
FAR_KM = 100.0


def parse_wkb(buf):
    """Return list of polygons; each polygon is a list of (n,2) ring arrays (lon, lat)."""
    def read_poly(off):
        bo = "<" if buf[off] == 1 else ">"
        gtype = struct.unpack_from(bo + "I", buf, off + 1)[0]
        off += 5
        return gtype, bo, off

    gtype, bo, off = read_poly(0)
    polys = []

    def rings_at(off, bo):
        (nr,) = struct.unpack_from(bo + "I", buf, off)
        off += 4
        rings = []
        for _ in range(nr):
            (npt,) = struct.unpack_from(bo + "I", buf, off)
            off += 4
            arr = np.frombuffer(buf, dtype=bo + "f8", count=npt * 2, offset=off).reshape(-1, 2)
            off += npt * 16
            rings.append(arr)
        return rings, off

    if gtype == 3:
        rings, _ = rings_at(off, bo)
        polys.append(rings)
    elif gtype == 6:
        (n,) = struct.unpack_from(bo + "I", buf, off)
        off += 4
        for _ in range(n):
            g2, bo2, off = read_poly(off)
            assert g2 == 3, g2
            rings, off = rings_at(off, bo2)
            polys.append(rings)
    else:
        raise ValueError(f"unsupported WKB type {gtype}")
    return polys


def contains(polys, x, y):
    """Even-odd point-in-polygon for arrays x, y against a (multi)polygon."""
    inside = np.zeros(len(x), dtype=bool)
    for rings in polys:
        for r in rings:
            x1, y1 = r[:-1, 0], r[:-1, 1]
            x2, y2 = r[1:, 0], r[1:, 1]
            # (points, edges) broadcast; rings are small enough after the bbox prefilter
            cond = (y1[None, :] > y[:, None]) != (y2[None, :] > y[:, None])
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = x1 + (y[:, None] - y1) * (x2 - x1) / (y2 - y1)
            inside ^= (np.sum(cond & (x[:, None] < xint), axis=1) % 2).astype(bool)
    return inside


def dist_km(polys, lon, lat):
    """Shortest distance (km) from one point to the polygon boundary, local equirectangular."""
    kx = KM_PER_DEG * np.cos(np.radians(lat))
    best = np.inf
    for rings in polys:
        for r in rings:
            ax, ay = (r[:-1, 0] - lon) * kx, (r[:-1, 1] - lat) * KM_PER_DEG
            bx, by = (r[1:, 0] - lon) * kx, (r[1:, 1] - lat) * KM_PER_DEG
            dx, dy = bx - ax, by - ay
            L = dx * dx + dy * dy
            t = np.clip(np.where(L > 0, -(ax * dx + ay * dy) / np.where(L > 0, L, 1), 0), 0, 1)
            px, py = ax + t * dx, ay + t * dy
            best = min(best, float(np.sqrt(px * px + py * py).min()))
    return best


def ring_area_km2(r, lat0):
    x = r[:, 0] * KM_PER_DEG * np.cos(np.radians(lat0))
    y = r[:, 1] * KM_PER_DEG
    return 0.5 * (np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))


def norm(s):
    return re.sub(r"[^a-z ]", " ", str(s).lower()).replace(" s o", " ").replace(" b o", " ").replace(" h o", " ").strip()


def main(bpath, fpath, ppath, out):
    out = Path(out)
    stats = {}
    b = pd.read_parquet(bpath)
    stats["boundary_rows"] = len(b)
    stats["boundary_null_rate"] = {c: float(b[c].isna().mean()) for c in b.columns if c != "bbox"}
    b["Pincode"] = b["Pincode"].astype(str).str.strip()
    stats["pincode_not_6_digits"] = int((~b.Pincode.str.fullmatch(r"[1-9]\d{5}")).sum())
    stats["distinct_pincodes"] = int(b.Pincode.nunique())
    stats["pincodes_with_2plus_rows"] = int((b.Pincode.value_counts() > 1).sum())
    stats["circles"] = b.Circle.value_counts().to_dict()

    geoms = [parse_wkb(bytes(g)) for g in b.geometry]
    bb = pd.DataFrame(list(b["bbox"]))
    stats["n_vertices_total"] = int(sum(len(r) for p in geoms for rings in p for r in rings))
    stats["multipolygon_rows"] = int(sum(len(p) > 1 for p in geoms))
    unclosed = sum(not np.array_equal(r[0], r[-1]) for p in geoms for rings in p for r in rings)
    stats["unclosed_rings"] = int(unclosed)
    lat_c = (bb.ymin + bb.ymax) / 2
    areas = np.array([abs(sum(ring_area_km2(rings[0], lat_c[i]) for rings in p)) for i, p in enumerate(geoms)])
    b["area_km2"] = areas
    stats["area_km2_quantiles"] = {str(q): round(float(np.quantile(areas, q)), 2) for q in (0, .01, .5, .9, .99, 1)}
    stats["tiny_polygons_lt_0p01km2"] = int((areas < 0.01).sum())

    # coverage vs India Post directory
    pdir = pd.read_parquet(ppath, columns=["pincode", "statename"])
    dpins = set(pdir.pincode.astype(str).str.strip())
    bpins = set(b.Pincode)
    stats["directory_distinct_pins"] = len(dpins)
    stats["directory_pins_with_polygon"] = len(dpins & bpins)
    stats["polygon_pins_not_in_directory"] = len(bpins - dpins)
    st = pdir.assign(p=pdir.pincode.astype(str)).groupby("statename").p.apply(lambda s: round(len(set(s) & bpins) / len(set(s)), 3))
    stats["directory_pin_coverage_by_state"] = st.sort_values().to_dict()

    # facilities
    f = pd.read_parquet(fpath)
    f = f[f.name.notna()].reset_index(drop=True)
    stats["facilities_nonnull"] = len(f)
    zipraw = f.address_zipOrPostcode.fillna("").astype(str).str.replace(r"\s", "", regex=True)
    f["pin"] = zipraw.str.extract(r"^([1-9]\d{5})$")[0]
    ok_xy = f.latitude.between(6, 38) & f.longitude.between(68, 98)
    x, y = f.longitude.to_numpy(), f.latitude.to_numpy()
    f["poly_pins"] = [[] for _ in range(len(f))]
    hits = [[] for _ in range(len(f))]
    idx_ok = np.where(ok_xy)[0]
    for i, p in enumerate(geoms):
        r = bb.iloc[i]
        m = idx_ok[(x[idx_ok] >= r.xmin) & (x[idx_ok] <= r.xmax) & (y[idx_ok] >= r.ymin) & (y[idx_ok] <= r.ymax)]
        if len(m) == 0:
            continue
        ins = contains(p, x[m], y[m])
        for j in m[ins]:
            hits[j].append(i)
    f["hit_rows"] = hits
    f["n_hits"] = f.hit_rows.map(len)
    f["in_pin"] = [b.Pincode.iloc[h[0]] if h else None for h in hits]
    f["in_office"] = [b.Office_Name.iloc[h[0]] if h else None for h in hits]
    f["in_division"] = [b.Division.iloc[h[0]] if h else None for h in hits]
    f["in_circle"] = [b.Circle.iloc[h[0]] if h else None for h in hits]

    stats["fac_valid_coords"] = int(ok_xy.sum())
    stats["fac_inside_any_polygon"] = int((f.n_hits > 0).sum())
    stats["fac_inside_2plus_polygons"] = int((f.n_hits > 1).sum())
    stats["fac_valid_pin"] = int(f.pin.notna().sum())
    cand = f[ok_xy & f.pin.notna() & f.pin.isin(bpins)].copy()
    stats["join_denominator_validpin_validcoord_pin_has_polygon"] = len(cand)
    stats["fac_valid_pin_but_no_polygon"] = int((ok_xy & f.pin.notna() & ~f.pin.isin(bpins)).sum())
    cand["pip_match"] = [p in [b.Pincode.iloc[h] for h in hr] for p, hr in zip(cand.pin, cand.hit_rows)]
    stats["fac_point_in_stated_pin_polygon"] = int(cand.pip_match.sum())

    # distance from point to the stated PIN's polygon(s), only for non-matches
    pin_rows = b.groupby("Pincode").indices
    d = []
    for _, r in cand.iterrows():
        if r.pip_match:
            d.append(0.0)
            continue
        d.append(min(dist_km(geoms[k], r.longitude, r.latitude) for k in pin_rows[r.pin]))
    cand["d_stated_poly_km"] = d
    bins = [-0.01, 0, 1, 2, 5, 10, 25, 50, 100, 250, 500, 5000]
    stats["d_stated_poly_km_bins"] = {str(k): int(v) for k, v in pd.cut(cand.d_stated_poly_km, bins).value_counts(sort=False).items()}
    stats["fac_gt100km_from_stated_pin_polygon"] = int((cand.d_stated_poly_km > FAR_KM).sum())

    # name-level corroboration: facility city vs contained polygon office/division name
    def city_score(r):
        c = norm(r.address_city)
        if not c or r.in_office is None:
            return np.nan
        return max(fuzz.token_set_ratio(c, norm(r.in_office)), fuzz.token_set_ratio(c, norm(r.in_division)))
    cand["city_vs_poly_name"] = cand.apply(city_score, axis=1)
    stats["city_vs_poly_name_ge80_share_of_inside"] = round(float((cand.city_vs_poly_name >= 80).sum() / cand.city_vs_poly_name.notna().sum()), 3)

    # compare with the audit centroid-distance signal if available
    audit = Path("/Users/karthikvattem/projects/datathon/audit/geo/facility_geo.parquet")
    if audit.exists():
        a = pd.read_parquet(audit, columns=["unique_id", "d_pin_km"])
        cc = cand.merge(a, on="unique_id", how="left")
        far_c = cc.d_pin_km > FAR_KM
        stats["audit_centroid_gt100_in_denominator"] = int(far_c.sum())
        stats["audit_centroid_gt100_and_poly_gt100"] = int((far_c & (cc.d_stated_poly_km > FAR_KM)).sum())
        stats["audit_centroid_gt100_but_inside_stated_polygon"] = int((far_c & cc.pip_match).sum())
        stats["audit_centroid_le10_but_outside_poly_gt10"] = int(((cc.d_pin_km <= 10) & (cc.d_stated_poly_km > 10)).sum())
        cand = cc

    cols = ["unique_id", "name", "address_city", "address_stateOrRegion", "pin", "latitude", "longitude",
            "in_pin", "in_office", "in_division", "in_circle", "n_hits", "pip_match", "d_stated_poly_km",
            "city_vs_poly_name"] + (["d_pin_km"] if "d_pin_km" in cand else [])
    cand[cols].to_parquet(out / "facility_pin_polygon_check.parquet", index=False)
    rng = np.random.default_rng(7)
    m = cand[cand.pip_match]
    nm = cand[~cand.pip_match]
    sample = pd.concat([m.iloc[rng.choice(len(m), 12, replace=False)], nm.iloc[rng.choice(len(nm), 8, replace=False)]])
    sample[cols].to_csv(out / "handcheck_sample.csv", index=False)
    b.drop(columns=["geometry"]).assign(bbox=b.bbox.map(json.dumps)).to_csv(out / "boundary_attrs.csv", index=False)
    (out / "stats.json").write_text(json.dumps(stats, indent=1, default=str))
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:5])
