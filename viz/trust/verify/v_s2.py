"""Independent recomputation of story 2 (pins that moved).

Route differs from the analyst: 'located elsewhere' is rebuilt from derived/v1/claims.parquet
(attribution == other_facility is the quarantine; places_other_state / places_other_district non-empty),
not from audit/merge tables; distances are recomputed with my own haversine from data/raw coordinates to
(a) derived/v1/pin_gazetteer.parquet points for the repaired PIN, (b) raw India Post medians for the raw PIN.
Cross-state: state of the nearest India Post office via a BallTree on true great-circle distance.
"""
import re

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree
from statsmodels.stats.proportion import proportion_confint

R = "/Users/karthikvattem/projects/datathon/"
ci = lambda k, n: tuple(round(100 * x, 1) for x in proportion_confint(k, n, method="wilson"))


def hav(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    return 6371.0088 * 2 * np.arcsin(np.sqrt(np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2))


loc = pd.read_parquet(R + "derived/v1/facility_location.parquet")
raw = pd.read_parquet(R + "data/raw/facilities.parquet").drop_duplicates("unique_id").set_index("unique_id")
gaz = pd.read_parquet(R + "derived/v1/pin_gazetteer.parquet")
gaz["pin"] = pd.to_numeric(gaz.pin, errors="coerce")
d = loc[["unique_id", "name", "pin"]].merge(gaz[["pin", "lat", "lon", "state"]], on="pin", how="left")
d["la"] = d.unique_id.map(raw.latitude)
d["lo"] = d.unique_id.map(raw.longitude)
d["km"] = hav(d.la, d.lo, d.lat, d.lon)
ok = d.km.notna()
n, far = int(ok.sum()), int((d.km > 50).sum())
print("S2 cleaned-pin far", far, n, round(100 * far / n, 1), ci(far, n), ">500", int((d.km > 500).sum()),
      "<10", round(100 * (d.km[ok] < 10).mean(), 1))
print("   agrees with facility_location.raw_coords_to_pin_km within 1 km:",
      float((abs(d.km - loc.raw_coords_to_pin_km) < 1)[ok].mean()))
print("S2 top 3 farthest", d[ok].nlargest(3, "km")[["name", "pin", "km"]].round(0).values.tolist())

# located elsewhere, from claims.parquet
cl = pd.read_parquet(R + "derived/v1/claims.parquet", columns=["unique_id", "text", "attribution", "places_other_state",
                                                               "places_other_district"])
LOC = re.compile(r"\b(located|situated|based in|address)\b", re.I)
q = cl[(cl.attribution == "other_facility") & ((cl.places_other_state.fillna("") != "") |
                                              (cl.places_other_district.fillna("") != ""))]
le = set(q.loc[q.text.map(lambda t: bool(LOC.search(t))), "unique_id"])
print("S2 records 'located elsewhere' (claims route)", len(le))

# raw PIN medians (v_missed definition, recomputed)
pin = pd.read_parquet(R + "data/raw/india_post_pincode_directory.parquet", columns=["pincode", "statename", "latitude",
                                                                                      "longitude"])
pin["la"] = pd.to_numeric(pin.latitude, errors="coerce")
pin["lo"] = pd.to_numeric(pin.longitude, errors="coerce")
pin = pin[pin.la.between(6, 38) & pin.lo.between(68, 98)]
pc = pin.groupby(pin.pincode.astype(str))[["la", "lo"]].median()
z = raw.loc[loc.unique_id, "address_zipOrPostcode"].astype(str).str.extract(r"(\d{6})")[0]
j = pd.DataFrame({"z": z.values, "la": raw.loc[loc.unique_id, "latitude"].values,
                  "lo": raw.loc[loc.unique_id, "longitude"].values}, index=loc.unique_id.values).join(pc, on="z", rsuffix="_p")
j["km"] = hav(j.la, j.lo, j.la_p, j.lo_p)
j = j[j.km.notna()]
j["isle"] = j.index.isin(le)
for v in (True, False):
    g = j[j.isle == v]
    k = int((g.km > 50).sum())
    print(f"S2 raw-median locelse={v}", k, len(g), round(100 * k / len(g), 1), ci(k, len(g)))
# same split on cleaned distances
dd = d[ok].assign(isle=d.unique_id.isin(le))
for v in (True, False):
    g = dd[dd.isle == v]
    k = int((g.km > 50).sum())
    print(f"S2 cleaned locelse={v}", k, len(g), round(100 * k / len(g), 1), ci(k, len(g)))

# cross-state far pins (nearest post office, great-circle)
tree = BallTree(np.radians(pin[["la", "lo"]].to_numpy()), metric="haversine")
f = d[d.km > 50].copy()
_, i = tree.query(np.radians(f[["la", "lo"]].to_numpy()), k=1)
f["pt_state"] = pin.statename.str.upper().str.strip().to_numpy()[i[:, 0]]
f["xstate"] = f.pt_state != f.state.str.upper().str.strip()
print("S2 far pins in another state", int(f.xstate.sum()), "of", len(f))
print("  far & locelse (map legend)", int(f.unique_id.isin(le).sum()))
print(f[f.xstate].pt_state.value_counts().head(5).to_dict())
odd = d[ok & loc.raw_coords_to_pin_km.isna()]
print("S2 records with raw coords that facility_location leaves without a distance:", len(odd),
      odd[["name", "la", "lo", "km"]].round(1).values.tolist())
f2 = f[f.unique_id.isin(loc.loc[loc.raw_coords_to_pin_km.notna(), "unique_id"])]
print("S2 cross-state among the", len(f2), "far pins inside India:", int(f2.xstate.sum()))
print("S2 farthest inside India", f2.nlargest(3, "km")[["name", "pin", "km"]].round(0).values.tolist())
