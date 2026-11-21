"""F3 interpretation probe: for the finder's other-district sentences, distance from the record's coordinates to the
median PIN-directory coordinate of the mentioned district. Near (<40 km) mentions are neighbouring districts of one
metro (Mumbai/Thane, Hyderabad/Rangareddy, Kolkata/Howrah), not contradictions. Also draws a fresh 30-sentence sample."""
import os, re
import numpy as np, pandas as pd
D = os.path.dirname(os.path.abspath(__file__))
rec = pd.read_parquet(f"{D}/out/rec.parquet").set_index("unique_id")
pin = pd.read_parquet("/Users/karthikvattem/projects/datathon/data/raw/india_post_pincode_directory.parquet", columns=["district", "latitude", "longitude"])
n_ = lambda x: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(x or "").lower().replace("&", " and "))).strip()
pin["d"] = pin.district.map(n_)
pin["la"] = pd.to_numeric(pin.latitude, errors="coerce"); pin["lo"] = pd.to_numeric(pin.longitude, errors="coerce")
pin = pin[pin.la.between(6, 38) & pin.lo.between(68, 98)]
cen = pin.groupby("d")[["la", "lo"]].median()
for a in ("urban", "rural"):
    for d in list(cen.index):
        if d.endswith(" " + a) and d.rsplit(" ", 1)[0] not in cen.index:
            cen.loc[d.rsplit(" ", 1)[0]] = cen.loc[d]
fin = pd.read_parquet("/Users/karthikvattem/projects/datathon/audit/merge/out/sentences_flagged.parquet")
od = fin[fin.has_other_district].copy()
def hav(a, b, c, d):
    a, b, c, d = map(np.radians, (a, b, c, d))
    return 6371 * 2 * np.arcsin(np.sqrt(np.sin((c - a) / 2) ** 2 + np.cos(a) * np.cos(c) * np.sin((d - b) / 2) ** 2))
dmin = []
for u, ps in zip(od.unique_id, od.places_other_district):
    la, lo = rec.latitude[u], rec.longitude[u]
    ds = [hav(la, lo, *cen.loc[p]) for p in ps.split("; ") if p in cen.index]
    dmin.append(max(ds) if ds else np.nan)  # farthest mentioned district in the sentence
od["km"] = dmin
print("other-district sentences", len(od), "with a district centroid", int(od.km.notna().sum()))
for lo_, hi_ in [(0, 40), (40, 100), (100, 300), (300, 1e9)]:
    m = (od.km >= lo_) & (od.km < hi_)
    print(f"  farthest mentioned district {lo_}-{hi_} km: sentences {int(m.sum())}, records {od[m].unique_id.nunique()}")
far = od[od.km >= 40]
print("records with an other-district mention >= 40 km from the record's own coordinates:", far.unique_id.nunique(), "of", len(rec))
print("records whose ONLY other-district mentions are < 40 km away:", od.groupby("unique_id").km.max().lt(40).sum())
print("top place names in near (<40 km) hits:", pd.Series("; ".join(od[od.km < 40].places_other_district).split("; ")).value_counts().head(12).to_dict())
smp = od.sample(30, random_state=4242)
smp.assign(rec_name=smp.unique_id.map(rec.name), city=smp.unique_id.map(rec.address_city))[
    ["unique_id", "rec_name", "city", "places_other_district", "km", "text"]].to_csv(f"{D}/handcheck/v_f3_od_sample.tsv", sep="\t", index=False)
