"""Polite one-off pull of the e-RaktKosh blood centre directory.

Usage: python -I fetch.py <out_dir> <pincode_parquet>

Steps (all GET, sequential, >= 1.1 s apart):
1. State mode (legacy BLDAHIMS endpoint) for state codes 1..38: every blood
   bank (BB) and blood storage unit (BSU) with name, address, category, type,
   hospitalCode, distId, stateId.
2. District list per state: distId -> district name.
3. Coordinates: the portal's /bloodbank/nearest endpoint returns lat/lon. We
   query it on a 1-degree grid (radius 100 km) restricted to grid points near
   an India Post office, then keep the first lat/lon seen per hospitalCode.

Phone numbers and emails are dropped before anything is written: many are
personal mobiles of staff.
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://eraktkosh.mohfw.gov.in"
STATE_URL = BASE + "/BLDAHIMS/bloodbank/nearbyBB.cnt?hmode=GETNEARBYBLOODBANK&stateCode={s}&districtCode=-1&lang=0"
DIST_URL = BASE + "/BLDAHIMS/bloodbank/nearbyBB.cnt?hmode=GETDISTRICTLIST&selectedStateCode={s}"
NEAR_URL = BASE + "/eraktkoshPortal/eraktkosh/bloodbank/nearest?latitude={lat}&longitude={lon}&radius=100000"
UA = "Mozilla/5.0 (research datathon; one-off directory pull)"
STATE_CODES = range(1, 39)  # Census 2011 / LGD state codes; Goa = 30
PAUSE_S = 1.1
GRID_STEP = 1.0  # degrees; radius 100 km covers the ~78 km half-diagonal
LINK_RE = re.compile(r"distId=(\d+)&stateId=(\d+)&hospitalCode=(\d+)")
CAMP_RE = re.compile(r"hospitalCode=(\d+)")


def get_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = r.read()
            time.sleep(PAUSE_S)
            return json.loads(body.decode("utf-8", errors="replace"))
        except Exception as e:  # network or JSON error: back off and retry
            print(f"  retry {attempt + 1} {url}: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    print(f"  FAILED {url}", file=sys.stderr)
    return None


def parse_state_row(row, state_code):
    links = row[7] if len(row) > 7 else ""
    m = LINK_RE.search(links)
    hc = m.group(3) if m else (CAMP_RE.search(links).group(1) if CAMP_RE.search(links) else None)
    return {
        "sno": row[0], "name": row[1], "address": row[2], "category": row[5],
        "type": row[8] if len(row) > 8 else None,
        "hospital_code": int(hc) if hc else None,
        "dist_id": int(m.group(1)) if m else None,
        "state_id": int(m.group(2)) if m else state_code,
        "query_state_code": state_code,
    }


def grid_points(pin_parquet):
    pins = pd.read_parquet(pin_parquet, columns=["latitude", "longitude"])
    lat = pd.to_numeric(pins.latitude, errors="coerce")
    lon = pd.to_numeric(pins.longitude, errors="coerce")
    ok = lat.between(6, 37.5) & lon.between(68, 98)
    cells = set(zip((lat[ok] / GRID_STEP).round().astype(int), (lon[ok] / GRID_STEP).round().astype(int)))
    return sorted((a * GRID_STEP, b * GRID_STEP) for a, b in cells)


def main(out_dir, pin_parquet):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, dists = [], []
    for s in STATE_CODES:
        d = get_json(STATE_URL.format(s=s))
        data = (d or {}).get("data") or []
        print(f"state {s}: {len(data)} rows")
        rows += [parse_state_row(r, s) for r in data]
        if data:
            dl = get_json(DIST_URL.format(s=s)) or {}
            dists += [{"state_code": s, "dist_id": int(x["value"]), "district": x["id"]} for x in dl.get("records", [])]
    pd.DataFrame(rows).to_parquet(out / "state_mode_rows.parquet", index=False)
    pd.DataFrame(dists).to_parquet(out / "districts.parquet", index=False)

    coords = {}
    pts = grid_points(pin_parquet)
    print(f"grid points: {len(pts)}")
    for i, (lat, lon) in enumerate(pts):
        d = get_json(NEAR_URL.format(lat=lat, lon=lon)) or []
        for x in d:
            hc = x.get("hospitalCode")
            if hc is not None and hc not in coords:
                coords[hc] = {k: x.get(k) for k in ("hospitalCode", "name", "address", "hospitalType", "type",
                                                    "latitude", "longitude", "distId", "stateCode")}
        if i % 25 == 0:
            print(f"  grid {i}/{len(pts)} unique coords so far {len(coords)}")
    pd.DataFrame(list(coords.values())).to_parquet(out / "nearest_coords.parquet", index=False)
    print(f"done: {len(rows)} state-mode rows, {len(coords)} with coordinates")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
