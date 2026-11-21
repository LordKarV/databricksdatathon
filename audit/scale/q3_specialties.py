"""Q3: specialty breadth per record vs facility type, doctors, beds, number of sources."""
import json
import pandas as pd
from common import df, num, jlist

d = df()
d["nd"] = d["numberDoctors"].map(num)
d["cap"] = d["capacity"].map(num)
sp = d["specialties"].map(jlist)
d["n_raw"] = sp.map(len)
d["n_spec"] = sp.map(lambda x: len(set(x)))
d["n_urls"] = d["source_urls"].map(lambda v: len(set(jlist(v))))
out = {"denominator_rows": len(d)}
vocab = pd.Series([s for x in sp for s in set(x)]).value_counts()
out["vocabulary_size"] = int(len(vocab))
out["top_specialties_record_share"] = {k: int(v) for k, v in vocab.head(12).items()}
out["records_with_duplicated_specialty_items"] = int((d["n_raw"] > d["n_spec"]).sum())
out["raw_items_total"] = int(d["n_raw"].sum())
out["distinct_items_total"] = int(d["n_spec"].sum())
q = lambda s: s.quantile([0.5, 0.9, 0.99]).round(1).tolist()
out["distinct_by_type"] = {t: {"rows": int(len(g)), "p50_p90_p99": q(g["n_spec"]), "max": int(g["n_spec"].max())}
                           for t, g in d.groupby(d["facilityTypeId"].fillna("<NULL>"))}
bucket = pd.cut(d["nd"], [-1, 1, 5, 20, 100, 1e9], labels=["0-1", "2-5", "6-20", "21-100", ">100"])
out["distinct_by_doctor_bucket"] = {str(b): {"rows": int(len(g)), "p50_p90": q(g["n_spec"])[:2]} for b, g in d.groupby(bucket, observed=True)}
out["distinct_doctors_missing"] = {"rows": int(d["nd"].isna().sum()), "p50_p90": q(d.loc[d["nd"].isna(), "n_spec"])[:2]}
ubucket = pd.cut(d["n_urls"], [-1, 1, 3, 6, 12, 1e9], labels=["0-1", "2-3", "4-6", "7-12", ">12"])
out["distinct_by_source_url_bucket"] = {str(b): {"rows": int(len(g)), "p50_p90": q(g["n_spec"])[:2]} for b, g in d.groupby(ubucket, observed=True)}
out["spearman_nspec_vs_nurls"] = round(float(d["n_spec"].rank().corr(d["n_urls"].rank())), 3)
out["spearman_nspec_vs_doctors"] = round(float(d.loc[d["nd"].notna(), "n_spec"].rank().corr(d.loc[d["nd"].notna(), "nd"].rank())), 3)

# "claims everything": more distinct specialties than a facility of its size could staff
small = (d["nd"] <= 2) | ((d["cap"] <= 30) & d["cap"].notna())
rules = {
    "ge_30_distinct_any": d["n_spec"] >= 30,
    "clinic_ge_15_distinct": (d["facilityTypeId"] == "clinic") & (d["n_spec"] >= 15),
    "dentist_ge_10_distinct": (d["facilityTypeId"] == "dentist") & (d["n_spec"] >= 10),
    "small_ge_15_distinct": small & (d["n_spec"] >= 15),
}
out["claims_everything"] = {k: {"count": int(m.sum()), "ids": d.loc[m, "unique_id"].head(10).tolist()} for k, m in rules.items()}
anyflag = pd.concat(rules.values(), axis=1).any(axis=1)
out["claims_everything_union"] = int(anyflag.sum())
d.loc[anyflag, ["unique_id", "name", "facilityTypeId", "nd", "cap", "n_spec", "n_urls"]].to_csv(
    "/Users/karthikvattem/projects/datathon/audit/scale/q3_claims_everything.csv", index=False)
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q3_specialties.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str))

# refined: large facilities (>=200 beds or >=50 doctors) legitimately carry 30+ specialties
large = (d["cap"] >= 200) | (d["nd"] >= 50)
refined = anyflag & ~large
out["claims_everything_union_excluding_large"] = int(refined.sum())
json.dump(out, open("/Users/karthikvattem/projects/datathon/audit/scale/q3_specialties.json", "w"), indent=1, default=str)
print("refined union:", int(refined.sum()))
