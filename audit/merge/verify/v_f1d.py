"""F1 record-level precision for records with >=2 flagged sentences: seeded sample of 15, showing distinct foreign names."""
import os
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
ff = fin[fin.has_foreign]
k = ff.groupby("unique_id").size()
ids = pd.Series(k[k >= 2].index).sample(15, random_state=123)
rows = [(rec.name[u], rec.address_city[u], int(k[u]), " | ".join(sorted(set("; ".join(ff[ff.unique_id == u].foreign_names).split("; ")))[:4])[:150],
         ff[ff.unique_id == u].text.iloc[0][:120]) for u in ids]
out = pd.DataFrame(rows, columns=["name", "city", "n", "foreign", "ex"])
out.to_csv(f"{D}/handcheck/v_f1_multi.tsv", sep="\t", index=False)
pd.set_option("display.width", 320); pd.set_option("display.max_colwidth", 150)
print(out.to_string())
