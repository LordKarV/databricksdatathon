"""Specialties enum vs text agreement, and the 50-item cap on JSON arrays. Writes out/enum_check.json."""
import json
import pandas as pd
from common import load, TEXT_FIELDS
from services import norm_spec
df = load()
g = pd.read_parquet("out/grades.parquet")
res = {}
for svc in ["dialysis", "cardiac_surgery", "burns", "trauma", "icu"]:
    s = g[g.service == svc]
    res[svc] = dict(enum_hit=int(s.enum_hit.sum()), enum_and_text=int((s.enum_hit & (s.n_core > 0)).sum()),
                    enum_only=int((s.enum_hit & (s.n_core == 0)).sum()), text_without_enum=int((~s.enum_hit & (s.n_core > 0)).sum()))
# prerequisite specialty present but service absent: e.g. nephrology without any dialysis text
neph = df.specialties_l.map(lambda l: "nephrology" in {norm_spec(x) for x in l})
dial = set(g[(g.service == "dialysis") & (g.n_core > 0)].unique_id)
res["nephrology_enum_facilities"] = int(neph.sum())
res["nephrology_enum_with_dialysis_text"] = int(df[neph].unique_id.isin(dial).sum())
cap = {}
for f in TEXT_FIELDS + ["specialties"]:
    n = df[f + "_l"].map(len)
    cap[f] = dict(at_50=int((n == 50).sum()), over_50=int((n > 50).sum()))
sp50 = df[df.specialties_l.map(len) == 50]
cap["specialties_at_50_mean_distinct"] = round(sp50.specialties_l.map(lambda l: len(set(l))).mean(), 2)
cap["specialties_below_50_mean_distinct"] = round(df[df.specialties_l.map(len) < 50].specialties_l.map(lambda l: len(set(l))).mean(), 2)
res["array_cap"] = cap
# within-field duplicate sentences (exact, case-folded)
res["exact_duplicate_items_within_field"] = {f: int(df[f + "_l"].map(lambda l: len(l) - len({x.lower() for x in l})).sum()) for f in TEXT_FIELDS}
res["total_items"] = {f: int(df[f + "_l"].map(len).sum()) for f in TEXT_FIELDS}
json.dump(res, open("out/enum_check.json", "w"), indent=1)
print(json.dumps(res, indent=1))
