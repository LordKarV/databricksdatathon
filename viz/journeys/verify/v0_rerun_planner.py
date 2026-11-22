"""Independent re-run of the planner for the journeys stories (verification, not the analyst's run_plans.py).

Re-draws the origins from derived/v1/pin_gazetteer.parquet with the stated seed, assigns each PIN origin
its OWN gazetteer state (the analyst used the nearest PIN's state), each benchmark query the state of the
nearest gazetteer row, runs planner.core.plan with the derived/v1 stub, and writes the best plan per origin
x pathway to verify/out/rerun_best.parquet. Compare with data/plans_raw.json.gz in v1_check_plans.py.
"""
import json
import os
import sys
from pathlib import Path

os.environ["TRAVEL_CACHE"] = "off"
R = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(R))
import numpy as np
import pandas as pd
from planner.core import plan
from planner.data_v1 import V1Store

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
pins = pd.read_parquet(R / "derived/v1/pin_gazetteer.parquet", columns=["pin", "state", "district", "lat", "lon", "src"])
rng = np.random.default_rng(20261121)
rows = []
for q in json.loads((R / "model/gold/queries.json").read_text()):
    ok = pins.dropna(subset=["lat", "lon", "state"])
    d2 = (ok.lat - q["lat"]) ** 2 + ((ok.lon - q["lon"]) * np.cos(np.radians(q["lat"]))) ** 2
    rows.append(("Benchmark (40 queries)", q["query_id"], q["lat"], q["lon"], ok.state.values[int(np.argmin(d2.values))]))
for st, nice in [("BIHAR", "Bihar"), ("UTTAR PRADESH", "Uttar Pradesh"), ("MAHARASHTRA", "Maharashtra")]:
    pool = pins[(pins.state == st) & (pins.src == "pin_median")].dropna(subset=["lat", "lon"])
    idx = rng.choice(len(pool), 150, replace=False)
    for r in pool.iloc[idx].itertuples():
        rows.append((nice, f"pin{r.pin}", float(r.lat), float(r.lon), st))
paths = json.loads((R / "kb/pathways/care_pathways.json").read_text())["pathways"]
store = V1Store(v1=R / "derived/v1", caps_path=R / "kb/pathways/capabilities.json")
fac = store.facilities()
out = []
for s, oid, lat, lon, st in rows:
    for pw in paths:
        r = plan((lat, lon), pw, fac, store.capability_p, state=st)
        rec = {"origin_set": s, "origin_id": oid, "lat": lat, "lon": lon, "state": st, "pathway": pw["id"],
               "best": "abstain" if r["abstain"] else r["plans"][0]["type"]}
        if not r["abstain"]:
            b = r["plans"][0]
            rec.update(first_eta=b["stops"][0]["eta_minutes"], def_eta=b["stops"][-1]["eta_minutes"],
                       def_id=b["stops"][-1]["facility_id"], def_name=b["stops"][-1]["name"],
                       p_obj=b["totals"].get("p_objective"), p_first=b["totals"].get("p_first_care"))
        out.append(rec)
pd.DataFrame(out).to_parquet(OUT / "rerun_best.parquet")
print(len(out), "rows")
