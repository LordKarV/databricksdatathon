"""Hand check of extracted facts.

`sample`: draw 50 usable text facts (status ok or flagged, polarity positive, method regex or llm), stratified by
fact type with a fixed seed, and write out/handcheck_sample.csv with the facility name and full sentence.
`score`: read handcheck_labels.csv (fact_id, correct 1/0, note) and write out/handcheck.json with precision and
95% Wilson intervals, overall and per fact type.
A fact is correct when its type, attribute, value and polarity are what the sentence says, and the sentence
states it about this facility now (not a chain total, a past or planned state, a person's career or a directory).
Web truth is not checked here.
"""
from __future__ import annotations

import json
import math
import os
import sys

import pandas as pd

D = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(D, "out")
ALLOC = {"hours_24x7": 6, "unit_beds": 6, "empanelment": 6, "staffing": 5, "accreditation": 5, "ambulance": 4, "free_or_government": 4,
         "blood_centre": 4, "equipment_count": 4, "opd_hours": 4, "hours_dialysis_shifts": 2}
SEED = 20261121


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(c - h, 3), round(c + h, 3)


def sample() -> None:
    f = pd.read_parquet(os.path.join(OUT, "facts.parquet"))
    u = f[f.status.isin(["ok", "flagged"]) & (f.polarity == "positive") & f.method.isin(["regex", "llm"])]
    names = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/facilities.parquet", columns=["unique_id", "name"]).drop_duplicates("unique_id")
    parts = []
    for t, n in ALLOC.items():
        g = u[u.fact_type == t]
        if t == "opd_hours":  # make sure LLM-read schedules are in the check
            parts.append(g[g.method == "llm"].sample(1, random_state=SEED))
            g, n = g[g.method == "regex"], n - 1
        parts.append(g.sample(min(n, len(g)), random_state=SEED))
    s = pd.concat(parts).merge(names, on="unique_id", how="left")
    s[["fact_id", "name", "fact_type", "attribute", "value_num", "value_text", "status", "flags", "method", "quote", "source_text"]].to_csv(
        os.path.join(OUT, "handcheck_sample.csv"), index=False)
    print(len(s))


def score() -> None:
    lab = pd.read_csv(os.path.join(D, "handcheck_labels.csv"))
    s = pd.read_csv(os.path.join(OUT, "handcheck_sample.csv")).merge(lab, on="fact_id", how="inner")
    assert len(s) == len(lab) == 50, (len(s), len(lab))
    k, n = int(s.correct.sum()), len(s)
    res = {"n": n, "correct": k, "precision": round(k / n, 3), "wilson95": wilson(k, n), "by_type": {}, "by_status": {}}
    for col, key in (("fact_type", "by_type"), ("status", "by_status")):
        for t, g in s.groupby(col):
            res[key][t] = {"n": len(g), "correct": int(g.correct.sum()), "wilson95": wilson(int(g.correct.sum()), len(g))}
    res["errors"] = s[s.correct == 0][["fact_id", "fact_type", "attribute", "note"]].to_dict("records")
    json.dump(res, open(os.path.join(OUT, "handcheck.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    assert wilson(45, 50) == (0.786, 0.957), wilson(45, 50)
    {"sample": sample, "score": score}[sys.argv[1]]()
