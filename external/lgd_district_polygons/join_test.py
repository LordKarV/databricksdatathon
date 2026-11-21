"""Join test for LGD district polygons.

Usage: python -I join_test.py <LGD_Districts.parquet> <out_dir>
Point-in-polygon is done in numpy (no shapely in the venv): WKB is parsed by hand and rings are
tested with even-odd ray casting, so holes are handled. ponytail: O(points x candidate rings) after a
bbox prefilter, fine for ~10k facilities and ~165k post offices; use DuckDB spatial or Sedona at scale.
Writes facility_lgd_district.parquet, pin_lgd_district.parquet, nfhs_lgd_crosswalk.csv, stats.json.
"""
import json
import re
import struct
import sys

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

RAW = "/Users/karthikvattem/projects/datathon/data/raw"
DIST_NFHS = "/Users/karthikvattem/projects/datathon/audit/geo/district_nfhs_map.csv"
AUDIT_DIST = "/Users/karthikvattem/projects/datathon/audit/geo/facility_district.parquet"
SAME_DISTRICT_SCORE = 85  # token_sort_ratio threshold for "same district name"


def norm(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower().replace("&", " and ")
    s = re.sub(r"\b(district|dist)\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def parse_wkb(b):
    """Return a list of rings (Nx2 arrays) for a WKB Polygon or MultiPolygon."""
    rings, off = [], 0

    def geom(off):
        bo = "<" if b[off] == 1 else ">"
        gtype = struct.unpack_from(bo + "I", b, off + 1)[0] % 1000
        off += 5
        if gtype == 3:
            (nr,) = struct.unpack_from(bo + "I", b, off); off += 4
            for _ in range(nr):
                (npt,) = struct.unpack_from(bo + "I", b, off); off += 4
                rings.append(np.frombuffer(b, dtype=bo + "f8", count=2 * npt, offset=off).reshape(-1, 2))
                off += 16 * npt
        elif gtype == 6:
            (ng,) = struct.unpack_from(bo + "I", b, off); off += 4
            for _ in range(ng):
                off = geom(off)
        else:
            raise ValueError(f"unexpected WKB type {gtype}")
        return off

    geom(off)
    return rings


def points_in_rings(px, py, rings):
    inside = np.zeros(len(px), dtype=bool)
    for r in rings:
        x1, y1 = r[:-1, 0], r[:-1, 1]
        x2, y2 = r[1:, 0], r[1:, 1]
        for i in range(0, len(px), 2000):
            X, Y = px[i:i + 2000, None], py[i:i + 2000, None]
            cond = (y1 > Y) != (y2 > Y)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (x2 - x1) * (Y - y1) / (y2 - y1) + x1
            inside[i:i + 2000] ^= (np.sum(cond & (X < xint), axis=1) % 2).astype(bool)
    return inside


def assign(lat, lon, poly):
    """Index into poly for each point, -1 if outside every polygon (or multiple: first wins, counted)."""
    out = np.full(len(lat), -1)
    hits = np.zeros(len(lat), dtype=int)
    ok = ~(np.isnan(lat) | np.isnan(lon))
    for k, row in enumerate(poly.itertuples()):
        bb = row.bbox
        cand = np.where(ok & (lon >= bb["xmin"]) & (lon <= bb["xmax"]) & (lat >= bb["ymin"]) & (lat <= bb["ymax"]))[0]
        if len(cand) == 0:
            continue
        ins = cand[points_in_rings(lon[cand], lat[cand], row.rings)]
        hits[ins] += 1
        out[ins[out[ins] == -1]] = k
    return out, hits


def snap_outside(lat, lon, k, poly, max_deg=0.03):
    """Coastal points fall outside simplified polygons: give them the district of the nearest vertex
    within max_deg (about 3 km). Returns new index array and the count snapped."""
    k = k.copy()
    todo = np.where((k < 0) & (lat > 6) & (lat < 38) & (lon > 68) & (lon < 98))[0]
    for i in todo:
        best, bestd = -1, max_deg
        for j, row in enumerate(poly.itertuples()):
            bb = row.bbox
            if not (bb["xmin"] - max_deg <= lon[i] <= bb["xmax"] + max_deg and bb["ymin"] - max_deg <= lat[i] <= bb["ymax"] + max_deg):
                continue
            d = min(np.hypot(r[:, 0] - lon[i], r[:, 1] - lat[i]).min() for r in row.rings)
            if d < bestd:
                best, bestd = j, d
        k[i] = best
    return k, int((k[todo] >= 0).sum())


def same_name(a, b):
    return fuzz.token_sort_ratio(norm(a), norm(b)) >= SAME_DISTRICT_SCORE or (norm(a) and norm(a) in norm(b)) or (norm(b) and norm(b) in norm(a))


def main(poly_path, out_dir):
    poly = pd.read_parquet(poly_path)
    poly["rings"] = [parse_wkb(bytes(g)) for g in poly.geometry]
    stats = {"districts": len(poly), "states": int(poly.stname.nunique()),
             "dist_lgd_unique": int(poly.dist_lgd.nunique()),
             "dist_lgd_dupes": poly.dist_lgd[poly.dist_lgd.duplicated()].tolist(),
             "year_stat": poly.year_stat.value_counts().to_dict(),
             "remarks_nonblank": int((poly.remarks.str.strip() != "").sum()),
             "rings_total": int(sum(len(r) for r in poly.rings)),
             "vertices_total": int(sum(sum(len(x) for x in r) for r in poly.rings))}

    # Facilities
    fac = pd.read_parquet(f"{RAW}/facilities.parquet",
                          columns=["unique_id", "name", "latitude", "longitude", "address_city",
                                   "address_stateOrRegion", "address_zipOrPostcode"])
    lat, lon = fac.latitude.to_numpy(float), fac.longitude.to_numpy(float)
    k, hits = assign(lat, lon, poly)
    k, fac_snapped = snap_outside(lat, lon, k, poly)
    fac["lgd_dtname"] = np.where(k >= 0, poly.dtname.to_numpy()[k], None)
    fac["lgd_stname"] = np.where(k >= 0, poly.stname.to_numpy()[k], None)
    fac["dist_lgd"] = np.where(k >= 0, poly.dist_lgd.to_numpy()[k], -1)
    fac["poly_hits"] = hits
    has_xy = ~(np.isnan(lat) | np.isnan(lon))
    aud = pd.read_parquet(AUDIT_DIST)
    # 11 unique_ids repeat in the raw file; keep one audit row per id so the merge keeps 10,088 rows
    fac = fac.merge(aud[["unique_id", "district", "dstate", "district_src"]].drop_duplicates("unique_id"), on="unique_id", how="left")
    both = fac[(fac.dist_lgd >= 0) & fac.district.notna()]
    agree = both.apply(lambda r: bool(same_name(r.lgd_dtname, r.district)), axis=1)
    fac["agrees_pin_district"] = None
    fac.loc[both.index, "agrees_pin_district"] = agree
    stats["facilities"] = {
        "rows": len(fac), "with_coords": int(has_xy.sum()),
        "inside_a_polygon": int((k >= 0).sum()), "outside_all_polygons": int((has_xy & (k < 0)).sum()),
        "in_two_or_more_polygons": int((hits > 1).sum()), "snapped_coastal_within_3km": fac_snapped,
        "unique_lgd_districts_hit": int(fac.loc[k >= 0, "dist_lgd"].nunique()),
        "compared_with_pin_district": len(both), "name_agrees_with_pin_district": int(agree.sum()),
        "agree_rate_by_district_src": both.assign(a=agree).groupby("district_src").a.agg(["size", "mean"]).round(4).to_dict("index"),
    }
    fac.to_parquet(f"{out_dir}/facility_lgd_district.parquet", index=False)

    # India Post offices: tests the polygons and the name crosswalk on 165k known-district points
    pin = pd.read_parquet(f"{RAW}/india_post_pincode_directory.parquet", columns=["pincode", "officename", "district", "statename", "latitude", "longitude"])
    plat = pd.to_numeric(pin.latitude, errors="coerce").to_numpy(float, copy=True)
    plon = pd.to_numeric(pin.longitude, errors="coerce").to_numpy(float, copy=True)
    bad = (plat < 6) | (plat > 38) | (plon < 68) | (plon > 98)
    plat[bad], plon[bad] = np.nan, np.nan
    pk, _ = assign(plat, plon, poly)
    pin["lgd_dtname"] = np.where(pk >= 0, poly.dtname.to_numpy()[pk], None)
    pin["dist_lgd"] = np.where(pk >= 0, poly.dist_lgd.to_numpy()[pk], -1)
    pin.to_parquet(f"{out_dir}/pin_lgd_district.parquet", index=False)
    pb = pin[pin.dist_lgd >= 0]
    pagree = np.array([bool(same_name(a, b)) for a, b in zip(pb.lgd_dtname, pb.district)])
    stats["post_offices"] = {"rows": len(pin), "valid_coords_in_india_bbox": int((~np.isnan(plat)).sum()),
                             "inside_a_polygon": int((pk >= 0).sum()), "name_agrees": int(pagree.sum()),
                             "lgd_districts_with_any_post_office": int(pb.dist_lgd.nunique())}

    # NFHS crosswalk by name within state
    nf = pd.read_parquet(f"{RAW}/nfhs_5_district_health_indicators.parquet", columns=["district_name", "state_ut"])
    rows = []
    st_choices = {norm(s): s for s in nf.state_ut.unique()}
    for r in poly.itertuples():
        sm = process.extractOne(norm(r.stname), list(st_choices), scorer=fuzz.token_sort_ratio)
        cands = nf[nf.state_ut == st_choices[sm[0]]]
        m = process.extractOne(norm(r.dtname), [norm(x) for x in cands.district_name], scorer=fuzz.token_sort_ratio)
        rows.append({"dist_lgd": r.dist_lgd, "dtname": r.dtname, "stname": r.stname,
                     "nfhs_district": cands.district_name.iloc[m[2]] if m else None, "score": m[1] if m else 0})
    cw = pd.DataFrame(rows)
    # New districts (post NFHS-5) have no NFHS name: fall back to the NFHS district that most of the
    # post offices inside the polygon map to, via the geo audit's directory-district -> NFHS table.
    dmap = pd.read_csv(DIST_NFHS)
    dmap = dict(zip(dmap.district.map(norm) + "|" + dmap.state.map(norm), dmap.final_dn))
    pb2 = pb.assign(nf=[dmap.get(norm(d) + "|" + norm(s)) for d, s in zip(pb.district, pb.statename)]).dropna(subset=["nf"])
    maj = pb2.groupby("dist_lgd").nf.agg(lambda x: x.value_counts().index[0])
    share = pb2.groupby("dist_lgd").nf.agg(lambda x: round(x.value_counts(normalize=True).iloc[0], 3))
    cw["nfhs_by_post_offices"] = cw.dist_lgd.map(maj)
    cw["po_majority_share"] = cw.dist_lgd.map(share)
    # Name wins at >= 90; at 80-89 only when the post offices agree (catches Korea -> Korba).
    by_name = (cw.score >= 90) | ((cw.score >= 80) & (cw.nfhs_district.map(norm) == cw.nfhs_by_post_offices))
    cw["nfhs_final"] = np.where(by_name, cw.nfhs_district.map(norm), cw.nfhs_by_post_offices)
    cw["nfhs_how"] = np.where(by_name, "name", np.where(cw.nfhs_by_post_offices.notna(), "post_office_majority", "none"))
    cw.to_csv(f"{out_dir}/nfhs_lgd_crosswalk.csv", index=False)
    stats["nfhs_crosswalk"] = {"lgd_districts": len(cw), "score_ge_90": int((cw.score >= 90).sum()),
                               "score_80_89": int(((cw.score >= 80) & (cw.score < 90)).sum()),
                               "score_lt_80": int((cw.score < 80).sum()),
                               "nfhs_districts_hit_ge_90": int(cw[cw.score >= 90].nfhs_district.nunique()),
                               "nfhs_total": len(nf),
                               "name_vs_post_office_agree_when_both": int((cw[cw.score >= 90].nfhs_district.map(norm) == cw[cw.score >= 90].nfhs_by_post_offices).sum()),
                               "final_how": cw.nfhs_how.value_counts().to_dict(),
                               "nfhs_districts_covered_final": int(cw.nfhs_final.nunique())}
    json.dump(stats, open(f"{out_dir}/stats.json", "w"), indent=1, default=str)
    print(json.dumps(stats, indent=1, default=str))


if __name__ == "__main__":
    # self-check of ray casting with a hole: unit square minus inner square
    sq = [np.array([[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], float), np.array([[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]], float)]
    assert points_in_rings(np.array([0.5, 2.0, 5.0]), np.array([0.5, 2.0, 2.0]), sq).tolist() == [True, False, False]
    main(sys.argv[1], sys.argv[2])
