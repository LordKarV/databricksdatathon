"""Fit the constants geo/travel.py uses for its estimate, from the measured OSRM pairs.

For each terrain class (plain, hill) and straight-line distance band: the road factor, the
free-flow speed, and the 10th and 90th percentile of (OSRM minutes / estimated minutes), pooled
and by urban / rural origin. travel.py turns those percentiles into the low and high of a range,
so the range is a measured spread, not an assumed speed.

Terrain: a candidate state (measure_road_factor.HILL_CANDIDATES) is "hill" when its measured
median road factor is at least HILL_MIN_FACTOR. The cut is chosen after seeing the data, so the
per-state table in out/travel_constants_summary.json is the thing to check, not the cut.

Plain constants come from the balanced core sample (4 origins per state and stratum) without the
hill states. Hill constants come from every pair measured in the hill states.

Input:   geo/out/road_factor_pairs.csv (written by geo/measure_road_factor.py)
Outputs: geo/road_factor.json, geo/out/travel_constants_summary.json
Run:     .venv/bin/python geo/fit_travel_constants.py     (no network)
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from measure_road_factor import BANDS, HILL_CANDIDATES, MIN_HAV_KM, SEED, boot_ci

GEO = Path(__file__).resolve().parent
OUT = GEO / "out"
HILL_MIN_FACTOR = 1.5
MIN_CELL = 30        # fewest pairs for a band x area cell to get its own percentiles
FOLDS = 10


def load():
    df = pd.read_csv(OUT / "road_factor_pairs.csv")
    ok = df.dropna(subset=["road_km", "osrm_min"])
    ok = ok[(ok.o_snap_m <= 2000) & (ok.f_snap_m <= 2000) & (ok.hav_km >= MIN_HAV_KM) & (ok.osrm_min > 0)].copy()
    ok["factor"] = ok.road_km / ok.hav_km
    ok["kmh"] = ok.road_km / ok.osrm_min * 60
    ok["band"] = np.digitize(ok.hav_km, BANDS[1:-1])
    return df, ok


def interp(bands, km, key):
    """Same rule as travel._consts: linear between band mid points, flat outside."""
    mids = [b["mid_km"] for b in bands]
    return np.interp(km, mids, [b[key] for b in bands])


def fit_bands(g):
    bands = []
    for i, (lo, hi) in enumerate(zip(BANDS[:-1], BANDS[1:])):
        b = g[g.band == i]
        if len(b) == 0:
            continue
        bands.append({"from_km": lo, "to_km": hi, "mid_km": round(float(b.hav_km.median()), 1),
                      "factor": round(float(b.factor.median()), 3), "kmh_free_flow": round(float(b.kmh.median()), 1),
                      "n_pairs": int(len(b)), "n_origins": int(b.pin.nunique())})
    est = g.hav_km * interp(bands, g.hav_km, "factor") / interp(bands, g.hav_km, "kmh_free_flow") * 60
    ratio = g.osrm_min / est
    for i, b in enumerate(bands):
        idx = g.band == [k for k, (lo, _) in enumerate(zip(BANDS[:-1], BANDS[1:])) if lo == b["from_km"]][0]
        r = ratio[idx]
        b["ratio_p10_p90"] = [round(float(r.quantile(.1)), 3), round(float(r.quantile(.9)), 3)]
        b["ratio_by_area"] = {}
        for area in ("urban", "rural"):
            ra = ratio[idx & (g.stratum == area)]
            if len(ra) >= MIN_CELL:
                b["ratio_by_area"][area] = {"p10_p90": [round(float(ra.quantile(.1)), 3), round(float(ra.quantile(.9)), 3)],
                                            "n_pairs": int(len(ra))}
    return bands


def predict(bands, g, use_area):
    """Estimated minutes with low and high, as travel.py computes them."""
    est = g.hav_km.values * interp(bands, g.hav_km, "factor") / interp(bands, g.hav_km, "kmh_free_flow") * 60
    mids = [b["mid_km"] for b in bands]
    lo = np.interp(g.hav_km, mids, [b["ratio_p10_p90"][0] for b in bands])
    hi = np.interp(g.hav_km, mids, [b["ratio_p10_p90"][1] for b in bands])
    if use_area:
        for area in ("urban", "rural"):
            m = (g.stratum == area).values
            if not m.any():
                continue
            lo_a = [b["ratio_by_area"].get(area, {"p10_p90": b["ratio_p10_p90"]})["p10_p90"][0] for b in bands]
            hi_a = [b["ratio_by_area"].get(area, {"p10_p90": b["ratio_p10_p90"]})["p10_p90"][1] for b in bands]
            lo[m] = np.interp(g.hav_km[m], mids, lo_a)
            hi[m] = np.interp(g.hav_km[m], mids, hi_a)
    return est, est * lo, est * hi


def held_out(g, use_area):
    """Grouped k-fold by origin: fit on the rest, score the held-out origins."""
    pins = g.pin.unique()
    rng = np.random.default_rng(SEED)
    fold = dict(zip(pins, rng.permutation(len(pins)) % FOLDS))
    f = g.pin.map(fold)
    parts = []
    for k in range(FOLDS):
        tr, te = g[f != k], g[f == k]
        if len(te) == 0:
            continue
        est, lo, hi = predict(fit_bands(tr), te, use_area)
        parts.append(pd.DataFrame({"stratum": te.stratum.values, "osrm": te.osrm_min.values, "est": est, "lo": lo, "hi": hi}))
    r = pd.concat(parts)

    def stats(x):
        ape = (x.est - x.osrm).abs() / x.osrm
        return {"n_pairs": int(len(x)), "ratio_median": round(float((x.osrm / x.est).median()), 3),
                "ape_median": round(float(ape.median()), 3), "ape_p90": round(float(ape.quantile(.9)), 3),
                "share_inside_range": round(float(((x.osrm >= x.lo) & (x.osrm <= x.hi)).mean()), 3),
                "share_above_high": round(float((x.osrm > x.hi).mean()), 3),
                "range_width_median": round(float(((x.hi - x.lo) / x.est).median()), 3)}
    return {"all": stats(r), **{a: stats(x) for a, x in r.groupby("stratum")}}


def class_block(g):
    return {"n_pairs": int(len(g)), "n_origins": int(g.pin.nunique()), "n_states": int(g.state.nunique()),
            "factor": round(float(g.factor.median()), 3), "factor_ci95": boot_ci(g, "factor"),
            "kmh_free_flow": round(float(g.kmh.median()), 1), "kmh_free_flow_ci95": boot_ci(g, "kmh"),
            "bands": fit_bands(g)}


def main():
    df, ok = load()
    per_state = {}
    for s in HILL_CANDIDATES:
        g = ok[ok.state == s]
        if len(g) == 0:
            per_state[s] = {"n_pairs": 0, "n_origins": 0, "terrain": "plain", "note": "no usable pairs"}
            continue
        per_state[s] = {"n_pairs": int(len(g)), "n_origins": int(g.pin.nunique()),
                        "n_origins_requested": int(df[df.state == s].pin.nunique()),
                        "factor_median": round(float(g.factor.median()), 3), "factor_ci95": boot_ci(g, "factor"),
                        "kmh_median": round(float(g.kmh.median()), 1), "kmh_ci95": boot_ci(g, "kmh")}
        per_state[s]["terrain"] = "hill" if per_state[s]["factor_median"] >= HILL_MIN_FACTOR else "plain"
    hill_states = sorted(s for s, v in per_state.items() if v["terrain"] == "hill")

    hill = ok[ok.state.isin(hill_states)]
    plain = ok[ok.core & ~ok.state.isin(hill_states)]
    national = ok[ok.core]
    classes = {"plain": class_block(plain), "hill": class_block(hill)}

    # what the hill class buys: hill-state pairs scored with the plain constants and with their own
    est_plain, _, _ = predict(classes["plain"]["bands"], hill, False)
    est_hill, _, _ = predict(classes["hill"]["bands"], hill, False)
    gain = {"hill_pairs_scored_with_plain_constants": {
                "ratio_median": round(float((hill.osrm_min / est_plain).median()), 3),
                "ape_median": round(float(((est_plain - hill.osrm_min).abs() / hill.osrm_min).median()), 3)},
            "hill_pairs_scored_with_hill_constants_in_sample": {
                "ratio_median": round(float((hill.osrm_min / est_hill).median()), 3),
                "ape_median": round(float(((est_hill - hill.osrm_min).abs() / hill.osrm_min).median()), 3)}}

    summary = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pairs": {"measured": int(len(df)), "usable": int(len(ok)), "core_usable": int(len(national)),
                  "origins_measured": int(df.pin.nunique())},
        "hill_rule": f"candidate state with median road factor >= {HILL_MIN_FACTOR}",
        "candidate_states": per_state,
        "hill_states": hill_states,
        "classes": {k: {x: v[x] for x in v if x != "bands"} for k, v in classes.items()},
        "held_out_by_origin": {
            "plain_pooled_range": held_out(plain, False), "plain_area_range": held_out(plain, True),
            "hill_pooled_range": held_out(hill, False), "hill_area_range": held_out(hill, True)},
        "hill_class_gain": gain,
    }
    (OUT / "travel_constants_summary.json").write_text(json.dumps(summary, indent=1))

    consts = {
        "version": 2,
        "built_utc": summary["built_utc"],
        "note": "factor = road km / straight-line km; kmh_free_flow = OSRM road km / OSRM hours (no traffic); "
                "ratio = OSRM minutes / estimated minutes. Built by geo/fit_travel_constants.py from "
                "geo/out/road_factor_pairs.csv; details in geo/out/travel_constants_summary.json.",
        "national": {"n_pairs": int(len(national)), "n_origins": int(national.pin.nunique()),
                     "factor": round(float(national.factor.median()), 3), "factor_ci95": boot_ci(national, "factor"),
                     "kmh_free_flow": round(float(national.kmh.median()), 1)},
        "hill_states": hill_states,
        "classes": classes,
    }
    (GEO / "road_factor.json").write_text(json.dumps(consts, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
