"""Round 3 (seed 3): named-other-facility detector after the distinctive-token fix."""
import os, sys
if os.path.exists("out/FROZEN") and "--force" not in sys.argv:
    sys.exit("hand-check samples are frozen (labels in labels.py refer to them); pass --force to redraw")

import pandas as pd, duckdb
m = pd.read_parquet("out/mentions.parquet")
f = duckdb.sql("select unique_id, name, address_city c from '/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet'").df()
m = m.merge(f, on="unique_id")
m["key"] = m.unique_id.str[:8] + "|" + m.service + "|" + m.field.str[:4]
x = m[m.named_other].drop_duplicates(["unique_id", "sentence"])
print("named_other sentences", int(m.named_other.sum()), "distinct", len(x), "facilities", x.unique_id.nunique(), "of", m.unique_id.nunique())
x.sample(40, random_state=3)[["key", "name", "c", "named_other_names", "sentence"]].to_csv("out/handcheck3_named.tsv", sep="\t")
