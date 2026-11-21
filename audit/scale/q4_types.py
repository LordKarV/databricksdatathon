"""Q4: facilityTypeId / operatorTypeId / organization_type / affiliationTypeIds quality, and name-vs-type checks."""
import json
import re
import pandas as pd
from common import df, jlist

d = df()
N = len(d)
out = {"denominator_rows": N}
for c in ["facilityTypeId", "operatorTypeId", "organization_type"]:
    out[c + "_values"] = d[c].fillna("<SQL NULL>").value_counts().to_dict()
aff = d["affiliationTypeIds"].map(jlist)
out["affiliation"] = {
    "null_like": int((aff.map(len) == 0).sum()),
    "with_values": int((aff.map(len) > 0).sum()),
    "with_duplicates": int((aff.map(len) > aff.map(lambda x: len(set(x)))).sum()),
    "distinct_value_counts": pd.Series([v for x in aff for v in set(x)]).value_counts().to_dict(),
    "multi_distinct_values": int((aff.map(lambda x: len(set(x))) >= 2).sum()),
}

name = d["name"].fillna("").str.lower()
t = d["facilityTypeId"]
op = d["operatorTypeId"]
HOSP = name.str.contains(r"\bhospitals?\b")
CLIN = name.str.contains(r"\bclinics?\b|\bpolyclinic\b")
NH = name.str.contains(r"nursing home")
DENT = name.str.contains(r"\bdental\b|\bdentist|\bdentistry\b|\bteeth\b|\btooth\b|\bsmile\b|\borthodont")
DIAG = name.str.contains(r"diagnostic|\blabs?\b|laborator|patholog|\bimaging\b|\bscans?\b|\bradiology\b")
PHARM = name.str.contains(r"pharmac|chemist|medical stores?|\bmedicals\b|druggist")
# ponytail: keyword list tuned by hand-check; "general hospital" and "rural hospital" dropped because
# most India records with those words are private (3-4 of 20 sampled were government).
GOV = name.str.contains(
    r"\bgovt\.?\b|\bgovernment\b|\bdistrict hospital\b|\bcivil hospital\b|\baiims\b|\besic?\b|"
    r"\brailway hospital\b|\bphc\b|\bchc\b|primary health|community health cent|\bsub[- ]?centre\b|"
    r"\btaluk hospital\b|\bsub[- ]?divisional hospital\b|\bmunicipal\b|\bcantonment (?:general )?hospital\b|"
    r"\bpgimer\b|\bjipmer\b|\bcghs\b|\binhs\b|\bcommand hospital\b|\bmilitary hospital\b|"
    r"\bdistrict headquarters? hospital\b|\bpublic health cent")
VET = name.str.contains(r"\b(?:pets?|veterinary|vet|animal|canine|feline)\b") & ~name.str.contains(r"\bpet[- ]?(?:ct|scan|mri)\b|\bpet\s*/\s*ct\b")
rules = {
    "name_veterinary": VET,
    "name_hospital_typed_clinic": HOSP & (t == "clinic"),
    "name_clinic_not_hospital_typed_hospital": CLIN & ~HOSP & (t == "hospital"),
    "name_nursing_home_typed_clinic": NH & (t == "clinic"),
    "name_dental_typed_not_dentist": DENT & ~HOSP & (t != "dentist"),
    "name_dental_hospital_typed_hospital": DENT & HOSP & (t == "hospital"),
    "name_diagnostic_lab_typed_hospital": DIAG & ~HOSP & (t == "hospital"),
    "name_diagnostic_lab_any": DIAG & ~HOSP,
    "name_pharmacy_typed_not_pharmacy": PHARM & ~t.isin(["farmacy", "pharmacy"]),
    "name_government_typed_private": GOV & (op == "private"),
    "name_government_any": GOV,
    "affiliation_government_operator_private": aff.map(lambda x: "government" in x) & (op == "private"),
    "operator_public_or_government": op.isin(["public", "government"]),
}
out["rules"] = {k: {"count": int(m.sum()), "ids": d.loc[m, "unique_id"].head(10).tolist()} for k, m in rules.items()}
out["type_by_name_hospital"] = t[HOSP].value_counts().to_dict()
out["type_by_name_clinic_only"] = t[CLIN & ~HOSP].value_counts().to_dict()
out["operator_by_name_government"] = op[GOV].value_counts().to_dict()
out["operator_by_type"] = pd.crosstab(t, op).to_dict()
samples = {k: d.loc[m, ["unique_id", "name", "facilityTypeId", "operatorTypeId"]].sample(min(20, int(m.sum())), random_state=0).values.tolist()
           for k, m in rules.items() if k.startswith("name_") and not k.endswith("_any")}
json.dump(samples, open("/Users/karthikvattem/projects/datathon/audit/scale/q4_handcheck_samples.json", "w"), indent=1)
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q4_types.json", "w"), indent=1, default=str)
print(json.dumps({k: v for k, v in out.items() if k != "rules"}, indent=1, default=str))
print(json.dumps({k: v["count"] for k, v in out["rules"].items()}, indent=1))
