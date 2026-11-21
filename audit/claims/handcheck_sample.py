"""Draw the deterministic hand-check samples (seed 42). Writes out/handcheck_*.tsv; labels live in labels_*.py."""
import os, sys
if os.path.exists("out/FROZEN") and "--force" not in sys.argv:
    sys.exit("hand-check samples are frozen (labels in labels.py refer to them); pass --force to redraw")

import pandas as pd
m = pd.read_parquet("out/mentions.parquet")
m["key"] = m.unique_id.str[:8] + "|" + m.service + "|" + m.field.str[:4]
core = m.groupby("service", group_keys=False).apply(lambda g: g.sample(min(25, len(g)), random_state=42))
core[["key", "sentence"]].to_csv("out/handcheck_core.tsv", sep="\t")
cues = ["negation", "referral", "future", "partner", "camp", "past"]
no = m[m.nonoffer]
no = no.groupby("service", group_keys=False).apply(lambda g: g.sample(min(8, len(g)), random_state=42))
no.assign(cues=no[cues].apply(lambda r: ",".join(c for c in cues if r[c]), axis=1))[["key", "cues", "sentence"]].to_csv("out/handcheck_nonoffer.tsv", sep="\t")
fo = m[m.foreign].sample(40, random_state=42)
fo[["key", "foreign_names", "sentence"]].to_csv("out/handcheck_foreign.tsv", sep="\t")
