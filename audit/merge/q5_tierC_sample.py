"""Draw 20 seeded tier-C dialysis records (unanchored dialysis claim inside a record with merge evidence)
for a hand check of whether the dialysis claim plausibly belongs to the named facility."""
import pandas as pd
D = "/Users/karthikvattem/projects/datathon/audit/merge"
s = pd.read_parquet(f"{D}/out/sentences_flagged.parquet").merge(pd.read_parquet(f"{D}/out/sentence_decisions.parquet"), on=["unique_id", "field", "idx"])
r = pd.read_parquet(f"{D}/out/records_flagged.parquet").set_index("unique_id")
flag = s.groupby("unique_id").agg(q=("quarantine", "any"), t=("tag_only", "any"))
merged = flag.q | flag.t
m = s[s.text.str.contains(r"\b(?:dialysis|haemodialysis|hemodialysis)\b", case=False, regex=True)]
anch = m[(m.self_names != "") & ~m.quarantine].unique_id.unique()
c = m[m.unique_id.map(merged) & ~m.unique_id.isin(anch) & ~m.quarantine]
ids = pd.Series(c.unique_id.unique()).sample(20, random_state=2026)
rows = []
for u in ids:
    x = s[s.unique_id == u]
    rows.append({"unique_id": u, "name": r.name[u], "city": r.address_city[u], "type": r.facilityTypeId[u],
                 "dialysis": " || ".join(c[c.unique_id == u].text.head(2)),
                 "merge_evidence": " || ".join(x[x.quarantine | x.tag_only].text.head(2))})
pd.DataFrame(rows).to_csv(f"{D}/handcheck/q5_tierC_dialysis.tsv", sep="\t", index=False)
