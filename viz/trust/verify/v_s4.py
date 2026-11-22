"""Independent recomputation of story 4 (shared directory phones).

My own normalisation (last 10 digits of any number with >= 10 digits; toll-free 1800/1860 kept whole) and my own
state normalisation (canonical state from the cleaned location table, so spellings collapse), to test whether the
headline survives a different parse. Inputs: data/raw/facilities.parquet, derived/v1/facility_location.parquet,
derived/v1/source_urls.parquet, derived/v1/record_trust.parquet (cleaning's hidden phones, cross-check).
"""
import json
import re

import pandas as pd
from statsmodels.stats.proportion import proportion_confint

R = "/Users/karthikvattem/projects/datathon/"
ci = lambda k, n: tuple(round(100 * x, 1) for x in proportion_confint(k, n, method="wilson"))


def norm(p):
    d = re.sub(r"\D", "", str(p))
    m = re.search(r"(18[06]0\d{6,7})$", d)
    if m:
        return m.group(1)
    return d[-10:] if len(d) >= 10 else None


def items(s):
    try:
        v = json.loads(s)
    except Exception:
        return []
    return [x for x in (v if isinstance(v, list) else [v]) if x]


loc = pd.read_parquet(R + "derived/v1/facility_location.parquet")
raw = pd.read_parquet(R + "data/raw/facilities.parquet").drop_duplicates("unique_id")
raw = raw[raw.unique_id.isin(set(loc.unique_id))].merge(loc[["unique_id", "state_final"]], on="unique_id")
rows = []
for r in raw.itertuples():
    off = norm(r.officialPhone) if isinstance(r.officialPhone, str) and r.officialPhone.lower() != "null" else None
    for n in {norm(x) for x in items(r.phone_numbers) + ([r.officialPhone] if off else [])} - {None}:
        rows.append((r.unique_id, n, n == off, str(r.address_city).strip().lower(), str(r.address_stateOrRegion).strip().lower(),
                     r.state_final))
h = pd.DataFrame(rows, columns=["uid", "ph", "off", "city", "state_raw", "state"])
per = h.groupby("ph").agg(rec=("uid", "nunique"), off=("off", "sum"), cities=("city", "nunique"),
                          raw_states=("state_raw", "nunique"), states=("state", "nunique")).sort_values("rec", ascending=False)
print("S4 top 3\n", per.head(3).to_string())
multi = per[per.cities >= 3].index
n_off = h[h.off].uid.nunique()
k_off = h[h.off & h.ph.isin(multi)].uid.nunique()
rm = h[h.ph.isin(multi)].uid.nunique()
print("S4 multi-city numbers", len(multi), "records", rm, len(raw), ci(rm, len(raw)), "official", k_off, n_off, ci(k_off, n_off))
su = pd.read_parquet(R + "derived/v1/source_urls.parquet", columns=["unique_id", "domain"]).drop_duplicates()
top = per.index[0]
u = set(h[h.ph == top].uid)
print("S4 top holders citing proptiger.com", su[su.unique_id.isin(u) & (su.domain == "proptiger.com")].unique_id.nunique(), "of", len(u))
print("S4 all records citing proptiger.com", su[su.domain == "proptiger.com"].unique_id.nunique())
rt = pd.read_parquet(R + "derived/v1/record_trust.parquet")
print("S4 top number still displayed after cleaning:", int(rt.display_phones.map(lambda L: any(norm(x) == top for x in L)).sum()))
