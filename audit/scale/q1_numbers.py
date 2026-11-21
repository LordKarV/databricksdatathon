"""Q1: parse numberDoctors, capacity, yearEstablished; impossible values; distributions by type."""
import json
import pandas as pd
from common import df, num, NULLS

d = df()
N = len(d)
out = {"denominator_rows": N}
FIELDS = ["numberDoctors", "capacity", "yearEstablished"]
for c in FIELDS:
    raw = d[c]
    nullish = raw.isin(NULLS) | raw.isna()
    parsed = raw.map(num)
    fail = (~nullish) & parsed.isna()
    d[c + "_n"] = parsed
    out[c] = {
        "null_like": int(nullish.sum()),
        "non_null": int((~nullish).sum()),
        "parsed_int": int(parsed.notna().sum()),
        "parse_failures": int(fail.sum()),
        "parse_failure_examples": raw[fail].head(10).tolist(),
        "pure_digit_strings": int(raw[~nullish].str.fullmatch(r"\d+").sum()),
    }

nd, cap, yr = d["numberDoctors_n"], d["capacity_n"], d["yearEstablished_n"]
ids = lambda m: d.loc[m, "unique_id"].tolist()
imp = {
    "doctors_zero": nd == 0,
    "doctors_gt_1000": nd > 1000,
    "capacity_zero": cap == 0,
    "capacity_gt_5000": cap > 5000,
    "year_lt_1800": yr < 1800,
    "year_lt_1000": yr < 1000,
    "year_gt_2026": yr > 2026,
    "capacity_equals_year": cap.notna() & (cap == yr),
    "capacity_looks_like_year_1900_2026": cap.between(1900, 2026),
    "doctors_looks_like_year_1900_2026": nd.between(1900, 2026),
}
out["impossible"] = {k: {"count": int(m.sum()), "ids": ids(m)[:15]} for k, m in imp.items()}

# numberDoctors=1 as a placeholder: share among large hospitals
big = cap >= 300
out["doctors_eq_1_among_capacity_ge_300"] = {
    "count": int((big & (nd == 1)).sum()),
    "denominator_capacity_ge_300_with_doctors": int((big & nd.notna()).sum()),
    "ids": ids(big & (nd == 1))[:15],
}
out["doctors_value_counts_top"] = nd.value_counts().head(10).to_dict()


def dist(s):
    s = s.dropna()
    if s.empty:
        return {"n": 0}
    q = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).round(1).to_dict()
    return {"n": int(len(s)), "min": int(s.min()), "max": int(s.max()), **{f"p{int(k*100)}": v for k, v in q.items()}}


d["ftype"] = d["facilityTypeId"].fillna("<SQL NULL>")
out["by_type"] = {}
for t, g in d.groupby("ftype"):
    out["by_type"][t] = {
        "rows": int(len(g)),
        **{c: {"coverage": int(g[c + "_n"].notna().sum()), **dist(g[c + "_n"])} for c in FIELDS},
    }
# year decade histogram
out["year_by_decade"] = (yr.dropna() // 10 * 10).astype(int).value_counts().sort_index().to_dict()
out["year_value_counts_top"] = yr.value_counts().head(8).to_dict()

json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q1_numbers.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))
