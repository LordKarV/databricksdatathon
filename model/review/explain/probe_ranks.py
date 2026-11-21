"""Where do the two known contaminated records rank for queries at each of their candidate locations? Read-only."""
import json
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
ROOT = Path("/Users/karthikvattem/projects/datathon")
sys.path.insert(0, str(ROOT / "model/proto/decision"))
from decide import distances, load, run_u_system, system_table  # noqa: E402
from resolve import Resolver  # noqa: E402

PROBES = [("dialysis", "Mumbai", "3ac5ae50"), ("dialysis", "400078", "3ac5ae50"), ("dialysis", "Hyderabad", "b8a5401f"),
          ("dialysis", "605001", "b8a5401f"), ("dialysis", "110002", "b8a5401f"), ("trauma_emergency", "Gautam Buddha Nagar", "7e420f3f"),
          ("trauma_emergency", "Chandauli", "7e420f3f"), ("emergency_csection", "Sheikhpura", "830706f4"),
          ("emergency_csection", "Sitamarhi", "830706f4")]
fac, pairs = load()
st_all = system_table(pairs, "WL")
R = Resolver()
out = []
for svc, place, pre in PROBES:
    res = R.resolve_place(place)
    if res["status"] != "ok":
        out.append(dict(service=svc, place=place, status=res["status"], matches=res["matches"][:5]))
        continue
    idx = np.flatnonzero(pairs.service.to_numpy() == svc)
    fs = fac.set_index("unique_id").loc[pairs.unique_id.iloc[idx]].reset_index()
    d1, d2 = distances(fs, res["lat"], res["lon"])
    t, cand, Ru, _ = run_u_system(dict(service=svc), fs, system_table(pairs, "WL").iloc[idx].reset_index(drop=True), d1, d2)
    hit = [i for i, u in enumerate(cand.unique_id) if u.startswith(pre)]
    row = cand.iloc[hit[0]] if hit else None
    out.append(dict(service=svc, place=place, note=res["note"], R_used=Ru, n_cand=len(cand), rank=hit[0] + 1 if hit else None,
                    top3=list(cand.name.head(3)),
                    rec=None if row is None else dict(d1=round(row.d1, 1), d2=None if not np.isfinite(row.d2) else round(row.d2, 1),
                                                      P_L=round(row.P_L, 3), P_S=round(row.P_S, 3), U=round(row.U, 4), P_succ=round(row.P_succ, 3), band=row.band)))
Path("probe_ranks.json").write_text(json.dumps(out, indent=1, default=str))
print(json.dumps(out, indent=1, default=str))
