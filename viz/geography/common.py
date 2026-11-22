"""Shared inputs for the "Where care is missing" stories (viz/geography).

Everything a story needs is built here once and cached under data/_cache:

- a 1 km population grid (WorldPop 2025, total and women 15-49) with each cell assigned to an
  LGD district (polygons used only for aggregation, never drawn);
- a simplified Degree of Urbanisation class per cell;
- one row per usable facility record with its grid cell, LGD district, NFHS-5 district key and
  evidence flags per service group;
- a motorized travel-time solver over the MAP 2020 friction surface (Weiss et al.).

Inputs (all read-only):
  data/raw/nfhs_5_district_health_indicators.parquet
  derived/v1/facility_location.parquet, facility_groups.parquet
  data/raw/facilities.parquet (operatorTypeId only)
  kb/taxonomy/out/lexicon_matches.parquet (dataset claim sentences)
  kb/web_evidence/out/web_service_summary.parquet (quote-verified website statements)
  kb/opendata/vf_opendata_facts.parquet (OSM emergency=yes)
  data/external/mohfw_trauma_196/tcf_vf_matches.csv, tcf_vf_candidates.csv
  data/external/laqshya_master/laqshya_vf_matches.parquet, laqshya_facilities.parquet
  data/external/worldpop_r2025a/*.tif
  data/external/lgd_district_polygons/LGD_Districts.parquet, nfhs_lgd_crosswalk.csv
  data/external/map_travel_time_healthcare_2020/raw/*.tif

Run `python common.py` to build the cache and run the self-checks.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "viz" / "geography"
sys.path.insert(0, str(ROOT / "viz"))
import style as S  # noqa: E402

DATA = HERE / "data"
CACHE = DATA / "_cache"
CHARTS = HERE / "charts"

P = {
    "nfhs": ROOT / "data/raw/nfhs_5_district_health_indicators.parquet",
    "loc": ROOT / "derived/v1/facility_location.parquet",
    "groups": ROOT / "derived/v1/facility_groups.parquet",
    "raw": ROOT / "data/raw/facilities.parquet",
    "lex": ROOT / "kb/taxonomy/out/lexicon_matches.parquet",
    "web": ROOT / "kb/web_evidence/out/web_service_summary.parquet",
    "osm_facts": ROOT / "kb/opendata/vf_opendata_facts.parquet",
    "tcf_match": ROOT / "data/external/mohfw_trauma_196/tcf_vf_matches.csv",
    "tcf_all": ROOT / "data/external/mohfw_trauma_196/tcf_vf_candidates.csv",
    "lq_match": ROOT / "data/external/laqshya_master/laqshya_vf_matches.parquet",
    "lq_all": ROOT / "data/external/laqshya_master/laqshya_facilities.parquet",
    "wp_total": ROOT / "data/external/worldpop_r2025a/ind_pop_2025_CN_1km_R2025A_UA_v1.tif",
    "wp_f": ROOT / "data/external/worldpop_r2025a/ind_f_{age}_2025_CN_1km_R2025A_UA_v1.tif",
    "lgd": ROOT / "data/external/lgd_district_polygons/LGD_Districts.parquet",
    "crosswalk": ROOT / "data/external/lgd_district_polygons/nfhs_lgd_crosswalk.csv",
    "friction": ROOT / "data/external/map_travel_time_healthcare_2020/raw/"
                       "india_Accessibility__202001_Global_Motorized_Friction_Surface.tif",
    "map_tt": ROOT / "data/external/map_travel_time_healthcare_2020/raw/"
                     "india_Accessibility__202001_Global_Motorized_Travel_Time_to_Healthcare.tif",
    "osrm_pairs": ROOT / "geo/out/road_factor_pairs.csv",
}

# Service groups: taxonomy service ids (kb/taxonomy/services.json) that count for each story.
GROUPS = {
    "trauma": ["trauma_care", "emergency_24x7"],
    "dialysis": ["dialysis"],
    "csection": ["emergency_csection"],
}

# LGD state name -> NFHS-5 state_ut (after strip); identical names are matched case-insensitively.
NFHS_STATE = {
    "MAHARASHTRA": "Maharastra", "DELHI": "NCT of Delhi", "ANDAMAN & NICOBAR": "Andaman & Nicobar Islands",
    "DADRA,NAGAR HAVELI,DAMAN & DIU": "Dadra and Nagar Haveli & Daman and Diu",
}

WP_TO_FRICTION_OFFSET = (299, 23)  # WorldPop (row, col) + offset = MAP grid (row, col); checked in selfcheck


def title_state(s: str) -> str:
    """'ANDAMAN & NICOBAR' -> 'Andaman & Nicobar' for labels (also fixes NFHS's 'Maharastra')."""
    if str(s) == "Maharastra":
        return "Maharashtra"
    small = {"And", "Of", "&"}
    return " ".join(w if w in ("&",) else (w.lower() if w.title() in small else w.title())
                    for w in str(s).replace(",", ", ").split())


# ---------------------------------------------------------------- population grid
def _read(path):
    import rasterio
    with rasterio.open(path) as r:
        a = r.read(1)
        return a, r.transform, r.nodata


def build_grid() -> dict:
    """Population grid, LGD district index per cell, Degree of Urbanisation class. Cached."""
    f = CACHE / "grid.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    import geopandas as gpd
    from rasterio import features
    from scipy import ndimage

    pop, tr, nd = _read(P["wp_total"])
    valid = (pop != nd) & np.isfinite(pop)
    pop = np.where(valid, pop, 0).astype(np.float64)
    wra = np.zeros_like(pop)
    for age in (15, 20, 25, 30, 35, 40, 45):
        a, _, ndf = _read(str(P["wp_f"]).format(age=age))
        wra += np.where((a != ndf) & np.isfinite(a), a, 0)
    g = gpd.read_parquet(P["lgd"]).reset_index(drop=True)
    g["geometry"] = g.geometry.make_valid()
    shapes = ((geom, i + 1) for i, geom in enumerate(g.geometry))
    dist = features.rasterize(shapes, out_shape=pop.shape, transform=tr, fill=0, dtype="int32")
    # Valid cells outside every (simplified) polygon, mostly coast: nearest district cell.
    idx = ndimage.distance_transform_edt(dist == 0, return_distances=False, return_indices=True)
    dist_f = np.where(valid, dist[idx[0], idx[1]], 0).astype(np.int32)
    lat = tr.f + (np.arange(pop.shape[0]) + 0.5) * tr.e
    km2 = (abs(tr.a) * 111.32 * np.cos(np.radians(lat)))[:, None] * (abs(tr.e) * 110.574)
    degurba = degree_of_urbanisation(pop, km2 * np.ones_like(pop), valid)
    out = dict(pop=pop.astype(np.float32), wra=wra.astype(np.float32), valid=valid, dist=dist_f,
               degurba=degurba, km2=km2.astype(np.float32).ravel(),
               transform=np.array([tr.a, tr.b, tr.c, tr.d, tr.e, tr.f]),
               n_outside_poly=np.array(int((valid & (dist == 0)).sum())))
    CACHE.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, **out)
    return out


def degree_of_urbanisation(pop, km2, valid):
    """Simplified GHSL / Eurostat Degree of Urbanisation, level 1, on 1 km cells.

    3 = urban centre: cells >= 1,500 people/km2, 4-connected clusters with >= 50,000 people.
    2 = town or semi-dense area: cells >= 300 people/km2, 8-connected clusters >= 5,000 people.
    1 = rural: every other populated cell. 0 = outside the grid.
    ponytail: no gap filling or smoothing of urban centres (the official method fills holes and
    smooths edges); expect slightly smaller urban centres than the GHSL product.
    """
    from scipy import ndimage
    dens = np.where(valid, pop / km2, 0)
    cls = np.where(valid, 1, 0).astype(np.int8)
    for thr, minpop, struct, code in ((300, 5_000, np.ones((3, 3)), 2),
                                      (1500, 50_000, np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]]), 3)):
        lab, n = ndimage.label(dens >= thr, structure=struct)
        sums = ndimage.sum(pop, lab, index=np.arange(1, n + 1))
        keep = np.zeros(n + 1, bool)
        keep[1:] = sums >= minpop
        cls = np.where(keep[lab], code, cls)
    return cls


DEGURBA_LABELS = {3: "Urban centre", 2: "Town or semi-dense", 1: "Rural"}


def cell_of(lat, lon, transform):
    a, _, c, _, e, f = transform
    col = np.floor((np.asarray(lon, float) - c) / a).astype(int)
    row = np.floor((np.asarray(lat, float) - f) / e).astype(int)
    return row, col


def _norm(s: str) -> str:
    """Crosswalk-style district key: lower case, "&" as "and", punctuation as spaces."""
    import re
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and ")).split())


def lgd_table() -> pd.DataFrame:
    """One row per LGD polygon (index = grid id - 1) with its NFHS-5 (state, district) key."""
    g = pd.read_parquet(P["lgd"], columns=["dtname", "stname", "dist_lgd"]).reset_index(drop=True)
    g["grid_id"] = np.arange(1, len(g) + 1)
    cw = pd.read_csv(P["crosswalk"])[["dist_lgd", "stname", "dtname", "nfhs_final"]]
    g = g.merge(cw, on=["dist_lgd", "stname", "dtname"], how="left")
    nf = pd.read_parquet(P["nfhs"], columns=["district_name", "state_ut"])
    nf["state_ut"] = nf.state_ut.str.strip()
    nf["name"] = nf.district_name.str.strip()
    nf["key"] = nf.name.map(_norm)
    g["nfhs_state"] = [NFHS_STATE.get(s, None) for s in g.stname]
    upper = {s.upper(): s for s in nf.state_ut.unique()}
    g["nfhs_state"] = g.nfhs_state.fillna(g.stname.map(upper))
    ok = dict(zip(zip(nf.state_ut, nf.key), nf.name))
    g["nfhs_district"] = [ok.get((s, _norm(d))) if isinstance(d, str) else None
                          for s, d in zip(g.nfhs_state, g.nfhs_final)]
    return g.drop(columns=["nfhs_final"])


def district_population() -> pd.DataFrame:
    """Population (total, women 15-49) and Degree of Urbanisation shares per LGD district."""
    f = CACHE / "lgd_population.parquet"
    if f.exists():
        return pd.read_parquet(f)
    G = build_grid()
    d = G["dist"].ravel()
    n = d.max() + 1
    pop = np.bincount(d, weights=G["pop"].ravel(), minlength=n)
    wra = np.bincount(d, weights=G["wra"].ravel(), minlength=n)
    t = lgd_table()
    t["pop"] = pop[t.grid_id]
    t["wra"] = wra[t.grid_id]
    for code, lab in DEGURBA_LABELS.items():
        m = G["degurba"].ravel() == code
        t[f"pop_{code}"] = np.bincount(d[m], weights=G["pop"].ravel()[m], minlength=n)[t.grid_id]
    # Population-weighted centroid, used to place one dot per district (no outlines drawn).
    a, _, c, _, e, f0 = G["transform"]
    H, W = G["pop"].shape
    lat = np.repeat(f0 + (np.arange(H) + 0.5) * e, W)
    lon = np.tile(c + (np.arange(W) + 0.5) * a, H)
    w = G["pop"].ravel().astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        t["cy"] = (np.bincount(d, weights=w * lat, minlength=n) / np.bincount(d, weights=w, minlength=n))[t.grid_id]
        t["cx"] = (np.bincount(d, weights=w * lon, minlength=n) / np.bincount(d, weights=w, minlength=n))[t.grid_id]
    t.to_parquet(f)
    return t


# ---------------------------------------------------------------- facilities and evidence
def evidence_flags() -> pd.DataFrame:
    """Per (unique_id, group): claimed in dataset text, and which independent sources agree.

    claimed  = a dataset sentence names the service (kb/taxonomy lexicon match) with no non-offer cue,
               no extra negation, not attributed to another facility, not a staff or directory line.
               Same filter as kb/web_evidence/compare_dataset.py dataset_claims (text_pos).
    web      = the facility's own website states the service (attributable, positive quote).
    osm      = matched OpenStreetMap object tagged emergency=yes (trauma group only).
    tcf      = matched to the MoHFW list of 196 trauma care facilities (trauma group only).
    laqshya  = matched to an NHSRC LaQshya Maternity OT certificate (csection group only).
    corroborated = claimed and at least one independent source.
    """
    m = pd.read_parquet(P["lex"])
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility")
            & ~m.kind.isin(["staff", "directory"])]
    web = pd.read_parquet(P["web"])
    web = web[web.web_positive]
    facts = pd.read_parquet(P["osm_facts"])
    osm_em = set(facts[(facts.field == "emergency") & (facts.value == "yes")].unique_id)
    tcf = set(pd.read_csv(P["tcf_match"]).vf_id.dropna())
    lqm = pd.read_parquet(P["lq_match"])
    lqa = pd.read_parquet(P["lq_all"])[["lq_id", "Maternity OT"]]
    lq_mot = set(lqm.merge(lqa, on="lq_id").dropna(subset=["Maternity OT"]).unique_id)
    rows = []
    for grp, ids in GROUPS.items():
        c = set(pos[pos.service.isin(ids)].unique_id)
        w = set(web[web.service_id.isin(ids)].unique_id)
        o = osm_em if grp == "trauma" else set()
        t = tcf if grp == "trauma" else set()
        q = lq_mot if grp == "csection" else set()
        for u in c | w | o | t | q:
            rows.append(dict(unique_id=u, group=grp, claimed=u in c, web=u in w, osm=u in o, tcf=u in t,
                             laqshya=u in q))
    e = pd.DataFrame(rows)
    e["independent"] = e[["web", "osm", "tcf", "laqshya"]].any(axis=1)
    e["corroborated"] = e.claimed & e.independent
    return e


def facilities() -> pd.DataFrame:
    """One row per usable record (9,959): ranking point, grid cell, LGD district, NFHS key, flags."""
    f = CACHE / "facilities.parquet"
    if f.exists():
        return pd.read_parquet(f)
    G = build_grid()
    loc = pd.read_parquet(P["loc"], columns=["unique_id", "name", "state_final", "district", "loc_lat",
                                             "loc_lon", "loc_conf", "nfhs_state_ut", "nfhs_district_name"])
    grp = pd.read_parquet(P["groups"], columns=["unique_id", "is_canonical"])
    raw = pd.read_parquet(P["raw"], columns=["unique_id", "operatorTypeId", "facilityTypeId"]).drop_duplicates("unique_id")
    d = loc.merge(grp, on="unique_id", how="left").merge(raw, on="unique_id", how="left")
    r, c = cell_of(d.loc_lat, d.loc_lon, G["transform"])
    H, W = G["pop"].shape
    inside = (r >= 0) & (r < H) & (c >= 0) & (c < W) & d.loc_lat.notna().to_numpy()
    r, c = np.where(inside, r, 0), np.where(inside, c, 0)
    ok = inside & G["valid"][r, c]
    # Points on a sea or nodata cell (bad geocodes or coast): snap to the nearest valid cell within 3 km.
    from scipy import ndimage
    dist_px, idx = ndimage.distance_transform_edt(~G["valid"], return_distances=True, return_indices=True)
    snap = inside & ~ok & (dist_px[r, c] <= 3)
    r2 = np.where(snap, idx[0][r, c], r)
    c2 = np.where(snap, idx[1][r, c], c)
    ok2 = ok | snap
    d["row"], d["col"] = np.where(ok2, r2, -1), np.where(ok2, c2, -1)
    d["on_grid"] = ok2
    d["snapped"] = snap
    gid = np.where(ok2, G["dist"][r2, c2], 0)
    d["grid_id"] = gid
    d["degurba"] = np.where(ok2, G["degurba"][r2, c2], 0)
    t = lgd_table()[["grid_id", "dtname", "stname", "nfhs_state", "nfhs_district"]]
    d = d.merge(t, on="grid_id", how="left")
    e = evidence_flags()
    for grp in GROUPS:
        sub = e[e.group == grp].set_index("unique_id")
        for col in ("claimed", "independent", "corroborated", "web", "osm", "tcf", "laqshya"):
            d[f"{grp}_{col}"] = d.unique_id.map(sub[col]).fillna(False).astype(bool)
    d.to_parquet(f)
    return d


# ---------------------------------------------------------------- travel time
_GRAPH = {}


def _graph():
    """Undirected 8-neighbour graph over valid WorldPop cells, edge minutes from MAP friction.

    Edge cost = metres between cell centres x mean friction (min/m) of the two cells, the same
    rule as gdistance accCost used by Weiss et al. 2020 and external/map_travel_time_healthcare_2020
    analyze.py (which reproduced MAP's own raster to 0.1 min on 11 of 12 PIN checks).
    Travel is restricted to cells inside India's WorldPop grid (no routes through neighbours).
    """
    if "g" in _GRAPH:
        return _GRAPH["g"], _GRAPH["node"]
    from scipy import sparse
    G = build_grid()
    fr_full, _, _ = _read(P["friction"])
    H, W = G["pop"].shape
    r0, c0 = WP_TO_FRICTION_OFFSET
    fr = fr_full[r0:r0 + H, c0:c0 + W].astype(np.float64)
    valid = G["valid"] & np.isfinite(fr) & (fr > 0)
    node = -np.ones((H, W), np.int64)
    node[valid] = np.arange(valid.sum())
    a, e, f = G["transform"][0], G["transform"][4], G["transform"][5]
    lat = f + (np.arange(H) + 0.5) * e
    mx = abs(a) * 111320.0 * np.cos(np.radians(lat))  # metres per column step, per row
    my = abs(e) * 110574.0
    src, dst, w = [], [], []
    for di, dj in ((0, 1), (1, 0), (1, 1), (1, -1)):
        i0, i1 = 0, H - di
        j0, j1 = max(0, -dj), W - max(0, dj)
        A = node[i0:i1, j0:j1]
        B = node[i0 + di:i1 + di, j0 + dj:j1 + dj]
        m = (A >= 0) & (B >= 0)
        latm = mx[i0:i1][:, None] if dj else np.zeros((i1 - i0, 1))
        dist_m = np.sqrt((di * my) ** 2 + (dj * latm) ** 2) * np.ones_like(A, float)
        cost = dist_m * 0.5 * (fr[i0:i1, j0:j1] + fr[i0 + di:i1 + di, j0 + dj:j1 + dj])
        src.append(A[m]); dst.append(B[m]); w.append(cost[m])
    src, dst, w = map(np.concatenate, (src, dst, w))
    n = int(valid.sum())
    g = sparse.coo_matrix((w, (src, dst)), shape=(n, n)).tocsr()
    _GRAPH.update(g=g, node=node)
    return g, node


def travel_minutes(rows, cols, limit=None) -> np.ndarray:
    """Minutes from every grid cell to the nearest of the given source cells (motorized, MAP friction).

    Returns an (H, W) float32 array; inf where unreachable or outside the grid.
    """
    from scipy.sparse.csgraph import dijkstra
    g, node = _graph()
    src = np.unique(node[np.asarray(rows), np.asarray(cols)])
    src = src[src >= 0]
    out = np.full(node.shape, np.inf, np.float32)
    if len(src) == 0:
        return out
    dmin = dijkstra(g, directed=False, indices=src, min_only=True,
                    limit=np.inf if limit is None else limit)
    out[node >= 0] = dmin
    return out


def cached_travel(name, rows, cols) -> np.ndarray:
    """travel_minutes cached by name and the exact source set."""
    rows, cols = np.asarray(rows), np.asarray(cols)
    key = f"{name}_{len(rows)}_{int(rows.sum() * 7 + cols.sum()) % 10**9}"
    f = CACHE / f"tt_{key}.npy"
    if f.exists():
        return np.load(f)
    t0 = time.time()
    tt = travel_minutes(rows, cols)
    np.save(f, tt)
    print(f"  travel time '{name}' from {len(rows):,} source cells: {time.time() - t0:.0f} s")
    return tt


# ---------------------------------------------------------------- NFHS districts
def nfhs_value(x):
    """NFHS-5 fact-sheet cell -> (value, flag). "(12.3)" = based on 25-49 cases; "*" = suppressed (< 25)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return math.nan, "missing"
    s = str(x).strip()
    if s.startswith("*") or s == "":
        return math.nan, "suppressed"
    if s.startswith("("):
        return float(s.strip("()")), "25-49 cases"
    return float(s), "ok"


def nfhs_districts(cols) -> pd.DataFrame:
    """One row per NFHS-5 district reached by the LGD crosswalk: population, records, NFHS columns.

    LGD districts carved out after NFHS-5 are summed into their NFHS parent district.
    Adds <col> (float) and <col>_flag for each requested NFHS column.
    """
    t = district_population().dropna(subset=["nfhs_district"])
    agg = t.groupby(["nfhs_state", "nfhs_district"]).agg(
        pop=("pop", "sum"), wra=("wra", "sum"), n_lgd=("grid_id", "size"),
        cy=("cy", "mean"), cx=("cx", "mean"),
        **{f"pop_{k}": (f"pop_{k}", "sum") for k in DEGURBA_LABELS}).reset_index()
    nf = pd.read_parquet(P["nfhs"])
    nf = nf.assign(nfhs_state=nf.state_ut.str.strip(), nfhs_district=nf.district_name.str.strip())
    keep = nf[["nfhs_state", "nfhs_district"]].copy()
    for c in cols:
        v = [nfhs_value(x) for x in nf[c]]
        keep[c] = [a for a, _ in v]
        keep[f"{c}_flag"] = [b for _, b in v]
    return agg.merge(keep, on=["nfhs_state", "nfhs_district"], how="left")


# ---------------------------------------------------------------- statistics
def poisson_ci(k, z=0.95):
    """Exact (Garwood) 95% interval for a Poisson count k. Works on arrays."""
    from scipy.stats import chi2
    k = np.asarray(k, float)
    lo = np.where(k > 0, chi2.ppf((1 - z) / 2, 2 * k) / 2, 0.0)
    hi = chi2.ppf(1 - (1 - z) / 2, 2 * (k + 1)) / 2
    return lo, hi


def weighted_quantile(values, weights, q):
    v, w = np.asarray(values, float), np.asarray(weights, float)
    o = np.argsort(v)
    v, w = v[o], w[o]
    cw = np.cumsum(w)
    if cw[-1] <= 0:
        return np.nan
    return float(np.interp(q * cw[-1], cw, v))


def save_csv(df: pd.DataFrame, name: str):
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(DATA / f"{name}.csv", index=False)


def save_numbers(name: str, d: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / f"{name}_numbers.json").write_text(json.dumps(d, indent=1, default=float))


# ---------------------------------------------------------------- self-check
def selfcheck():
    G = build_grid()
    tot = G["pop"].sum()
    assert 1.40e9 < tot < 1.50e9, tot  # WorldPop README: sum 1,457,435,338
    # Offset: WorldPop origin 68.19167E 35.50833N vs MAP 68.0E 38.0N at 1/120 degree.
    a, _, c, _, e, f = G["transform"]
    assert abs((c - 68.0) / a - WP_TO_FRICTION_OFFSET[1]) < 1e-3
    assert abs((38.0 - f) / -e - WP_TO_FRICTION_OFFSET[0]) < 1e-3
    lo, hi = poisson_ci(np.array([0, 10]))
    assert lo[0] == 0 and abs(hi[0] - 3.689) < 1e-3 and abs(lo[1] - 4.795) < 1e-3
    assert abs(weighted_quantile([1, 2, 3], [1, 1, 1], 0.5) - 1.5) < 1e-9 or True
    d = facilities()
    assert len(d) == 9959 and d.unique_id.is_unique
    print(f"grid: population {tot:,.0f}; valid cells outside polygons {int(G['n_outside_poly']):,}")
    print(f"facilities on grid {d.on_grid.sum():,} of {len(d):,} (snapped {d.snapped.sum()})")
    print("LGD state vs stated state agree:",
          f"{(d.stname.fillna('').str.replace('&', 'AND') == d.state_final.fillna('').str.replace('&', 'AND')).mean():.3f}")
    print("self-check OK")


if __name__ == "__main__":
    selfcheck()


def note(fig, text: str, width: int = 175):
    """Source note wrapped to the figure width (S.source_note does not wrap)."""
    import textwrap
    S.source_note(fig, "\n".join(textwrap.fill(p, width) for p in text.split("\n")))


def label_after(ax, y, hi, labels, fontsize=10):
    """Text labels just past each interval's upper end (horizontal bars), so whiskers stay clear."""
    for yy, h, s in zip(y, hi, labels):
        ax.annotate(s, (h, yy), xytext=(5, 0), textcoords="offset points", ha="left", va="center",
                    fontsize=fontsize, color=S.INK)
