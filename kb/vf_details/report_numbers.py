"""Coverage and plausibility numbers quoted in VF_DETAILS.md. Run: .venv/bin/python report_numbers.py > out/report_numbers.txt"""
import pandas as pd

N = 9959
f = pd.read_parquet("out/facts.parquet")
f["usable"] = f.status.isin(["ok", "flagged"]) & (f.polarity == "positive")
t = f[f.method != "structured"]
print("facts total", len(f), "text", len(t), "structured", (f.method == "structured").sum(), "llm", (f.method == "llm").sum())
print("status text", t.status.value_counts().to_dict(), "polarity", f.polarity.value_counts().to_dict())
print("| type | text facts | ok | flagged | excluded | facilities with usable text fact | share |")
for k, g in t.groupby("fact_type"):
    u = g[g.usable].unique_id.nunique()
    print(f'| {k} | {len(g):,} | {(g.status == "ok").sum():,} | {(g.status == "flagged").sum():,} | {(g.status == "excluded").sum():,} | {u:,} | {u / N:.1%} |')
print("any usable text fact", t[t.usable].unique_id.nunique(), "any usable incl structured", f[f.usable].unique_id.nunique())
for (k, a), g in t.groupby(["fact_type", "attribute"]):
    u = g[g.usable].unique_id.nunique()
    print(f"{k}.{a}: facts {len(g)}, facilities usable {u} ({u / N:.1%})")
print("structured", f[f.method == "structured"].groupby(["fact_type", "attribute"]).unique_id.nunique().to_dict())
sc = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/scale/scale_flags.parquet").drop_duplicates("unique_id").set_index("unique_id")
tb = t[t.attribute == "total"]
cap = tb.unique_id.map(sc.capacity_clean)
print("text total beds", len(tb), "with capacity", cap.notna().sum(), "equal", (tb.value_num == cap).sum(), "disagree>25%", tb["flags"].str.contains("disagrees_capacity").sum())
ub = t[(t.fact_type == "unit_beds") & (t.attribute != "total")]
print("unit beds", len(ub), "exceeds_total", ub["flags"].str.contains("exceeds_total").sum(), "clinic_or_dentist", ub["flags"].str.contains("type_scale").sum())
dd = t[t.attribute == "doctors"]
nd = dd.unique_id.map(sc.doctors_clean)
print("doctor counts", len(dd), "with numberDoctors", nd.notna().sum(), "equal", (dd.value_num == nd).sum(), "disagree>50%", dd["flags"].str.contains("disagrees_numberDoctors").sum(),
      "doctors>2x beds", dd["flags"].str.contains("doctors_exceed").sum())
print("implausible", t[t["flags"].str.contains("implausible")].attribute.value_counts().to_dict())
print("zero", t[t["flags"].str.contains("zero_count")].attribute.value_counts().to_dict())
print("flags", t["flags"].str.split("|").explode().value_counts().to_dict())
print("attribution", t.attribution.value_counts().to_dict())
ft = pd.read_parquet("out/facility_details.parquet")
print("facility rows", len(ft), "conflicting", (ft.n_distinct_values > 1).sum(), ft[ft.n_distinct_values > 1].attribute.value_counts().head(8).to_dict())
