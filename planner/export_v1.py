"""Build step: export the stub planner inputs from derived/v1 so the app can plan without pandas.

Writes planner/out/planner_v1.json.gz (git-ignored: it holds facility data):
  facilities    columns id, name, lat, lon, town, district, state, conf
  capabilities  per capability tag: facility indexes with evidence, their stub probability and
                up to 3 evidence claim ids
Probabilities are the stub described in planner/data_v1.py, not the fitted model.

Run: .venv/bin/python planner/export_v1.py        (needs pandas and pyarrow; about 10 s)
"""
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.data_v1 import NO_MENTION_P, V1Store  # noqa: E402

OUT = Path(__file__).resolve().parent / "out" / "planner_v1.json.gz"


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
           "capabilities": caps}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(fac)} facilities, {len(caps)} capabilities, {OUT.stat().st_size / 1024:.0f} KB")
    for cap, c in caps.items():
        print(f"  {cap:26s} {len(c['i']):5d} facilities with evidence")


if __name__ == "__main__":
    main()
