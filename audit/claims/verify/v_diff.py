"""Show finder-only mention sentences for services where my strict detector disagrees. Prints samples."""
import sys
import pandas as pd
g = pd.read_parquet("../out/grades.parquet"); fm = pd.read_parquet("../out/mentions.parquet"); m = pd.read_parquet("out/v_mentions.parquet")
for mine, fs, n in [("csection_strict", "csection", 17), ("cardiac_surgery", "cardiac_surgery", 25), ("mri", "mri", 8), ("nicu", "nicu", 6)]:
    only = set(g[(g.service == fs) & (g.n_core > 0)].unique_id) - set(m[m.service == mine].unique_id)
    x = fm[(fm.service == fs) & fm.unique_id.isin(only)].drop_duplicates("unique_id").sample(min(n, len(only)), random_state=1)
    gr = g[(g.service == fs) & g.unique_id.isin(only)].grade.value_counts().to_dict()
    print(f"== {fs}: finder-only facilities {len(only)}; their grades {gr}")
    for r in x.itertuples():
        print("  ", r.unique_id[:8], "|", r.sentence[:150])
