"""Q1: candidate duplicate groups by five keys, union-find, and a rule-based class per group.
Writes out/dup_pairs.csv (one row per linked pair and key) and out/dup_groups.csv."""
import itertools, collections
import numpy as np, pandas as pd
from rapidfuzz import fuzz
from common import load, OUT, norm_phone, domain, haversine

df = load()
df = df.drop_duplicates("unique_id").reset_index(drop=True)  # 11 exact duplicate rows (q5)
N = len(df)
print("rows after dropping exact unique_id duplicates:", N)

df["dom"] = df.officialWebsite.map(domain)
df["phones"] = [sorted({norm_phone(p)[0] for p in ([o] if o else []) + l if norm_phone(p)[1] != "invalid"})
                for o, l in zip(df.officialPhone, df.phone_numbers_l)]
df["ophone"] = df.officialPhone.map(lambda p: norm_phone(p)[0] if p and norm_phone(p)[1] != "invalid" else None)

pairs = collections.defaultdict(set)  # (i, j) -> set of keys


def link_by(col, key, max_group=None):
    sub = df.dropna(subset=[col])
    big = 0
    for k, pos in sub.groupby(col).indices.items():
        idx = sub.index[pos]  # positions in sub -> labels in df
        if len(idx) < 2 or k == "":
            continue
        if max_group and len(idx) > max_group:
            big += 1
            continue
        for i, j in itertools.combinations(sorted(idx), 2):
            pairs[(i, j)].add(key)
    return big


df["k_name_city"] = np.where(df.nname.ne("") & df.ncity.ne(""), df.nname + "|" + df.ncity, None)
df["k_name_pin"] = np.where(df.nname.ne("") & df.pin.notna(), df.nname + "|" + df.pin.fillna(""), None)
link_by("k_name_city", "name_city")
link_by("k_name_pin", "name_pin")
link_by("ophone", "official_phone", max_group=50)
link_by("dom", "official_domain", max_group=50)

# any shared phone (explode), skip phones on > 50 records (call centres)
ex = df[["phones"]].explode("phones").dropna()
ph_groups = ex.groupby("phones").indices
for ph, pos in ph_groups.items():
    idx = ex.index[pos]
    if 2 <= len(idx) <= 50:
        for i, j in itertools.combinations(sorted(set(idx)), 2):
            pairs[(i, j)].add("any_phone")

# near coordinates (< 0.2 km) with similar names (token_set_ratio >= 85)
la, lo = df.latitude.to_numpy(), df.longitude.to_numpy()
order = np.argsort(la)
GEO_KM, NAME_SIM = 0.2, 85
for a in range(N):
    i = order[a]
    for b in range(a + 1, N):
        j = order[b]
        if la[j] - la[i] > 0.002:
            break
        if abs(lo[j] - lo[i]) > 0.003:
            continue
        if haversine(la[i], lo[i], la[j], lo[j]) < GEO_KM and \
                fuzz.token_set_ratio(df.nname[i], df.nname[j]) >= NAME_SIM:
            pairs[tuple(sorted((i, j)))].add("geo_name")

# pair features
rows = []
for (i, j), keys in pairs.items():
    a, b = df.iloc[i], df.iloc[j]
    rows.append(dict(i=i, j=j, uid_a=a.unique_id, uid_b=b.unique_id, keys="+".join(sorted(keys)),
                     name_a=a["name"], name_b=b["name"], city_a=a.address_city, city_b=b.address_city,
                     pin_a=a.pin, pin_b=b.pin, km=round(haversine(a.latitude, a.longitude, b.latitude, b.longitude), 3),
                     name_sim=fuzz.token_set_ratio(a.nname, b.nname), same_name=a.nname == b.nname,
                     dom_a=a.dom, dom_b=b.dom, type_a=a.facilityTypeId, type_b=b.facilityTypeId,
                     same_claims=(a.procedure, a.equipment, a.capability) == (b.procedure, b.equipment, b.capability),
                     same_desc=a.description == b.description))
P = pd.DataFrame(rows)
P.to_csv(OUT + "dup_pairs.csv", index=False)
print("linked pairs:", len(P))
for k in ["name_city", "name_pin", "official_phone", "any_phone", "official_domain", "geo_name"]:
    s = P[P["keys"].str.contains(k)]
    print(f"  key {k}: pairs {len(s)}, records {len(set(s.i) | set(s.j))}")

# connected components per key, and a "strong" union over identity keys only
# (name+city, name+PIN, near coords+similar name). Phone and domain links are too
# loose to merge on: they chain unrelated facilities through call centres and directories.
def components(keyset):
    parent = list(range(N))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for r in P.itertuples():
        if set(r.keys.split("+")) & keyset:
            parent[find(r.i)] = find(r.j)
    g = pd.Series([find(i) for i in range(N)])
    return g.where(g.map(g.value_counts()) > 1)


for name, ks in [("strong(name_city|name_pin|geo_name)", {"name_city", "name_pin", "geo_name"}),
                 ("official_phone", {"official_phone"}), ("official_domain", {"official_domain"}),
                 ("any_phone", {"any_phone"}), ("all keys", set(P["keys"].str.split("+").explode()))]:
    g = components(ks)
    vc = g.value_counts()
    print(f"components {name}: groups {len(vc)}, records {int(vc.sum())}, max size {int(vc.max())}")
    df["grp_" + name.split("(")[0]] = g


def classify_pair(r):
    """Rule-based pair class, checked by hand in hand_check.py."""
    near = r.km < 1.0
    if r.same_name and near:
        return "likely_true_duplicate"
    if r.name_sim >= 90 and near:
        return "likely_true_duplicate"
    if r.dom_a and r.dom_a == r.dom_b and not near:
        return "chain_branch_or_shared_site"
    if r.name_sim >= 90 and not near:
        return "same_name_different_place"
    return "different_facility_shared_contact"


P["cls"] = P.apply(classify_pair, axis=1)
P.to_csv(OUT + "dup_pairs.csv", index=False)
print("\npair class by key combo (top 25):")
print(P.groupby(["keys", "cls"]).size().sort_values(ascending=False).head(25).to_string())
print("\npair classes:", P.cls.value_counts().to_dict())
td = P[P.cls == "likely_true_duplicate"]
print("likely_true_duplicate: pairs", len(td), "records", len(set(td.i) | set(td.j)),
      "| identical claim lists", int(td.same_claims.sum()), "| identical description", int(td.same_desc.sum()))
df[["unique_id"] + [c for c in df.columns if c.startswith("grp_")]].to_csv(OUT + "dup_groups.csv", index=False)
