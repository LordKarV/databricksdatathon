"""Independent geometry layer for the verification (own code; does not import the auditor's modules).
Projected CRS EPSG:7755 (India LCC, metres). Results cached to verify/out/*.parquet."""
from functools import lru_cache
from pathlib import Path
import numpy as np, pandas as pd, geopandas as gpd

ROOT = Path("/Users/karthikvattem/projects/datathon")
V1, EXT = ROOT / "derived/v1", ROOT / "data/external"
OUT = Path(__file__).parent / "out"
PRJ = "EPSG:7755"


def hav(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    lat1, lon1, lat2, lon2 = (np.asarray(x, float) * p for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


@lru_cache(None)
def L():
    return pd.read_parquet(V1 / "facility_location.parquet")


@lru_cache(None)
def GZ():
    return pd.read_parquet(V1 / "pin_gazetteer.parquet")


@lru_cache(None)
def lgd():
    g = gpd.read_parquet(EXT / "lgd_district_polygons/LGD_Districts.parquet")[["dtname", "stname", "dist_lgd", "geometry"]]
    return g.set_crs("EPSG:4326", allow_override=True).to_crs(PRJ)


@lru_cache(None)
def pinpoly():
    g = gpd.read_parquet(EXT / "pincode_boundaries/Datagov_Pincode_Boundaries.parquet")[["Pincode", "Circle", "geometry"]]
    g = g.set_crs("EPSG:4326", allow_override=True).to_crs(PRJ)
    g["pin"] = g.Pincode.astype(int)
    return g.set_index("pin")


def pts(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    return gpd.GeoSeries(gpd.points_from_xy(np.nan_to_num(lon), np.nan_to_num(lat)), crs="EPSG:4326").to_crs(PRJ), np.isfinite(lat) & np.isfinite(lon)


def in_lgd(lat, lon):
    """LGD district containing each point; for points in no polygon, nearest district and distance km."""
    g, ok = pts(lat, lon)
    df = gpd.GeoDataFrame({"i": np.arange(len(g))}, geometry=g.values, crs=PRJ)[ok]
    j = gpd.sjoin_nearest(df, lgd(), how="left", distance_col="dm").sort_values("dm").drop_duplicates("i").set_index("i")
    out = pd.DataFrame(index=np.arange(len(g)))
    out["dtname"], out["stname"], out["dist_lgd"] = j.dtname, j.stname, j.dist_lgd
    out["lgd_km"] = j.dm / 1000
    return out


def to_own_pin_poly_km(lat, lon, pins):
    g, ok = pts(lat, lon)
    P = pinpoly()
    pins = pd.Series(pins).astype("Int64")
    has = ok & pins.isin(P.index).fillna(False).values
    out = np.full(len(g), np.nan)
    idx = np.where(has)[0]
    out[idx] = g.iloc[idx].reset_index(drop=True).distance(gpd.GeoSeries(P.geometry.reindex(pins.iloc[idx].astype(int)).values, crs=PRJ)).values / 1000
    return out


def cached(name, fn):
    p = OUT / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    d = fn()
    d.to_parquet(p)
    return d


def fac_geo():
    def build():
        l = L()
        c, r = in_lgd(l.loc_lat, l.loc_lon), in_lgd(l.raw_lat, l.raw_lon)
        d = pd.DataFrame({"unique_id": l.unique_id})
        for k, t in (("c", c), ("r", r)):
            for col in t:
                d[f"{k}_{col}"] = t[col].values
        d["c_pinpoly_km"] = to_own_pin_poly_km(l.loc_lat, l.loc_lon, l.pin)
        d["r_pinpoly_km"] = to_own_pin_poly_km(l.raw_lat, l.raw_lon, l.pin)
        return d
    return cached("fac_geo", build)


def pin_geo():
    """Facility PINs: gazetteer point vs own polygon; LGD district of gazetteer point vs LGD district of polygon interior point."""
    def build():
        fp = sorted(set(L().pin.dropna().astype(int)))
        g = GZ().set_index("pin").reindex(fp).reset_index()
        P = pinpoly()
        g["gz_pinpoly_km"] = to_own_pin_poly_km(g.lat, g.lon, g.pin)
        inpoly = g.pin.isin(P.index)
        rp = gpd.GeoSeries(P.geometry.reindex(g.pin[inpoly]).representative_point().values, crs=PRJ).to_crs("EPSG:4326")
        g.loc[inpoly, "poly_lat"], g.loc[inpoly, "poly_lon"] = rp.y.values, rp.x.values
        a, b = in_lgd(g.lat, g.lon), in_lgd(g.poly_lat, g.poly_lon)
        g["gz_dist"], g["gz_st"], g["poly_dist"], g["poly_st"] = a.dtname.values, a.stname.values, b.dtname.values, b.stname.values
        g["gz_to_polyrep_km"] = hav(g.lat, g.lon, g.poly_lat, g.poly_lon)
        return g.drop(columns=["districts"])
    return cached("pin_geo", build)


if __name__ == "__main__":
    import time
    t = time.time(); f = fac_geo(); print(f.describe().T, time.time() - t)
    t = time.time(); p = pin_geo(); print(p.describe().T, time.time() - t)
