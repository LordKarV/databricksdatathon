"""20-sentence precision check per core service. Criterion: read alone, the sentence says THIS facility provides the
service (or has its unit or equipment). Wrong: another facility, a staff member's past work, a narrower or different
service, or a non-offer that no lexicon cue flags. A sentence the lexicon flags with a non-offer cue counts as handled.
Usage: python handcheck_lexicon.py <lexicon_matches.parquet> <out_csv> <seed> [services...]
The v0 check (seed 2026) ran on the lexicon before the kb fixes in lexicon_src.KB_FIXES; the v1 check re-samples."""
from __future__ import annotations
import sys
import pandas as pd
from handcheck_specialty_map import wilson

CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
CORE = ["dialysis", "emergency_csection", "nicu", "cardiac_surgery", "mri", "burn_care", "trauma_emergency"]
WRONG = {  # (service, claim_id) -> reason
    ("emergency_csection", "dad3fe96:capa:10"): "'paediatric section' matched c-?section (fixed: \\bc-?section)",
    ("cardiac_surgery", "dec67a52:proc:10"): "peripheral (vascular) bypass, not cardiac (fixed)",
    ("cardiac_surgery", "e0893a32:capa:29"): "'plans to establish' not caught by future cue (fixed)",
    ("burn_care", "07f992f7:capa:2"): "doctor's past experience at PGIMER",
    ("burn_care", "f4b8714b:proc:0"): "minor burns in OPD urgent care, not burn care (fixed)",
    ("trauma_emergency", "db16cac8:capa:16"): "neurosurgery sentence mentioning head trauma",
    ("trauma_emergency", "5de355f7:capa:0"): "cardiac-only emergency (fixed)",
    ("trauma_emergency", "c013e4d7:proc:0"): "obstetric-only emergency (fixed)",
    ("trauma_emergency", "0f6a2352:capa:1"): "affiliation with another trauma centre (fixed)",
    ("trauma_emergency", "fa445a1d:capa:45"): "emergency medicine training programme (fixed)",
    ("trauma_emergency", "22add191:proc:47"): "hand and face trauma (plastic surgery) (fixed)",
    # v1 (after fixes, seed 7, trauma_emergency only)
    ("trauma_emergency", "b86c3180:proc:0"): "home X-ray service listing 'trauma X-ray'",
    ("trauma_emergency", "01bc6107:capa:2"): "doctor's orthopaedic trauma expertise, not an emergency department",
    ("trauma_emergency", "c7a8fbac:capa:8"): "orthopaedic sports-injury care",
}


def main(matches: str, out_csv: str, seed: int, services: list[str]) -> None:
    m = pd.read_parquet(matches).merge(pd.read_parquet(CLAIMS, columns=["claim_id", "text"]), on="claim_id")
    rows = []
    for s in services:
        x = m[m.service == s].sample(20, random_state=seed).assign(service=s)
        rows.append(x)
    r = pd.concat(rows)[["service", "claim_id", "nonoffer_cue", "text"]]
    r["correct"] = [(s, c) not in WRONG for s, c in zip(r.service, r.claim_id)]
    r["note"] = [WRONG.get((s, c), "") for s, c in zip(r.service, r.claim_id)]
    r.to_csv(out_csv, index=False)
    for s, g in r.groupby("service", sort=False):
        k = int(g.correct.sum())
        print(f"{s:20s} {k}/20  Wilson95 {wilson(k, 20)}")
    k, n = int(r.correct.sum()), len(r)
    print(f"all {k}/{n}  Wilson95 {wilson(k, n)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:] or CORE)
