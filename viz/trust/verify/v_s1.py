"""Independent recomputation of story 1 (merged records). Does not import the analyst's scripts.

Inputs: derived/v1/claims.parquet, derived/v1/facility_location.parquet, data/raw/facilities.parquet,
audit/provenance/q1_records.parquet (cross-check only), data/raw/india_post_pincode_directory.parquet.
Type and URL count are taken from the RAW record here (the analyst used audit tables), so agreement is
a real cross-check.
"""
import json
import math

import pandas as pd
from statsmodels.stats.proportion import proportion_confint

R = "/Users/karthikvattem/projects/datathon/"
ci = lambda k, n: tuple(round(100 * x, 1) for x in proportion_confint(k, n, method="wilson"))

loc = pd.read_parquet(R + "derived/v1/facility_location.parquet")
cl = pd.read_parquet(R + "derived/v1/claims.parquet", columns=["unique_id", "field", "idx", "text", "context",
                                                               "attribution", "services"])
raw = pd.read_parquet(R + "data/raw/facilities.parquet").drop_duplicates("unique_id")
ids = set(loc.unique_id)
flag = set(cl.loc[cl.context == "direct", "unique_id"]) & ids
N, K = len(ids), len(flag)
print("S1 overall", K, N, round(100 * K / N, 2), ci(K, N))


def n_urls(s):
    try:
        v = json.loads(s)
        return sum(isinstance(x, str) and bool(x.strip()) for x in v) if isinstance(v, list) else 0  # arrays carry trailing nulls
    except Exception:
        return 0


r = loc[["unique_id", "state_final"]].merge(raw[["unique_id", "facilityTypeId", "source_urls"]], on="unique_id",
                                            how="left")
r["n"] = r.source_urls.map(n_urls)
r["f"] = r.unique_id.isin(flag)
print("max urls", r.n.max(), "zero urls", (r.n == 0).sum())
q1 = pd.read_parquet(R + "audit/provenance/q1_records.parquet", columns=["unique_id", "n_urls"]).drop_duplicates("unique_id")
m = r.merge(q1, on="unique_id", how="left", suffixes=("", "_q1"))
print("url count agrees with audit q1:", (m.n == m.n_urls).mean(), "disagree", (m.n != m.n_urls).sum())
r["band"] = pd.cut(r.n, [0, 2, 7, 14, 29, 50], labels=["1-2", "3-7", "8-14", "15-29", "30-50"])
for b, g in r.groupby("band", observed=True):
    print("S1 band", b, g.f.sum(), len(g), round(100 * g.f.mean(), 1), ci(g.f.sum(), len(g)))
print("S1 band NaN (0 urls)", r.band.isna().sum(), r[r.band.isna()].f.sum())
for t, g in r.groupby(r.facilityTypeId.fillna("NA")):
    if len(g) > 50:
        print("S1 type", t, g.f.sum(), len(g), round(100 * g.f.mean(), 1), ci(g.f.sum(), len(g)))
st = r.groupby("state_final").f.agg(["sum", "count"])
st = st[st["count"] >= 100]
p = K / N
out = []
for s, row in st.iterrows():
    lo, hi = proportion_confint(row["sum"], row["count"], method="wilson")
    out.append((s, int(row["sum"]), int(row["count"]), round(100 * row["sum"] / row["count"], 1), lo > p or hi < p))
out.sort(key=lambda x: x[3])
print("S1 states", len(out), out[0], out[-1])
print("S1 states excluding national", [o[0] for o in out if o[4]])

# Anatomy records
for uid in ["b8a5401f-42f1-422a-8cd9-686a15b4cb76", "3ac5ae50-9ce2-4de3-a13c-d95a4ef218ee"]:
    s = cl[cl.unique_id == uid]
    print("\nS1 anatomy", uid[:8], loc.set_index("unique_id").loc[uid, ["name", "address_city", "pin", "raw_lat",
                                                                       "raw_lon", "raw_coords_to_pin_km", "loc_conf"]].to_dict())
    print(" sentences", len(s), s.attribution.value_counts().to_dict(), "context direct", (s.context == "direct").sum())
    sv = s[s.services.fillna("") != ""]
    print(" service sentences", len(sv), sv.attribution.value_counts().to_dict())
    for kw in ["dialysis", "trauma", "1241", "1,241", "Delhi", "Government", "Fortis", "Nair", "Mira Road", "3T MRI"]:
        hits = s[s.text.str.contains(kw, case=False, regex=False)]
        print(f"  '{kw}':", len(hits), "|", " || ".join(hits.text.str[:110].head(3)))
pin = pd.read_parquet(R + "data/raw/india_post_pincode_directory.parquet")
for p_ in ["110002", "400078"]:
    print(p_, pin[pin.pincode.astype(str) == p_][["district", "statename"]].drop_duplicates().values.tolist())
