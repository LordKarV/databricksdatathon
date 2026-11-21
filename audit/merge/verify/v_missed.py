"""Missed-issue probes: (a) coordinates vs PIN location, split by whether the record asserts a location elsewhere;
(b) records whose name is only a place name; (c) generic institutional names (ESI, PHC, CHC, district/sub-division
hospital, government dispensary) and their rate of other-place location assertions."""
import os, re
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
M = "/Users/karthikvattem/projects/datathon/audit/merge/out"
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
s = pd.read_parquet(f"{M}/sentences_flagged.parquet").merge(pd.read_parquet(f"{M}/sentence_decisions.parquet"), on=["unique_id", "field", "idx"])
pin = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/india_post_pincode_directory.parquet", columns=["pincode", "district", "latitude", "longitude"])
pin["la"] = pd.to_numeric(pin.latitude, errors="coerce"); pin["lo"] = pd.to_numeric(pin.longitude, errors="coerce")
pc = pin[pin.la.between(6, 38) & pin.lo.between(68, 98)].groupby("pincode")[["la", "lo"]].median()
zp = pd.to_numeric(rec.address_zipOrPostcode.astype(str).str.extract(r"(\d{6})")[0], errors="coerce")
def hav(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    return 6371 * 2 * np.arcsin(np.sqrt(np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2))
j = pd.DataFrame({"z": zp.values, "la": rec.latitude.values, "lo": rec.longitude.values}, index=rec.index).join(pc, on="z", rsuffix="_p")
j["km"] = hav(j.la, j.lo, j.la_p, j.lo_p)
LOC = re.compile(r"\b(located|situated|based in|address)\b", re.I)
s["locelse"] = s.quarantine & (s.has_other_state | s.has_other_district) & s.text.map(lambda t: bool(LOC.search(t)))
le = s.groupby("unique_id").locelse.any()
j["locelse"] = j.index.map(le).fillna(False).astype(bool)
ok = j.km.notna()
print("records with PIN coordinate available", int(ok.sum()), "of", len(j))
for v in (True, False):
    g = j[ok & (j.locelse == v)]
    print(f"  asserts location elsewhere={v}: n={len(g)}, coords >50 km from own PIN: {int((g.km > 50).sum())} ({100*(g.km > 50).mean():.1f}%)")
# (b) name is only a place name
places = set(pin.district.str.lower().str.strip()) | set(rec.address_city.dropna().str.lower().str.strip())
nm = rec.name.fillna("").str.lower().str.strip()
pn = nm.isin(places)
print("records whose whole name is a place name:", int(pn.sum()), rec[pn].name.head(8).tolist())
# (c) generic institutional names
GEN = re.compile(r"^(?:esi(?:c)?\b|e\.s\.i|primary health cent|community health cent|phc\b|chc\b|district hospital|civil hospital|"
                 r"sub[- ]?division(?:al)? hospital|government (?:hospital|ayurved\w* (?:dispensary|hospital)|dispensary|homoeopathic)|"
                 r"general hospital|urban health|rural hospital|taluk hospital|area hospital|referral hospital)", re.I)
gn = rec.name.fillna("").str.strip().str.match(GEN)
od = s[s.has_other_state | s.has_other_district].groupby("unique_id").size()
q = s.groupby("unique_id").quarantine.any()
for v in (True, False):
    idx = rec.index[gn == v]
    print(f"generic institutional name={v}: n={len(idx)}, any other-place mention {100*idx.map(lambda u: u in od.index).to_numpy().mean():.1f}%, "
          f"any quarantined {100*idx.map(q).to_numpy().astype(bool).mean():.1f}%, location-elsewhere {100*idx.map(le).to_numpy().astype(bool).mean():.1f}%")
