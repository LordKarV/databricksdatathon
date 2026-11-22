"""Run the multi-stop planner on the 40 benchmark queries and a sample of PIN centroids.

Origins
- bench: the 40 points of model/gold/queries.json (every query run against every pathway, as in
  planner/README.md).
- Bihar, Uttar Pradesh, Maharashtra: N_PER_STATE PIN centroids per state drawn at random (seed SEED)
  from derived/v1/pin_gazetteer.parquet rows with src == "pin_median" (centroid of the PIN's own
  post offices). A PIN sample is not a population sample: PINs are smaller where people are dense,
  so it leans towards people but is not weighted.

Planner inputs: planner.data_v1.V1Store (derived/v1 stub probabilities, not the fitted model),
geo.travel estimate with no network calls (TRAVEL_CACHE=off so nothing is written outside viz/).

Writes data/plans_raw.json.gz (every result) and data/plans_best.csv (one row per origin x pathway).
Run: .venv-viz/bin/python viz/journeys/scripts/run_plans.py   (about 5 minutes)
"""
import gzip
import json
import os
import sys
import time
from pathlib import Path

os.environ["TRAVEL_CACHE"] = "off"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA as OUT, ROOT  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from planner.core import plan  # noqa: E402
from planner.data_v1 import V1Store  # noqa: E402

SEED = 20261121
N_PER_STATE = 150
STATES = {"BIHAR": "Bihar", "UTTAR PRADESH": "Uttar Pradesh", "MAHARASHTRA": "Maharashtra"}


def origins(pins):
    q = json.loads((ROOT / "model/gold/queries.json").read_text())
    rows = [{"origin_set": "Benchmark (40 queries)", "origin_id": x["query_id"], "lat": x["lat"], "lon": x["lon"],
             "label": x["location_text"]} for x in q]
    rng = np.random.default_rng(SEED)
    for st, nice in STATES.items():
        pool = pins[(pins.state == st) & (pins.src == "pin_median")].dropna(subset=["lat", "lon"])
        take = pool.iloc[rng.choice(len(pool), N_PER_STATE, replace=False)]
        rows += [{"origin_set": nice, "origin_id": f"pin{r.pin}", "lat": float(r.lat), "lon": float(r.lon),
                  "label": f"PIN {r.pin}, {r.district}"} for r in take.itertuples()]
    return pd.DataFrame(rows)


def nearest_state(pins, lat, lon):
    # ponytail: planar nearest on degrees, same as service.py's nearest PIN state (border cases may flip)
    d = (pins.lat.values - lat) ** 2 + ((pins.lon.values - lon) * np.cos(np.radians(lat))) ** 2
    return pins.state.values[int(np.nanargmin(d))]


def flatten(o, pid, r):
    row = {**o, "pathway": pid, "best_type": "abstain" if r["abstain"] else r["plans"][0]["type"]}
    if r["abstain"]:
        return row
    b = r["plans"][0]
    t = b["totals"]
    first = b["stops"][0]
    row.update(n_plans=len(r["plans"]), first_name=first["name"], first_eta=first["eta_minutes"],
               first_low=first["eta_low"], first_high=first["eta_high"], first_km=first["leg"]["km"],
               def_name=b["stops"][-1]["name"], def_eta=b["stops"][-1]["eta_minutes"],
               def_low=b["stops"][-1]["eta_low"], def_high=b["stops"][-1]["eta_high"],
               def_district=b["stops"][-1]["district"], def_state=b["stops"][-1]["state"])
    if "p_objective" in t:
        row.update(p_objective=t["p_objective"], p_first_care=t["p_first_care"], p_treated=t["p_treated"],
                   expected_minutes=t["expected_minutes"])
        th = r.get("thresholds") or {}
        row.update(t1=th.get("first_care_minutes"), t2=th.get("definitive_minutes"),
                   gate=th.get("add_stop_only_if_definitive_beyond_minutes"))
        vs = b.get("vs_direct") or {}
        row.update(direct_minutes=vs.get("direct_minutes"), direct_p_objective=vs.get("direct_p_objective"),
                   direct_p_first_care=vs.get("direct_p_first_care"))
        row["stop_plans_dropped"] = (r.get("considered") or {}).get("stop_plans_dropped_below_margin")
    else:
        row.update(distinct_sites=t["distinct_sites"], one_way_minutes=t["one_way_minutes_to_recurring_site"],
                   travel_minutes_12w=t["travel_minutes_over_planning_weeks"], p_all_stages=t["p_all_stages"],
                   recurring_km=b["stops"][-1]["leg"]["km"])
    return row


def main():
    pins = pd.read_parquet(ROOT / "derived/v1/pin_gazetteer.parquet", columns=["pin", "state", "district", "lat", "lon", "src"])
    pins_ok = pins.dropna(subset=["lat", "lon", "state"])
    org = origins(pins)
    pathways = {p["id"]: p for p in json.loads((ROOT / "kb/pathways/care_pathways.json").read_text())["pathways"]}
    store = V1Store(v1=ROOT / "derived/v1", caps_path=ROOT / "kb/pathways/capabilities.json")
    fac = store.facilities()
    raw, flat = [], []
    t0 = time.time()
    for i, o in enumerate(org.to_dict("records")):
        state = nearest_state(pins_ok, o["lat"], o["lon"])
        o["state"] = state
        for pid, pw in pathways.items():
            r = plan((o["lat"], o["lon"]), pw, fac, store.capability_p, state=state)
            raw.append({"origin": o, "pathway": pid, "result": r})
            flat.append(flatten(o, pid, r))
        if i % 50 == 0:
            print(f"{i}/{len(org)} origins, {time.time() - t0:.0f} s", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / "plans_raw.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"meta": {"stub": True, "probabilities": store.describe(), "seed": SEED, "n_per_state": N_PER_STATE,
                            "travel": "geo.travel estimate, no network"}, "runs": raw}, fh)
    df = pd.DataFrame(flat)
    df.to_csv(OUT / "plans_best.csv", index=False)
    print(df.groupby(["origin_set", "pathway"]).best_type.value_counts().unstack(fill_value=0))
    print(f"done in {time.time() - t0:.0f} s; {len(df)} rows")


if __name__ == "__main__":
    main()
