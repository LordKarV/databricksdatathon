"""F2 independent re-derivation of near-spelling merges, using my own detector hits (v_f1b filter) and my own
distinctive-token rule; plus a seeded sample of the finder's 107 records for labelling (handcheck/v_f2_sample.tsv)."""
import os, re
import pandas as pd
from rapidfuzz import fuzz
import v_f1b  # noqa: F401  (re-runs the filter; prints its summary)
from v_f1 import dist
D = os.path.dirname(os.path.abspath(__file__))
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
v2 = v_f1b.v2
rows = []
for u, ms, t in zip(v2.unique_id, v2.v2, v2.text):
    od = "".join(dist(rec.name[u]))
    for m in ms.split("; "):
        md = "".join(dist(m))
        if od and md and md != od:
            rows.append((u, m, fuzz.ratio(md, od), t))
nn = pd.DataFrame(rows, columns=["unique_id", "mention", "ratio", "text"])
for th in (75, 80):
    g = nn[nn.ratio >= th]
    print(f"mine: ratio>={th}: sentences {g[['unique_id','text']].drop_duplicates().shape[0]}, records {g.unique_id.nunique()}")
# finder's 107: rebuild exactly from its own parquet + its own near_name to get the record list
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/merge")
import analyze
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
f = fin[fin.has_foreign]
f = f.assign(sim=[analyze.near_name(x, rec.name[u]) for x, u in zip(f.foreign_names, f.unique_id)])
f = f[f.sim >= 75]
ids = f.unique_id.unique()
print("finder near-name records", len(ids), "sentences", len(f))
mine = set(nn[nn.ratio >= 75].unique_id)
print("overlap with mine", len(set(ids) & mine))
smp = pd.Series(ids).sample(25, random_state=31337)
out = f[f.unique_id.isin(smp)].groupby("unique_id").agg(foreign=("foreign_names", lambda x: " | ".join(sorted(set(x)))[:120]),
                                                       ex=("text", lambda x: " || ".join(list(x)[:2])[:260]), n=("text", "size"))
out = out.assign(rec_name=out.index.map(rec.name), city=out.index.map(rec.address_city))
out[["rec_name", "city", "n", "foreign", "ex"]].to_csv(f"{D}/handcheck/v_f2_sample.tsv", sep="\t")
pd.set_option("display.width", 300); pd.set_option("display.max_colwidth", 260)
print(out[["rec_name", "city", "foreign", "ex"]].to_string())
