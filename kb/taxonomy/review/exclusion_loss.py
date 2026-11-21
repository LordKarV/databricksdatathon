"""Sentences where a service's include pattern hits but its exclude pattern vetoes the whole sentence, plus counts of
specific recall gaps found by probe_lexicon.py. Exclusions are sentence-level, so a list sentence that names a
service next to an excluded word loses the service. Run from kb/taxonomy:
/Users/karthikvattem/projects/datathon/.venv/bin/python review/exclusion_loss.py
"""
from __future__ import annotations

import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lexicon_src as LS  # noqa: E402

CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
GAPS = {
    "psychiatry reversed ('department of psychiatry')": (r"(department|dept\.?|division|unit|ward|services?|centre|center|clinic) (of|for) psychiatr", "psychiatric_care"),
    "obstetric scan words": (r"fetal well|anomaly scan|\bNT scan|growth scan|level ?(ii|2) scan|\bTIFFA\b", "ultrasound"),
    "thalassaemia transfusion": (r"thalass?a?emi\w*.{0,40}transfus|transfus\w*.{0,40}thalass", "blood_bank"),
    "spine surgery": (r"spin(e|al) surg", "neurosurgery"),
    "regional cancer centre": (r"regional cancer cent", "radiotherapy"),
}


def main() -> None:
    comp = LS.compile_specs(LS.all_specs())
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "text"])
    rows = []
    for sid, p in comp.items():
        if not p["exclude"]:
            continue
        t = c.text if not p["strip_before_match"] else c.text.str.replace(p["strip_before_match"], " ", regex=True)
        inc = t.str.contains(p["include"])
        exc = inc & t.str.contains(p["exclude"])
        rows.append((sid, int(inc.sum()), int(exc.sum())))
        if sid in ("trauma_emergency", "dialysis", "cardiac_surgery", "icu"):
            for s in c.text[exc].sample(min(6, int(exc.sum())), random_state=1):
                print(f"  vetoed {sid}: {s[:200]}")
    print(pd.DataFrame(rows, columns=["service", "include_hits", "vetoed"]).sort_values("vetoed", ascending=False).to_string(index=False))
    for name, (pat, sid) in GAPS.items():
        r = re.compile(pat, re.I)
        hit = c.text.str.contains(r)
        missed = sum(sid not in LS.match(s, comp) for s in c.text[hit])
        print(f"gap {name}: {int(hit.sum())} sentences, {missed} not tagged {sid}")


if __name__ == "__main__":
    main()
