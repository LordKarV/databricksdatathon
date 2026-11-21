"""ID9 verbatim cross-city sentences; ID11 tertiary claims at small chain sites. Own brand list."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
import collections
d = dedup(wellformed(raw()))
exec(open("/Users/karthikvattem/projects/datathon/audit/identity/verify/v_id9_id10.py").read().split("d[\"chain\"] =")[0].split("brands = ")[1].join(["brands = ", ""]) if False else "")
brands = open("/Users/karthikvattem/projects/datathon/audit/identity/verify/v_id9_id10.py").read().split('brands = r"')[1].split('"\n')[0]
d["chain"] = d.name.str.lower().str.contains(brands, regex=True)
d["c"] = d.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
ns = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()
S = [(i, ns(s)) for i, r in d.iterrows() for f in ["procedure", "equipment", "capability"] for s in jlist(r[f])]
S = pd.DataFrame(S, columns=["i", "ns"])
S["c"] = S.i.map(d.c)
agg = S.groupby("ns").agg(nrec=("i", "nunique"), ncity=("c", "nunique"))
S = S.join(agg, on="ns")
dist = S[(S.ns.str.len() >= 40) & (S.nrec <= 10) & (S.ncity >= 2)]
has = d.index.isin(dist.i)
withc = d.index.isin(S.i)
for lab, m in [("chain", d.chain.values), ("non-chain", ~d.chain.values)]:
    base = m & withc
    print(f"ID9 verbatim distinctive cross-city: {lab} {int((has & base).sum())}/{int(base.sum())} ({(has & base).sum()/base.sum():.1%})")
# ID11
T = {"transplant": r"(kidney|renal|liver|heart|lung|bone marrow|stem cell|organ) transplant",
     "cardiac_surgery": r"cardiac surg|cardiothoracic|\bcabg\b|bypass surg|open heart|valve replacement",
     "cath_lab": r"cath(eterization)? ?lab|angioplasty|\bptca\b"}
small = d.facilityTypeId.isin(["clinic", "dentist", "doctor", "farmacy"]) | d.name.str.lower().str.contains(r"clinic|diagnostic|\blabs?\b|dental|collection")
txt = d.apply(lambda r: " ".join(jlist(r.procedure) + jlist(r.capability) + jlist(r.equipment)).lower(), axis=1)
for k, p in T.items():
    h = txt.str.contains(p, regex=True)
    a, b = (small & d.chain), (small & ~d.chain)
    print(f"ID11 {k}: chain small {int((a & h).sum())}/{int(a.sum())} ({(a & h).sum()/a.sum():.1%}) vs non-chain small {int((b & h).sum())}/{int(b.sum())} ({(b & h).sum()/b.sum():.1%})")
neg = txt.str.contains(r"(does not|do not|doesn't|no) (perform|offer|provide)[^.]{0,40}(bypass|transplant|surgery)", regex=True)
print("records with a negated tertiary sentence (all types):", int(neg.sum()))
