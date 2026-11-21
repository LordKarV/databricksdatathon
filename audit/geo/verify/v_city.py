"""GEO-02/05 verification: city name vs PIN-side and coordinate-side place names, and the
three-way state vote, using my own simple matcher (token containment, no fuzzy)."""
import json
import re
import sys

import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import VER, directory

v = pd.read_parquet(VER + "/v_fac.parquet")
p = directory()
n = lambda s: re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", str(s).lower())).strip()
SUF = re.compile(r"\s+(b o|s o|h o|bo|so|ho|gpo)\b.*$")
ALIAS = {"bangalore": "bengaluru", "gurgaon": "gurugram", "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai",
         "trivandrum": "thiruvananthapuram", "vizag": "visakhapatnam", "allahabad": "prayagraj", "ahmedabad": "ahmadabad",
         "mysore": "mysuru", "mangalore": "mangaluru", "belgaum": "belagavi", "baroda": "vadodara", "cochin": "kochi",
         "pondicherry": "puducherry", "nasik": "nashik", "gulbarga": "kalaburagi", "calicut": "kozhikode"}
p["names"] = (p.officename.map(n).str.replace(SUF, "", regex=True) + "|" + p.district.map(n) + "|" +
              p.divisionname.map(n).str.replace(r"\b(division|city|north|south|east|west|central|rural|urban)\b", "", regex=True).str.strip())
pin_names = p.groupby("pincode").names.agg(lambda s: {x.strip() for t in s for x in t.split("|") if x.strip()})
delhi = set(p.pincode[p.statename == "DELHI"])


def match(city, pin):
    if pd.isna(pin) or not city:
        return False
    c = ALIAS.get(city, city)
    names = pin_names.get(int(pin), set()) | ({"delhi", "new delhi"} if int(pin) in delhi else set())
    toks = {t for x in names for t in x.split()}
    return c in names or (len(c) >= 4 and (c in toks or any(x.startswith(c) for x in names))) or any(len(x) >= 4 and c.startswith(x) for x in names)


v["city"] = v.address_city.map(n).str.replace(r"\b(city|district|dist)\b", "", regex=True).str.strip()
v["m_pin"] = [match(c, q) for c, q in zip(v.city, v.pin)]
v["m_co"] = [match(c, q) for c, q in zip(v.city, v.c_pincode)]
o = {}
inpin = v.pin.isin(pin_names.index)
o["city_check_denominator"] = int(inpin.sum())
o["city_no_match_pin"] = int((inpin & ~v.m_pin).sum())
far = v.d_finder > 100
lab = (v.m_pin.map({True: "pin", False: ""}) + v.m_co.map({True: "co", False: ""})).replace({"": "neither", "pinco": "both", "co": "coords_only", "pin": "pin_only"})
o["gt100_city_agrees"] = lab[far].value_counts().to_dict()
o["gt50_city_agrees"] = lab[v.d_finder > 50].value_counts().to_dict()
# three-way state vote (simple normaliser from v_fac)
vote = []
for s, a, c in zip(v.s_state, v.p_state, v.c_statename):
    sig = {k: x for k, x in (("stated", s), ("pin", a), ("coord", c)) if isinstance(x, str)}
    vals = list(sig.values())
    if len(vals) < 3:
        vote.append("missing")
    elif len(set(vals)) == 1:
        vote.append("all_agree")
    elif len(set(vals)) == 2:
        vote.append("odd:" + [k for k, x in sig.items() if vals.count(x) == 1][0])
    else:
        vote.append("all_differ")
o["state_vote"] = pd.Series(vote).value_counts().to_dict()
v.assign(m_pin=v.m_pin, m_co=v.m_co, vote=vote)[["unique_id", "address_city", "pin", "c_pincode", "m_pin", "m_co", "d_finder", "vote"]].to_parquet(VER + "/v_city.parquet")
json.dump(o, open(VER + "/v_city_stats.json", "w"), indent=1)
print(json.dumps(o, indent=1))
print(v[far & ~v.m_pin & ~v.m_co][["address_city", "pin", "p_district", "c_district"]].sample(15, random_state=3).to_string())
