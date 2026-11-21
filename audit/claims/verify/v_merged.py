"""Claims-02 re-derivation: named-other and cross-state sentence counts, grades of the known-bad records,
and a fresh random sample (seed 99) of named-other sentences for my own precision read. Writes out/v_merged.json."""
import json
import pandas as pd
m = pd.read_parquet("../out/mentions.parquet"); g = pd.read_parquet("../out/grades.parquet")
r = {}
x = m[m.named_other].drop_duplicates(["unique_id", "sentence"])
r["named_other_distinct_sentences"] = len(x); r["named_other_facilities"] = int(x.unique_id.nunique())
r["facilities_with_any_mention"] = int(m.unique_id.nunique())
f = m[m.foreign].drop_duplicates(["unique_id", "sentence"])
r["foreign_distinct_sentences"] = len(f); r["foreign_facilities"] = int(f.unique_id.nunique())
r["strong_dialysis_with_named_other"] = int(((g.service == "dialysis") & (g.grade == "strong") & g.any_named_other).sum())
r["strong_any_service_with_named_other"] = int(((g.grade == "strong") & g.any_named_other).sum())
for p in ["b8a5401f", "3ac5ae50", "e0fcd8ad", "13e107f9"]:
    gg = g[g.unique_id.str.startswith(p)]
    r["grades_" + p] = dict(zip(gg.service, gg.grade))
r["fresh_sample"] = x.sample(12, random_state=99)[["unique_id", "service", "named_other_names", "sentence"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
r["foreign_all"] = f[["unique_id", "service", "foreign_places", "sentence"]].assign(unique_id=lambda d: d.unique_id.str[:8]).values.tolist()
json.dump(r, open("out/v_merged.json", "w"), indent=1)
print(json.dumps(r, indent=1)[:9000])
