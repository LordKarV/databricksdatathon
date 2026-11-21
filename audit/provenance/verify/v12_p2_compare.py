"""Compare my P2 (v10) with finder P2 (q1_records.parquet); show my-only hits; classify P2 URL kinds."""
import pandas as pd, re, json
me = pd.read_parquet("v10_records.parquet"); fi = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/provenance/q1_records.parquet")
m = me.merge(fi[["unique_id", "p2_url_cross_state", "p2_examples", "state_norm"]], on="unique_id")
a, b = m.p2.fillna(False).astype(bool), m.p2_url_cross_state.fillna(False).astype(bool)
print("mine", a.sum(), "finder", b.sum(), "both", (a & b).sum(), "mine_only", (a & ~b).sum(), "finder_only", (~a & b).sum())
for r in m[a & ~b].sample(8, random_state=1).itertuples(): print("  mine-only |", r.name, "|", r.city, r.state_norm, "|", r.p2_ex[0][:110])
# what kind of URL drives finder P2 hits
kinds = {"practo_doctor": r"practo\.com/[^/]+/doctor/", "justdial_category_nct": r"justdial\.com/.*/nct-", "justdial_listing": r"justdial\.com/.*_BZDET",
         "practo_clinic_or_hospital": r"practo\.com/[^/]+/(clinic|hospital)/", "medindia": r"medindia", "lybrate": r"lybrate", "hexahealth": r"hexahealth"}
c = {k: 0 for k in kinds}
ex = [u for s in fi.p2_examples.dropna() for u in json.loads(s)]
for u in ex:
    for k, rx in kinds.items():
        if re.search(rx, u): c[k] += 1; break
print("finder P2 example URLs (first 3 per record):", len(ex), c)
