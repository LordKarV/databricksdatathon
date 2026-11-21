"""F1 record-level precision probe: share of flagged records resting on a single flagged sentence, and a seeded
sample of such single-hit records for labelling (handcheck/v_f1_single.tsv)."""
import os
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
ff = fin[fin.has_foreign]
k = ff.groupby("unique_id").size()
print("flagged records", len(k), "with exactly 1 flagged sentence", int((k == 1).sum()), "with 2", int((k == 2).sum()), "with >=3", int((k >= 3).sum()))
# distinct foreign-name strings per record: a record whose only foreign mention is AIIMS (credential/model) is benign
fd = ff[ff.context == "direct"]
kd = fd.groupby("unique_id").size()
print("direct-context records", len(kd), "single direct sentence", int((kd == 1).sum()))
aiims_only = ff.groupby("unique_id").foreign_names.agg(lambda x: all(set(n.strip() for n in v.split(";")) <= {"AIIMS", "AIIMS New Delhi", "AIIMS, New Delhi", "AIIMS Delhi"} for v in x))
print("records whose only foreign mentions are AIIMS variants", int(aiims_only.sum()))
one = ff[ff.unique_id.isin(k[k == 1].index)].sample(20, random_state=99)
one.assign(rec_name=one.unique_id.map(rec.name), rec_city=one.unique_id.map(rec.address_city))[
    ["unique_id", "rec_name", "rec_city", "foreign_names", "context", "text"]].to_csv(f"{D}/handcheck/v_f1_single.tsv", sep="\t", index=False)
