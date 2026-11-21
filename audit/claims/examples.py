"""Draw 3 records per service per grade (strong/medium/weak), seed 5, with the exact sentences.
These are both the FINDINGS examples and the grade hand-check sample. Writes out/grade_examples.json."""
import os, sys
if os.path.exists("out/FROZEN") and "--force" not in sys.argv:
    sys.exit("hand-check samples are frozen (labels in labels.py refer to them); pass --force to redraw")

import json
import pandas as pd
g = pd.read_parquet("out/grades.parquet")
m = pd.read_parquet("out/mentions.parquet")
out = []
for svc in g.service.unique():
    for gr in ["strong", "medium", "weak"]:
        sub = g[(g.service == svc) & (g.grade == gr)]
        for r in sub.sample(min(3, len(sub)), random_state=5).itertuples():
            s = m[(m.unique_id == r.unique_id) & (m.service == svc)]
            out.append(dict(service=svc, grade=gr, unique_id=r.unique_id, name=r.name, type=r.facilityTypeId, beds=r.beds,
                            prereqs={c[4:]: bool(getattr(r, c)) for c in g.columns if c.startswith("pre_") and pd.notna(getattr(r, c))},
                            fields_own=int(r.n_fields_own), qty=bool(r.has_qty), scope_conflict=bool(r.scope_conflict),
                            sentences=[f"[{x.field}] {x.sentence}" + (" {LIST}" if x.is_list else "") + (" {STAFF}" if x.staff else "")
                                       + (" {DIR}" if x.directory else "") + (" {NONOFFER}" if x.nonoffer else "") for x in s.itertuples()][:4]))
json.dump(out, open("out/grade_examples.json", "w"), indent=1)
for i, e in enumerate(out):
    print(i, e["service"], e["grade"], e["unique_id"][:8], (e["name"] or "")[:40], e["type"], e["beds"], e["prereqs"], "F", e["fields_own"], "Q", e["qty"], "SC" if e["scope_conflict"] else "")
    for s in e["sentences"][:3]:
        print("     ", s[:170])
