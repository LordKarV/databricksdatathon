"""Claims-04: re-count scope-capped grades, name-category counts with my own regex, and which name
tokens trigger caps (to find false triggers such as 'Siddha' inside 'Siddhartha'). Writes out/v_scope.json."""
import json, re, sys
import pandas as pd
from v_common import load
sys.path.insert(0, ".."); from services import SCOPE_NAME
g = pd.read_parquet("../out/grades.parquet"); df = load().drop_duplicates("unique_id")
r = {}
cap = g[g.scope_conflict & g.grade_text.isin(["strong", "medium"])]
r["capped_pairs"] = len(cap); r["capped_by_service"] = cap.service.value_counts().to_dict()
r["capped_from_strong"] = int((cap.grade_text == "strong").sum())
r["pairs_text_mention"] = int((g.n_core > 0).sum()); r["pairs_all_rows"] = len(g)
r["capped_dentist_type"] = int((cap.facilityTypeId == "dentist").sum())
trig = cap.assign(tok=cap.name.fillna("").map(lambda n: (SCOPE_NAME.search(n).group(0).lower() if SCOPE_NAME.search(n) else "TYPE=dentist")))
r["capped_by_trigger"] = trig.tok.value_counts().to_dict()
r["capped_names_suspect"] = trig[trig.tok.isin(["siddha", "smile", "rehab", "aesthetic", "hair", "nayan", "\bent", "ent"])][["name", "service", "grade_text"]].values.tolist()
EYE = re.compile(r"\beye\b|netra|nethra|nayan|ophthal|vision|retina|lasik", re.I)
DENT = re.compile(r"dental|\bdent|teeth|tooth|orthodont", re.I)
for k, rx in [("eye", EYE), ("dental", DENT)]:
    ids = set(df[df.name.fillna("").str.contains(rx)].unique_id)
    sub = g[g.unique_id.isin(ids) & (g.n_core > 0)]
    r[k] = dict(named=len(ids), claiming_any=int(sub.unique_id.nunique()), by_service=sub.service.value_counts().to_dict())
r["random_capped_sample"] = cap.sample(8, random_state=21)[["unique_id", "name", "service", "grade_text"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
json.dump(r, open("out/v_scope.json", "w"), indent=1)
print(json.dumps(r, indent=1))
