"""Independent rebuild of the inputs behind the "Where care is missing" stories.

Written for the adversarial check; it does not import common.py or any story script.
Different methods from the analyst on purpose, so agreement means something:
- records -> LGD district by geopandas point-in-polygon (analyst: raster cell lookup);
- population per district by a per-polygon geometry mask over the WorldPop rasters (analyst: one
  rasterize of all polygons plus a nearest-district fill of coastal cells, so totals differ slightly);
- evidence flags rebuilt from the source tables with the compare_dataset.py claim filter.

Inputs (read-only): derived/v1/facility_location.parquet, data/raw/facilities.parquet,
kb/taxonomy/out/lexicon_matches.parquet, kb/web_evidence/out/web_service_summary.parquet,
kb/web_evidence/out/site_identity.parquet, kb/opendata/vf_opendata_facts.parquet,
data/external/mohfw_trauma_196/tcf_vf_matches.csv, data/external/laqshya_master/*.parquet,
data/external/worldpop_r2025a/*.tif, data/external/lgd_district_polygons/{LGD_Districts.parquet,
nfhs_lgd_crosswalk.csv}, data/raw/nfhs_5_district_health_indicators.parquet.
Cache: verify/out/*.parquet.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
OUT = ROOT / "viz/geography/verify/out"
OUT.mkdir(parents=True, exist_ok=True)
WP = ROOT / "data/external/worldpop_r2025a"
WP_TOTAL = WP / "ind_pop_2025_CN_1km_R2025A_UA_v1.tif"
LGD = ROOT / "data/external/lgd_district_polygons/LGD_Districts.parquet"
SERVICE = {"trauma": {"trauma_care", "emergency_24x7"}, "dialysis": {"dialysis"},
           "csection": {"emergency_csection"}}


def key(s) -> str:
    """Loose name key: lower case, '&' -> 'and', drop punctuation and the words 'and'/'the'."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("&", " and "))
    return " ".join(w for w in s.split() if w not in ("and", "the"))


# ---------------------------------------------------------------- records
def records() -> pd.DataFrame:
    f = OUT / "records.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import geopandas as gpd
    loc = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet",
                          columns=["unique_id", "loc_lat", "loc_lon", "state_final"])
    raw = pd.read_parquet(ROOT / "data/raw/facilities.parquet", columns=["unique_id", "operatorTypeId"])
    raw = raw.drop_duplicates("unique_id")
    d = loc.merge(raw, on="unique_id", how="left")
    poly = gpd.read_parquet(LGD)[["dtname", "stname", "dist_lgd", "geometry"]]
    poly["geometry"] = poly.geometry.make_valid()
    has = d.loc_lat.notna() & d.loc_lon.notna()
    pts = gpd.GeoDataFrame(d[has][["unique_id"]], geometry=gpd.points_from_xy(d.loc_lon[has], d.loc_lat[has]),
                           crs=4326)
    j = gpd.sjoin(pts, poly.to_crs(4326), how="left", predicate="within").drop_duplicates("unique_id")
    miss = j.dist_lgd.isna()
    # Points just outside the simplified polygons (coast, river): nearest polygon within 5 km.
    near = gpd.sjoin_nearest(pts[miss.values].to_crs(7755), poly.to_crs(7755), how="left",
                             max_distance=5000).drop_duplicates("unique_id")
    j = j.set_index("unique_id")
    nn = near.set_index("unique_id")[["dtname", "stname", "dist_lgd"]]
    j.loc[nn.index, ["dtname", "stname", "dist_lgd"]] = nn.values
    d = d.merge(j[["dtname", "stname", "dist_lgd"]], left_on="unique_id", right_index=True, how="left")
    d = d.merge(evidence(), on="unique_id", how="left")
    for c in [c for c in d.columns if c.endswith(("_claim", "_conf", "_web", "_osm", "_tcf", "_lq"))]:
        d[c] = d[c].fillna(False).astype(bool)
    si = pd.read_parquet(ROOT / "kb/web_evidence/out/site_identity.parquet", columns=["unique_id", "kind", "attributable"])
    d["own_site"] = d.unique_id.isin(set(si[si.attributable & si.kind.isin(["site", "branch"])].unique_id))
    d.to_parquet(f)
    return d


def evidence() -> pd.DataFrame:
    """Per record: <svc>_claim (dataset text), <svc>_web/_osm/_tcf/_lq (other sources), <svc>_conf."""
    m = pd.read_parquet(ROOT / "kb/taxonomy/out/lexicon_matches.parquet")
    keep = (m.nonoffer_cue == "") & (~m.negation_extra) & (m.attribution != "other_facility") \
        & (~m.kind.isin(["staff", "directory"]))
    m = m[keep]
    w = pd.read_parquet(ROOT / "kb/web_evidence/out/web_service_summary.parquet",
                        columns=["unique_id", "service_id", "web_positive"])
    w = w[w.web_positive]
    f = pd.read_parquet(ROOT / "kb/opendata/vf_opendata_facts.parquet", columns=["unique_id", "field", "value"])
    osm = set(f.loc[(f.field == "emergency") & (f.value == "yes"), "unique_id"])
    tcf = set(pd.read_csv(ROOT / "data/external/mohfw_trauma_196/tcf_vf_matches.csv").vf_id.dropna())
    lqm = pd.read_parquet(ROOT / "data/external/laqshya_master/laqshya_vf_matches.parquet")
    lqa = pd.read_parquet(ROOT / "data/external/laqshya_master/laqshya_facilities.parquet")
    lq = set(lqm[lqm.lq_id.isin(lqa.loc[lqa["Maternity OT"].notna(), "lq_id"])].unique_id)
    ids = sorted(set(m.unique_id) | set(w.unique_id) | osm | tcf | lq)
    e = pd.DataFrame({"unique_id": ids})
    for s, sids in SERVICE.items():
        e[f"{s}_claim"] = e.unique_id.isin(set(m.loc[m.service.isin(sids), "unique_id"]))
        e[f"{s}_web"] = e.unique_id.isin(set(w.loc[w.service_id.isin(sids), "unique_id"]))
        e[f"{s}_osm"] = e.unique_id.isin(osm) & (s == "trauma")
        e[f"{s}_tcf"] = e.unique_id.isin(tcf) & (s == "trauma")
        e[f"{s}_lq"] = e.unique_id.isin(lq) & (s == "csection")
        e[f"{s}_conf"] = e[f"{s}_claim"] & e[[f"{s}_web", f"{s}_osm", f"{s}_tcf", f"{s}_lq"]].any(axis=1)
    return e


# ---------------------------------------------------------------- population per LGD district
def wp_arrays():
    import rasterio
    with rasterio.open(WP_TOTAL) as r:
        pop = r.read(1).astype(np.float64)
        tr, nd = r.transform, r.nodata
    valid = (pop != nd) & np.isfinite(pop)
    pop[~valid] = 0
    wra = np.zeros_like(pop)
    for a in range(15, 50, 5):
        with rasterio.open(WP / f"ind_f_{a}_2025_CN_1km_R2025A_UA_v1.tif") as r:
            x = r.read(1).astype(np.float64)
            wra += np.where((x != r.nodata) & np.isfinite(x), x, 0)
    return pop, wra, valid, tr


def district_pop() -> pd.DataFrame:
    """Population and women 15-49 per LGD polygon by per-polygon mask (cell centre inside)."""
    f = OUT / "district_pop.parquet"
    if f.exists():
        return pd.read_parquet(f)
    import geopandas as gpd
    from rasterio import features, windows
    pop, wra, valid, tr = wp_arrays()
    g = gpd.read_parquet(LGD)[["dtname", "stname", "dist_lgd", "geometry"]]
    g["geometry"] = g.geometry.make_valid()
    rows = []
    for r in g.itertuples():
        win = windows.from_bounds(*r.geometry.bounds, transform=tr).round_offsets().round_lengths()
        r0, c0 = max(int(win.row_off), 0), max(int(win.col_off), 0)
        r1, c1 = min(int(win.row_off + win.height) + 1, pop.shape[0]), min(int(win.col_off + win.width) + 1, pop.shape[1])
        wt = windows.transform(windows.Window(c0, r0, c1 - c0, r1 - r0), tr)
        inside = features.geometry_mask([r.geometry], out_shape=(r1 - r0, c1 - c0), transform=wt, invert=True)
        rows.append(dict(dist_lgd=r.dist_lgd, dtname=r.dtname, stname=r.stname,
                         pop=pop[r0:r1, c0:c1][inside].sum(), wra=wra[r0:r1, c0:c1][inside].sum()))
    t = pd.DataFrame(rows)
    t.to_parquet(f)
    return t


# ---------------------------------------------------------------- NFHS link
def nfhs_link() -> pd.DataFrame:
    """LGD polygon -> NFHS-5 (state_ut, district_name) via the crosswalk's nfhs_final name."""
    cw = pd.read_csv(ROOT / "data/external/lgd_district_polygons/nfhs_lgd_crosswalk.csv")
    nf = pd.read_parquet(ROOT / "data/raw/nfhs_5_district_health_indicators.parquet",
                         columns=["state_ut", "district_name"])
    nf["st"] = nf.state_ut.str.strip()
    nf["sk"] = nf.st.map(key).replace({"maharastra": "maharashtra", "nct of delhi": "delhi",
                                       "andaman nicobar islands": "andaman nicobar",
                                       "dadra nagar haveli daman diu": "dadra nagar haveli daman diu"})
    nf["dk"] = nf.district_name.map(key)
    lut = {(a, b): (s, n.strip()) for a, b, s, n in zip(nf.sk, nf.dk, nf.st, nf.district_name)}
    cw["sk"] = cw.stname.map(key)
    hit = [lut.get((a, key(b))) if isinstance(b, str) else None for a, b in zip(cw.sk, cw.nfhs_final)]
    cw["nfhs_state"] = [h[0] if h else None for h in hit]
    cw["nfhs_district"] = [h[1] if h else None for h in hit]
    return cw[["dist_lgd", "stname", "dtname", "nfhs_state", "nfhs_district"]]


def nfhs_num(x):
    s = str(x).strip()
    if s in ("", "None", "nan") or s.startswith("*"):
        return np.nan, "suppressed"
    if s.startswith("("):
        return float(s.strip("()")), "bracket"
    return float(s), "ok"


if __name__ == "__main__":
    d = records()
    t = district_pop()
    print("records", len(d), "with polygon", d.dist_lgd.notna().sum())
    print("population", t["pop"].sum())
