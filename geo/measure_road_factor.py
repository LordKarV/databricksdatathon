"""Re-measure the road factor (road km / straight-line km) and road speed on a stratified sample.

Sample: PIN centroids as origins, stratified by state and by an urban / rural proxy (4 per state
and stratum, 12 in the candidate hill states), each with 10
facilities at spread distances (nearest three, then about 5, 10, 20, 35, 50, 75, 110 km).
One OSRM table request per origin (1 x 10), at most one request per 1.1 s, every response cached
under geo/out/osrm_raw/ so a re-run sends nothing.

OSRM demo server policy (https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server): at most
1 request per second, reasonable non-commercial use, valid User-Agent, no uptime guarantee.

Urban / rural proxy: the gazetteer has no urban flag, so a PIN is "urban" when the number of other
PIN centroids within 10 km is in the national top quartile. It is a postal-density proxy, not a
census class.

Inputs:  derived/v1/pin_gazetteer.parquet, derived/v1/facility_location.parquet
Outputs: geo/out/road_factor_pairs.csv, geo/out/road_factor_summary.json
         (then run geo/fit_travel_constants.py, which writes geo/road_factor.json)
Run:     .venv/bin/python geo/measure_road_factor.py            (sends requests on first run)
         .venv/bin/python geo/measure_road_factor.py --offline  (cache only, never sends)
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "geo"
OUT = GEO / "out"
RAW = OUT / "osrm_raw"
BASE = "https://router.project-osrm.org"
UA = "cmu-datathon-care-finder/0.1"
SEED = 7
PER_STRATUM = 4            # origins per (state, urban/rural)
PER_STRATUM_HILL = 12      # more origins where the road factor is far from the national figure
# candidate hill states: Himalayan states and the North East. Which of them get the hill constants
# is decided from the measurement (see terrain_classes in main).
HILL_CANDIDATES = ["HIMACHAL PRADESH", "UTTARAKHAND", "JAMMU AND KASHMIR", "LADAKH", "SIKKIM", "ARUNACHAL PRADESH",
                   "NAGALAND", "MANIPUR", "MIZORAM", "MEGHALAYA", "TRIPURA", "ASSAM"]
TARGETS_KM = [5, 10, 20, 35, 50, 75, 110]
MAX_KM = 150.0
MIN_HAV_KM = 2.0           # ratios explode for near-zero straight-line distance
DENSITY_KM = 10.0
BANDS = [2, 10, 25, 50, 100, 150]
OFFLINE = "--offline" in sys.argv


def hav_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def get(url, tag):
    f = RAW / f"{tag}.json"
    if f.exists():
        return json.loads(f.read_text())
    if OFFLINE:
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            status, body = r.status, json.load(r)
    except urllib.error.HTTPError as e:
        status, body = e.code, {"code": "HTTPError", "message": str(e)}
    except Exception as e:  # network failure: record nothing, so a re-run retries this origin
        print(f"  request failed for {tag}: {type(e).__name__}: {e}")
        time.sleep(1.1)
        return None
    rec = {"url": url, "status": status, "ms": round((time.perf_counter() - t0) * 1000), "body": body,
           "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if status == 200 and body.get("code") == "Ok":
        f.write_text(json.dumps(rec))
    time.sleep(1.1)
    return rec


def pin_density(pins):
    """Number of other PIN centroids within DENSITY_KM of each PIN."""
    la, lo = pins.lat.values, pins.lon.values
    n = np.empty(len(pins), dtype=int)
    for i in range(0, len(pins), 400):
        d = hav_km(la[i:i + 400, None], lo[i:i + 400, None], la[None, :], lo[None, :])
        n[i:i + 400] = (d <= DENSITY_KM).sum(axis=1) - 1
    return n


def pick_destinations(d_sorted):
    """Indices into a distance-sorted array: nearest three, then nearest to each target, then fill."""
    chosen = [0, 1, 2]
    for t in TARGETS_KM:
        order = np.argsort(np.abs(d_sorted - t))
        nxt = next((int(j) for j in order if int(j) not in chosen), None)
        if nxt is not None:
            chosen.append(nxt)
    return sorted(chosen)[:10]


def sample():
    pins = pd.read_parquet(ROOT / "derived/v1/pin_gazetteer.parquet")
    pins = pins[(pins.src == "pin_median") & pins.lat.notna() & pins.state.notna()].reset_index(drop=True)
    pins["density"] = pin_density(pins)
    cut = float(pins.density.quantile(0.75))
    pins["stratum"] = np.where(pins.density >= cut, "urban", "rural")

    fac = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet")
    fac = fac[(fac.loc_conf == "high") & (fac.loc_src == "listing_coordinates")]
    fac = fac.drop_duplicates(subset=["loc_lat", "loc_lon"]).reset_index(drop=True)

    rng = np.random.default_rng(SEED)
    origins = []
    for (state, stratum), g in pins.groupby(["state", "stratum"]):
        for i in rng.permutation(len(g)):
            limit = PER_STRATUM_HILL if state in HILL_CANDIDATES else PER_STRATUM
            have = sum(1 for o in origins if o["state"] == state and o["stratum"] == stratum)
            if have >= limit:
                break
            p = g.iloc[int(i)]
            d = hav_km(p.lat, p.lon, fac.loc_lat.values, fac.loc_lon.values)
            near = np.argsort(d)
            near = near[d[near] <= MAX_KM]
            if len(near) < 10:
                continue
            sel = near[pick_destinations(d[near])]
            # core = the balanced national sample (first PER_STRATUM per state and stratum)
            origins.append({"pin": int(p.pin), "state": state, "stratum": stratum, "density": int(p.density),
                            "core": have < PER_STRATUM,
                            "lat": float(p.lat), "lon": float(p.lon),
                            "dests": [(fac.unique_id[j], float(fac.loc_lat[j]), float(fac.loc_lon[j]), float(d[j])) for j in sel]})
    return origins, cut, len(pins), len(fac)


def boot_ci(df, col, n=2000):
    """95% CI of the median of df[col], resampling whole origins (pairs from one origin share roads)."""
    rng = np.random.default_rng(SEED)
    groups = [g[col].values for _, g in df.groupby("pin")]
    if len(groups) < 2:
        return [None, None]
    meds = [np.median(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])) for _ in range(n)]
    return [round(float(np.quantile(meds, .025)), 3), round(float(np.quantile(meds, .975)), 3)]


def wmedian(x, w):
    o = np.argsort(x.values)
    c = np.cumsum(w.values[o])
    return float(x.values[o][np.searchsorted(c, c[-1] / 2)])


def describe(df):
    return {"n_pairs": int(len(df)), "n_origins": int(df.pin.nunique()),
            "factor_median": round(float(df.factor.median()), 3), "factor_ci95": boot_ci(df, "factor"),
            "factor_p10_p90": [round(float(df.factor.quantile(.1)), 3), round(float(df.factor.quantile(.9)), 3)],
            "kmh_median": round(float(df.kmh.median()), 1), "kmh_ci95": boot_ci(df, "kmh"),
            "kmh_p10_p90": [round(float(df.kmh.quantile(.1)), 1), round(float(df.kmh.quantile(.9)), 1)]}


def leave_origin_out(df, by=None):
    """Absolute percentage error of minutes = hav_km x factor / kmh x 60 against OSRM, with the
    constants fitted without the held-out origin. by=None: one global pair of constants; else per group."""
    errs = []
    for pin, te in df.groupby("pin"):
        tr = df[df.pin != pin]
        if by is None:
            pred = te.hav_km * tr.factor.median() / tr.kmh.median() * 60
        else:
            f, v = tr.groupby(by).factor.median(), tr.groupby(by).kmh.median()
            keys = te[by].astype(str)
            pred = te.hav_km * keys.map(f.rename(index=str)).fillna(tr.factor.median()).values \
                / keys.map(v.rename(index=str)).fillna(tr.kmh.median()).values * 60
        errs += list(np.abs(pred - te.osrm_min) / te.osrm_min)
    errs = np.array(errs, dtype=float)
    return {"mape": round(float(errs.mean()), 3), "median_ape": round(float(np.median(errs)), 3),
            "p90_ape": round(float(np.quantile(errs, .9)), 3), "share_within_20pct": round(float((errs <= .2).mean()), 3)}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    origins, cut, n_pins, n_fac = sample()
    print(f"{len(origins)} origins sampled from {n_pins} PINs; {n_fac} candidate facilities; urban cut = {cut:.0f} PINs within {DENSITY_KM:.0f} km")
    rows, failed = [], 0
    for k, o in enumerate(origins):
        coords = ";".join([f"{o['lon']:.6f},{o['lat']:.6f}"] + [f"{lo:.6f},{la:.6f}" for _, la, lo, _ in o["dests"]])
        q = urllib.parse.urlencode({"sources": 0, "annotations": "duration,distance"})
        rec = get(f"{BASE}/table/v1/driving/{coords}?{q}", f"table_{o['pin']}")
        if rec is None or rec["status"] != 200 or rec["body"].get("code") != "Ok":
            failed += 1
            continue
        b = rec["body"]
        for j, (uid, la, lo, d) in enumerate(o["dests"]):
            dist, dur = b["distances"][0][j + 1], b["durations"][0][j + 1]
            rows.append({"pin": o["pin"], "state": o["state"], "stratum": o["stratum"], "density": o["density"],
                         "core": o["core"],
                         "o_lat": o["lat"], "o_lon": o["lon"], "o_snap_m": round(b["sources"][0]["distance"]),
                         "facility_id": uid, "f_lat": la, "f_lon": lo, "f_snap_m": round(b["destinations"][j + 1]["distance"]),
                         "hav_km": round(d, 3), "road_km": None if dist is None else round(dist / 1000, 3),
                         "osrm_min": None if dur is None else round(dur / 60, 2)})
        if (k + 1) % 25 == 0:
            print(f"  {k + 1}/{len(origins)} origins")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "road_factor_pairs.csv", index=False)

    # the national summary uses the balanced core sample only; the extra hill-state origins are
    # analysed by geo/fit_travel_constants.py
    n_all = len(df)
    df = df[df.core]
    ok = df.dropna(subset=["road_km", "osrm_min"])
    n_unrouted = len(df) - len(ok)
    # a snap of more than 2 km means the point is off the road network (island, forest, bad point)
    far_snap = (ok.o_snap_m > 2000) | (ok.f_snap_m > 2000)
    ok = ok[~far_snap & (ok.hav_km >= MIN_HAV_KM) & (ok.osrm_min > 0)].copy()
    ok["factor"] = ok.road_km / ok.hav_km
    ok["kmh"] = ok.road_km / ok.osrm_min * 60
    ok["band"] = pd.cut(ok.hav_km, BANDS, right=False).astype(str)

    by_state = {s: describe(g) for s, g in ok.groupby("state")}
    # the sample gives every state the same number of origins; reweight pairs by each state's share
    # of facility records to see what a typical query would meet
    fac_share = pd.read_parquet(ROOT / "derived/v1/facility_location.parquet").state_final.value_counts(normalize=True)
    w = ok.state.map(fac_share).fillna(0) / ok.groupby("state").state.transform("size")
    # error of the shipped fallback (per-band constants) by stratum: ratio = OSRM minutes / fallback minutes
    band_f, band_v = ok.groupby("band").factor.median(), ok.groupby("band").kmh.median()
    ok["fallback_min"] = ok.hav_km * ok.band.map(band_f) / ok.band.map(band_v) * 60
    ok["ratio"] = ok.osrm_min / ok.fallback_min

    def ratio_stats(g):
        ape = (g.fallback_min - g.osrm_min).abs() / g.osrm_min
        return {"n_pairs": int(len(g)), "ratio_median": round(float(g.ratio.median()), 3),
                "ratio_p10_p90": [round(float(g.ratio.quantile(.1)), 3), round(float(g.ratio.quantile(.9)), 3)],
                "ape_median": round(float(ape.median()), 3), "ape_p90": round(float(ape.quantile(.9)), 3)}
    summary = {
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": f"{BASE} table service, car profile, free flow (no traffic)",
        "sampling": {"seed": SEED, "origins_per_state_stratum": PER_STRATUM, "targets_km": TARGETS_KM,
                     "urban_proxy": f"other PIN centroids within {DENSITY_KM:.0f} km >= {cut:.0f} (national 75th percentile)",
                     "origins_sampled": len(origins), "origins_core": int(df.pin.nunique()),
                     "pairs_all_origins": int(n_all), "origins_per_state_stratum_hill_candidates": PER_STRATUM_HILL,
                     "origins_failed_or_not_cached": failed,
                     "states": int(df.state.nunique()) if len(df) else 0},
        "pairs": {"requested": int(len(df)), "unrouted": int(n_unrouted), "dropped_snap_over_2km": int(far_snap.sum()),
                  "used": int(len(ok)), "min_hav_km": MIN_HAV_KM},
        "all": describe(ok),
        "by_stratum": {s: describe(g) for s, g in ok.groupby("stratum")},
        "by_distance_band": {b: describe(g) for b, g in ok.groupby("band")},
        "weighted_by_state_facility_share": {"factor_median": round(wmedian(ok.factor, w), 3),
                                             "kmh_median": round(wmedian(ok.kmh, w), 1)},
        "fallback_ratio_osrm_over_estimate": {"all": ratio_stats(ok),
                                              **{s: ratio_stats(g) for s, g in ok.groupby("stratum")}},
        "by_state": by_state,
        "states_highest_factor": sorted(((v["factor_median"], s, v["n_pairs"]) for s, v in by_state.items()), reverse=True)[:6],
        "state_factor_median_range": [min(v["factor_median"] for v in by_state.values()),
                                      max(v["factor_median"] for v in by_state.values())],
        "fallback_error_leave_origin_out": {
            "global_constants": leave_origin_out(ok),
            "by_stratum": leave_origin_out(ok, "stratum"),
            "by_distance_band": leave_origin_out(ok, "band"),
            "by_state": leave_origin_out(ok, "state"),
        },
        "old_assumptions_vs_osrm_minutes": {
            name: {"median_ratio": round(float(np.median(ok.hav_km * f / v * 60 / ok.osrm_min)), 3),
                   "mape": round(float((np.abs(ok.hav_km * f / v * 60 - ok.osrm_min) / ok.osrm_min).mean()), 3)}
            for name, (f, v) in {"spec_1.3_at_40": (1.3, 40.0), "spec_1.3_at_25": (1.3, 25.0),
                                 "feasibility_1.26_at_69.4": (1.26, 69.4), "feasibility_1.26_at_40": (1.26, 40.0)}.items()},
    }
    (OUT / "road_factor_summary.json").write_text(json.dumps(summary, indent=1))

    print(json.dumps({k: summary[k] for k in ("pairs", "all", "weighted_by_state_facility_share",
                                               "fallback_ratio_osrm_over_estimate", "states_highest_factor",
                                               "fallback_error_leave_origin_out")}, indent=1))


if __name__ == "__main__":
    main()
