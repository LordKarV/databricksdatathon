"""Collect the hand-labelled sentences in the repo into one evaluation set for the evidence reader.

Two targets, one row per (claim, target[, service]):
  about_this  1 = the sentence is about THIS facility, 0 = it is about another facility
  offers      1 = the sentence says the facility offers the service, 0 = it does not (referral,
              plan, negation, another facility, staff history, narrower or different service)

Every row keeps its source file, the row or item it came from, the original label and the mapping
rule used, so a reader can audit it. Rows whose original label does not settle the target
(uncertain, "names another facility" without a harm judgement) are written with label = -1 and
are not used for scoring.

Mapping rules (label_rule column)
  cleaning/claims/handcheck_labels.csv
    A_other_facility   TP -> about_this 0, FP -> about_this 1, U -> -1
    B_ambiguous        other -> about_this 0, own -> about_this 1, others -> -1
    C_unanchored...    plausible_own -> about_this 1, cannot_tell -> -1
    D_nonoffer         correct -> offers 0, false_alarm -> offers 1     (service: every service the sentence matches)
    E_v2_strong        key is a facility-service pair, not a sentence: not used
  audit/merge/handcheck (labels.tsv gives row numbers in each 30-row sample)
    q1_holdout                harmful rows -> about_this 0, FP rows -> about_this 1, other TP rows -> -1
    dev/q1_precision_dev      FP rows -> about_this 1, TP rows -> -1 (no harm judgement recorded)
    q2_holdout                misattribution rows -> about_this 0, FP rows -> about_this 1, others -> -1
    q1_recall_U1, q1_recall_U2 and their dev versions
                              FN rows -> about_this 0, all other rows -> about_this 1
    q3_sample                 likely contamination rows -> about_this 0, legitimate -> 1, uncertain -> -1
  kb/taxonomy/out/handcheck_lexicon_v0.csv, handcheck_lexicon_v1_trauma.csv, handcheck_v1_1_sample.csv
    correct True -> offers 1, False -> offers 0 (criterion in kb/taxonomy/handcheck_lexicon.py:
    "read alone, the sentence says THIS facility provides the service").
    Two exceptions where 'correct' means the lexicon was right to reject the sentence, so the
    offers label is inverted: the clause_veto set of handcheck_v1_1_sample.csv, and rows that carry
    a non-offer cue ("a sentence the lexicon flags with a non-offer cue counts as handled").

service_canonical is the service id in the current taxonomy (kb/taxonomy/services.json). Rows
labelled under the old 'trauma_emergency' tag go to emergency_24x7 when the sentence matches that
service's pattern, else to trauma_care, because the old tag covered both.

Output: model/reader/eval/eval_set.csv and eval_set_stats.json
Run: .venv/bin/python model/reader/build_eval.py
"""
import json
from pathlib import Path

import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Lexicon  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).resolve().parent / "eval"
FIELD4 = {"procedure": "proc", "capability": "capa", "equipment": "equi", "description": "desc"}

# row numbers copied from audit/merge/handcheck/labels.tsv (1-based within each 30-row sample)
MERGE = {
    "q1_holdout.tsv": {"zero": [1, 2, 3, 5, 9, 13, 21, 23, 26, 28, 30], "one": [4, 22, 6, 11, 16, 17, 18, 29, 25], "rest": -1,
                       "rule": "harmful misattribution -> 0; FP (not another facility) -> 1; other TP -> -1"},
    "dev/q1_precision_dev.tsv": {"zero": [], "one": [5, 7, 12, 13, 14, 15, 19, 27], "rest": -1,
                                 "rule": "FP (not another facility) -> 1; TP -> -1 (no harm judgement)"},
    "q2_holdout.tsv": {"zero": [12, 13, 14, 25, 26, 30], "one": [6, 16, 28], "rest": -1,
                       "rule": "misattribution -> 0; FP -> 1; chain, credential, scheme -> -1"},
    "q1_recall_U1.tsv": {"zero": [14], "one": [], "rest": 1, "rule": "FN (names another facility) -> 0; rest -> 1"},
    "q1_recall_U2.tsv": {"zero": [5, 17, 29, 30], "one": [], "rest": 1, "rule": "FN (names another facility) -> 0; rest -> 1"},
    "dev/q1_recall_U1_dev.tsv": {"zero": [5], "one": [], "rest": 1, "skip": [14],
                                 "rule": "FN -> 0; row 14 uncertain -> -1; rest -> 1"},
    "dev/q1_recall_U2_dev.tsv": {"zero": [24, 26, 4, 15, 29], "one": [], "rest": 1, "rule": "FN (names another facility) -> 0; rest -> 1"},
    "q3_sample.tsv": {"zero": [1, 3, 22, 28, 5, 10, 15, 16, 23, 29], "one": [], "rest": 1, "skip": [7, 27, 19],
                      "rule": "likely contamination -> 0; uncertain -> -1; legitimate -> 1"},
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    claims = pd.read_parquet(ROOT / "derived/v1/claims.parquet", columns=["claim_id", "unique_id", "field", "idx", "text", "services"])
    by_id = claims.set_index("claim_id")
    by_text = claims.drop_duplicates(["unique_id", "text"]).set_index(["unique_id", "text"]).claim_id
    rows = []

    def add(claim_id, target, label, src, item, orig, rule, service=None, note=""):
        rows.append({"claim_id": claim_id, "target": target, "service_id": service, "label": label, "source_file": src,
                     "source_item": item, "original_label": orig, "label_rule": rule, "note": note})

    # 1. cleaning/claims hand check
    src = "cleaning/claims/handcheck_labels.csv"
    lab = pd.read_csv(ROOT / src).fillna("")
    amap = {("A_other_facility", "TP"): 0, ("A_other_facility", "FP"): 1, ("B_ambiguous", "other"): 0, ("B_ambiguous", "own"): 1,
            ("C_unanchored_in_contaminated_record", "plausible_own"): 1}
    for r in lab.itertuples():
        if r.sample in ("A_other_facility", "B_ambiguous", "C_unanchored_in_contaminated_record"):
            add(r.key, "about_this", amap.get((r.sample, r.label), -1), src, f"{r.sample}:{r.item}", r.label,
                "see module docstring", note=r.note)
        elif r.sample == "D_nonoffer":
            svcs = (by_id.services.get(r.key) or "").split("|") if r.key in by_id.index else [""]
            for s in svcs:
                add(r.key, "offers", {"correct": 0, "false_alarm": 1}.get(r.label, -1), src, f"{r.sample}:{r.item}", r.label,
                    "non-offer cue correct -> 0; false alarm -> 1", service=s or None, note=r.note)

    # 2. audit/merge hand checks (labels by row number)
    for name, spec in MERGE.items():
        src = f"audit/merge/handcheck/{name}"
        d = pd.read_csv(ROOT / src, sep="\t", dtype=str).fillna("")
        for i, r in enumerate(d.itertuples(), start=1):
            if "idx" in d.columns and "field" in d.columns:
                cid = f"{r.unique_id[:8]}:{FIELD4.get(r.field, r.field[:4])}:{r.idx}"
            else:
                cid = by_text.get((r.unique_id, r.text))
            label = 0 if i in spec["zero"] else 1 if i in spec["one"] else -1 if i in spec.get("skip", []) else spec["rest"]
            add(cid, "about_this", label, src, str(i), "", spec["rule"])

    # 3. kb/taxonomy lexicon hand checks
    for name in ("handcheck_lexicon_v0.csv", "handcheck_lexicon_v1_trauma.csv", "handcheck_v1_1_sample.csv"):
        src = f"kb/taxonomy/out/{name}"
        d = pd.read_csv(ROOT / src).astype(object).fillna("")
        for i, r in enumerate(d.itertuples(), start=1):
            ok = str(r.correct) == "True"
            if getattr(r, "set", "") == "clause_veto":
                # here 'correct' means the lexicon's veto was right, i.e. the sentence is NOT an offer
                label, rule = (0 if ok else 1), "clause_veto set: veto correct -> 0; veto wrong -> 1"
            elif getattr(r, "nonoffer_cue", ""):
                # a sentence the lexicon flagged with a non-offer cue was counted as 'handled'
                label, rule = (0 if ok else 1), "flagged non-offer cue: handled correctly -> 0; else 1"
            else:
                label, rule = int(ok), "correct True -> 1; False -> 0"
            add(r.claim_id, "offers", label, src, str(i), str(r.correct), rule, service=r.service, note=r.note)

    e = pd.DataFrame(rows)
    e["in_claims"] = e.claim_id.isin(by_id.index)
    e = e.merge(claims[["claim_id", "unique_id", "text"]], on="claim_id", how="left")
    # service ids as the current taxonomy names them. The older samples used 'trauma_emergency' (or
    # 'trauma') for what the taxonomy has since split into emergency_24x7 and trauma_care, and judged
    # a sentence correct if the facility offers either. Such a row goes to emergency_24x7 when the
    # sentence matches that service's pattern, else to trauma_care.
    lex = Lexicon()

    def canonical(service, text):
        if not isinstance(service, str) or not service:
            return None
        if service in ("trauma_emergency", "trauma"):
            return "emergency_24x7" if isinstance(text, str) and lex.rx["emergency_24x7"]["include"].search(text) else "trauma_care"
        return lex.canon(service)
    e["service_canonical"] = [canonical(s, t) for s, t in zip(e.service_id, e.text)]
    # the same (claim, target, service) can be sampled twice: keep one, and drop it if the labels disagree
    key = ["claim_id", "target", "service_canonical"]
    conflict = e[e.label >= 0].groupby(key, dropna=False).label.nunique()
    n_conflict = int((conflict > 1).sum())
    e = e.sort_values("label", ascending=False).drop_duplicates(key)
    e = e.sort_values(["target", "source_file", "source_item"]).reset_index(drop=True)
    e.to_csv(OUT / "eval_set.csv", index=False)

    use = e[(e.label >= 0) & e.in_claims]
    stats = {"rows": int(len(e)), "usable": int(len(use)), "not_in_claims": int((~e.in_claims).sum()),
             "unsettled_label": int((e.label < 0).sum()), "conflicting_duplicates": n_conflict,
             "facilities": int(use.unique_id.nunique()),
             "by_target": {t: {"n": int(len(g)), "positive": int((g.label == 1).sum()), "negative": int((g.label == 0).sum())}
                           for t, g in use.groupby("target")},
             "by_source": {f"{t} | {s}": {"n": int(len(g)), "positive": int((g.label == 1).sum()), "negative": int((g.label == 0).sum())}
                           for (t, s), g in use.groupby(["target", "source_file"])},
             "offers_by_service": {s: int(n) for s, n in use[use.target == "offers"].service_canonical.value_counts().items()}}
    (OUT / "eval_set_stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
