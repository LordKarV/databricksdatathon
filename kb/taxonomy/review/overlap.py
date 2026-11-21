"""Service overlap and data sufficiency from out/lexicon_matches.parquet (positive matches only).
- text_2plus: facilities whose positive text evidence spans 2+ distinct text fields (specialties excluded).
- pair overlap: facilities with positive text for both services, and sentences matching both.
- explicit trauma share of trauma_emergency sentences.
Run: /Users/karthikvattem/projects/datathon/.venv/bin/python review/overlap.py
"""
from __future__ import annotations

import os
import re

import pandas as pd

T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
PAIRS = [("nicu", "picu"), ("icu", "picu"), ("icu", "ventilator_support"), ("trauma_emergency", "orthopaedic_trauma_surgery"),
         ("emergency_csection", "institutional_delivery"), ("emergency_csection", "high_risk_pregnancy"),
         ("cath_lab_angioplasty", "cardiac_surgery"), ("chemotherapy", "surgical_oncology"), ("chemotherapy", "radiotherapy"),
         ("psychiatric_care", "de_addiction"), ("ct_scan", "mri"), ("stroke_care", "neurosurgery")]


def main() -> None:
    m = pd.read_parquet(os.path.join(T, "out", "lexicon_matches.parquet"))
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility")]
    f2 = pos.groupby(["service", "unique_id"]).field.nunique().reset_index()
    suff = pd.DataFrame({"text_facilities": pos.groupby("service").unique_id.nunique(),
                         "text_2plus_fields": f2[f2.field >= 2].groupby("service").unique_id.nunique()}).fillna(0).astype(int)
    print(suff.sort_values("text_2plus_fields").to_string())
    fac = pos.groupby("service").unique_id.apply(set)
    sent = pos.groupby("service").claim_id.apply(set)
    for a, b in PAIRS:
        both = fac[a] & fac[b]
        print(f"{a} & {b}: facilities {len(fac[a])} / {len(fac[b])}, both {len(both)}; sentences both {len(sent[a] & sent[b])}")
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "text"]).set_index("claim_id")
    tr = c.loc[list(sent["trauma_emergency"]), "text"]
    explicit = tr.str.contains(r"trauma|polytrauma|accident|injur|fracture|casualty", flags=re.I)
    print(f"trauma_emergency sentences {len(tr)}, with trauma/accident/injury/casualty words {int(explicit.sum())}")
    tf = pos[pos.service == "trauma_emergency"].assign(explicit=lambda d: d.claim_id.map(explicit))
    g = tf.groupby("unique_id").explicit.any()
    print(f"trauma_emergency facilities {len(g)}, with any explicit trauma sentence {int(g.sum())}")


if __name__ == "__main__":
    main()
