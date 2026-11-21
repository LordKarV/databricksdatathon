"""v1.1 precision re-checks after the review fixes.

Stage 1 (python handcheck_v1_1.py sample): draws the samples into out/handcheck_v1_1_sample.csv:
  - new: 20 random positive matches (seed 1111) for each new or split service;
  - recovered: sentences the fixes added (emergency_24x7 vs the claims.parquet trauma tag, psychiatric_care,
    ultrasound and dialysis vs v1.0), up to 20 / 10 / 10 / all;
  - clause_veto: emergency_24x7 sentences vetoed only by the new clause-level rule (10);
  - rescore: the builder's 140-sentence v0 sample and the reviewer's 40-sentence sample re-matched with the new lexicon.
Stage 2 (python handcheck_v1_1.py score): applies the author's verdicts (WRONG below; every row not listed is correct)
and prints precision with 95% Wilson intervals. Doctor names are masked in stored text.
Criterion (same as v1.0): read alone, the sentence says THIS facility provides the service or has its unit or equipment.
For clause_veto rows, 'correct' means the veto was right (the sentence is not a general 24x7 emergency offer).
"""
from __future__ import annotations

import os
import re
import sys

import pandas as pd

import lexicon_src as LS
from handcheck_specialty_map import wilson

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
CLAIMS = "/Users/karthikvattem/projects/datathon/cleaning/claims/out/claims.parquet"
SAMPLE = os.path.join(OUT, "handcheck_v1_1_sample.csv")
NEW = ["emergency_24x7", "trauma_care", "stemi_thrombolysis", "paediatric_inpatient", "safe_abortion_mtp"]
DR = re.compile(r"\bDr\.?\s+[A-Z][\w.]*(\s+[A-Z][\w.]*){0,2}")

# (set, "claim_id|service") -> reason. Verdicts on the final sample (after the round-1 fixes listed in TAXONOMY.md).
WRONG: dict[tuple[str, str], str] = {
    ("new", "6c7797e4:capa:26|trauma_care"): "company name contains 'Trauma Care Centre'; no trauma service stated",
    ("new", "88263303:desc:3|trauma_care"): "emotional trauma of infertility",
    ("new", "1fc510fc:capa:46|paediatric_inpatient"): "historic: a ward added by 1923",
    ("new", "75dc9676:capa:32|paediatric_inpatient"): "future ('will include'); future cue does not fire on 'will include'",
    ("new", "e67e983b:capa:29|safe_abortion_mtp"): "states compliance with the MTP Act, not that MTP is offered",
    ("recovered", "accc6b79:desc:0|emergency_24x7"): "directory template 'Emergency: Yes' on a gynaecology and eye clinic",
    ("recovered", "e144639d:capa:26|emergency_24x7"): "postgraduate seat intake, not a service (fixed after the check)",
    ("recovered", "d6070c03:capa:17|emergency_24x7"): "postgraduate degrees offered, not a service (fixed after the check)",
    ("recovered", "017a80f7:capa:29|psychiatric_care"): "doctor's past post at another college",
    ("recovered", "d6ed2253:proc:5|dialysis"): "AV fistula access surgery; 'Centre' in a hospital name defeats the unit-word guard",
}
EXPLICIT_THROMBOLYSIS = r"thromboly|tenecteplase|streptokinase|reteplase"


def mask(t: str) -> str:
    return DR.sub("Dr [name]", t)


def sample() -> None:
    c = pd.read_parquet(CLAIMS, columns=["claim_id", "text", "services"])
    m = pd.read_parquet(os.path.join(OUT, "lexicon_matches.parquet"))
    pos = m[(m.nonoffer_cue == "") & ~m.negation_extra & (m.attribution != "other_facility") & ~m.kind.isin(["staff", "directory"])]
    old = pd.read_parquet(os.path.join(OUT, "v1_0", "lexicon_matches.parquet"))
    rows = [pos[pos.service == s].sample(min(20, (pos.service == s).sum()), random_state=1111).assign(set="new") for s in NEW]
    trauma_old = set(c.claim_id[c.services.str.contains("trauma")])
    ed = pos[(pos.service == "emergency_24x7") & ~pos.claim_id.isin(trauma_old)]
    rows.append(ed.sample(20, random_state=1111).assign(set="recovered"))
    for s, n in [("psychiatric_care", 10), ("ultrasound", 10), ("dialysis", 99)]:
        new = pos[(pos.service == s) & ~pos.claim_id.isin(set(old.claim_id[old.service == s]))]
        rows.append(new.sample(min(n, len(new)), random_state=1111).assign(set="recovered"))
    comp = LS.compile_specs(LS.all_specs())
    e = comp["emergency_24x7"]
    t = c[c.text.str.contains(e["include"]) & ~c.text.str.contains(e["exclude"])]
    veto = t[[not LS.clause_ok(x, e["include"], e["exclude_clause"]) for x in t.text]]
    print(f"emergency_24x7 clause-level vetoes: {len(veto)} sentences")
    rows.append(veto.sample(10, random_state=1111).assign(set="clause_veto", service="emergency_24x7")[["claim_id", "service", "set"]])
    s = pd.concat(rows)[["set", "service", "claim_id"]].merge(c[["claim_id", "text"]], on="claim_id")
    # re-score the earlier samples: does the new lexicon still match them?
    v0 = pd.read_csv(os.path.join(OUT, "handcheck_lexicon_v0.csv")).assign(set="rescore_v0")
    v0["service"] = v0.service.replace({"trauma_emergency": "emergency_24x7"})
    r40 = pd.read_csv(os.path.join(D, "review", "lexicon_sample40.csv")).assign(set="rescore_review40")
    print("review40 columns:", list(r40.columns))
    s["text"] = s.text.map(mask)
    s.to_csv(SAMPLE, index=False)
    for x in (v0,):
        x["now_matched"] = [sv in LS.match(t, comp) for sv, t in zip(x.service, x.text)]
        print(x.groupby(["service", "correct", "now_matched"]).size().to_string())
        for r in x[~x.now_matched].itertuples():
            print("  NO LONGER MATCHED", r.service, r.correct, r.claim_id, r.text[:160])


def score() -> None:
    s = pd.read_csv(SAMPLE)
    s["correct"] = [(st, f"{cid}|{sv}") not in WRONG for st, cid, sv in zip(s.set, s.claim_id, s.service)]
    s["note"] = [WRONG.get((st, f"{cid}|{sv}"), "") for st, cid, sv in zip(s.set, s.claim_id, s.service)]
    s.to_csv(SAMPLE, index=False)
    for (st, sv), g in s.groupby(["set", "service"], sort=False):
        k, n = int(g.correct.sum()), len(g)
        print(f"{st:12s} {sv:22s} {k}/{n}  Wilson95 {wilson(k, n)}")
    st_ = s[(s.set == "new") & (s.service == "stemi_thrombolysis")]
    print(f"stemi_thrombolysis sample sentences that name thrombolysis or a thrombolytic: {int(st_.text.str.contains(EXPLICIT_THROMBOLYSIS, case=False).sum())}/{len(st_)}")
    for st, g in s.groupby("set", sort=False):
        k, n = int(g.correct.sum()), len(g)
        print(f"{st:12s} {'all':22s} {k}/{n}  Wilson95 {wilson(k, n)}")


if __name__ == "__main__":
    {"sample": sample, "score": score}[sys.argv[1]]()
