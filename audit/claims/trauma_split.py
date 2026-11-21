"""How much of the 'trauma' service is generic emergency vs explicit trauma/casualty wording. Writes out/trauma_split.json."""
import json, re
import pandas as pd
m = pd.read_parquet("out/mentions.parquet")
g = pd.read_parquet("out/grades.parquet")
t = m[(m.service == "trauma") & ~m.nonoffer]
exp = t.sentence.str.contains(r"\btrauma|polytrauma|casualty|accident", case=False, regex=True)
fac_exp = set(t[exp].unique_id)
tg = g[(g.service == "trauma") & (g.n_core > 0)]
res = dict(sentences=len(t), explicit_trauma_sentences=int(exp.sum()), facilities=int(tg.unique_id.nunique()),
           facilities_with_explicit_trauma_wording=len(fac_exp),
           strong_with_explicit=int(tg[tg.grade == "strong"].unique_id.isin(fac_exp).sum()),
           strong_total=int((tg.grade == "strong").sum()))
w = g[(g.unique_id.str.startswith("3ac5ae50")) & (g.service == "dialysis")]
res["wockhardt_nagpur_dialysis"] = w[["grade", "any_named_other"]].to_dict("records")
json.dump(res, open("out/trauma_split.json", "w"), indent=1)
print(res)
