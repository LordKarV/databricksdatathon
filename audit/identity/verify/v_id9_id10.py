"""ID9/ID10: claim sentences naming another city. Own gazetteer, plus a distance-filtered variant
and an education-sentence filter; chain vs non-chain with a text-volume control."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
V = "/Users/karthikvattem/projects/datathon/audit/identity/verify/"
d = dedup(wellformed(raw()))
N = len(d)
low = lambda v: "" if nul(v) else re.sub(r"[^a-z ]", " ", str(v).lower())
d["c"] = d.address_city.map(lambda v: re.sub(r"\s+", " ", low(v)).strip())
ALIAS = {"bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "madras": "chennai", "calcutta": "kolkata",
         "trivandrum": "thiruvananthapuram", "calicut": "kozhikode", "vizag": "visakhapatnam", "cochin": "kochi",
         "poona": "pune", "mysore": "mysuru", "baroda": "vadodara", "new delhi": "delhi", "shimoga": "shivamogga",
         "secunderabad": "hyderabad", "navi mumbai": "mumbai", "thane": "mumbai"}
can = lambda c: ALIAS.get(c, c)
vc = d.c.value_counts()
GAZ = sorted({c for c in vc[vc >= 25].index if len(c) >= 5} | set(ALIAS) | set(ALIAS.values()), key=len, reverse=True)
rx = re.compile(r"\b(" + "|".join(map(re.escape, GAZ)) + r")\b")
# centroid of each canonical gazetteer city = median coords of records stating it
d["cc"] = d.c.map(can)
cent = d[d.cc.isin({can(g) for g in GAZ})].groupby("cc")[["latitude", "longitude"]].median()
def km(a1, o1, a2, o2):
    r = np.pi / 180
    h = np.sin((a2-a1)*r/2)**2 + np.cos(a1*r)*np.cos(a2*r)*np.sin((o2-o1)*r/2)**2
    return 12742*np.arcsin(np.sqrt(h))
EDU = re.compile(r"\b(mbbs|m\.?d\.?|m\.?s\.?|dnb|frcs|mrcp|fellowship|trained|graduat|alumn|degree|studied|completed|residency|formerly|previously|worked)\b", re.I)
brands = r"\bapollo\b|\bfortis\b|manipal hospital|\bmax (super|smart|healthcare|hospital|lab)|narayana|\bcare hospital|yashoda|medanta|\bkims\b|\baster\b|\bhcg\b|asg eye|agarwal|sankara|indira ivf|nova ivf|cloudnine|motherhood|\bparas\b|kauvery|rainbow|shalby|wockhardt|\besic?\b|redcliffe|pathkind|agilus|sabka dentist|clove dental|partha dental|saaol|columbia asia|gleneagles|global hospital|medicover|sparsh|ujala cygnus|vasan|maxivision|dr batra|metropolis|\bsrl\b|thyrocare|lal path|healthians|ruby hall|lilavati|jupiter hospital|sahyadri|kokilaben|zoi hospital|homeocare|seeds of innocens|oasis fertility|birla fertility|bloom ivf|nephroplus|cygnus|sunshine hospital|centre for sight"
d["chain"] = d.name.str.lower().str.contains(brands, regex=True)
rows = []
for i, r in d.iterrows():
    own_txt = " ".join(low(r[k]) for k in ["address_city", "address_line1", "address_line2", "address_line3", "address_stateOrRegion", "name"])
    mine = {can(m) for m in rx.findall(re.sub(r"\s+", " ", own_txt))} | {r.cc}
    for f in ["procedure", "equipment", "capability"]:
        for s in jlist(r[f]):
            hits = {can(m) for m in rx.findall(re.sub(r"\s+", " ", low(s)))} - mine
            if not hits: continue
            far = [h for h in hits if h in cent.index and not np.isnan(r.latitude) and km(r.latitude, r.longitude, *cent.loc[h]) > 40]
            rows.append(dict(i=i, uid=r.unique_id, name=r["name"], city=r.address_city, chain=r.chain, field=f, text=s,
                             hits=";".join(sorted(hits)), far=";".join(sorted(far)), edu=bool(EDU.search(s))))
X = pd.DataFrame(rows); X.to_csv(V + "v_foreign_city.csv", index=False)
nsent = d.apply(lambda r: sum(len(jlist(r[f])) for f in ["procedure", "equipment", "capability"]), axis=1)
print("gazetteer size", len(GAZ))
print("ID10 raw: sentences", len(X), "records", X.i.nunique(), "of", N, f"({X.i.nunique()/N:.1%})")
Xf = X[(X.far != "") & ~X.edu]
print("ID10 filtered (mentioned city >40 km from record coords, non-education): sentences", len(Xf), "records", Xf.i.nunique(), f"({Xf.i.nunique()/N:.1%})")
for lab, m in [("chain", d.chain), ("non-chain", ~d.chain)]:
    n = m.sum(); a = X[X.i.isin(d.index[m])].i.nunique(); b = Xf[Xf.i.isin(d.index[m])].i.nunique()
    print(f"  {lab}: records {n}, raw {a} ({a/n:.1%}), filtered {b} ({b/n:.1%}), sentences per record {nsent[m].mean():.1f}")
# text-volume control: stratify by sentence-count quartile
q = pd.qcut(nsent, 4, labels=False, duplicates="drop")
hit = pd.Series(d.index.isin(Xf.i), index=d.index)
print("filtered hit rate by sentence-count quartile (chain vs non-chain):")
for k in sorted(q.unique()):
    m = q == k
    print(f"  q{k} range {nsent[m].min()}-{nsent[m].max()}: chain {hit[m & d.chain].mean():.1%} (n={int((m & d.chain).sum())}) non-chain {hit[m & ~d.chain].mean():.1%} (n={int((m & ~d.chain).sum())})")
print("sentence-level filtered rate: chain", round(len(Xf[Xf.chain]) / nsent[d.chain].sum(), 4), "non-chain", round(len(Xf[~Xf.chain]) / nsent[~d.chain].sum(), 4))
print("edu sentences among raw", X.edu.sum())
X.sample(20, random_state=7)[["name", "city", "hits", "far", "edu", "text"]].to_csv(V + "v_foreign_city_sample20.csv", index=False)
