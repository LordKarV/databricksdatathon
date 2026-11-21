import sys; sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/identity/verify")
from v_base import *
import itertools, random
r = raw(); w = wellformed(r)
print("raw", len(r), "wellformed", len(w))
vc = w.unique_id.value_counts(); dup_ids = vc[vc > 1]
print("ID1 unique_ids with >1 row:", len(dup_ids), "max mult", dup_ids.max() if len(dup_ids) else 0)
# identical across all columns (NaN==NaN)
ident = 0
for u in dup_ids.index:
    g = w[w.unique_id == u].astype(object).where(w[w.unique_id == u].notna(), "<NA>")
    ident += int((g.nunique(dropna=False) == 1).all())
print("ID1 groups identical in all 51 cols:", ident)
# Across raw (incl broken rows)?
vr = r.unique_id.value_counts(); print("raw unique_id dup values:", (vr > 1).sum())
# full-row duplicates ignoring unique_id among distinct ids
d = dedup(w)
cols = [c for c in d.columns if c not in ("unique_id",)]
print("rows identical in all non-id cols (distinct uid):", d.astype(str).duplicated(cols, keep=False).sum())
c2 = [c for c in d.columns if c not in ("unique_id", "cluster_id", "source_content_id", "content_table_id", "source_ids")]
print("rows identical except ids:", d.astype(str).duplicated(c2, keep=False).sum())
# cluster_id
print("ID13 distinct cluster_id over wellformed:", w.cluster_id.nunique(), "null:", w.cluster_id.isna().sum())
cv = w.cluster_id.value_counts(); sh = cv[cv > 1]
print("shared cluster_ids:", len(sh), "covering rows", sh.sum())
print("shared cluster ids all from exact dup uid?", set(w[w.cluster_id.isin(sh.index)].unique_id) <= set(dup_ids.index))
hex32 = d.cluster_id.fillna("").str.fullmatch(r"[0-9a-f]{32}"); uu = d.cluster_id.fillna("").str.fullmatch(r"[0-9a-f-]{36}")
print("hex32", hex32.sum(), "uuid", uu.sum(), "other", (~hex32 & ~uu).sum(), "of", len(d))
print("uuid == own unique_id", (d.cluster_id == d.unique_id).sum())
print("hex32 in own source_ids", sum(1 for _, x in d[hex32].iterrows() if x.cluster_id in str(x.source_ids)))
# ID14 source_content_id
sc = d.source_content_id.where(~d.source_content_id.map(nul))
print("source_content_id non-null:", sc.notna().sum(), "eq content_table_id:", (d.source_content_id == d.content_table_id).sum())
scv = sc.value_counts(); g = scv[scv > 1]
print("ID14 groups", len(g), "rows", g.sum(), "max", g.max())
d["urls"] = d.source_urls.map(lambda v: set(jlist(v)))
d["ph"] = d.phone_numbers.map(lambda v: {digits(p) for p in jlist(v) if len(digits(p)) >= 10})
d["st"] = d.address_stateOrRegion.fillna("").str.lower().str.strip()
pairs = []
for k in g.index:
    idx = d.index[d.source_content_id == k]
    pairs += list(itertools.combinations(idx, 2))
def stats(P):
    u = sum(bool(d.urls[a] & d.urls[b]) for a, b in P)
    s = sum(d.st[a] == d.st[b] and d.st[a] != "" for a, b in P)
    p = sum(bool(d.ph[a] & d.ph[b]) for a, b in P)
    return len(P), u, s, p
print("within pairs (n, shareURL, sameState, sharePhone):", stats(pairs))
random.seed(1); n = len(d)
rp = [tuple(random.sample(range(n), 2)) for _ in range(len(pairs))]
print("random pairs:", stats(rp))
# scg size distribution by rows
print("seed group size top:", g.head(5).to_dict())
# TRANSTAN
tr = d[d.source_urls.fillna("").str.contains("transtan", case=False)]
print("rows with transtan url", len(tr), "by scid", tr.source_content_id.value_counts().head(3).to_dict())
k = "1f311955-3650-4ced-a2c9-6217a6e16cda"
gg = d[d.source_content_id == k]
kid = gg.apply(lambda x: bool(re.search(r"kidney|renal", " ".join(jlist(x.procedure) + jlist(x.capability)), re.I) and re.search(r"transplant", " ".join(jlist(x.procedure)+jlist(x.capability)), re.I)), axis=1)
print("TRANSTAN group", len(gg), "kidney+transplant mention", kid.sum())
print(gg.source_urls.map(lambda v: [u for u in jlist(v) if 'transtan' in u.lower()][:1]).head(3).tolist())
