"""Second hand-check round after tuning (fresh seed 7): v2 non-offer cues and cross-state place flag."""
import os, sys
if os.path.exists("out/FROZEN") and "--force" not in sys.argv:
    sys.exit("hand-check samples are frozen (labels in labels.py refer to them); pass --force to redraw")

import pandas as pd, duckdb
m = pd.read_parquet("out/mentions.parquet")
f = duckdb.sql("select unique_id, name, address_city c, address_stateOrRegion s from '/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet'").df()
m = m.merge(f, on="unique_id")
m["key"] = m.unique_id.str[:8] + "|" + m.service + "|" + m.field.str[:4]
cues = ["negation", "referral", "future", "partner", "camp", "past"]
no = m[m.nonoffer].drop_duplicates("sentence")
print("v2 nonoffer sentences", m.nonoffer.sum(), "distinct", len(no), "v1", m.nonoffer_v1.sum())
no = no.sample(min(40, len(no)), random_state=7)
no.assign(cues=no[cues].apply(lambda r: ",".join(c for c in cues if r[c]), axis=1))[["key", "cues", "sentence"]].to_csv("out/handcheck2_nonoffer.tsv", sep="\t")
fo = m[m.foreign].drop_duplicates(["unique_id", "sentence"])
print("foreign sentences", m.foreign.sum(), "facilities", fo.unique_id.nunique())
fo.sample(min(40, len(fo)), random_state=11)[["key", "name", "c", "s", "foreign_places", "sentence"]].to_csv("out/handcheck2_foreign.tsv", sep="\t")
