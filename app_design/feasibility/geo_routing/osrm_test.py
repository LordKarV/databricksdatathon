"""OSRM demo server table test, rural Bihar, plus haversine-times-circuity fit.

Policy (https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server and
https://routing.openstreetmap.de/about.html): at most 1 request per second, reasonable
non-commercial use, valid User-Agent, no scraping or heavy use, no uptime guarantee.
This script sends 12 requests in total, 1.1 s apart, and caches every response under out/osrm_raw/
so a re-run sends nothing.

Requests:
  5 x table 1x10 (5 rural Bihar origins, 10 nearest facilities with clean coordinates each)
  2 x table repeat of origin 1 (latency spread)
  2 x table size probe (100 and 101 coordinates) to find the coordinate limit
  1 x nearest (snap the expressway test point to a road) + 1 Nominatim reverse of the snapped point
Writes out/osrm_pairs.csv and out/osrm_summary.json.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from geocode_test import OUT, UA
from geo_common import GEO, hav_km

RAW = OUT / "osrm_raw"
RAW.mkdir(parents=True, exist_ok=True)
BASE = "https://router.project-osrm.org"
ORIGINS = [
    ("bihar_madhubani_rural", 26.45, 85.95),
    ("bihar_gaya_rural", 24.85, 85.30),
    ("bihar_saharsa_rural", 25.95, 86.75),
    ("bihar_west_champaran_rural", 26.95, 84.45),
    ("bihar_rohtas_rural", 25.30, 84.10),
]
DECISION_LAYER_ASSUMED = {"circuity": 1.4, "kmh": 40.0}  # model/design/proposal_decision.md 13.3


def get(url, tag):
    f = RAW / f"{tag}.json"
    if f.exists():
        return json.loads(f.read_text())
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, json.load(r)
    except urllib.error.HTTPError as e:
        status, body = e.code, json.loads(e.read() or b"{}")
    rec = {"url": url, "status": status, "ms": round((time.perf_counter() - t0) * 1000), "body": body,
           "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    f.write_text(json.dumps(rec))
    time.sleep(1.1)
    return rec


def clean_facilities():
    g = pd.read_parquet(GEO / "facility_geo.parquet")
    g = g.dropna(subset=["latitude", "longitude"])
    bad = g[["coord_zero", "coord_swapped", "coord_outside", "geo_conflict"]].fillna(False).any(axis=1)
    # ponytail: coord_dup_n > 1 means several records share one point (often a city centroid), skip them
    return g[~bad & (g.coord_dup_n.fillna(1) <= 1)][["unique_id", "name", "address_city", "latitude", "longitude"]]


def table(olat, olon, dests, tag):
    coords = ";".join([f"{olon:.6f},{olat:.6f}"] + [f"{lo:.6f},{la:.6f}" for la, lo in dests])
    q = urllib.parse.urlencode({"sources": 0, "annotations": "duration,distance"})
    return get(f"{BASE}/table/v1/driving/{coords}?{q}", tag)


def main():
    fac = clean_facilities()
    rows, lat_ms = [], {}
    for name, la, lo in ORIGINS:
        d = hav_km(la, lo, fac.latitude.values, fac.longitude.values)
        near = fac.assign(hav_km=d).nsmallest(10, "hav_km")
        rec = table(la, lo, list(zip(near.latitude, near.longitude)), f"table_{name}")
        lat_ms[name] = rec["ms"]
        b = rec["body"]
        snap0 = b["sources"][0]["distance"]
        for j, (_, f) in enumerate(near.iterrows()):
            rows.append({"origin": name, "o_lat": la, "o_lon": lo, "o_snap_m": round(snap0),
                         "facility_id": f.unique_id, "facility": f["name"], "city": f.address_city,
                         "f_lat": f.latitude, "f_lon": f.longitude, "hav_km": round(f.hav_km, 2),
                         "f_snap_m": round(b["destinations"][j + 1]["distance"]),
                         "road_km": None if b["distances"][0][j + 1] is None else round(b["distances"][0][j + 1] / 1000, 2),
                         "osrm_min": None if b["durations"][0][j + 1] is None else round(b["durations"][0][j + 1] / 60, 1)})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "osrm_pairs.csv", index=False)

    # latency spread: two more identical calls for origin 1
    la, lo = ORIGINS[0][1:]
    d = hav_km(la, lo, fac.latitude.values, fac.longitude.values)
    near = fac.assign(hav_km=d).nsmallest(10, "hav_km")
    rep = [table(la, lo, list(zip(near.latitude, near.longitude)), f"table_repeat_{k}")["ms"] for k in (1, 2)]

    # size probe: 100 and 101 coordinates (OSRM default max-table-size is 100 locations)
    near100 = fac.assign(hav_km=d).nsmallest(100, "hav_km")
    size = {}
    for n in (100, 101):
        r = table(la, lo, list(zip(near100.latitude, near100.longitude))[: n - 1],f"table_size_{n}")
        size[n] = {"status": r["status"], "code": r["body"].get("code"), "message": r["body"].get("message"), "ms": r["ms"]}

    # expressway snap and reverse geocode
    nr = get(f"{BASE}/nearest/v1/driving/73.370000,18.783500?number=1", "nearest_expressway")
    wp = nr["body"]["waypoints"][0]
    slon, slat = wp["location"]
    nq = urllib.parse.urlencode({"format": "jsonv2", "lat": slat, "lon": slon, "zoom": 18, "addressdetails": 1, "accept-language": "en"})
    nom = get(f"https://nominatim.openstreetmap.org/reverse?{nq}", "nominatim_snapped_expressway")

    ok = df.dropna(subset=["osrm_min"])
    ok = ok[ok.hav_km > 0.5]  # ratios explode for near-zero straight-line distance
    circ = ok.road_km / ok.hav_km
    mph = ok.osrm_min / ok.hav_km  # minutes per straight-line km
    # leave-one-out error of two fallbacks: constant minutes-per-km, and linear a + b*km
    loo_ratio, loo_lin = [], []
    for i in range(len(ok)):
        tr = ok.drop(ok.index[i])
        k = np.median(tr.osrm_min / tr.hav_km)
        loo_ratio.append(abs(k * ok.hav_km.iloc[i] - ok.osrm_min.iloc[i]) / ok.osrm_min.iloc[i])
        b, a = np.polyfit(tr.hav_km, tr.osrm_min, 1)
        loo_lin.append(abs(a + b * ok.hav_km.iloc[i] - ok.osrm_min.iloc[i]) / ok.osrm_min.iloc[i])
    # pairs from one origin share roads, so also hold out a whole origin at a time and bootstrap by origin
    loo_origin = []
    for o in ok.origin.unique():
        tr, te = ok[ok.origin != o], ok[ok.origin == o]
        k = np.median(tr.osrm_min / tr.hav_km)
        loo_origin += list(abs(k * te.hav_km - te.osrm_min) / te.osrm_min)
    rng = np.random.default_rng(7)
    groups = [g for _, g in ok.groupby("origin")]
    boot = [np.median(pd.concat([groups[i] for i in rng.integers(0, len(groups), len(groups))]).pipe(lambda x: x.road_km / x.hav_km))
            for _ in range(2000)]
    assumed = ok.hav_km * DECISION_LAYER_ASSUMED["circuity"] / DECISION_LAYER_ASSUMED["kmh"] * 60
    b_all, a_all = np.polyfit(ok.hav_km, ok.osrm_min, 1)
    summary = {
        "n_pairs": int(len(df)), "n_pairs_routed": int(df.osrm_min.notna().sum()), "n_pairs_used_for_fit": int(len(ok)),
        "table_latency_ms_by_origin": lat_ms, "table_latency_ms_repeats_origin1": rep,
        "size_probe": size,
        "origin_snap_m": df.groupby("origin").o_snap_m.first().to_dict(),
        "facility_snap_m_median_max": [float(df.f_snap_m.median()), float(df.f_snap_m.max())],
        "hav_km_median_range": [float(ok.hav_km.median()), float(ok.hav_km.min()), float(ok.hav_km.max())],
        "circuity_road_over_hav_median_iqr": [round(float(circ.median()), 3), round(float(circ.quantile(.25)), 3), round(float(circ.quantile(.75)), 3)],
        "circuity_p10_p90": [round(float(circ.quantile(.1)), 3), round(float(circ.quantile(.9)), 3)],
        "osrm_speed_kmh_on_road_median": round(float((ok.road_km / ok.osrm_min * 60).median()), 1),
        "minutes_per_hav_km_median_iqr": [round(float(mph.median()), 3), round(float(mph.quantile(.25)), 3), round(float(mph.quantile(.75)), 3)],
        "linear_fit_minutes": {"intercept": round(float(a_all), 2), "per_hav_km": round(float(b_all), 3)},
        "loo_mape_constant_ratio": round(float(np.mean(loo_ratio)), 3),
        "loo_p90_ape_constant_ratio": round(float(np.quantile(loo_ratio, .9)), 3),
        "loo_mape_linear": round(float(np.mean(loo_lin)), 3),
        "leave_origin_out_mape_constant_ratio": round(float(np.mean(loo_origin)), 3),
        "leave_origin_out_p90_ape": round(float(np.quantile(loo_origin, .9)), 3),
        "circuity_median_origin_bootstrap_95ci": [round(float(np.quantile(boot, .025)), 3), round(float(np.quantile(boot, .975)), 3)],
        "share_osrm_within_20pct_of_ratio_fit": round(float(np.mean(np.array(loo_origin) <= 0.2)), 3),
        "decision_layer_assumed_mape": round(float((abs(assumed - ok.osrm_min) / ok.osrm_min).mean()), 3),
        "decision_layer_assumed_bias_median": round(float(np.median(assumed / ok.osrm_min)), 3),
        "expressway_nearest": {"input": [18.7835, 73.37], "snapped": [slat, slon], "snap_m": round(wp["distance"]),
                               "road_name": wp.get("name"), "ms": nr["ms"]},
        "expressway_snapped_nominatim": {"display": nom["body"].get("display_name"),
                                         "state_district": nom["body"].get("address", {}).get("state_district"),
                                         "road": nom["body"].get("address", {}).get("road"), "ms": nom["ms"]},
    }
    (OUT / "osrm_summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
