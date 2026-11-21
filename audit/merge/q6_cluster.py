"""Q6: what cluster_id / source ids are.

Hypothesis tested and REJECTED: that the 32-hex ids ('08f...') are Overture legacy ids whose first
16 hex digits are an H3 res-15 cell, so the cell would locate each source. The bits do parse as a
res-15 H3 header, but records with a single source id that share a decoded res-2 parent cell
are spread over ~5.9 degrees of latitude (median SD), i.e. all over India, so the prefix carries
no usable location here. Only the count of distinct source ids is used below."""
import re
import pandas as pd
import common

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def h3_parent(oid, res):
    h = int(oid[1:16], 16)
    if (h >> 52) & 0xF != 15:  # resolution nibble must be 15 for these ids
        return None
    return ((h >> 45) & 0x7F,) + tuple((h >> (45 - 3 * i)) & 7 for i in range(1, res + 1))


df = common.load()
n = len(df)
cid = df.cluster_id
print("cluster_id distinct", cid.nunique(), "of", n, "deduplicated records")
print("cluster_id format: uuid", int(cid.str.match(common.UUID.pattern).sum()), "hex32", int(cid.str.match(HEX32.pattern).sum()))
sid = df.source_ids.map(lambda x: sorted(set(common.parse_list(x))))
hexc = cid.str.match(HEX32.pattern)
print("hex32 cluster_id equal to one of the record's own source_ids:", sum(c in s for c, s, h in zip(cid, sid, hexc) if h), "of", int(hexc.sum()))
print("hex32 cluster_id valid H3-res15 prefix:", sum(h3_parent(c, 3) is not None for c in cid[hexc]), "of", int(hexc.sum()))
st = df.source_types.map(lambda x: set(common.parse_list(x)))
print("records with overture in source_types and hex32 cluster_id:", int((hexc & st.map(lambda s: "overture" in s)).sum()),
      "; uuid cluster_id with overture source:", int((~hexc & st.map(lambda s: "overture" in s)).sum()))
sc = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/record_scores.parquet").set_index("unique_id")
df["contam"] = df.unique_id.map(sc.n_q).fillna(0) > 0
df["os"] = df.unique_id.map(sc.n_os).fillna(0) > 0
df["od"] = df.unique_id.map(sc.n_od).fillna(0) > 0
one = df[sid.map(len) == 1].assign(p2=sid[sid.map(len) == 1].str[0].map(lambda x: h3_parent(x, 2)))
g = one.groupby("p2").latitude.agg(["size", "std"])
print("H3 test: decoded res-2 cells with >=5 single-source records:", int((g["size"] >= 5).sum()),
      "; median latitude SD inside a cell:", round(float(g[g["size"] >= 5]["std"].median()), 2), "degrees (an H3 res-2 cell is ~3 deg across)")
k = sid.map(len)
for lo, hi in [(0, 1), (1, 2), (2, 5), (5, 10), (10, 100)]:
    m = (k >= lo) & (k < hi)
    print(f"distinct source_ids [{lo},{hi}): records {int(m.sum())}, any quarantined {df[m].contam.mean():.3f},"
          f" other-state claim {df[m].os.mean():.3f}, other-district claim {df[m].od.mean():.3f}")
dup = pd.read_parquet(common.RAW)
dup = dup[dup.unique_id.fillna("").str.match(common.UUID) & (dup.source == "kie")]
print("byte-identical duplicate rows removed by common.load():", len(dup) - dup.unique_id.nunique())
