"""Build step: export the stub planner inputs from derived/v1 so the app can plan without pandas.

Writes planner/out/planner_v1.json.gz (git-ignored: it holds facility data):
  facilities    columns id, name, lat, lon, town, district, state, conf
  capabilities  per capability tag: facility indexes with evidence, their stub probability and
                up to 3 evidence claim ids
  pins          PIN centroids with their state, to find the state of an origin (hill-road
                travel constants are chosen by state)
Probabilities are the stub described in planner/data_v1.py, not the fitted model.

Run: .venv/bin/python planner/export_v1.py        (needs pandas and pyarrow; about 10 s)
"""
import gzip
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from planner.data_v1 import DATA_ROOT, NO_MENTION_P, V1, V1Store  # noqa: E402

# PLANNER_OUT moves the output folder (for example when the code folder is read-only)
OUT = Path(os.environ.get("PLANNER_OUT") or Path(__file__).resolve().parent / "out") / "planner_v1.json.gz"


def pins():
    g = pd.read_parquet(V1 / "pin_gazetteer.parquet", columns=["state", "lat", "lon"]).dropna()
    states = sorted(g.state.unique())
    code = {s: i for i, s in enumerate(states)}
    return {"states": states, "lat": [round(float(x), 3) for x in g.lat], "lon": [round(float(x), 3) for x in g.lon],
            "s": [code[s] for s in g.state]}


ERK = DATA_ROOT / "data" / "external" / "eraktkosh_blood_centres"


def blood(idx):
    """Blood-centre list facts, when the e-RaktKosh outputs are on this machine (they are not in git:
    see external/eraktkosh_blood_centres/README.md). None otherwise."""
    if not (ERK / "erk_vf_matches.parquet").is_file() or not (ERK / "erk_centres.parquet").is_file():
        return None
    m = pd.read_parquet(ERK / "erk_vf_matches.parquet", columns=["unique_id", "erk_name", "erk_type"]).drop_duplicates("unique_id")
    c = pd.read_parquet(ERK / "erk_centres.parquet", columns=["name", "latitude", "longitude"]).dropna()
    # 22.3511, 78.6677 is India's centroid: a failed geocode in the source
    c = c[~((c.latitude.round(4) == 22.3511) & (c.longitude.round(4) == 78.6677))]
    return {"source": "e-RaktKosh blood centres (external/eraktkosh_blood_centres)",
            "matched": {u: {"name": n, "type": t} for u, n, t in zip(m.unique_id, m.erk_name, m.erk_type) if u in idx},
            "centres": {"lat": [round(float(x), 4) for x in c.latitude], "lon": [round(float(x), 4) for x in c.longitude],
                        "name": [str(x) for x in c.name]}}


def main():
    store = V1Store()
    fac = store.facilities()
    idx = {f["id"]: i for i, f in enumerate(fac)}
    caps = {}
    for cap, info in store.caps.items():
        if info["kb_status"] == "existing":
            ids = [u for (u, s) in store._svc if s == info["kb_service"] and u in idx]
        else:
            ids = [u for u in store._match(cap) if u in idx]
        rows = sorted((idx[u], *store.capability_p(u, cap)) for u in ids)
        caps[cap] = {"i": [r[0] for r in rows], "p": [round(r[1], 4) for r in rows], "e": [r[2] for r in rows]}
    doc = {"version": 1, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "probabilities": store.describe(), "no_mention_p": NO_MENTION_P,
           "facilities": {"id": [f["id"] for f in fac], "name": [f["name"] for f in fac],
                          "lat": [round(f["lat"], 5) for f in fac], "lon": [round(f["lon"], 5) for f in fac],
                          "town": [f["town"] for f in fac], "district": [f["district"] for f in fac],
                          "state": [f["state"] for f in fac], "flags": [f["flags"] for f in fac]},
           "capabilities": caps, "pins": pins(), "blood": blood(idx)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(f"wrote {OUT}: {len(fac)} facilities, {len(caps)} capabilities, {len(doc['pins']['s'])} PIN "
          f"centroids, {OUT.stat().st_size / 1024:.0f} KB")
    if doc["blood"]:
        print(f"  blood list: {len(doc['blood']['matched'])} matched facilities, {len(doc['blood']['centres']['lat'])} centres")
    else:
        print("  blood list: not on this machine (data/external/eraktkosh_blood_centres); blood comes from record text")
    for cap, c in caps.items():
        print(f"  {cap:26s} {len(c['i']):5d} facilities with evidence")


if __name__ == "__main__":
    main()
