"""PROV-15/16/18: NFHS cell notation, duplicate rows, missing districts, need indicators."""
import json, re, pandas as pd, numpy as np
n = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/nfhs_5_district_health_indicators.parquet")
ind = [c for c in n.columns if c not in ("district_name", "state_ut")]
o = {"rows": len(n), "cols": len(n.columns), "indicators": len(ind)}
dbl = [c for c in ind if pd.api.types.is_float_dtype(n[c])]; st = [c for c in ind if c not in dbl]
o["double"] = len(dbl); o["string"] = len(st); o["double_with_nan"] = int(sum(n[c].isna().any() for c in dbl))
cells = pd.concat([n[c] for c in st]).astype(object)
s = cells.dropna().astype(str).str.strip()
o["string_cells"] = len(cells); o["string_null"] = int(cells.isna().sum())
o["paren"] = int(s.str.fullmatch(r"\(-?\d+(\.\d+)?\)").sum()); o["star"] = int((s == "*").sum())
o["plain_num"] = int(s.str.fullmatch(r"-?\d+(\.\d+)?").sum()); o["other"] = s[~s.str.fullmatch(r"\(?-?\d+(\.\d+)?\)?|\*")].value_counts().head(10).to_dict()
o["trailing_space_cells"] = int((cells.dropna().astype(str) != cells.dropna().astype(str).str.rstrip()).sum())
o["all_cells"] = len(n) * len(ind)
def flags(c):
    v = n[c].astype(str).str.strip()
    return {"star": int((v == "*").sum()), "paren": int(v.str.startswith("(").sum()), "plain": int(v.str.fullmatch(r"-?\d+(\.\d+)?").sum())}
for c in ["pregnant_w15_49_who_are_anaemic_lt_11_0_g_dl_22_pct", "births_in_a_private_fac_that_were_delivered_by_csection_5y_pct",
          "children_with_fever_or_symptoms_of_ari_2wk_taken_to_a_healt_pct", "births_delivered_by_csection_5y_pct",
          "institutional_birth_5y_pct", "hh_member_covered_health_insurance_pct", "average_out_of_pocket_expenditure_per_delivery_in_a_public_fac"]:
    o["col:" + c] = {"dtype": str(n[c].dtype), **flags(c)}
worst = sorted(st, key=lambda c: -(n[c].astype(str).str.strip() == "*").sum())[:3]
o["most_star"] = {c: flags(c) for c in worst}
for c in ["births_delivered_by_csection_5y_pct", "institutional_birth_5y_pct", "hh_member_covered_health_insurance_pct"]:
    o["range:" + c] = [float(n[c].min()), float(n[c].max())]
key = n[ind].astype(str).apply(lambda r: "|".join(x.strip() for x in r), axis=1)
o["identical_rows"] = (n.state_ut.str.strip() + " / " + n.district_name.str.strip())[key.duplicated(keep=False)].tolist()
o["mizoram_districts"] = sorted(n[n.state_ut.str.strip().str.upper() == "MIZORAM"].district_name.str.strip())
wb = n[n.state_ut.str.strip().str.upper() == "WEST BENGAL"].district_name.str.strip().tolist()
o["wb_bardhaman_like"] = [d for d in wb if "ardh" in d.lower() or "burdwan" in d.lower()]
o["wb_n"] = len(wb)
o["district_trailing_space"] = int((n.district_name != n.district_name.str.rstrip()).sum())
o["state_values_odd"] = sorted({s for s in n.state_ut if s != s.strip() or "Maharas" in s})
o["longest_names"] = sorted(n.district_name.str.strip(), key=len)[-4:]
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v8_nfhs.json", "w"), indent=1, default=str)
