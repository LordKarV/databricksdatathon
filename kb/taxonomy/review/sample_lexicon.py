"""Reviewer's 40-sentence lexicon check on cleaning/claims/out/claims.parquet.

Part A (false positives): one random matched sentence per service that the builder did not precision-check
(the 21 services new in kb/taxonomy), 21 sentences.
Part B (false negatives): 19 random sentences that no service matched but that contain a broad referral keyword.
Writes review/lexicon_sample40.csv with empty verdict columns for hand judgement.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python review/sample_lexicon.py
"""
from __future__ import annotations

import os
import re

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
T = os.path.dirname(D)
CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
SEED = 4242
CORE = {"dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care", "trauma_emergency", "icu"}
CANDIDATES = {"anti_rabies", "snakebite_antivenom", "nutrition_rehabilitation"}
# Broad recall net: words an intermediary's target services are commonly written with.
NET = re.compile(r"emergenc|casualty|accident|icu\b|intensive|ventilat|deliver|labou?r room|caesar|cesar|lscs|newborn|neonat|"
                 r"sncu|dialy|kidney|renal|cancer|oncolog|chemo|radiat|tumou?r|scan|x-?ray|imaging|blood|transfus|"
                 r"cardiac|heart|angio|stent|stroke|paraly|brain|spine|fracture|ortho|burn|psychiat|mental|addict|"
                 r"cataract|eye|tb\b|tubercul|hiv|poison|snake|rabies|trauma|24 ?x ?7|24 hours|round the clock", re.I)


def main() -> None:
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "unique_id", "field", "text"])
    m = pd.read_parquet(os.path.join(T, "out", "lexicon_matches.parquet"))
    new = m[~m.service.isin(CORE | CANDIDATES)]
    a = new.groupby("service", group_keys=False).sample(1, random_state=SEED).merge(c[["claim_id", "text"]], on="claim_id")
    a = a.assign(part="A_fp", lexicon_services=a.service)[["part", "claim_id", "field", "lexicon_services", "nonoffer_cue", "text"]]
    matched = set(m.claim_id)
    pool = c[~c.claim_id.isin(matched) & c.text.str.contains(NET)]
    b = pool.sample(19, random_state=SEED).assign(part="B_fn", lexicon_services="", nonoffer_cue="")
    b = b[["part", "claim_id", "field", "lexicon_services", "nonoffer_cue", "text"]]
    out = pd.concat([a, b]).assign(verdict="", should_be="", note="")
    out.to_csv(os.path.join(D, "lexicon_sample40.csv"), index=False)
    print(f"claims {len(c)}, matched sentences {len(matched)}, unmatched with net keyword {len(pool)}; A={len(a)} B={len(b)}")
    for r in out.itertuples():
        print(f"[{r.part}] {r.claim_id} | {r.lexicon_services} | {r.nonoffer_cue} | {r.text[:400]}")


if __name__ == "__main__":
    main()
