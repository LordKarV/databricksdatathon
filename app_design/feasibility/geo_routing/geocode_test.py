"""Reverse geocoding test: Nominatim (online) vs nearest PIN centroid / nearest post office (offline).

Five test points (rural Bihar x2, rural Maharashtra x2, one point on an expressway).
Nominatim: 1 request at a time, >= 1.1 s apart, identifying User-Agent, responses cached to
out/nominatim_cache.json so re-runs send no requests (usage policy:
https://operations.osmfoundation.org/policies/nominatim/).
Writes out/geocode_results.json.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo")
from geo_common import GEO, PIN_DIR, hav_km  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)
CACHE = OUT / "nominatim_cache.json"
UA = "cmu-datathon-care-finder-feasibility/0.1 (one-off research test, python-urllib)"

POINTS = [
    ("bihar_rural_north", 26.45, 85.95, "rural Bihar, between Sitamarhi and Madhubani"),
    ("bihar_rural_south", 24.85, 85.30, "rural Bihar, south of Gaya towards the Jharkhand border"),
    ("mh_rural_marathwada", 18.95, 75.95, "rural Maharashtra, Marathwada (Beed area)"),
    ("mh_rural_gadchiroli", 19.85, 80.10, "rural Maharashtra, forested Gadchiroli"),
    ("highway_mumbai_pune", 18.7835, 73.3700, "Mumbai-Pune Expressway near Khalapur"),
]


def nominatim_reverse(lat, lon, cache):
    key = f"{lat:.5f},{lon:.5f}"
    if key in cache:
        return cache[key], None
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18,
                                "addressdetails": 1, "accept-language": "en"})
    req = urllib.request.Request(f"https://nominatim.openstreetmap.org/reverse?{q}", headers={"User-Agent": UA})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=20) as r:
        body = json.load(r)
    ms = round((time.perf_counter() - t0) * 1000)
    cache[key] = {"response": body, "ms": ms}
    time.sleep(1.1)  # policy: absolute maximum 1 request per second
    return cache[key], ms


def offline_tables():
    cen = pd.read_parquet(GEO / "pin_centroids.parquet").dropna(subset=["best_lat"])
    cen = cen[["pincode", "best_lat", "best_lon", "state", "district", "n_offices", "spread_km_p90"]]
    off = pd.read_parquet(PIN_DIR)
    off["lat"] = pd.to_numeric(off.latitude, errors="coerce")
    off["lon"] = pd.to_numeric(off.longitude, errors="coerce")
    off = off.dropna(subset=["lat", "lon"])
    off = off[off.lat.between(6, 38) & off.lon.between(68, 98)]
    # ponytail: drop offices far from their own PIN centroid (misplaced points), 50 km cut is a judgement call
    off = off.merge(cen[["pincode", "best_lat", "best_lon"]], on="pincode")
    off = off[hav_km(off.lat, off.lon, off.best_lat, off.best_lon) < 50]
    return cen.reset_index(drop=True), off[["officename", "pincode", "district", "statename", "lat", "lon"]].reset_index(drop=True)


def nearest(df, lat, lon, la, lo):
    d = hav_km(lat, lon, df[la].values, df[lo].values)
    i = int(np.argmin(d))
    return df.iloc[i].to_dict(), float(d[i])


def main():
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    cen, off = offline_tables()
    rows = []
    for name, lat, lon, desc in POINTS:
        hit, ms = nominatim_reverse(lat, lon, cache)
        CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
        a = hit["response"].get("address", {})
        t0 = time.perf_counter()
        pc, dpc = nearest(cen, lat, lon, "best_lat", "best_lon")
        po, dpo = nearest(off, lat, lon, "lat", "lon")
        offline_ms = round((time.perf_counter() - t0) * 1000, 1)
        rows.append({
            "point": name, "lat": lat, "lon": lon, "desc": desc,
            "nominatim_ms_live": ms, "nominatim_ms_cached_first_call": hit["ms"],
            "nominatim_display": hit["response"].get("display_name"),
            "nominatim_osm_type": hit["response"].get("osm_type"),
            "nominatim_category": hit["response"].get("category"),
            "nominatim_type": hit["response"].get("type"),
            "nom_district": a.get("state_district") or a.get("county"),
            "nom_district_key": "state_district" if a.get("state_district") else ("county" if a.get("county") else None),
            "nom_subdistrict": a.get("county") if a.get("state_district") else None,
            "nom_state": a.get("state"), "nom_postcode": a.get("postcode"),
            "nom_village": a.get("village") or a.get("hamlet") or a.get("town") or a.get("city"),
            "nom_address_keys": sorted(a.keys()),
            "pin_centroid": int(pc["pincode"]), "pin_centroid_km": round(dpc, 2),
            "pin_district": pc["district"], "pin_state": pc["state"],
            "pin_spread_km_p90": pc["spread_km_p90"],
            "office": po["officename"], "office_pin": int(po["pincode"]), "office_km": round(dpo, 2),
            "office_district": po["district"], "office_state": po["statename"],
            "offline_lookup_ms": offline_ms,
        })
    (OUT / "geocode_results.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    for r in rows:
        print(json.dumps({k: r[k] for k in ["point", "nominatim_ms_live", "nom_district", "nom_district_key", "nom_state",
                                            "nom_postcode", "nom_village", "pin_centroid", "pin_centroid_km", "pin_district",
                                            "pin_state", "office", "office_km", "office_district", "offline_lookup_ms"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
