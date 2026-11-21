"""F5 independent re-derivation: provenance categories (my own URL rules for gov and wikipedia), URL-count bins,
size-adjusted ratios, the mechanical effect of record size, and the shared-seed-page claim."""
import json, os, re
from collections import Counter
from urllib.parse import urlparse
import pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
s = pd.read_parquet(f"{D}/out/sent.parquet")
dec = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentence_decisions.parquet")
def pl(v):
    try:
        x = json.loads(v); return [i.strip() for i in x if isinstance(i, str) and i.strip()] if isinstance(x, list) else []
    except Exception:
        return []
urls = rec.source_urls.map(lambda v: sorted(set(pl(v))))
host = urls.map(lambda l: {urlparse(u).netloc.lower().removeprefix("www.") for u in l})
gov = host.map(lambda h: any(x.endswith(".gov.in") or x.endswith(".nic.in") for x in h))
wiki = host.map(lambda h: any("wikipedia.org" in x for x in h))
nq = dec.groupby("unique_id").quarantine.sum()
ns_ = s.groupby("unique_id").size()
contam = rec.index.map(lambda u: nq.get(u, 0) > 0).to_numpy()
r = pd.DataFrame({"nurl": urls.map(len), "gov": gov, "wiki": wiki, "contam": contam, "nq": rec.index.map(lambda u: nq.get(u, 0)),
                  "ns": rec.index.map(lambda u: ns_.get(u, 0))}, index=rec.index)
print("baseline contam", int(r.contam.sum()), "of", len(r))
for c in ("gov", "wiki"):
    print(f"{c}: n={int(r[c].sum())} contam {r[r[c]].contam.mean():.3f} vs {r[~r[c]].contam.mean():.3f}")
r["bin"] = pd.cut(r.nurl, [-1, 2, 7, 14, 29, 10**6], labels=["0-2", "3-7", "8-14", "15-29", "30+"])
t = r.groupby("bin", observed=True).agg(n=("contam", "size"), contam=("contam", "mean"), sent=("ns", "mean"), q=("nq", "sum"), S=("ns", "sum"))
t["per_sentence_q_rate"] = t.q / t.S
print(t.round(4).to_string())
for c in ("gov", "wiki"):
    num = den = 0
    for b, g in r.groupby("bin", observed=True):
        a, o = g[g[c]], g[~g[c]]
        if len(a) and len(o):
            num += a.contam.sum(); den += len(a) * o.contam.mean()
    print(f"{c} size-adjusted observed/expected {num/den:.2f}")
# mechanical check: if each sentence were quarantined independently at the clean-record base rate p, how much of
# the size gradient would appear anyway? p = overall per-sentence rate in the 3-7 bin
p = float(t.loc["3-7", "per_sentence_q_rate"])
r["p_any_if_const"] = 1 - (1 - p) ** r.ns
print("expected any-quarantine at constant per-sentence rate:", r.groupby("bin", observed=True).p_any_if_const.mean().round(3).to_dict())
# shared seed pages: does every group of >1 record share at least one URL across all members?
grp = rec.groupby("source_content_id").groups
sizes, ok, examples = 0, 0, []
for k, idx in grp.items():
    if len(idx) < 2:
        continue
    sizes += 1
    common = set.intersection(*(set(urls[u]) for u in idx))
    ok += bool(common)
    if len(idx) >= 20:
        examples.append((len(idx), sorted(common)[:1], Counter(rec.address_stateOrRegion[list(idx)]).most_common(2)))
print("shared groups", sizes, "with a URL common to all members", ok)
print("largest groups", sorted(examples, reverse=True)[:3])
