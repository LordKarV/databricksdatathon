"""Story 6: does the stub's 0.02-for-silence rule explain the Bihar obstetric funnel?
For every Bihar record graded strong/moderate for C-section, print the stub p of each definitive-stage capability."""
import json
from pathlib import Path

import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
import sys
sys.path.insert(0, str(R))
from planner.data_v1 import V1Store  # noqa: E402

s = V1Store(v1=R / "derived/v1", caps_path=R / "kb/pathways/capabilities.json")
pw = {p["id"]: p for p in json.loads((R / "kb/pathways/care_pathways.json").read_text())["pathways"]}
g = pd.read_parquet(R / "derived/v1/grades.parquet", columns=["unique_id", "service", "grade"])
f = pd.read_parquet(R / "derived/v1/facility_location.parquet", columns=["unique_id", "name", "state_final", "district", "loc_lat"])
x = g[(g.service == "csection") & g.grade.isin(["strong", "moderate"])].merge(f, on="unique_id")
b = x[x.state_final == "BIHAR"]
print("Bihar csection strong/moderate:", len(b))
for pid, stage in [("obstetric_emergency", -1), ("major_trauma", -1)]:
    st = pw[pid]["stages"][stage]
    caps = st["requires_all"] + [c for grp in st["requires_any"] for c in grp]
    print("\n", pid, st["id"], "requires_all", st["requires_all"], "any", st["requires_any"])
    ids = b.unique_id if pid == "obstetric_emergency" else f[f.state_final == "BIHAR"].unique_id
    rows = []
    for u in ids:
        p = {c: round(s.capability_p(u, c)[0], 3) for c in caps}
        prod = 1.0
        for c in st["requires_all"]:
            prod *= p[c]
        for grp in st["requires_any"]:
            prod *= max(p[c] for c in grp)
        rows.append({"name": f.set_index("unique_id").name[u][:40], "has_loc": pd.notna(f.set_index("unique_id").loc_lat[u]), **p, "stage_p": round(prod, 3)})
    t = pd.DataFrame(rows).sort_values("stage_p", ascending=False)
    print(t.head(15).to_string())
    print("records with stage_p >= 0.05 (planner candidate floor):", int((t.stage_p >= 0.05).sum()), "of", len(t))
