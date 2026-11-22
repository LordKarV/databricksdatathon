"""Own stated-city resolver: LGD district and sub-district names only (no urban bodies, no India Post),
inside the record's state_final, accepted only when the name maps to exactly one LGD district."""
import re
from functools import lru_cache
import numpy as np, pandas as pd, geopandas as gpd
from geo import EXT, L, lgd, pts

ALIAS = {"bangalore": "bengaluru urban", "bengaluru": "bengaluru urban", "gurgaon": "gurugram", "trivandrum": "thiruvananthapuram",
         "calicut": "kozhikode", "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai", "cochin": "ernakulam", "kochi": "ernakulam",
         "baroda": "vadodara", "allahabad": "prayagraj", "mysore": "mysuru", "mangalore": "dakshina kannada", "mangaluru": "dakshina kannada",
         "belgaum": "belagavi", "gulbarga": "kalaburagi", "shimoga": "shivamogga", "bellary": "ballari", "vizag": "visakhapatnam",
         "pondicherry": "puducherry", "poona": "pune", "hubli": "dharwad", "hubballi": "dharwad", "tumkur": "tumakuru", "new delhi": "new delhi"}


def n(s):
    s = re.sub(r"[^a-z ]", " ", str(s).lower().replace("&", " and "))
    s = re.sub(r"\s+", " ", s).strip()
    return {"orissa": "odisha", "the dadra and nagar haveli and daman and diu": "dnhdd", "dadra and nagar haveli and daman and diu": "dnhdd",
            "andaman and nicobar": "andaman and nicobar islands", "nct of delhi": "delhi", "pondicherry": "puducherry"}.get(s, s)


@lru_cache(None)
def table():
    e = EXT / "lgd_archive_parquet"
    d = pd.read_parquet(e / "districts.parquet")
    s = pd.read_parquet(e / "subdistricts.parquet")
    rows = [(n(a), n(b), int(c)) for a, b, c in zip(d.state_name, d.district_name, d.district_code)]
    rows += [(n(a), n(b), int(c)) for a, b, c in zip(s.state_name, s.subdistrict_name, s.district_code)]
    t = pd.DataFrame(rows, columns=["st", "nm", "code"]).drop_duplicates()
    return t.groupby(["st", "nm"]).code.agg(frozenset)


@lru_cache(None)
def city_dist():
    l = L()
    T = table()
    G = lgd().assign(code=lambda g: g.dist_lgd.astype(int)).set_index("code").geometry
    codes = []
    for st, c in zip(l.state_final.map(n), l.address_city.map(n)):
        c = ALIAS.get(c, c)
        k = T.get((st, c))
        if k is None:
            k = T.get((st, c.replace(" city", "")))
        codes.append(k if k is not None and len(k) == 1 and next(iter(k)) in G.index else None)
    out = {}
    for which in ("loc", "raw"):
        g, ok = pts(l[f"{which}_lat"], l[f"{which}_lon"])
        dd = np.full(len(l), np.nan)
        for i, k in enumerate(codes):
            if k is not None and ok[i]:
                dd[i] = G[next(iter(k))].distance(g.iloc[i]) / 1000
        out[which] = dd
    return pd.DataFrame({"unique_id": l.unique_id, "city_code": [next(iter(k)) if k else np.nan for k in codes],
                         "d_loc": out["loc"], "d_raw": out["raw"]})
