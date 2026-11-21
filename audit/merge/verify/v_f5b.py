"""F5 mechanism probe: do records that share a seed page (source_content_id) carry text naming another member of the
same group? And is the shared-page contamination gap explained by record size (URL-count bins)?"""
import json, os, re
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
M = "/Users/karthikvattem/projects/datathon/audit/merge/out"
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
s = pd.read_parquet(f"{D}/out/sent.parquet")
q = pd.read_parquet(f"{M}/sentence_decisions.parquet").groupby("unique_id").quarantine.any()
gsize = rec.groupby("source_content_id").source_content_id.transform("size")
shared = rec[gsize > 1]
norm = lambda x: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(x).lower())).strip()
txt = s.groupby("unique_id").text.agg(lambda x: norm(" ".join(x)))
hit = 0
for k, g in shared.groupby("source_content_id"):
    names = {u: norm(n) for u, n in g.name.items()}
    for u in g.index:
        t = txt.get(u, "")
        if any(len(n) >= 12 and n != names[u] and n not in names[u] and n in t for v, n in names.items() if v != u):
            hit += 1
print("shared-seed records", len(shared), "whose text names another member of the same group:", hit)
def pl(v):
    try:
        x = json.loads(v); return [i for i in x if isinstance(i, str) and i.strip()] if isinstance(x, list) else []
    except Exception:
        return []
r = pd.DataFrame({"shared": gsize > 1, "contam": rec.index.map(q).to_numpy().astype(bool),
                  "nurl": rec.source_urls.map(lambda v: len(set(pl(v))))}, index=rec.index)
r["bin"] = pd.cut(r.nurl, [-1, 2, 7, 14, 29, 10**6])
num = den = 0
for b, g in r.groupby("bin", observed=True):
    a, o = g[g.shared], g[~g.shared]
    if len(a) and len(o):
        num += a.contam.sum(); den += len(a) * o.contam.mean()
print(f"shared-seed contam raw {r[r.shared].contam.mean():.3f} vs {r[~r.shared].contam.mean():.3f}; size-adjusted observed/expected {num/den:.2f}")
print("median distinct URLs: shared", r[r.shared].nurl.median(), "not shared", r[~r.shared].nurl.median())
