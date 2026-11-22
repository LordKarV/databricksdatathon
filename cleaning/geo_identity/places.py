"""Place-name layers built only from the India Post directory (never from facility coordinates, so
they can be used to check facility coordinates without circularity).

district layer: (state, normalised district name) -> median of the district's repaired PIN points
office layer:   (state, office base name, 'Navrangpura S.O' -> 'navrangpura') -> median of its PIN points
Each entry carries spread_km (p90 distance of its points from the median) and n_points.
"""
import numpy as np
import pandas as pd

from common import OUT, ROOT, hav_km, norm
from geo_common import CITY_ALIAS, PIN_DIR, office_base

GOOD_SRC = ["pin_median", "facility_consensus", "district_median"]


def _agg(df: pd.DataFrame, keys: list) -> pd.DataFrame:
    med = df.groupby(keys)[["lat", "lon"]].median()
    j = df.join(med.set_axis(["mla", "mlo"], axis=1), on=keys)
    j["d"] = hav_km(j.lat, j.lon, j.mla, j.mlo)
    out = med.assign(spread_km=j.groupby(keys).d.quantile(0.9).round(1), n_points=df.groupby(keys).size())
    return out.reset_index()


def build_layers() -> dict:
    gz = pd.read_parquet(OUT / "pin_gazetteer.parquet")
    gz = gz[gz.src.isin(GOOD_SRC)].dropna(subset=["lat", "state"])
    d = gz.assign(name=gz.district.map(norm))
    p = pd.read_parquet(PIN_DIR)[["pincode", "officename"]]
    o = p.merge(gz[["pin", "state", "lat", "lon"]], left_on="pincode", right_on="pin")
    o["name"] = o.officename.map(office_base)
    o = o.drop_duplicates(["name", "pin"])
    return {"district": _agg(d, ["state", "name"]), "office": _agg(o, ["state", "name"])}


def city_point(name, state, layers: dict, max_office_spread: float = 30.0):
    """Unambiguous point for a typed or stated place name inside one state.
    Returns (lat, lon, kind, spread_km) or None. Office names that are spread over more than
    max_office_spread km (common village names) are refused rather than guessed."""
    n = norm(name)
    n = CITY_ALIAS.get(n, n)
    if not n or not isinstance(state, str):
        return None
    for kind in ("district", "office"):
        t = layers[kind]
        hit = t[(t.state == state) & (t.name.isin({n, n.replace(" district", "")}))]
        if len(hit) == 1:
            r = hit.iloc[0]
            if kind == "office" and r.spread_km > max_office_spread:
                return None
            return float(r.lat), float(r.lon), kind, float(r.spread_km)
    return None


if __name__ == "__main__":
    L = build_layers()
    kai = city_point("Kaithal", "HARYANA", L)
    assert kai and kai[2] == "district" and abs(kai[0] - 29.8) < 0.3, kai
    assert city_point("Punalur", "KERALA", L) is not None
    assert city_point("Nowhere Town", "KERALA", L) is None
    print("ok", {k: len(v) for k, v in L.items()}, np.round(kai[:2], 3))
