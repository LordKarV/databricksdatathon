"""Missed-issue probe: cross-record duplicates (same facility split over several unique_ids) and
an independent test of whether hex source ids carry an H3 location prefix."""
import json, re, math
import pandas as pd
from v_base import con
df = con.execute("select distinct * from wf").df()
print("records", len(df))
nm = df.name.fillna("").str.lower().str.replace(r"[^a-z0-9]+", " ", regex=True).str.strip()
df["nm"] = nm
df["lat3"] = df.latitude.round(3); df["lon3"] = df.longitude.round(3)
g = df.groupby(["nm", "lat3", "lon3"]).unique_id.transform("size")
print("records sharing normalised name AND coords rounded to 0.001 deg with another record:", int((g > 1).sum()), "groups", df[g > 1].groupby(["nm", "lat3", "lon3"]).ngroups)
g2 = df.groupby(["nm", "address_city"]).unique_id.transform("size")
print("records sharing normalised name AND address_city with another record:", int((g2 > 1).sum()))
def pl(s):
    try:
        x = json.loads(s); return [i.strip() for i in x if isinstance(i, str) and i.strip()] if isinstance(x, list) else []
    except Exception:
        return []
ph = df[["unique_id", "phone_numbers"]].assign(p=df.phone_numbers.map(pl)).explode("p").dropna(subset=["p"])
ph["p"] = ph.p.str.replace(r"\D", "", regex=True).str[-10:]
ph = ph[ph.p.str.len() == 10]
pc = ph.groupby("p").unique_id.nunique()
shared = ph[ph.p.map(pc) > 1].unique_id.nunique()
print("records sharing at least one 10-digit phone with another record:", shared, "; phones shared by >=5 records:", int((pc >= 5).sum()), "max", int(pc.max()))
print(df[df.unique_id.isin(ph[ph.p == pc.idxmax()].unique_id)][["name", "address_city"]].head(8).to_string())
ex = df[g > 1].sort_values(["nm"])[["unique_id", "name", "address_city", "latitude", "longitude"]].head(10)
print(ex.to_string())
# H3 prefix test: hex32 source ids; records with exactly one source id; compare lat/lon of records sharing a 7-hex prefix
sid = df.source_ids.map(lambda v: sorted(set(pl(v))))
one = df[sid.map(len) == 1].assign(s=sid[sid.map(len) == 1].str[0])
one = one[one.s.str.fullmatch(r"[0-9a-f]{32}")]
print("single-hex-source records", len(one))
for k in (6, 8, 10):
    gg = one.groupby(one.s.str[:k]).agg(n=("latitude", "size"), sd=("latitude", "std"), sdl=("longitude", "std"))
    gg = gg[gg.n >= 3]
    print(f"prefix len {k}: groups>=3 {len(gg)}, median lat SD {gg.sd.median():.2f}, median lon SD {gg.sdl.median():.2f}")
