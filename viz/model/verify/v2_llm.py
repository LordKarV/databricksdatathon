"""Independent recomputation of story 2 (LLM judge vs ledger). No labels; AUROCs only read from results.json.

Run: .venv-viz/bin/python viz/model/verify/v2_llm.py
"""
import json
import math
from pathlib import Path

import pandas as pd

R = Path("/Users/karthikvattem/projects/datathon")
llm = pd.read_parquet(R / "model/proto/decision/llm_b3_pairs.parquet")
ps = pd.read_parquet(R / "model/proto/fusion/pair_scores.parquet")


def wilson(k, n, z=1.959964):
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(c - h, 4), round(c + h, 4)


print("rows", len(llm), "distinct facilities", llm.unique_id.nunique(), "queries", llm.query_id.nunique(),
      "dup (query,uid)", llm.duplicated(["query_id", "unique_id"]).sum())
print("offers", llm.offers.value_counts().to_dict(), "raw-json offers agree:",
      (llm.raw.map(lambda s: json.loads(s)["offers"]) == llm.offers).mean())
y = (llm.offers == "yes").sum()
print("yes", y, "of", len(llm), f"{y / len(llm):.4f}", "wilson", wilson(y, len(llm)))
print("confidence counts", llm.confidence.value_counts().sort_index().to_dict(),
      "conf==1 among yes", int(((llm.confidence == 1) & (llm.offers == "yes")).sum()))
d = llm.merge(ps, on=["unique_id", "service"], how="left")
assert d.p_s.notna().all()
print("P_S range", round(d.p_s.min(), 4), round(d.p_s.max(), 4))
for t in range(6):
    g = d[d["T"] == t]
    print(f"T={t}: yes {(g.offers == 'yes').sum()} of {len(g)}")
for lab, m in (("C>=1", d.C >= 1), ("S>=1", d.S >= 1), ("band Unlikely", d.band == "Unlikely"), ("P_S<=0.20", d.p_s <= 0.20)):
    g = d[m]
    print(f"{lab}: yes {(g.offers == 'yes').sum()} of {len(g)}")
print("no rows:", d[d.offers == "no"][["name", "service", "T", "p_s", "confidence"]].round(3).values.tolist())
ex = d[d.name.str.contains("Deshmukh Eye")]
print("Deshmukh:", ex[["service", "offers", "confidence", "quote", "p_s", "S", "band"]].to_dict("records"))
# spread of P_S among yes at conf 1: does the LLM rank anything? (no labels involved)
y1 = d[(d.offers == "yes") & (d.confidence == 1)]
print("P_S among LLM yes conf 1: n", len(y1), "p10/p50/p90", y1.p_s.quantile([.1, .5, .9]).round(3).tolist())
print("non-ASCII bytes in quotes:", sum(sum(ord(ch) > 127 for ch in str(q)) for q in d.quote))
r = json.loads((R / "model/review/stats/results.json").read_text())["pair_level_test"]
a = r["primary_target_all"]["auroc"]
for k in ("B3_llm_judge", "WL_shipped"):
    print(k, a[k]["raw"], a[k]["raw_boot"]["ci95"])
print("paired WL-B3", r["paired_diff_raw_primary"]["B3_llm_judge"])
print("searched-39 B3", r["primary_target_searched"]["auroc"]["B3_llm_judge"])
