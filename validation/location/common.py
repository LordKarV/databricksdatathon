"""Read-only loaders and helpers for the location / geography / outside-source audit.

Nothing here writes outside validation/location/. All inputs are opened read-only.
"""
from functools import lru_cache
from math import sqrt
from pathlib import Path
import re

import numpy as np
import pandas as pd

ROOT = Path("/Users/karthikvattem/projects/datathon")
HERE = ROOT / "validation" / "location"
OUT = HERE / "out"
JUDG = HERE / "judgments"
V1 = ROOT / "derived" / "v1"
GEO = ROOT / "cleaning" / "geo_identity"
EXT = ROOT / "data" / "external"
SEED = 20261121

INDIA_BBOX = (6.0, 37.6, 68.0, 97.6)  # lat_min, lat_max, lon_min, lon_max (same box as s2)


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def result(name, status, metric, threshold, detail, examples=()):
    return dict(name=name, status=status, metric=metric, threshold=threshold, detail=detail,
                examples=[str(x) for x in list(examples)[:5]])


def norm(s):
    if not isinstance(s, str):
        return ""
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_pin(x):
    """Same rule as audit/geo/geo_common.parse_pin: the whole field, spaces and hyphens removed, is [1-9]ddddd."""
    s = re.sub(r"[\s-]", "", str(x or "")) if isinstance(x, str) else ""
    return float(s) if re.fullmatch(r"[1-9]\d{5}", s) else np.nan


def parse_pin_loose(x):
    """Any standalone 6-digit [1-9]ddddd run inside the field."""
    m = re.search(r"(?<!\d)([1-9]\d{5})(?!\d)", x) if isinstance(x, str) else None
    return float(m.group(1)) if m else np.nan


@lru_cache(None)
def raw():
    return pd.read_parquet(ROOT / "data/raw/facilities.parquet")


@lru_cache(None)
def loc():
    return pd.read_parquet(V1 / "facility_location.parquet")


@lru_cache(None)
def pin_gz():
    return pd.read_parquet(V1 / "pin_gazetteer.parquet")


@lru_cache(None)
def place_gz():
    return pd.read_parquet(V1 / "place_gazetteer.parquet")


@lru_cache(None)
def post_dir():
    d = pd.read_parquet(ROOT / "data/raw/india_post_pincode_directory.parquet")
    d = d.assign(lat=pd.to_numeric(d.latitude, errors="coerce"), lon=pd.to_numeric(d.longitude, errors="coerce"))
    return d


@lru_cache(None)
def my_pin_centroids():
    """Independent PIN centroid: median of India Post office points inside the India box, dropping
    offices > 50 km from the first-pass median (no facility data used, so it is not circular)."""
    d = post_dir()
    lo, hi, lo2, hi2 = INDIA_BBOX
    d = d[d.lat.between(lo, hi) & d.lon.between(lo2, hi2)]
    m = d.groupby("pincode")[["lat", "lon"]].median()
    j = d.join(m, on="pincode", rsuffix="_m")
    j = j[hav_km(j.lat, j.lon, j.lat_m, j.lon_m) <= 50]
    g = j.groupby("pincode").agg(lat=("lat", "median"), lon=("lon", "median"), n=("lat", "size"),
                                 district=("district", lambda s: s.mode().iat[0]),
                                 state=("statename", lambda s: s.mode().iat[0]))
    return g


@lru_cache(None)
def lgd_polys():
    import geopandas as gpd
    return gpd.read_parquet(EXT / "lgd_district_polygons/LGD_Districts.parquet")[["dtname", "stname", "dist_lgd", "state_lgd", "geometry"]]


def pip_lgd(lat, lon):
    """Point-in-polygon against LGD district polygons. Returns DataFrame(dtname, stname, dist_lgd) aligned to input."""
    import geopandas as gpd
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    ok = np.isfinite(lat) & np.isfinite(lon)
    pts = gpd.GeoDataFrame({"i": np.arange(len(lat))[ok]}, geometry=gpd.points_from_xy(lon[ok], lat[ok]), crs="EPSG:4326")
    p = lgd_polys().to_crs("EPSG:4326") if lgd_polys().crs else lgd_polys().set_crs("EPSG:4326")
    j = gpd.sjoin(pts, p, how="left", predicate="within").drop_duplicates("i").set_index("i")
    out = pd.DataFrame(index=np.arange(len(lat)), columns=["dtname", "stname", "dist_lgd"])
    out.loc[j.index, ["dtname", "stname", "dist_lgd"]] = j[["dtname", "stname", "dist_lgd"]].values
    return out


@lru_cache(None)
def lgd_pin_districts():
    """PIN -> set of LGD district codes and names (villages + urban bodies via ULB coverage)."""
    v = pd.read_parquet(EXT / "lgd_archive_parquet/pincode_villages.parquet")
    a = v[["pincode", "district_code", "district_name", "state_name"]]
    try:
        u = pd.read_parquet(EXT / "lgd_archive_parquet/pincode_urban.parquet")
        c = pd.read_parquet(EXT / "lgd_archive_parquet/statewise_ulbs_coverage.parquet")
        dc = [x for x in c.columns if "district_code" in x][0]
        dn = [x for x in c.columns if "district_name" in x][0]
        lb = [x for x in c.columns if "local_body_code" in x][0]
        uu = u.merge(c[[lb, dc, dn]].drop_duplicates().rename(columns={lb: "local_body_code", dc: "district_code", dn: "district_name"}),
                     on="local_body_code")
        a = pd.concat([a, uu[["pincode", "district_code", "district_name", "state_name"]]])
    except Exception as e:  # noqa: BLE001 - urban layer optional; recorded
        print("urban LGD layer not joined:", e)
    a = a.drop_duplicates()
    a["pincode"] = a.pincode.astype(int)
    return a


STATE_ALIAS = {"andaman and nicobar": "andaman and nicobar islands",
               "dadra nagar haveli daman and diu": "the dadra and nagar haveli and daman and diu",
               "dadra and nagar haveli and daman and diu": "the dadra and nagar haveli and daman and diu",
               "orissa": "odisha", "pondicherry": "puducherry", "uttaranchal": "uttarakhand",
               "jammu and kashmir": "jammu and kashmir", "nct of delhi": "delhi"}


def nstate(s):
    """Normalise a state name from any of the vocabularies (LGD polygons, India Post, LGD archive)."""
    n = norm(s)
    return STATE_ALIAS.get(n, n)


OFFICE_SUFFIX = re.compile(r"\b(s\.?o|b\.?o|h\.?o|g\.?p\.?o|mdg|nsh|nsd|bo|so|ho|gpo)\b\.?", re.I)


@lru_cache(None)
def my_city_points():
    """Independent city layer from the raw India Post directory only (no repaired PINs, no facility points).
    Key (state_norm, name_norm) -> median lat/lon, p90 spread, kind ('district' first, else 'office')."""
    d = post_dir()
    lo, hi, lo2, hi2 = INDIA_BBOX
    d = d[d.lat.between(lo, hi) & d.lon.between(lo2, hi2)].copy()
    d["st"] = d.statename.map(nstate)
    d["dn"] = d.district.map(norm)
    d["on"] = d.officename.map(lambda s: norm(OFFICE_SUFFIX.sub(" ", str(s))))
    out = []
    for kind, key in (("district", "dn"), ("office", "on")):
        g = d.groupby(["st", key])
        m = g[["lat", "lon"]].median()
        j = d.join(m, on=["st", key], rsuffix="_m")
        j["dd"] = hav_km(j.lat, j.lon, j.lat_m, j.lon_m)
        sp = j.groupby(["st", key]).dd.quantile(0.9)
        t = m.assign(spread=sp, kind=kind).reset_index().rename(columns={key: "name"})
        out.append(t)
    t = pd.concat(out)
    t = t[t.name != ""]
    return t.drop_duplicates(["st", "name"], keep="first").set_index(["st", "name"])


ULB_WORDS = re.compile(r"\b(municipal|corporation|council|committee|nagar|panchayat|parishad|nigam|palika|mahanagar|"
                       r"town|notified|area|cantonment|board|city|greater|brihanmumbai|industrial|township|cmc|tmc|nac)\b")


@lru_cache(None)
def lgd_city_districts():
    """(state_norm, place_norm) -> frozenset of LGD district codes, from LGD district, sub-district and
    urban-local-body names (LGD archive only: independent of India Post and of facility coordinates)."""
    e = EXT / "lgd_archive_parquet"
    rows = []
    d = pd.read_parquet(e / "districts.parquet")
    rows += [(nstate(s), norm(n), c) for s, n, c in zip(d.state_name, d.district_name, d.district_code)]
    s = pd.read_parquet(e / "subdistricts.parquet")
    rows += [(nstate(a), norm(n), c) for a, n, c in zip(s.state_name, s.subdistrict_name, s.district_code)]
    u = pd.read_parquet(e / "statewise_ulbs_coverage.parquet")[["state_name", "local_body_name", "district_code"]].drop_duplicates()
    rows += [(nstate(a), re.sub(r"\s+", " ", ULB_WORDS.sub(" ", norm(n))).strip(), c)
             for a, n, c in zip(u.state_name, u.local_body_name, u.district_code)]
    t = pd.DataFrame(rows, columns=["st", "name", "code"])
    t = t[t.name != ""]
    t["code"] = t.code.astype(int)
    return t.groupby(["st", "name"]).code.agg(frozenset)


def dist_to_districts_km(lat, lon, codes_list):
    """Distance (km) from each point to the nearest polygon among its LGD district codes; 0 inside. NaN if no codes."""
    import geopandas as gpd
    P = lgd_polys()
    P = (P.set_crs("EPSG:4326") if P.crs is None else P.to_crs("EPSG:4326")).to_crs("EPSG:7755")
    geom = dict(zip(P.dist_lgd.astype(int), P.geometry))
    pts = gpd.GeoSeries(gpd.points_from_xy(np.asarray(lon, float), np.asarray(lat, float)), crs="EPSG:4326").to_crs("EPSG:7755")
    out = np.full(len(pts), np.nan)
    for i, (pt, codes) in enumerate(zip(pts, codes_list)):
        if not codes or pt is None or pt.is_empty:
            continue
        gs = [geom[c] for c in codes if c in geom]
        if gs:
            out[i] = min(g.distance(pt) for g in gs) / 1000.0
    return out
