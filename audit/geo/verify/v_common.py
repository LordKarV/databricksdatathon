"""Independent helpers for verifying the geo audit (not imported from audit/geo)."""
import re

import numpy as np
import pandas as pd

ROOT = "/Users/karthikvattem/projects/datathon"
VER = ROOT + "/audit/geo/verify"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BOX = (6.0, 37.6, 68.0, 97.6)


def hav(lat1, lon1, lat2, lon2):
    r = np.radians
    a = np.sin(r(lat2 - lat1) / 2) ** 2 + np.cos(r(lat1)) * np.cos(r(lat2)) * np.sin(r(lon2 - lon1) / 2) ** 2
    return 12742.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def facilities():
    f = pd.read_parquet(ROOT + "/data/raw/facilities.parquet")
    ok = f.unique_id.fillna("").str.match(UUID) & f.source.eq("kie")
    return f[ok].reset_index(drop=True)


def pin_of(z):
    if z is None or (isinstance(z, float) and np.isnan(z)):
        return None
    s = re.sub(r"[ \-]", "", str(z))
    return int(s) if re.fullmatch(r"[1-9][0-9]{5}", s) else None


def directory():
    p = pd.read_parquet(ROOT + "/data/raw/india_post_pincode_directory.parquet")
    p["la"] = pd.to_numeric(p.latitude, errors="coerce")
    p["lo"] = pd.to_numeric(p.longitude, errors="coerce")
    return p


def inbox(la, lo):
    return (la >= BOX[0]) & (la <= BOX[1]) & (lo >= BOX[2]) & (lo <= BOX[3])


def nn(qlat, qlon, plat, plon, chunk=300):
    """Nearest point index by exact haversine (brute force, chunked)."""
    out = np.empty(len(qlat), dtype=int)
    for i in range(0, len(qlat), chunk):
        d = hav(qlat[i:i + chunk, None], qlon[i:i + chunk, None], plat[None, :], plon[None, :])
        out[i:i + chunk] = d.argmin(axis=1)
    return out
