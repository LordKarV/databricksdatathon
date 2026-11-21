"""Q4 provenance contamination, controlled for record size (distinct source URL count bins).
Needs out/record_scores.parquet from analyze.py."""
import pandas as pd, numpy as np
r = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/record_scores.parquet")
r["nurl"] = r.source_urls.map(lambda x: len(set(__import__("common").parse_list(x))))
r["bin"] = pd.cut(r.nurl, [-1, 2, 7, 14, 29, 10**6], labels=["0-2", "3-7", "8-14", "15-29", "30+"])
r["contam"] = r.n_q.fillna(0) > 0
r["foreign"] = r.n_foreign.fillna(0) > 0
print("contamination by url-count bin:", r.groupby("bin", observed=True).contam.mean().round(3).to_dict())
rows = []
for cat in ["gov", "railway", "wikipedia", "wikipedia_list", "empanelment_insurance", "research_or_document", "directory"]:
    r["has"] = r.cats.map(lambda c: cat in list(c))
    num = den = numq = 0.0
    for b, g in r.groupby("bin", observed=True):
        a, o = g[g.has], g[~g.has]
        if len(a) and len(o):
            # expected rate for these records if they behaved like same-size records without the category
            num += a.contam.sum(); den += len(a) * o.contam.mean()
            numq += a.q_share.sum() / max(len(a) * o.q_share.mean(), 1e-9) * len(a)
    na = int(r.has.sum())
    rows.append((cat, na, int(r[r.has].contam.sum()), round(num / den, 2), round(numq / na, 2)))
print(pd.DataFrame(rows, columns=["category", "records", "contam_records", "observed/expected contam (size-adjusted)",
                                  "observed/expected q_share (size-adjusted)"]).to_string(index=False))
