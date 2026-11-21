"""GEO-08 verification: homonym districts, exact office hits for typos, and how WRatio>=85 behaves
on my own typo and near-miss inputs (including false-positive risks)."""
import json
import re
import sys

import pandas as pd
from rapidfuzz import fuzz, process

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER, directory, facilities

n = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", str(s).lower())).strip()
p = directory()
p = p[p.statename.ne("NA")]
p["dn"] = p.district.map(n)
p["ob"] = p.officename.map(n).str.replace(r"\s+(b o|s o|h o|bo|so|ho|gpo|ndso|mdg)(\s.*)?$", "", regex=True).str.strip()
o = {}
ds = p.groupby("dn").statename.nunique()
o["district_names"] = len(ds)
o["district_names_multi_state"] = sorted(ds[ds > 1].index.tolist())
ob = p.groupby("ob").statename.nunique()
o["office_base_names"] = len(ob)
o["office_base_multi_state"] = int((ob > 1).sum())
f = facilities()
cities = sorted(set(f.address_city.dropna().map(n)) - {"", "null"})
o["facility_city_names"] = len(cities)
choices = sorted(set(ds.index) | set(cities))
tests = ["hydrabad", "lucknw", "jaipur rajasthan", "bhopl", "patana", "kolkatta", "vishakapatnam", "tiruchirapalli", "gurgoan",
         "banglore", "ahmedbad", "chandigar", "bhubneswar", "varansi", "nagpure", "mumbay", "puri", "agra", "pune", "mau", "goa",
         "delhi ncr", "new delhi", "navi mumbai", "salem", "dewas", "rewa", "durg", "nashik road", "aurangabad bihar"]
rows = []
for t in tests:
    exact_d = t in ds.index
    exact_o = p.loc[p.ob == t, "statename"].unique().tolist()[:4]
    best = process.extract(t, choices, scorer=fuzz.WRatio, limit=3)
    rows.append([t, exact_d, exact_o, [(b[0], round(b[1])) for b in best]])
o["tests"] = rows
json.dump(o, open(VER + "/v_resolve_stats.json", "w"), indent=1)
print(json.dumps({k: v for k, v in o.items() if k != "tests"}, indent=1))
for r in rows:
    print(r)

# alias hazard: names that are an old name of one district and the current name of another
for nm in ["bijapur", "raigarh", "raigad", "vijayapura"]:
    print(nm, p.loc[p.dn == nm].groupby("statename").size().to_dict())
