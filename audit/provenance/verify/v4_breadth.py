"""PROV-02/06: does record breadth predict location error when only the non-mechanical proxy (P4) is used?
Also city-vs-PIN agreement among far records."""
import duckdb, json, re, pandas as pd
R = "/Users/karthikvattem/projects/datathon/data/raw"
f = duckdb.sql(f"""select distinct * from '{R}/facilities.parquet' where regexp_full_match(unique_id,'[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}') and source='kie'""").df()
def jl(s):
    try: v = json.loads(s) if isinstance(s, str) and s.startswith("[") else []
    except ValueError: v = []
    return [x for x in v if isinstance(x, str) and x.strip()]
f["nu"] = f.source_urls.map(lambda s: len(jl(s)))
f["ns"] = f.source_ids.map(lambda s: len(set(jl(s))))
f["nclaims"] = sum(f[c].map(lambda s: len(jl(s))) for c in ("procedure", "equipment", "capability"))
d = pd.read_parquet("v3_fac_pin_km.parquet")[["unique_id", "d", "pin"]]
m = f.merge(d, on="unique_id", how="left")
m["far"] = m.d > 50
o = {}
ub = pd.cut(m.nu, [-1, 5, 10, 20, 1000], labels=["0-5", "6-10", "11-20", "21+"])
sb = pd.cut(m.ns, [-1, 0, 1, 3, 10, 1000], labels=["0", "1", "2-3", "4-10", "11+"])
for nm, b in (("url_bucket", ub), ("sid_bucket", sb)):
    g = m[m.d.notna()].groupby(b[m.d.notna()], observed=True).far
    o[nm + "_p4"] = {str(k): [int(v.sum()), int(len(v)), round(100 * v.mean(), 1)] for k, v in g}
    o[nm + "_sizes"] = b.value_counts().sort_index().to_dict()
# city agreement: stated city token found in PIN directory district/office names of that PIN
p = pd.read_parquet(f"{R}/india_post_pincode_directory.parquet")
k = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
names = p.assign(n=p.officename.str.replace(r"\s+(H\.?O|S\.?O|B\.?O|G\.?P\.?O)\.?$", "", regex=True)).groupby("pincode").apply(
    lambda g: set(map(k, g.n)) | set(map(k, g.district)), include_groups=False)
def agree(r):
    s = names.get(r.pin); c = k(r.address_city)
    return None if s is None or len(c) < 3 else any(c in x or (len(x) >= 4 and x in c) for x in s)
mm = m[m.d.notna()].copy(); mm["city_pin_agree"] = mm.apply(agree, axis=1)
o["city_pin_agree_far"] = mm[mm.far].city_pin_agree.value_counts(dropna=False).to_dict()
o["city_pin_agree_near"] = mm[~mm.far].city_pin_agree.value_counts(dropna=False).to_dict()
o["base_far_over_9959"] = [int(m.far.sum()), len(m)]
o["claims_median_by_url_bucket"] = m.groupby(ub, observed=True).nclaims.median().to_dict()
print(json.dumps(o, indent=1, default=str)); json.dump(o, open("v4_breadth.json", "w"), indent=1, default=str)
