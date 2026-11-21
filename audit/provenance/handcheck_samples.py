"""Regenerates the two hand-check samples that q1/q3 do not write themselves:
handcheck_research_lang.csv (20 paper-style claims from records citing research URLs, 20 from
others) and handcheck_p4.csv (15 facilities 50-200 km from their PIN centroid).
Run after q3_pincode.py and q1_sources.py."""
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/provenance")
from common import OUT, facilities, jlist, norm_pin  # noqa: E402
from proxies import _k, institution_mentions, is_foreign  # noqa: E402
from q1_sources import RESEARCH_LANG  # noqa: E402

f = facilities()
rec = pd.read_parquet(f"{OUT}/q1_records.parquet")
rr = set(rec.unique_id[rec.n_research > 0])
rows = []
for _, r in f.iterrows():
    for k in ("procedure", "equipment", "capability"):
        for x in jlist(r[k]):
            if RESEARCH_LANG.search(x):
                fo = any(is_foreign(m, r["name"], {_k(r.address_city)}) for m in institution_mentions(x))
                rows.append((r.unique_id in rr, r.unique_id, r["name"], k, fo, x))
d = pd.DataFrame(rows, columns=["res_rec", "unique_id", "name", "field", "names_other_inst", "claim"])
print("paper-style claims", len(d), "in research-cited records", int(d.res_rec.sum()),
      "records", d.unique_id.nunique(), "naming another institution", int(d.names_other_inst.sum()))
pd.concat([d[d.res_rec].sample(20, random_state=3), d[~d.res_rec].sample(20, random_state=3)]).to_csv(
    f"{OUT}/handcheck_research_lang.csv", index=False)

km = pd.read_parquet(f"{OUT}/facility_coord_pin_km.parquet")
cen = pd.read_parquet(f"{OUT}/pin_centroids.parquet")
m = f.merge(km, on="unique_id").assign(pin=lambda x: x.address_zipOrPostcode.map(norm_pin))
m = m.merge(cen, left_on="pin", right_on="pincode")
m[(m.coord_pin_km > 50) & (m.coord_pin_km <= 200)].sample(15, random_state=8)[
    ["unique_id", "name", "address_city", "pin", "districts", "latitude", "longitude", "lat", "lon",
     "coord_pin_km"]].to_csv(f"{OUT}/handcheck_p4.csv", index=False)
