"""Self-check: local point lookups must equal the MAP server's own values.

For a few points, asks the WCS for a tiny bbox (about 3 x 3 cells) around the
point and compares the server cell containing the point with our lookup in
facility_access.parquet / the local clip. Catches half-cell or row-flip errors
in tiff_np. Also reports how well tt_motor > 30 at a facility flags the
geo audit's geo_conflict.

Usage: python -I check_lookup.py RAW_DIR DERIVED_DIR
"""
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import tiff_np  # noqa: E402

BASE = "https://data.malariaatlas.org/geoserver/Accessibility/wcs"
COV = analyze.COV["tt_motor"]
STEP = 1 / 120


def server_value(lat: float, lon: float) -> float:
    url = (f"{BASE}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={COV}&format=image/tiff"
           f"&subset=Lat({lat - 1.5 * STEP:.6f},{lat + 1.5 * STEP:.6f})&subset=Long({lon - 1.5 * STEP:.6f},{lon + 1.5 * STEP:.6f})")
    req = urllib.request.Request(url, headers={"User-Agent": "datathon-research-client"})
    with urllib.request.urlopen(req, timeout=60) as r, tempfile.NamedTemporaryFile(suffix=".tif") as f:
        f.write(r.read())
        f.flush()
        a, (lon0, lat0, dx, dy) = tiff_np.read(f.name)
    return float(a[int((lat0 - lat) // dy), int((lon - lon0) // dx)])


def main(raw: str, derived: str) -> None:
    rasters, geo = analyze.load(Path(raw))
    fa = pd.read_parquet(Path(derived) / "facility_access.parquet")
    pts = fa[fa.tt_motor > 0.5].sample(5, random_state=1)[["name", "latitude", "longitude", "tt_motor"]]
    for _, p in pts.iterrows():
        sv = server_value(p.latitude, p.longitude)
        local = float(analyze.sample(rasters, geo, [p.latitude], [p.longitude]).tt_motor[0])
        print(f"{p['name'][:40]:40s} local={local:.3f} server={sv:.3f} parquet={p.tt_motor:.3f}")
        assert np.isclose(local, sv, atol=1e-3) and np.isclose(local, p.tt_motor, atol=1e-3)
        time.sleep(1.5)
    print("lookup check passed: 5/5 points equal the server value")

    v = fa.dropna(subset=["tt_motor", "geo_conflict"])
    base = v.geo_conflict.mean()
    for t in (10, 30, 60):
        s = v[v.tt_motor > t]
        print(f"tt_motor>{t}: n={len(s)} geo_conflict={int(s.geo_conflict.sum())} ({s.geo_conflict.mean():.2f}) vs base rate {base:.3f} of {len(v)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
