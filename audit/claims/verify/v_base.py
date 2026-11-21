"""Independent re-derivation of the structural counts: 50-item cap, duplicates, specialties vocabulary,
nephrology tag vs dialysis text, capacity coverage. Writes out/v_base.json."""
import json, re
from collections import Counter
import pandas as pd
from v_common import load

df = load()
N = len(df)
L = {c: df[c].map(len) for c in ["procedure", "equipment", "capability", "specialties"]}
r = {"N": N}
r["at_50"] = {c: int((v == 50).sum()) for c, v in L.items()}
r["over_50"] = {c: int((v > 50).sum()) for c, v in L.items()}
r["at_49"] = {c: int((v == 49).sum()) for c, v in L.items()}
r["any_text_at_50"] = int(((L["procedure"] == 50) | (L["equipment"] == 50) | (L["capability"] == 50)).sum())
r["any_incl_specialties_at_50"] = int(((L["procedure"] == 50) | (L["equipment"] == 50) | (L["capability"] == 50) | (L["specialties"] == 50)).sum())
# length histogram tail, to see if 50 is a hard ceiling (spike) rather than a natural tail
r["len_hist_45_50"] = {c: {k: int((v == k).sum()) for k in range(45, 51)} for c, v in L.items()}
r["exact_dup_casefold"] = {c: int(df[c].map(lambda l: len(l) - len({x.lower() for x in l})).sum()) for c in ["procedure", "equipment", "capability"]}
r["items"] = {c: int(v.sum()) for c, v in L.items()}
# specialties vocabulary
fac = Counter()
for l in df.specialties:
    fac.update(set(l))
norm = lambda s: re.sub(r"[^a-z]", "", s.lower())
r["spec_distinct_raw"] = len(fac)
r["spec_distinct_norm"] = len({norm(k) for k in fac})
r["spec_singletons"] = sum(v == 1 for v in fac.values())
r["spec_10plus"] = sum(v >= 10 for v in fac.values())
r["spec_rows_nonempty"] = int((L["specialties"] > 0).sum())
r["spec_rows_with_dups"] = int(df.specialties.map(lambda l: len(l) != len(set(l))).sum())
r["spec_mean_items_all_rows"] = round(L["specialties"].mean(), 2)
r["spec_mean_distinct_all_rows"] = round(df.specialties.map(lambda l: len(set(l))).mean(), 2)
r["camel_share_uses"] = round(sum(v for k, v in fac.items() if re.fullmatch(r"[a-z]+([A-Z][a-z]+)*", k)) / sum(fac.values()), 4)
sets = df.specialties.map(lambda l: {norm(x) for x in l})
r["tag_dentistry_rows"] = int(sets.map(lambda s: "dentistry" in s).sum())
r["dentist_type_rows"] = int((df.facilityTypeId == "dentist").sum())
r["tag_familymedicine_rows"] = int(sets.map(lambda s: "familymedicine" in s).sum())
r["tag_nephrology_rows"] = int(sets.map(lambda s: "nephrology" in s).sum())
alltext = df.apply(lambda x: " ".join(list(x.procedure) + list(x.equipment) + list(x.capability)) + " " + x.description, axis=1)
dial = alltext.str.contains(r"dialy[sz]|haemodial|hemodial", case=False, regex=True)
r["tag_nephrology_with_dialysis_text"] = int((sets.map(lambda s: "nephrology" in s) & dial).sum())
r["tag_dentistry_with_dental_name_or_type"] = int((sets.map(lambda s: "dentistry" in s) & ((df.facilityTypeId == "dentist") | df.name.fillna("").str.contains("dent", case=False))).sum())
# capacity
cap = pd.to_numeric(df.capacity.where(~df.capacity.isin(["null", "NULL"])), errors="coerce")
r["capacity_numeric"] = int(cap.notna().sum())
r["capacity_literal_null"] = int(df.capacity.isin(["null", "NULL"]).sum())
r["capacity_sql_null"] = int(df.capacity.isna().sum())
r["capacity_zero"] = int((cap == 0).sum())
bins = pd.cut(cap, [-1, 0, 9, 49, 199, 1e9], labels=["0", "1-9", "10-49", "50-199", "200+"]).astype(str).replace("nan", "unknown")
r["capacity_bins"] = bins.value_counts().to_dict()
r["type_counts"] = df.facilityTypeId.fillna("NA").value_counts().to_dict()
json.dump(r, open("out/v_base.json", "w"), indent=1, default=int)
print(json.dumps(r, indent=1, default=int))
