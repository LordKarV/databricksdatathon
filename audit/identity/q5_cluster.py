"""Q5: rows sharing cluster_id or unique_id, and what they have in common."""
import os
from common import load, OUT

os.makedirs(OUT, exist_ok=True)
df = load()
n = len(df)
print("rows", n, "distinct unique_id", df.unique_id.nunique(), "distinct cluster_id", df.cluster_id.nunique())
print("cluster_id length dist", df.cluster_id.str.len().value_counts().to_dict())
print("cluster_id == unique_id:", (df.cluster_id == df.unique_id).sum(), "of", n)
print("cluster_id == source_content_id:", (df.cluster_id == df.source_content_id).sum())
print("source_content_id == content_table_id:", (df.source_content_id == df.content_table_id).sum())

dup_c = df[df.cluster_id.duplicated(keep=False)].sort_values("cluster_id")
dup_u = df[df.unique_id.duplicated(keep=False)]
print("rows in shared cluster_id:", len(dup_c), "groups", dup_c.cluster_id.nunique())
print("rows in shared unique_id:", len(dup_u), "groups", dup_u.unique_id.nunique())
print("same row set:", set(dup_c.index) == set(dup_u.index))
cols = [c for c in df.columns if not c.endswith("_l")]
for cid, g in dup_c.groupby("cluster_id"):
    same = [c for c in cols if g[c].fillna("<NA>").astype(str).nunique() == 1]
    diff = [c for c in cols if c not in same]
    print("\n", cid, "n=", len(g), "| differing cols:", diff)
    print(g[["unique_id", "name", "address_city", "pin", "latitude", "longitude"]].to_string(index=False))

# content id sharing: rows that share source_content_id (one scraped page -> several facilities?)
sc = df[df.source_content_id.duplicated(keep=False)]
print("\nrows sharing source_content_id:", len(sc), "groups", sc.source_content_id.nunique(),
      "max group", sc.source_content_id.value_counts().max())
print("source_content_id groups whose rows all share cluster_id:",
      (sc.groupby("source_content_id").cluster_id.nunique() == 1).sum())

print("\n== differing values in the 11 duplicated unique_id pairs")
for uid, g in dup_u.groupby("unique_id"):
    print(uid, {c: list(g[c]) for c in ["numberDoctors", "capacity", "email", "officialWebsite", "address_zipOrPostcode"]
                if g[c].fillna("<NA>").astype(str).nunique() > 1})

# what is cluster_id? overture-style 32 hex vs uuid; does a 32-hex cluster_id appear in source_ids?
ov = df[df.cluster_id.str.len() == 32]
print("\n32-hex cluster_id found inside own source_ids:",
      sum(c in s for c, s in zip(ov.cluster_id, ov.source_ids.fillna(""))), "of", len(ov))
uu = df[df.cluster_id.str.len() == 36]
print("uuid cluster_id equal to own unique_id:", (uu.cluster_id == uu.unique_id).sum(), "of", len(uu),
      "| equal to any unique_id:", uu.cluster_id.isin(set(df.unique_id)).sum())

print("\n== largest source_content_id groups")
vc = sc.source_content_id.value_counts()
print("group size distribution:", vc.value_counts().sort_index().to_dict())
for sid in list(vc.index[:3]) + list(vc[vc == 2].index[:3]):
    g = df[df.source_content_id == sid]
    print("\n", sid, len(g))
    print(g[["unique_id", "name", "address_city", "pin", "officialWebsite"]].head(8).to_string(index=False))
    print("  distinct names", g.nname.nunique(), "distinct cities", g.ncity.nunique(),
          "distinct description", g.description.nunique(), "distinct capability", g.capability.nunique())

# do records that share a source_content_id share phones or source URLs more than random pairs?
import itertools, random
from common import norm_phone
d1 = df.drop_duplicates("unique_id").reset_index(drop=True)
ph = [{norm_phone(p)[0] for p in l if norm_phone(p)[1] != "invalid"} for l in d1.phone_numbers_l]
su = [set(l) for l in d1.source_urls_l]
grp = d1.groupby("source_content_id").indices
within = [(i, j) for idx in grp.values() if len(idx) > 1 for i, j in itertools.combinations(idx, 2)]
random.seed(0)
rnd = [tuple(random.sample(range(len(d1)), 2)) for _ in range(len(within))]
for lab, pairs in [("same source_content_id", within), ("random pairs", rnd)]:
    print(f"{lab}: pairs {len(pairs)}, share a phone {sum(bool(ph[i] & ph[j]) for i, j in pairs)}, "
          f"share a source URL {sum(bool(su[i] & su[j]) for i, j in pairs)}, "
          f"same state {sum(d1.address_stateOrRegion[i] == d1.address_stateOrRegion[j] for i, j in pairs)}")
import collections
for sid in vc.index[:4]:
    idx = grp[sid]
    common = set.intersection(*[su[i] for i in idx])
    print(sid, len(idx), "URLs common to all members:", sorted(common)[:3])
idx = grp["1f311955-3650-4ced-a2c9-6217a6e16cda"]
t = [" ".join(d1.procedure_l[i] + d1.capability_l[i] + d1.equipment_l[i]).lower() for i in idx]
print("TRANSTAN seed group: members", len(idx), "| claim kidney/renal transplant:",
      sum(("kidney transplant" in x) or ("renal transplant" in x) for x in t))
