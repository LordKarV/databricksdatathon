"""Missed-issue probe: phone numbers shared by many unrelated records, and source_id formats."""
import json, re
from collections import Counter
import pandas as pd
from v_base import con
df = con.execute("select distinct * from wf").df()
def pl(s):
    try:
        x = json.loads(s); return [i.strip() for i in x if isinstance(i, str) and i.strip()] if isinstance(x, list) else []
    except Exception:
        return []
ph = df[["unique_id", "name", "address_city", "address_stateOrRegion"]].assign(p=df.phone_numbers.map(pl)).explode("p").dropna(subset=["p"])
ph["p10"] = ph.p.str.replace(r"\D", "", regex=True).str[-10:]
ph = ph[ph.p10.str.len() == 10].drop_duplicates(["unique_id", "p10"])
pc = ph.groupby("p10").agg(n=("unique_id", "nunique"), cities=("address_city", "nunique"), states=("address_stateOrRegion", "nunique"), raw=("p", "first"))
top = pc.sort_values("n", ascending=False).head(12)
print(top.to_string())
for p in top.index[:4]:
    print(p, ph[ph.p10 == p][["name", "address_city"]].head(5).values.tolist())
big = pc[(pc.n >= 5) & (pc.states >= 2)]
print("phones on >=5 records spanning >=2 states:", len(big), "; records carrying one:", ph[ph.p10.isin(big.index)].unique_id.nunique(), "of", len(df))
off = df.officialPhone.fillna("").str.replace(r"\D", "", regex=True).str[-10:]
oc = off[off.str.len() == 10].value_counts()
print("officialPhone shared by >=5 records:", int((oc >= 5).sum()), "records:", int(oc[oc >= 5].sum()), "top", oc.head(5).to_dict())
fmt = Counter()
for s in df.source_ids:
    for x in pl(s):
        fmt["hex32" if re.fullmatch(r"[0-9a-f]{32}", x) else "uuid" if re.fullmatch(r"[0-9a-f-]{36}", x) else "other"] += 1
print("source_id item formats", dict(fmt))
