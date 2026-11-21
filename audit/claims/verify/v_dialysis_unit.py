"""How many dialysis 'strong' grades meet the unit-or-machine prerequisite only through generic words
('dialysis facility/facilities/centre/center') rather than a unit, machine, bed, station, chair or RO plant.
Writes out/v_dialysis_unit.json."""
import json, re, sys
import pandas as pd
sys.path.insert(0, "..")
from services import SERVICES
from v_common import load
g = pd.read_parquet("../out/grades.parquet")
UNIT = SERVICES["dialysis"]["prereqs"]["dialysis_unit_or_machine"][0]
GENERIC = re.compile(r"dialy\w* (facility|facilities|centre|center)", re.I)
df = load().drop_duplicates("unique_id").set_index("unique_id")
def items(r):
    return list(r.procedure) + list(r.equipment) + list(r.capability) + re.split(r"(?<=[.!?])\s+", r.description)
out = {}
for gr in ["strong", "medium"]:
    ids = g[(g.service == "dialysis") & (g.grade == gr) & (g.pre_dialysis_unit_or_machine == True)].unique_id.unique()
    gen = []
    for u in ids:
        hits = [s for s in items(df.loc[u]) if UNIT.search(s)]
        if all(GENERIC.search(s) and not UNIT.search(GENERIC.sub(" ", s)) for s in hits):
            gen.append((u[:8], hits[0][:100]))
    out[gr] = dict(with_unit_prereq=len(ids), unit_prereq_only_generic_wording=len(gen), examples=gen[:6])
json.dump(out, open("out/v_dialysis_unit.json", "w"), indent=1)
print(json.dumps(out, indent=1))
