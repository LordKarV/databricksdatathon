"""Alternative explanations for GEO-01 far records:
(a) coords sit within 10 km of SOME raw office of the facility's own PIN (centroid artefact, not a bad coordinate);
(b) the state field holds a district name and the coordinates fall in that district (coords geocoded from a polluted field);
(c) finder centroids resting on a single office."""
import json
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/karthikvattem/projects/datathon/audit/geo/verify")
from v_common import ROOT, VER, directory, hav, inbox

v = pd.read_parquet(VER + "/v_fac.parquet")
p = directory()
sw = p.la.between(68, 98) & p.lo.between(6, 38)
p.loc[sw, ["la", "lo"]] = p.loc[sw, ["lo", "la"]].values
p = p[p.la.notna() & inbox(p.la, p.lo)]
offices = {k: g[["la", "lo"]].values for k, g in p.groupby("pincode")}
o = {}
far = v[v.d_finder > 50]
o["far"] = len(far)


def near_any(r, km=10):
    pts = offices.get(r.pin)
    return pts is not None and bool((hav(r.latitude, r.longitude, pts[:, 0], pts[:, 1]) <= km).any())


o["far_within_10km_of_any_own_pin_office"] = int(far.apply(near_any, axis=1).sum())
o["far_within_25km_of_any_own_pin_office"] = int(far.apply(lambda r: near_any(r, 25), axis=1).sum())
o["far_coord_district_eq_pin_district"] = int((far.c_district == far.p_district).sum())
# (b) state field equals a district name, and coordinates fall in that district
dn = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
v["sf"] = v.address_stateOrRegion.map(dn)
districts = set(p.district.map(dn))
states = set(p.statename.map(dn))
isd = v.sf.isin(districts) & ~v.sf.isin(states)
o["state_field_is_district"] = int(isd.sum())
o["of_which_coords_in_that_district"] = int((isd & (v.c_district.map(dn) == v.sf)).sum())
o["of_which_pin_in_that_district"] = int((isd & (v.p_district.map(dn) == v.sf)).sum())
o["of_which_far_gt50"] = int((isd & (v.d_finder > 50)).sum())
o["of_which_far_and_coords_in_state_field_district"] = int((isd & (v.d_finder > 50) & (v.c_district.map(dn) == v.sf)).sum())
o["far_rate_state_is_district"] = round(float((v.d_finder[isd] > 50).mean()), 3)
o["far_rate_overall"] = round(float((v.d_finder > 50).sum() / v.d_finder.notna().sum()), 3)
# also city field: coordinates in a district named like the city when PIN is far (coords from city geocode)
# (c) finder centroid built from one office
fin = pd.read_parquet(ROOT + "/audit/geo/pin_centroids.parquet")
o["finder_pins_n_used_1"] = int((fin.n_used == 1).sum())
v["n_used"] = v.pin.map(fin.set_index("pincode").n_used)
o["far_on_single_office_pin"] = int(((v.d_finder > 50) & (v.n_used == 1)).sum())
o["facilities_on_single_office_pin"] = int((v.n_used == 1).sum())
# mid band (10-50) by finder; what share has coords within 5 km of any own-PIN office
mid = v[v.d_finder.between(10, 50)]
o["mid"] = len(mid)
o["mid_within_5km_of_any_own_pin_office"] = int(mid.apply(lambda r: near_any(r, 5), axis=1).sum())
o["mid_coord_district_eq_pin_district"] = int((mid.c_district == mid.p_district).sum())
json.dump(o, open(VER + "/v_far_alt_stats.json", "w"), indent=1)
print(json.dumps(o, indent=1))
