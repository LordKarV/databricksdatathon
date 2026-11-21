"""Independent duplicate candidate generation (own normalization), wider than the finder's strict keys."""
import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
import itertools, collections
from rapidfuzz import fuzz
OUT = "/Users/karthikvattem/projects/datathon/audit/identity/verify/"
d = dedup(wellformed(raw()))
N = len(d)
def nm(s):
    s = str(s or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(the|pvt|private|ltd|limited|llp|and|of|dr|drs|a|unit)\b", " ", s)
    return " ".join(s.split())
d["n"] = d.name.map(nm)
d["c"] = d.address_city.map(lambda v: "" if nul(v) else re.sub(r"[^a-z]", "", v.lower()))
d["p"] = d.address_zipOrPostcode.map(lambda v: (lambda m: m.group(0) if m else "")(re.search(r"[1-9]\d{5}", re.sub(r"\s", "", str(v)))) if not nul(v) else "")
d["dom"] = d.officialWebsite.map(lambda u: "" if nul(u) else re.sub(r"^www\d?\.", "", re.sub(r"^[a-z]+://", "", u.lower().strip()).split("/")[0]))
d["ph"] = [ {x for x in ({digits(p) for p in jlist(l)} | ({digits(o)} if not nul(o) else set())) if len(x) == 10} for l, o in zip(d.phone_numbers, d.officialPhone)]
d["a1"] = d.address_line1.map(lambda v: "" if nul(v) else nm(v))
lat, lon = d.latitude.to_numpy(), d.longitude.to_numpy()
def km(i, j):
    r = np.pi / 180
    h = np.sin((lat[j]-lat[i])*r/2)**2 + np.cos(lat[i]*r)*np.cos(lat[j]*r)*np.sin((lon[j]-lon[i])*r/2)**2
    return 12742*np.arcsin(np.sqrt(h))
P = collections.defaultdict(set)
for col, key in [("n", "eq_name_city"), ("n", "eq_name_pin")]:
    other = "c" if key.endswith("city") else "p"
    for (a, b), idx in d.groupby(["n", other]).indices.items():
        if a and b and len(idx) > 1:
            for i, j in itertools.combinations(sorted(idx), 2): P[(i, j)].add(key)
# geo windows: 0.2 km & tset>=85 (finder's), plus wider 2 km & sort>=90
order = np.argsort(lat)
for a in range(N):
    i = order[a]
    for b in range(a+1, N):
        j = order[b]
        if lat[j] - lat[i] > 0.02: break
        if abs(lon[j]-lon[i]) > 0.025: continue
        k = km(i, j)
        if k < 0.2 and fuzz.token_set_ratio(d.n[i], d.n[j]) >= 85: P[tuple(sorted((i, j)))].add("geo02_tset85")
        if k < 2 and fuzz.token_sort_ratio(d.n[i], d.n[j]) >= 90: P[tuple(sorted((i, j)))].add("geo2_sort90")
        if k < 0.05: P[tuple(sorted((i, j)))].add("geo50m_any")
# same phone with name sort>=80 (phones on <=5 records), same domain + same city, same address_line1+pin
ex = collections.defaultdict(list)
for i, s in enumerate(d.ph):
    for x in s: ex[x].append(i)
for x, idx in ex.items():
    if 2 <= len(idx) <= 5:
        for i, j in itertools.combinations(sorted(set(idx)), 2):
            if fuzz.token_sort_ratio(d.n[i], d.n[j]) >= 80: P[(i, j)].add("phone_sort80")
for (dm, c), idx in d.groupby(["dom", "c"]).indices.items():
    if dm and c and 2 <= len(idx) <= 5:
        for i, j in itertools.combinations(sorted(idx), 2): P[(i, j)].add("dom_city")
for (a1, p), idx in d.groupby(["a1", "p"]).indices.items():
    if len(a1) > 8 and p and 2 <= len(idx) <= 5:
        for i, j in itertools.combinations(sorted(idx), 2): P[(i, j)].add("addr1_pin")
rows = []
for (i, j), ks in P.items():
    rows.append(dict(i=i, j=j, uid_a=d.unique_id[i], uid_b=d.unique_id[j], keys="+".join(sorted(ks)),
        name_a=d.name[i], name_b=d.name[j], city_a=d.address_city[i], city_b=d.address_city[j], pin_a=d.p[i], pin_b=d.p[j],
        km=round(float(km(i, j)), 3), tset=fuzz.token_set_ratio(d.n[i], d.n[j]), sort=fuzz.token_sort_ratio(d.n[i], d.n[j]),
        phone=bool(d.ph[i] & d.ph[j]), dom=bool(d.dom[i]) and d.dom[i] == d.dom[j], addr=fuzz.token_set_ratio(d.a1[i], d.a1[j]),
        type_a=d.facilityTypeId[i], type_b=d.facilityTypeId[j],
        same_claims=(d.procedure[i], d.equipment[i], d.capability[i]) == (d.procedure[j], d.equipment[j], d.capability[j]),
        same_desc=d.description[i] == d.description[j]))
R = pd.DataFrame(rows)
strict = {"eq_name_city", "eq_name_pin", "geo02_tset85"}
R["strict"] = R["keys"].map(lambda k: bool(set(k.split("+")) & strict))
R.to_csv(OUT + "v_pairs.csv", index=False)
print("total candidate pairs", len(R))
for k in ["eq_name_city", "eq_name_pin", "geo02_tset85", "geo2_sort90", "geo50m_any", "phone_sort80", "dom_city", "addr1_pin"]:
    print(k, R["keys"].str.contains(k).sum())
print("strict pairs", R.strict.sum())
# strict components
par = list(range(N))
def f(x):
    while par[x] != x: par[x] = par[par[x]]; x = par[x]
    return x
for r in R[R.strict].itertuples(): par[f(r.i)] = f(r.j)
g = pd.Series([f(i) for i in range(N)]); vc = g.value_counts(); vc = vc[vc > 1]
print("strict groups", len(vc), "records", vc.sum(), "sizes", vc.value_counts().to_dict())
pd.DataFrame({"unique_id": d.unique_id, "grp": g.where(g.isin(vc.index))}).to_csv(OUT + "v_strict_groups.csv", index=False)
nonstrict = R[~R.strict]
print("non-strict pairs", len(nonstrict))
print("non-strict, name sort>=90 & (phone|dom|addr>=70) & km<5:", ((nonstrict["sort"] >= 90) & (nonstrict.phone | nonstrict.dom | (nonstrict.addr >= 70)) & (nonstrict.km < 5)).sum())
print("same_claims among all pairs", R.same_claims.sum(), "same_desc", R.same_desc.sum())
